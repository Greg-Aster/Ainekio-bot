import unittest
from datetime import datetime, timezone
from typing import Any

from ainekio_motion.adapter import (
    ENVIRONMENT_BRIDGE_ACTION_RESULT,
    ENVIRONMENT_BRIDGE_OBSERVATION,
    ENVIRONMENT_BRIDGE_STREAM,
    AinekioEnvironmentAdapter,
)
from ainekio_motion.backend import VirtualBackend
from ainekio_motion.metahuman import BridgeEvent


class FakeBridgeClient:
    def __init__(self, events: list[BridgeEvent] | None = None) -> None:
        self.events = events or []
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.streams: list[tuple[str, dict[str, Any] | None]] = []

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.posts.append((path, payload))
        return {"success": True}

    def stream_events(self, path: str, *, query: dict[str, Any] | None = None) -> list[BridgeEvent]:
        self.streams.append((path, query))
        return self.events


class FakeSimulatorPublisher:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def publish_motion(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


class AinekioEnvironmentAdapterTests(unittest.TestCase):
    def test_stream_results_handles_pushed_move_and_reports_completed(self) -> None:
        client = FakeBridgeClient(
            [
                BridgeEvent("connected", {"sessionId": "ainekio-sim-1", "enabled": True}),
                BridgeEvent(
                    "actions",
                    {
                        "actions": [
                            {
                                "id": "action-1",
                                "type": "move",
                                "direction": "forward",
                                "durationMs": 750,
                                "createdAt": datetime.now(timezone.utc).isoformat(),
                            }
                        ]
                    },
                ),
            ]
        )
        backend = VirtualBackend()
        adapter = AinekioEnvironmentAdapter(
            client=client,
            backend=backend,
            max_action_age_ms=10_000,
        )

        results = list(adapter.stream_results())

        self.assertEqual(results[0].status, "completed")
        self.assertEqual(results[0].command, "walk")
        self.assertGreater(results[0].frames, 0)
        self.assertEqual(client.posts[0][0], ENVIRONMENT_BRIDGE_OBSERVATION)
        self.assertEqual(client.streams[0], (ENVIRONMENT_BRIDGE_STREAM, {"sessionId": "ainekio-sim-1", "limit": 10}))
        self.assertEqual(client.posts[-1][0], ENVIRONMENT_BRIDGE_ACTION_RESULT)
        self.assertEqual(client.posts[-1][1]["type"], "completed")
        self.assertEqual(backend.telemetry[-1].command.value, "walk")

    def test_publishes_robot_command_to_simulator_shim(self) -> None:
        client = FakeBridgeClient()
        simulator = FakeSimulatorPublisher()
        adapter = AinekioEnvironmentAdapter(
            client=client,
            simulator=simulator,
            max_action_age_ms=10_000,
        )

        result = adapter.handle_action(
            {
                "id": "action-sim",
                "type": "robotCommand",
                "command": "walk",
                "simulatorCommand": "run walk",
                "units": 5,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.command, "walk")
        self.assertEqual(len(simulator.payloads), 1)
        self.assertEqual(simulator.payloads[0]["source"], "ainekio-adapter")
        self.assertEqual(simulator.payloads[0]["sessionId"], "ainekio-sim-1")
        self.assertEqual(simulator.payloads[0]["command"], "walk")
        self.assertEqual(simulator.payloads[0]["simulatorCommand"], "run walk")
        self.assertEqual(simulator.payloads[0]["units"], 5)
        self.assertGreater(len(simulator.payloads[0]["frames"]), 0)

    def test_acknowledges_send_text_without_motion(self) -> None:
        client = FakeBridgeClient()
        simulator = FakeSimulatorPublisher()
        adapter = AinekioEnvironmentAdapter(client=client, simulator=simulator)

        result = adapter.handle_action({"id": "action-text", "type": "sendText", "text": "hello"}, at_ms=100)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.message, "text_received")
        self.assertEqual(result.command, "sendText")
        self.assertEqual(result.frames, 0)
        self.assertEqual(simulator.payloads, [])

    def test_rejects_unsupported_action(self) -> None:
        client = FakeBridgeClient()
        adapter = AinekioEnvironmentAdapter(client=client)

        result = adapter.handle_action({"id": "action-2", "type": "jump"}, at_ms=100)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.message, "unsupported_action:jump")

    def test_rejects_stale_action(self) -> None:
        client = FakeBridgeClient()
        adapter = AinekioEnvironmentAdapter(client=client, max_action_age_ms=100)

        result = adapter.handle_action(
            {
                "id": "action-3",
                "type": "move",
                "direction": "forward",
                "createdAt": "1970-01-01T00:00:00+00:00",
            },
            at_ms=1000,
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.message, "action_expired")


if __name__ == "__main__":
    unittest.main()
