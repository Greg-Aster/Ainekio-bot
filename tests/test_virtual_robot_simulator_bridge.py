"""End-to-end tests for the full-parity MuJoCo V2 Virtual Robot Simulator Bridge."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import struct

import pytest
from websockets.legacy.server import serve

from gateway.neural_gait.simulator_bridge import (
    BRIDGE_BIN_CAMERA_JPEG,
    BRIDGE_BIN_FACE_RGBA,
    BRIDGE_BIN_MIC_PCM,
    BRIDGE_BIN_SPEAKER_PCM,
    CAMERA_ORIGIN_REQUEST,
    VirtualRobotSimulatorBridge,
)
from gateway.server.service import GatewayService, GatewayServiceConfig
from protocol.binary_helpers import AUDIO_PAYLOAD_BYTES


def _minimal_jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def test_virtual_robot_simulator_full_parity_with_body_control_and_megameal(tmp_path: Path) -> None:
    async def run_scenario() -> None:
        robot_id = "ainekio-v2-sim-test"
        token = "sim-test-secret-token-123456"
        gateway = GatewayService(GatewayServiceConfig(tokens={robot_id: token}))
        received_media: list[dict[str, object]] = []
        gateway.subscribe_frames(lambda item: received_media.append(dict(item)))

        # Minimal Megameal relay server recording sim frames and injecting game responses.
        megameal_states: list[dict[str, object]] = []
        megameal_face_frames: list[bytes] = []
        megameal_speaker_frames: list[bytes] = []
        megameal_camera_requests: list[dict[str, object]] = []
        sim_ws_holder: list[object] = []

        async def relay_handler(ws, path):
            assert path == "/__megameal-dev-bridge"
            hello = json.loads(await ws.recv())
            assert hello["type"] == "bridge:hello"
            assert hello["role"] == "robot-sim"
            sim_ws_holder.append(ws)
            await ws.send(json.dumps({"type": "bridge:ready", "role": "robot-sim", "gameSessions": ["game-1"]}))
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    data = bytes(raw)
                    if data[0] == BRIDGE_BIN_FACE_RGBA:
                        megameal_face_frames.append(data)
                    elif data[0] == BRIDGE_BIN_SPEAKER_PCM:
                        megameal_speaker_frames.append(data)
                else:
                    msg = json.loads(raw)
                    if msg.get("type") == "robot:state":
                        megameal_states.append(msg)
                    elif msg.get("type") == "robot:camera-request":
                        megameal_camera_requests.append(msg)
                        # Simulate Megameal rendering the OV5647 chin camera JPEG
                        header = struct.pack(
                            "<BBHHI",
                            BRIDGE_BIN_CAMERA_JPEG,
                            int(msg["originCode"]),
                            1,  # VGA
                            0,
                            int(msg["originId"]),
                        )
                        await ws.send(header + _minimal_jpeg())

        gw_server = await serve(gateway.handler, "127.0.0.1", 0, ping_interval=None)
        mm_server = await serve(relay_handler, "127.0.0.1", 0, ping_interval=None)
        gw_port = gw_server.sockets[0].getsockname()[1]
        mm_port = mm_server.sockets[0].getsockname()[1]

        bridge = VirtualRobotSimulatorBridge(
            gateway_url=f"ws://127.0.0.1:{gw_port}/robot",
            megameal_url=f"ws://127.0.0.1:{mm_port}/__megameal-dev-bridge",
            robot_id=robot_id,
            token=token,
            arena_geometry_path=None,
            recordings_dir=tmp_path / "recordings",
            include_assembly=False,
            real_time=True,
        )
        runner = asyncio.create_task(bridge.run())
        try:
            # Wait for both Body Control and Megameal to connect & produce telemetry + face
            for _ in range(120):
                if bridge.gateway_connected and bridge.megameal_connected and megameal_face_frames and megameal_states:
                    break
                await asyncio.sleep(0.05)

            assert bridge.gateway_connected, "Virtual V2 body did not authenticate with Body Control"
            assert bridge.megameal_connected, "Virtual V2 body did not connect to Megameal relay"
            assert len(megameal_states) >= 1
            assert len(megameal_face_frames) >= 1
            # Verify 320x170 RGBA face payload size (10-byte header + 320*170*4)
            tag, w, h, _seq, flags = struct.unpack("<BHHIB", megameal_face_frames[0][:10])
            assert (tag, w, h, flags) == (BRIDGE_BIN_FACE_RGBA, 320, 170, 0)
            assert len(megameal_face_frames[0]) == 10 + 320 * 170 * 4

            # Start rollout recording from Megameal
            sim_ws = sim_ws_holder[0]
            await sim_ws.send(json.dumps({"type": "robot:record:start", "label": "parity_check"}))

            # 1. Real Body Control face command -> renders happy face + sets face_token
            face_seq = await gateway.queue_intent(
                "face", {"expr": "happy", "token": "sim_face_tok"}, robot_id=robot_id
            )
            face_done = await gateway.wait_terminal(face_seq, robot_id=robot_id, timeout=3.0)
            assert face_done["t"] == "done"

            # 2. Real Body Control camera snapshot -> Megameal renders JPEG -> Body Control receives JPEG + done
            snap_seq = await gateway.request_snap(robot_id=robot_id)
            snap_done = await gateway.wait_terminal(snap_seq, robot_id=robot_id, timeout=3.0)
            assert snap_done["t"] == "done"
            assert any(req["origin"] == "request" for req in megameal_camera_requests)
            assert any(m.get("frame_type") == 0x02 for m in received_media)

            # 3. Real Body Control TTS audio stream -> Megameal receives speaker PCM -> done receipt
            pcm_chunk = b"\x10\x00" * (AUDIO_PAYLOAD_BYTES // 2)
            tts_seq = await gateway.tts_speak([pcm_chunk, pcm_chunk], robot_id=robot_id)
            tts_done = await gateway.wait_terminal(tts_seq, robot_id=robot_id, timeout=4.0)
            assert tts_done["t"] == "done"
            assert len(megameal_speaker_frames) >= 2

            # 4. Real Megameal mic Tap-to-Talk -> Body Control receives MIC PCM frames
            # Wait past post-TTS external speech cooldown or clear it so mic opens cleanly
            bridge.external_speech = False
            await sim_ws.send(json.dumps({"type": "robot:interact:mic-gate", "capturing": True}))
            mic_hdr = struct.pack("<BIB", BRIDGE_BIN_MIC_PCM, 1, 0x01)
            await sim_ws.send(mic_hdr + (b"\x20\x00" * (AUDIO_PAYLOAD_BYTES // 2)))
            await asyncio.sleep(0.1)
            await sim_ws.send(json.dumps({"type": "robot:interact:mic-gate", "capturing": False}))
            await asyncio.sleep(0.1)
            assert any(m.get("frame_type") == 0x01 for m in received_media)

            # 5. Real Body Control motion command (stand) + player wrench & joint pin
            stand_seq = await gateway.queue_intent("stand", {}, robot_id=robot_id)
            conn = gateway._connection(robot_id)
            await conn.wait_acknowledged(stand_seq, timeout=3.0)

            await sim_ws.send(
                json.dumps(
                    {
                        "type": "robot:interact:wrench",
                        "forceMj": [0.0, 2.0, 0.0],
                        "torqueMj": [0.2, 0.0, 0.0],
                        "durationMs": 150,
                    }
                )
            )
            await sim_ws.send(
                json.dumps({"type": "robot:interact:pin-joint", "jointIndex": 6, "pinned": True})
            )
            await asyncio.sleep(0.25)
            assert 6 in bridge.pinned_joints
            await sim_ws.send(json.dumps({"type": "robot:interact:clear-pins"}))
            await asyncio.sleep(0.05)
            assert not bridge.pinned_joints

            # 6. Stop rollout recording and verify synchronized training artifacts
            await sim_ws.send(json.dumps({"type": "robot:record:stop"}))
            await asyncio.sleep(0.1)
            rec_dirs = list((tmp_path / "recordings").iterdir())
            assert len(rec_dirs) == 1
            rec_dir = rec_dirs[0]
            assert (rec_dir / "metadata.json").exists()
            assert (rec_dir / "summary.json").exists()
            telemetry_lines = (rec_dir / "telemetry.jsonl").read_text().strip().splitlines()
            assert len(telemetry_lines) >= 5
            sample_row = json.loads(telemetry_lines[-1])
            assert len(sample_row["qpos_joints_deg"]) == 12
            assert len(sample_row["measured_deg"]) == 12
            assert len(sample_row["imu_accel_m_s2"]) == 3
            assert len(sample_row["foot_contact"]) == 4

            # Verify live state pushed to Megameal includes 12 joints, face, IMU, foot contacts
            latest_state = megameal_states[-1]
            assert len(latest_state["jointsDeg"]) == 12
            assert len(latest_state["footContacts"]) == 4
            assert latest_state["face"]["name"] == "happy"
            assert latest_state["face"]["token"] == "sim_face_tok"
        finally:
            bridge._running = False
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)
            bridge.close()
            gw_server.close()
            mm_server.close()
            await gw_server.wait_closed()
            await mm_server.wait_closed()

    asyncio.run(run_scenario())
