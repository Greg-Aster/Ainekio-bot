from __future__ import annotations

import asyncio
import base64
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from websockets.legacy.client import connect
from websockets.legacy.server import serve

from gateway.dashboard.server import start_dashboard_server
from gateway.depth_motion import rigid
from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.environment_adapter.speech_transport import SPEECH_AUDIO_MAGIC, parse_speech_audio_message
from gateway.environment_adapter.translation import translate_environment_action
from gateway.plugins import (
    CameraFramePlugin,
    virtual_default_camera_settings,
    virtual_default_depth_settings,
)
from gateway.security import DashboardPasswordStore, RobotTokenStore
from gateway.server.service import GatewayError, GatewayService, GatewayServiceConfig
from gateway.simulation import (
    SimulationManager,
    default_simulator_dist_dir,
    find_chrome_binary,
)


class SimulationManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_static_server_serves_wasm_and_blocks_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("<!doctype html><title>Sim</title>", encoding="utf-8")
            (dist / "sim").mkdir()
            (dist / "sim" / "test.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
            secret = Path(tmp) / "outside.txt"
            secret.write_text("top-secret", encoding="utf-8")

            token_store = RobotTokenStore(Path(tmp) / "tokens.json")
            gw = GatewayService(GatewayServiceConfig(tokens={}))
            mgr = SimulationManager(
                gateway=gw,
                event_loop=asyncio.get_running_loop(),
                token_store=token_store,
                simulator_port=0,
                dist_dir=dist,
                chrome_bin=None,
            )
            try:
                port = mgr.ensure_local_server()
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    conn.request("GET", "/")
                    resp = conn.getresponse()
                    self.assertEqual(resp.status, 200)
                    self.assertIn("text/html", resp.getheader("Content-Type", ""))
                    self.assertIn(b"<title>Sim</title>", resp.read())

                    conn.request("GET", "/sim/test.wasm")
                    resp2 = conn.getresponse()
                    self.assertEqual(resp2.status, 200)
                    self.assertEqual(resp2.getheader("Content-Type"), "application/wasm")
                    self.assertEqual(resp2.read(), b"\x00asm\x01\x00\x00\x00")

                    conn.request("GET", "/../outside.txt")
                    resp3 = conn.getresponse()
                    resp3.read()
                    self.assertIn(resp3.status, (403, 404))
                finally:
                    conn.close()
            finally:
                mgr.close()

    async def test_prepare_rotate_revoke_preserves_physical_tokens_and_encodes_pairing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_store = RobotTokenStore(Path(tmp) / "tokens.json")
            physical_token = token_store.generate("ainekio-p4-physical")
            gw = GatewayService(GatewayServiceConfig(tokens=token_store.snapshot()))

            dist = Path(tmp) / "dist"
            dist.mkdir()
            (dist / "index.html").write_text("ok", encoding="utf-8")

            mgr = SimulationManager(
                gateway=gw,
                event_loop=asyncio.get_running_loop(),
                token_store=token_store,
                gateway_port=8790,
                simulator_port=0,
                dist_dir=dist,
            )
            try:
                res = mgr.prepare(
                    {
                        "model": "v3",
                        "level": "observatory",
                        "mp": "host",
                        "room": "Wander Lab",
                        "display_name": "Ainekio V3",
                        "remote_ws_url": "robot-gateway.ainek.io",
                    },
                    request_host="192.168.0.44:8791",
                )
                self.assertEqual(res["settings"]["robot_id"], "ainekio-v3-sim")
                self.assertEqual(res["settings"]["room"], "wander-lab")
                self.assertEqual(res["links"]["room_invite_url"], "https://simulator.ainek.io/?room=wander-lab")

                launch = res["launch"]
                self.assertTrue(launch["local_simulator_url"].startswith("http://192.168.0.44:"))
                self.assertIn("#", launch["local_simulator_url"])
                self.assertIn("bc=ws%3A%2F%2F192.168.0.44%3A8790%2Frobot", launch["local_simulator_url"])
                self.assertTrue(launch["pairing_code"].startswith("ainekio-pair:"))

                b64 = launch["pairing_code"].split("ainekio-pair:", 1)[1]
                padded = b64 + "=" * (-len(b64) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(padded))
                self.assertEqual(decoded["bc"], "wss://robot-gateway.ainek.io/robot")
                self.assertEqual(decoded["robotId"], "ainekio-v3-sim")
                self.assertEqual(decoded["model"], "v3")
                self.assertEqual(decoded["level"], "observatory")
                self.assertEqual(decoded["mp"], "host")
                self.assertEqual(decoded["room"], "wander-lab")
                first_token = decoded["token"]

                # Physical robot token untouched
                self.assertEqual(token_store.snapshot()["ainekio-p4-physical"], physical_token)

                # Rotate virtual token
                rotated = mgr.prepare({"model": "v3"}, rotate=True)
                b64_2 = rotated["launch"]["pairing_code"].split("ainekio-pair:", 1)[1]
                decoded_2 = json.loads(base64.urlsafe_b64decode(b64_2 + "=" * (-len(b64_2) % 4)))
                self.assertNotEqual(decoded_2["token"], first_token)
                self.assertEqual(token_store.snapshot()["ainekio-p4-physical"], physical_token)

                # Revoke virtual token
                after_revoke = mgr.revoke_virtual_token("ainekio-v3-sim")
                self.assertFalse(after_revoke["robot"]["paired"])
                self.assertNotIn("ainekio-v3-sim", token_store.snapshot())
                self.assertEqual(token_store.snapshot()["ainekio-p4-physical"], physical_token)
            finally:
                mgr.close()

    async def test_dashboard_simulation_endpoints_require_auth_and_expose_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pw = DashboardPasswordStore(Path(tmp) / "auth.json")
            pw.set_password("secret-pass")
            tok = RobotTokenStore(Path(tmp) / "tokens.json")
            gw = GatewayService(GatewayServiceConfig(tokens={}))
            srv = start_dashboard_server(
                "127.0.0.1",
                0,
                gateway=gw,
                event_loop=asyncio.get_running_loop(),
                password_store=pw,
                token_store=tok,
            )
            thread = threading.Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            port = srv.server_address[1]
            try:
                def _run_http_checks() -> tuple[int, dict, dict]:
                    # Unauthenticated rejected
                    c0 = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
                    c0.request("GET", "/api/simulation")
                    r0 = c0.getresponse()
                    r0.read()
                    c0.close()

                    # Login
                    c1 = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
                    c1.request(
                        "POST",
                        "/api/login",
                        body=json.dumps({"password": "secret-pass"}),
                        headers={"Content-Type": "application/json"},
                    )
                    r_login = c1.getresponse()
                    cookie = r_login.getheader("Set-Cookie", "").split(";", 1)[0]
                    csrf = json.loads(r_login.read())["csrf"]
                    c1.close()

                    # Status does not leak secrets
                    c2 = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
                    c2.request("GET", "/api/status", headers={"Cookie": cookie})
                    st_res = json.loads(c2.getresponse().read())
                    c2.close()

                    # Prepare returns launch links & pairing code
                    c3 = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
                    c3.request(
                        "POST",
                        "/api/simulation",
                        body=json.dumps({"op": "prepare", "model": "v2", "mp": "join", "room": "lab-alpha"}),
                        headers={"Cookie": cookie, "X-Ainekio-CSRF": csrf, "Content-Type": "application/json"},
                    )
                    prep_res = json.loads(c3.getresponse().read())
                    c3.close()
                    return r0.status, st_res, prep_res

                status_401, st, prep = await asyncio.to_thread(_run_http_checks)
                self.assertEqual(status_401, 401)
                self.assertIn("simulation", st)
                self.assertNotIn("launch", st["simulation"])
                self.assertIn("launch", prep)
                self.assertTrue(prep["launch"]["pairing_code"].startswith("ainekio-pair:"))
                self.assertEqual(prep["settings"]["room"], "lab-alpha")
            finally:
                srv.shutdown()
                srv.server_close()

    async def test_room_chat_bridge_and_device_agnostic_v3_translation(self) -> None:
        # 1. Device-agnostic V3 move translation matches V2 ongoing turn & crab distance
        turn_v3 = translate_environment_action({"type": "move", "direction": "left"}, model="v3-12servo")
        self.assertIsNotNone(turn_v3)
        assert turn_v3 is not None
        self.assertEqual(turn_v3.params["steps"], 0)

        crab_v3 = translate_environment_action(
            {
                "type": "move",
                "gait": "crab",
                "locomotionGoal": {"kind": "distance", "direction": "left", "meters": 0.5},
            },
            model="v3-12servo",
        )
        self.assertIsNotNone(crab_v3)

        # SpeechAudioMessage optional text parsing
        meta = json.dumps(
            {
                "type": "audio.speech",
                "version": 1,
                "sessionId": "s1",
                "actionId": "act1",
                "speechId": "sp1",
                "format": "pcm_s16le",
                "sampleRateHz": 16000,
                "channels": 1,
                "frameBytes": 640,
                "durationMs": 20,
                "pcmBytes": 640,
                "text": "Hello explorer!",
            }
        ).encode("utf-8")
        import struct

        pkt = SPEECH_AUDIO_MAGIC + struct.pack("<I", len(meta)) + meta + (b"\x00" * 640)
        parsed_speech = parse_speech_audio_message(pkt, expected_session_id="s1")
        self.assertEqual(parsed_speech.text, "Hello explorer!")

        # 2. Bidirectional room_chat <-> assistant_text only on room_chat_v1 bodies
        with tempfile.TemporaryDirectory() as tmp:
            tokens = {"sim-bot": "tok-sim", "phys-bot": "tok-phys"}
            gw = GatewayService(GatewayServiceConfig(tokens=tokens))
            adapter = EnvironmentAdapter(
                gw,
                EnvironmentAdapterConfig(
                    token="bridge-tok-1234567890",
                    receipt_path=str(Path(tmp) / "receipts.sqlite"),
                    session_id="s1",
                ),
            )
            ws_srv = await serve(gw.handler, "127.0.0.1", 0, ping_interval=None)
            port = ws_srv.sockets[0].getsockname()[1]
            try:
                async with (
                    connect(f"ws://127.0.0.1:{port}/robot") as sim_ws,
                    connect(f"ws://127.0.0.1:{port}/robot") as phys_ws,
                ):
                    await sim_ws.send(
                        json.dumps(
                            {
                                "t": "hello",
                                "ver": 1,
                                "id": "sim-bot",
                                "auth": "tok-sim",
                                "fw": "virtual-v2",
                                "model": "v2-12servo",
                                "features": ["body_capabilities_v1", "room_chat_v1"],
                                "capabilities": {
                                    "motion": True,
                                    "speaker": True,
                                    "microphone": True,
                                    "camera": True,
                                    "display": True,
                                },
                            }
                        )
                    )
                    welcome_sim = json.loads(await sim_ws.recv())
                    self.assertEqual(welcome_sim["t"], "welcome")

                    await phys_ws.send(
                        json.dumps(
                            {
                                "t": "hello",
                                "ver": 1,
                                "id": "phys-bot",
                                "auth": "tok-phys",
                                "fw": "p4",
                                "model": "v2-12servo",
                                "features": ["body_capabilities_v1"],
                                "capabilities": {
                                    "motion": True,
                                    "speaker": True,
                                    "microphone": True,
                                    "camera": True,
                                    "display": True,
                                },
                            }
                        )
                    )
                    welcome_phys = json.loads(await phys_ws.recv())
                    self.assertEqual(welcome_phys["t"], "welcome")

                    robots_snap = gw.status()["robots"]
                    self.assertTrue(robots_snap["sim-bot"]["virtual"])
                    self.assertFalse(robots_snap["phys-bot"]["virtual"])
                    with self.assertRaises(GatewayError):
                        await gw.maintenance_address("sim-bot")

                    for model_name in ("v1-8servo", "v2-12servo", "v3-12servo"):
                        dcfg = virtual_default_depth_settings(model_name)
                        self.assertEqual(dcfg["mode"], "moge-open3d")
                        rigid(dcfg["cameraToBody"])
                    cam_plugin = CameraFramePlugin(gw, None)
                    self.assertEqual(cam_plugin._effective_depth_config("sim-bot")["mode"], "moge-open3d")
                    self.assertEqual(cam_plugin._effective_depth_config("phys-bot"), {})

                    # Inbound room_chat from simulator peer -> recorded in EnvironmentAdapter text stream
                    await sim_ws.send(
                        json.dumps(
                            {
                                "t": "event",
                                "name": "room_chat",
                                "id": "msg-42",
                                "room": "observatory",
                                "sender": "Greggles",
                                "text": "Where are you heading?",
                            }
                        )
                    )
                    await asyncio.sleep(0.05)
                    stream_msgs = adapter.connection_status()["messages"]
                    self.assertTrue(
                        any(m["text"] == "Where are you heading?" for m in stream_msgs),
                        stream_msgs,
                    )

                    # Outbound assistant reply -> delivered ONLY to sim_ws (room_chat_v1), NOT phys_ws, and deduplicated
                    await gw.publish_transcript(
                        {
                            "source": "environment_adapter",
                            "session_id": "s1",
                            "text": "Exploring the upper ramp!",
                        }
                    )
                    await gw.publish_transcript(
                        {
                            "source": "environment_adapter",
                            "session_id": "s1",
                            "text": "Exploring the upper ramp!",
                        }
                    )
                    rx = json.loads(await asyncio.wait_for(sim_ws.recv(), timeout=2.0))
                    self.assertEqual(rx, {"t": "event", "name": "assistant_text", "text": "Exploring the upper ramp!"})
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(sim_ws.recv(), timeout=0.1)
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(phys_ws.recv(), timeout=0.1)

                    # Outbound user_transcript (voice STT / Body Control chat) -> delivered to sim_ws
                    await gw.publish_transcript(
                        {
                            "source": "environment_adapter",
                            "session_id": "s1",
                            "role": "user",
                            "text": "Hey Ainekio!",
                        }
                    )
                    rx_user = json.loads(await asyncio.wait_for(sim_ws.recv(), timeout=2.0))
                    self.assertEqual(rx_user, {"t": "event", "name": "user_transcript", "text": "Hey Ainekio!"})
            finally:
                ws_srv.close()
                await ws_srv.wait_closed()

    async def test_headless_chrome_boots_wasm_and_connects_to_gateway(self) -> None:
        dist = default_simulator_dist_dir()
        chrome = find_chrome_binary()
        if not (dist / "index.html").is_file() or not chrome:
            self.skipTest("Built simulator dist or Chrome binary not present")

        with tempfile.TemporaryDirectory() as tmp:
            tok = RobotTokenStore(Path(tmp) / "tokens.json")
            gw = GatewayService(GatewayServiceConfig(tokens={}))
            frames_seen: list[int] = []
            gw.subscribe_frames(lambda f: frames_seen.append(int(f.get("frame_type", 0))))

            ws_srv = await serve(gw.handler, "127.0.0.1", 0, ping_interval=None)
            gw_port = ws_srv.sockets[0].getsockname()[1]
            mgr = SimulationManager(
                gateway=gw,
                event_loop=asyncio.get_running_loop(),
                token_store=tok,
                gateway_port=gw_port,
                simulator_port=0,
                dist_dir=dist,
                chrome_bin=chrome,
            )
            try:
                started = mgr.start_headless({"model": "v2", "level": "v2_lab", "mp": "solo"})
                self.assertTrue(started["headless"]["running"])
                deadline = time.monotonic() + 15.0
                connected = False
                has_imu = False
                while time.monotonic() < deadline:
                    await asyncio.sleep(0.25)
                    st = mgr.status()
                    r_entry = gw.status().get("robots", {}).get("ainekio-v2-sim")
                    if st["robot"]["connected"] and r_entry:
                        connected = True
                        if (r_entry.get("status") or {}).get("imu"):
                            has_imu = True
                            break
                self.assertTrue(connected, f"Headless Chrome did not connect to /robot: {mgr.status()}")
                self.assertTrue(has_imu, "Headless Chrome connected but did not stream 50 Hz IMU telemetry")

                # Same-host browser via LAN IP gets 127.0.0.1 secure-context URLs; distinct LAN client keeps LAN IP
                same_host = mgr.status(request_host="192.168.0.44:8791", client_host="192.168.0.44", include_secrets=True)
                self.assertTrue(same_host["launch"]["local_simulator_url"].startswith("http://127.0.0.1:"))
                other_lan = mgr.status(request_host="192.168.0.44:8791", client_host="192.168.0.99", include_secrets=True)
                self.assertTrue(other_lan["launch"]["local_simulator_url"].startswith("http://192.168.0.44:"))

                # Opening an interactive tab while Solo headless is running automatically stops Solo headless
                tab_prep = mgr.prepare({"model": "v2", "level": "v2_lab", "mp": "solo"}, for_tab=True)
                self.assertTrue(tab_prep["launch"]["stopped_solo_headless"])
                self.assertFalse(tab_prep["headless"]["running"])
            finally:
                mgr.close()
                ws_srv.close()
                await ws_srv.wait_closed()

    def test_virtual_firmware_utterance_snapshot_and_camera_boot_parity(self) -> None:
        import numpy as np
        from gateway.neural_gait.native import BodyModel, VirtualBody
        from tests.test_neural_gait_sensors import robot_fixture

        self.assertEqual(
            virtual_default_camera_settings(),
            {
                "on": True,
                "fps": 1,
                "resolution": "VGA",
                "snapshot_resolution": "960P",
                "max_exposure_us": 0,
            },
        )

        robot = robot_fixture()
        robot["feedback"]["stand_enabled"] = True
        body = BodyModel(robot)
        pose = np.array([0.0, -5.46, -62.08] * 4)
        now_us = 1_000_000
        fw = VirtualBody(
            body,
            pose,
            joint_speed_deg_s=60.0 / 0.11,
            motion_rate=1.0,
            balance=False,
            heading_feedback=False,
            balance_tuning=(1.0, 1.0, 0.0, 0.0),
            idle_rest_seconds=0,
            now_us=now_us,
            full_parity=True,
        )
        try:
            fw.lib.virtual_body_open(1, now_us)
            fw.receive({"t": "welcome", "ver": 1, "epoch": 1, "profile": "home", "command_deadline_v1": True}, 1, now_us)
            fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"

            # 1. Camera boots OFF matching physical ESP32-P4 camera.c
            boot_stream = fw.camera_frame(now_us, fake_jpeg, origin="none", res="VGA")
            self.assertEqual(boot_stream["packet"], b"")
            self.assertIsNone(boot_stream["meta"])

            # 2. Gateway 1 FPS VGA camera command enables streaming & 960P still resolution
            now_us += 20_000
            ack = fw.receive(
                {
                    "t": "cam",
                    "seq": 1,
                    "epoch": 1,
                    "deadline_ms": 5000,
                    "on": True,
                    "fps": 1,
                    "res": "VGA",
                    "snapshot_res": "960P",
                },
                1,
                now_us,
            )
            self.assertEqual(ack[0]["t"], "ack")
            cam_actions = fw.media_actions()
            self.assertEqual(cam_actions[0]["kind"], "camera")
            self.assertEqual(cam_actions[0]["fps"], 1)
            live_stream = fw.camera_frame(now_us, fake_jpeg, origin="none", res="VGA", frame_completed_us=now_us, boot_id=7)
            self.assertEqual(live_stream["meta"]["fps"], 1)
            self.assertEqual(live_stream["meta"]["res"], "VGA")
            self.assertEqual(live_stream["meta"]["boot_id"], 7)
            self.assertTrue(len(live_stream["packet"]) > len(fake_jpeg))

            # 3. Utterance 1 (>= 300 ms): origin_id matches first PCM counter (0) and triggers 960P audio snapshot
            vad_open_1 = fw.mic_gate(now_us, open=True)
            self.assertEqual(vad_open_1, {"t": "event", "name": "vad_open", "origin_id": 0})
            tone_pcm = (np.full(320, 4096, dtype="<i2")).tobytes()
            for _ in range(16):
                now_us += 20_000
                pkt = fw.mic_frame(now_us, tone_pcm)
                self.assertEqual(len(pkt), 645)
            hb = fw.heartbeat(now_us, pong=True)
            self.assertTrue(hb["audio"]["capturing"])
            self.assertGreater(hb["audio"]["rms"], 0.05)

            vad_close_1 = fw.mic_gate(now_us, open=False)
            self.assertEqual(vad_close_1, {"t": "event", "name": "vad_close", "origin_id": 0})
            snap_actions = fw.media_actions()
            self.assertEqual(len(snap_actions), 1)
            self.assertEqual(snap_actions[0]["kind"], "snapshot")
            self.assertEqual(snap_actions[0]["origin"], "audio")
            self.assertEqual(snap_actions[0]["origin_id"], 0)
            self.assertEqual(snap_actions[0]["res"], "960P")

            audio_still = fw.camera_frame(
                now_us,
                fake_jpeg,
                origin="audio",
                origin_id=snap_actions[0]["origin_id"],
                res=snap_actions[0]["res"],
                frame_completed_us=now_us,
                boot_id=7,
            )
            self.assertEqual(audio_still["meta"]["origin"], "audio")
            self.assertEqual(audio_still["meta"]["origin_id"], 0)
            self.assertEqual(audio_still["meta"]["fps"], 0)
            self.assertEqual(audio_still["meta"]["res"], "960P")
            self.assertIsNone(audio_still["done"])

            # 4. Utterance 2 picks up monotonic microphone_counter = 16
            now_us += 20_000
            vad_open_2 = fw.mic_gate(now_us, open=True)
            self.assertEqual(vad_open_2, {"t": "event", "name": "vad_open", "origin_id": 16})
            now_us += 320_000
            vad_close_2 = fw.mic_gate(now_us, open=False)
            self.assertEqual(vad_close_2, {"t": "event", "name": "vad_close", "origin_id": 16})
            snap_actions_2 = fw.media_actions()
            self.assertEqual(snap_actions_2[0]["origin_id"], 16)
        finally:
            fw.close()

    async def test_typed_room_chat_and_operator_text_attach_firmware_snapshot_visual(self) -> None:
        import numpy as np
        from gateway.neural_gait.native import BodyModel, VirtualBody
        from tests.test_neural_gait_sensors import robot_fixture

        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
        robot = robot_fixture()
        robot["feedback"]["stand_enabled"] = True
        body = BodyModel(robot)
        pose = np.array([0.0, -5.46, -62.08] * 4)
        now_us = 1_000_000
        fw = VirtualBody(
            body,
            pose,
            joint_speed_deg_s=60.0 / 0.11,
            motion_rate=1.0,
            balance=False,
            heading_feedback=False,
            balance_tuning=(1.0, 1.0, 0.0, 0.0),
            idle_rest_seconds=0,
            now_us=now_us,
            full_parity=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            gw = GatewayService(GatewayServiceConfig(tokens={"ainekio-v2-sim": "tok-sim"}))
            adapter = EnvironmentAdapter(
                gw,
                EnvironmentAdapterConfig(
                    token="bridge-tok-1234567890",
                    receipt_path=str(Path(tmp) / "receipts.sqlite"),
                    session_id="s1",
                ),
            )

            async def route(ws, path):
                if path == "/environment":
                    await adapter.handler(ws)
                else:
                    await gw.handler(ws, path)

            ws_srv = await serve(route, "127.0.0.1", 0, ping_interval=None)
            port = ws_srv.sockets[0].getsockname()[1]
            robot_pump_task: asyncio.Task[None] | None = None
            try:
                async with (
                    connect(f"ws://127.0.0.1:{port}/robot") as sim_ws,
                    connect(f"ws://127.0.0.1:{port}/environment") as env_ws,
                ):
                    fw.lib.virtual_body_open(1, now_us)
                    hello = fw.hello("ainekio-v2-sim", "tok-sim", now_us)
                    hello["features"] = [*hello["features"], "room_chat_v1"]
                    await sim_ws.send(json.dumps(hello))
                    welcome_raw = await sim_ws.recv()
                    fw.receive(welcome_raw, 1, now_us)
                    await sim_ws.send(json.dumps(fw.status(now_us)))

                    async def pump_robot():
                        nonlocal now_us
                        while True:
                            incoming = await sim_ws.recv()
                            if isinstance(incoming, str):
                                now_us += 20_000
                                for reply in fw.receive(incoming, 1, now_us):
                                    await sim_ws.send(json.dumps(reply))
                                for act in fw.media_actions():
                                    if act.get("kind") == "snapshot":
                                        res = fw.camera_frame(
                                            now_us,
                                            fake_jpeg,
                                            origin=act.get("origin", "request"),
                                            origin_id=int(act.get("origin_id") or act.get("seq") or 0),
                                            res=str(act.get("res") or "960P"),
                                            frame_completed_us=now_us,
                                            boot_id=1,
                                        )
                                        if res["meta"]:
                                            await sim_ws.send(json.dumps(res["meta"]))
                                        if res["packet"]:
                                            await sim_ws.send(res["packet"])
                                        if res["done"]:
                                            await sim_ws.send(json.dumps(res["done"]))

                    robot_pump_task = asyncio.create_task(pump_robot())

                    # Authenticate Environment Bridge
                    await env_ws.send(json.dumps({"type": "bridge.connect", "version": 1, "token": "bridge-tok-1234567890"}))
                    ready_msg = json.loads(await asyncio.wait_for(env_ws.recv(), timeout=2.0))
                    self.assertEqual(ready_msg["type"], "bridge.ready")

                    async def next_player_observation() -> dict[str, object]:
                        while True:
                            raw_msg = await asyncio.wait_for(env_ws.recv(), timeout=3.0)
                            if not isinstance(raw_msg, str):
                                continue
                            msg = json.loads(raw_msg)
                            if msg.get("type") == "environment.observation":
                                obs = msg["observation"]
                                await env_ws.send(
                                    json.dumps(
                                        {
                                            "type": "environment.observation.ack",
                                            "version": 1,
                                            "observationId": obs["id"],
                                        }
                                    )
                                )
                                if obs.get("text"):
                                    return obs

                    # 1. Body Control typed turn -> captures firmware still and pairs visual with text
                    send_task = asyncio.create_task(adapter.submit_operator_text("what do toy see?"))
                    obs1 = await next_player_observation()
                    await send_task
                    self.assertEqual(obs1["text"][0]["text"], "what do toy see?")
                    self.assertIsNotNone(obs1.get("visual"))
                    self.assertTrue(str(obs1["visual"]["dataUrl"]).startswith("data:image/jpeg;base64,"))
                    self.assertEqual(obs1["visual"]["metadata"]["correlationId"], obs1["text"][0]["id"])

                    # 2. Simulator room_chat turn -> captures firmware still and pairs visual with text
                    await sim_ws.send(
                        json.dumps(
                            {
                                "t": "event",
                                "name": "room_chat",
                                "id": "sim-turn-2",
                                "sender": "Operator",
                                "text": "please walk forward",
                            }
                        )
                    )
                    obs2 = await next_player_observation()
                    self.assertEqual(obs2["text"][0]["text"], "please walk forward")
                    self.assertNotIn("[Operator]", obs2["text"][0]["text"])
                    self.assertIsNotNone(obs2.get("visual"))
                    self.assertEqual(obs2["visual"]["metadata"]["correlationId"], "room-chat:sim-turn-2")
            finally:
                if robot_pump_task is not None:
                    robot_pump_task.cancel()
                    await asyncio.gather(robot_pump_task, return_exceptions=True)
                ws_srv.close()
                await ws_srv.wait_closed()
                fw.close()


if __name__ == "__main__":
    unittest.main()
