from __future__ import annotations

import unittest

from gateway.body_capabilities import body_commands
from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.environment_adapter.translation import LEGACY_ROBOT_COMMANDS, translate_environment_action
from gateway.server.service import GatewayConnection, GatewayError, GatewayService, GatewayServiceConfig
from protocol.control_v1 import ProtocolValidationError, validate_control_message
from Emulator.tests.test_environment_adapter import FakeGateway
from Emulator.tests.test_p4_foundation import Socket


FEATURES = ("body_capabilities_v1", "body_commands_v1")


def capabilities(ready: bool) -> dict[str, object]:
    return {"motion": ready, "camera": False, "speaker": False, "microphone": False, "commands": ["walk", "stop"]}


TURNS = tuple(f"turn_{direction}_{angle}" for direction in ("left", "right") for angle in (15, 45, 90, 180))
GESTURES = ("sit", "rest", "wave", "dance", "swim", "point", "nod", "pushup", "bow",
            "cute", "freaky", "worm", "shake", "shrug", "dead", "crab", "celebrate",
            "stretch", "surprised", "sad", "curious")


class V2CommandsTests(unittest.IsolatedAsyncioTestCase):
    def connection(self, model: str, *, ready: bool = True) -> tuple[GatewayConnection, Socket]:
        gateway = GatewayService(GatewayServiceConfig(tokens={"test-body": "test"}), clock=lambda: 100.0)
        socket = Socket()
        connection = GatewayConnection(gateway, socket, "test-body", 7,
                                       FEATURES if model != "v1-8servo" else (), model=model,
                                       capabilities=capabilities(ready) if model != "v1-8servo" else None)
        gateway._connections["test-body"] = connection
        return connection, socket

    async def test_same_walk_wire_and_lifecycle_for_both_bodies(self) -> None:
        translated = translate_environment_action({"type": "robotCommand", "command": "walk", "units": 3})
        self.assertEqual((translated.kind, translated.name, translated.params),
                         ("intent", "walk", {"dir": "fwd", "steps": 3}))
        sent = []
        for model in ("v1-8servo", "v2-12servo"):
            connection, socket = self.connection(model)
            seq = await connection.service.queue_intent(translated.name, translated.params,
                                                       robot_id="test-body", received_at=100.0)
            await connection._handle_control({"t": "ack", "seq": seq})
            self.assertIn(seq, connection.pending)
            await connection._handle_control({"t": "done", "seq": seq})
            result = await connection.wait_terminal(seq, timeout=1)
            self.assertEqual(result["t"], "done")
            self.assertEqual(connection.service.terminals[-1]["epoch"], 7)
            sent.append(socket.messages)
        self.assertEqual(sent[0], sent[1])

    async def test_unimplemented_motions_and_v1_calibration_do_not_dispatch(self) -> None:
        connection, socket = self.connection("v2-12servo")
        requests = [
            {"t": "intent", "name": "stand"},
            {"t": "intent", "name": "walk", "dir": "back", "steps": 1},
            {"t": "intent", "name": "emote", "asset": "wave"},
            {"t": "servo", "id": 0, "deg": 90, "ms": 100},
            {"t": "cal_save"},
            {"t": "pose_save", "name": "neutral", "servos": [[0,90]]},
        ]
        for request in requests:
            with self.subTest(request=request), self.assertRaises(GatewayError):
                await connection.send_command(request, received_at=100.0)
        self.assertEqual(connection.next_sequence, 1)
        self.assertEqual(socket.messages, [])

    async def test_unready_body_still_accepts_stop(self) -> None:
        connection, socket = self.connection("v2-12servo",ready=False)
        with self.assertRaises(GatewayError):
            await connection.send_command({"t":"intent","name":"walk","dir":"fwd","steps":1},received_at=100.0)
        await connection.send_command({"t":"stop","detach":True},received_at=100.0)
        self.assertEqual(socket.messages,[{"t":"stop","detach":True,"seq":1}])

    async def test_newly_advertised_clip_uses_existing_semantic_motion_lifecycle(self) -> None:
        connection, socket = self.connection("v2-12servo")
        connection.capabilities["commands"].append("new_pose")
        seq = await connection.service.emote("new_pose", robot_id="test-body", received_at=100.0)
        self.assertEqual(socket.messages[-1], {"t": "intent", "name": "emote", "asset": "new_pose", "seq": seq})
        await connection._handle_control({"t": "ack", "seq": seq})
        self.assertIn(seq, connection.pending)
        await connection._handle_control({"t": "done", "seq": seq})
        self.assertEqual((await connection.wait_terminal(seq, timeout=1))["t"], "done")
        with self.assertRaises(GatewayError):
            await connection.service.emote("uninstalled_pose", robot_id="test-body", received_at=100.0)

    async def test_turns_use_same_wire_and_correlated_completion(self) -> None:
        for name in TURNS:
            models = ("v2-12servo",) if name.endswith("_15") else ("v1-8servo", "v2-12servo")
            sent = []
            for model in models:
                connection, socket = self.connection(model)
                if connection.capabilities is not None:
                    connection.capabilities["commands"] = list(TURNS)
                translated = translate_environment_action({"type": "robotCommand", "command": name})
                self.assertEqual((translated.name, translated.params), ("emote", {"asset": name}))
                seq = await connection.service.queue_intent(translated.name, translated.params,
                                                           robot_id="test-body", received_at=100.0)
                await connection._handle_control({"t": "ack", "seq": seq})
                self.assertIn(seq, connection.pending)
                await connection._handle_control({"t": "done", "seq": seq})
                self.assertEqual((await connection.wait_terminal(seq, timeout=1))["t"], "done")
                self.assertEqual(connection.service.terminals[-1]["epoch"], 7)
                sent.append(socket.messages)
            if len(sent) == 2:
                self.assertEqual(sent[0], sent[1])

    async def test_new_turns_require_declared_support_and_motion_readiness(self) -> None:
        for model, ready in (("v1-8servo", True), ("v2-12servo", False), ("v2-12servo", True)):
            connection, socket = self.connection(model, ready=ready)
            if model == "v2-12servo" and not ready:
                connection.capabilities["commands"] = list(TURNS)
            for name in ("turn_left_15", "turn_right_15"):
                with self.subTest(model=model, ready=ready, command=name), self.assertRaises(GatewayError):
                    await connection.service.queue_intent("emote", {"asset": name},
                                                           robot_id="test-body", received_at=100.0)
            self.assertEqual(socket.messages, [])
            self.assertEqual(connection.next_sequence, 1)

    async def test_gestures_keep_existing_wire_and_terminal_correlation_for_both_bodies(self) -> None:
        for name in GESTURES:
            sent = []
            translated = translate_environment_action({"type":"robotCommand", "command":name})
            expected = ("sit", {}) if name == "sit" else ("emote", {"asset":name})
            self.assertEqual((translated.name, translated.params), expected)
            for model in ("v1-8servo", "v2-12servo"):
                connection, socket = self.connection(model)
                if connection.capabilities is not None:
                    connection.capabilities["commands"] = ["walk", "stop", *TURNS, *GESTURES]
                seq = await connection.service.queue_intent(translated.name, translated.params,
                                                           robot_id="test-body", received_at=100.0)
                await connection._handle_control({"t":"ack", "seq":seq})
                self.assertIn(seq, connection.pending)
                # Cancellation uses the same session/action ownership as completion.
                terminal = {"t":"cancelled", "seq":seq, "reason":"stop"} if name == "rest" else {"t":"done", "seq":seq}
                await connection._handle_control(terminal)
                result = await connection.wait_terminal(seq, timeout=1)
                self.assertEqual(result["t"], terminal["t"])
                self.assertEqual(connection.service.terminals[-1]["epoch"], 7)
                sent.append(socket.messages)
            self.assertEqual(sent[0], sent[1])

    async def test_all_new_gestures_require_declaration_and_readiness(self) -> None:
        for ready in (False, True):
            connection, socket = self.connection("v2-12servo", ready=ready)
            connection.capabilities["commands"] = list(GESTURES) if not ready else ["walk", "stop"]
            for name in GESTURES:
                translated = translate_environment_action({"type":"robotCommand", "command":name})
                with self.subTest(ready=ready, command=name), self.assertRaises(GatewayError):
                    await connection.service.queue_intent(translated.name, translated.params,
                                                           robot_id="test-body", received_at=100.0)
            self.assertEqual(socket.messages, [])
            self.assertEqual(connection.next_sequence, 1)

    def test_complete_p4_catalog_stays_adapter_owned_and_ready_only(self) -> None:
        installed = ["walk", "stop", *TURNS, *GESTURES]
        class Gateway(FakeGateway):
            ready = True

            def status(self):
                result = super().status()
                result["robots"]["test-body"].update(model="v2-12servo", features=list(FEATURES),
                    capabilities={**capabilities(self.ready), "commands":installed})
                return result

        gateway = Gateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(receipt_path=":memory:", token="test"))
        self.addCleanup(adapter.receipts.close)
        observed = adapter._observation()["capabilities"]
        self.assertEqual(observed["robotCommands"], sorted(installed))
        self.assertEqual(set(observed["robotCommandDescriptions"]), set(installed))
        self.assertNotIn("twice", observed["robotCommandDescriptions"]["nod"])
        gateway.ready = False
        self.assertEqual(adapter._observation()["capabilities"]["robotCommands"], [])

    def test_new_turn_names_and_descriptions_are_only_advertised_when_declared_ready(self) -> None:
        class Gateway(FakeGateway):
            ready = True

            def status(self) -> dict[str, object]:
                result = super().status()
                result["robots"]["test-body"].update(model="v2-12servo", features=list(FEATURES),
                    capabilities={**capabilities(self.ready), "commands": list(TURNS)})
                return result

        gateway = Gateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(receipt_path=":memory:", token="test"))
        self.addCleanup(adapter.receipts.close)
        self.assertEqual(adapter._observation()["capabilities"]["robotCommands"], sorted(TURNS))
        gateway.ready = False
        self.assertEqual(adapter._observation()["capabilities"]["robotCommands"], [])
        self.assertNotIn("turn_left_15", LEGACY_ROBOT_COMMANDS)
        self.assertNotIn("turn_right_15", LEGACY_ROBOT_COMMANDS)
        for direction in ("left", "right"):
            for spelling in (f"turn_{direction}_15", f"turn {direction} 15 degrees"):
                translated = translate_environment_action({"type": "robotCommand", "command": spelling})
                self.assertEqual(translated.params, {"asset": f"turn_{direction}_15"})

    def test_adapter_advertises_only_body_subset_and_uses_existing_descriptions(self) -> None:
        class Gateway(FakeGateway):
            ready = True

            def status(self) -> dict[str, object]:
                result = super().status()
                result["robots"]["test-body"].update(model="v2-12servo", features=list(FEATURES), capabilities=capabilities(self.ready))
                return result

        gateway = Gateway()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(receipt_path=":memory:",token="test"))
        self.addCleanup(adapter.receipts.close)
        observation = adapter._observation()
        self.assertEqual(observation["capabilities"]["robotCommands"], ["stop","walk"])
        self.assertEqual(set(observation["capabilities"]["robotCommandDescriptions"]), {"stop","walk"})
        gateway.ready = False
        self.assertEqual(adapter._observation()["capabilities"]["robotCommands"], [])

    def test_new_models_never_inherit_legacy_catalog_without_declaration(self) -> None:
        self.assertIsNone(body_commands("v1-8servo",(),None))
        self.assertEqual(body_commands("v2-12servo",(),None),())
        self.assertEqual(body_commands("unknown",(),None),())
        self.assertEqual(body_commands("v2-12servo",FEATURES,capabilities(False)),())

    def test_handshake_requires_bounded_unique_command_names(self) -> None:
        hello = {"t":"hello","ver":1,"fw":"test","id":"p4","auth":"test","model":"v2-12servo",
                 "features":list(FEATURES),"capabilities":capabilities(False)}
        validate_control_message(hello)
        for commands in (None, ["walk","walk"], [""], [True], ["x"*33], [str(i) for i in range(65)]):
            with self.subTest(commands=commands), self.assertRaises(ProtocolValidationError):
                validate_control_message({**hello,"capabilities":{**capabilities(False),"commands":commands}})
        with self.assertRaises(ProtocolValidationError):
            validate_control_message({**hello,"features":["body_commands_v1"]})
