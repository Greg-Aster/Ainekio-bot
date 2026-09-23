from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from typing import Mapping

from emulator.body import BodySession, PortableCore
from emulator.body.calibration import CalibrationStore
from emulator.body.media import EnergyVad, FixtureCameraSource, QueueMicrophoneSource
from emulator.faults import EmulatorFaultController
from protocol.binary_helpers import (
    CAMERA_JPEG_FRAME_TYPE,
    MAX_BINARY_COUNTER,
    MAX_JPEG_BYTES,
    MIC_PCM_FRAME_TYPE,
    SPEAKER_PCM_FRAME_TYPE,
    decode_binary_frame,
    encode_binary_frame,
)
from Emulator.tests.support import build_core_library


class ImmediateMotionBackend:
    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        return None

    async def stop(self, sequence: int, *, session_id: str) -> None:
        return None


class BodyMediaTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library_path = build_core_library()

    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.now = 0.0
        self.core = PortableCore(self.library_path)
        self.camera = FixtureCameraSource(b"\xff\xd8fixture\xff\xd9")
        self.microphone = QueueMicrophoneSource()
        self.session = BodySession(
            self.core,
            ImmediateMotionBackend(),
            CalibrationStore(Path(self.temporary_directory.name) / "calibration.json"),
            clock=lambda: self.now,
            camera_source=self.camera,
            microphone_source=self.microphone,
        )
        self.controls: list[dict[str, object]] = []
        self.frames: list[bytes] = []
        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 1, "profile": "home"}
        )

    async def asyncTearDown(self) -> None:
        await self.session.close()
        self.core.close()
        self.temporary_directory.cleanup()

    async def emit(self, message: dict[str, object]) -> None:
        self.controls.append(message)

    async def emit_binary(self, frame: bytes) -> None:
        self.frames.append(frame)

    async def test_snapshot_ack_meta_binary_done_lifecycle(self) -> None:
        await self.session.handle(
            {"t": "snap", "seq": 1},
            self.emit,
            self.emit_binary,
        )

        self.assertEqual(
            self.controls,
            [
                {"t": "ack", "seq": 1},
                {
                    "t": "cam_meta",
                    "res": "XGA",
                    "fps": 0,
                    "counter_base": 0,
                    "origin": "request",
                    "origin_id": 1,
                },
                {"t": "done", "seq": 1},
            ],
        )
        decoded = decode_binary_frame(self.frames[0])
        self.assertEqual(decoded.frame_type, CAMERA_JPEG_FRAME_TYPE)
        self.assertEqual(decoded.counter, 0)
        self.assertTrue(self.core.servos_attached)

    async def test_completed_motion_emits_snapshot_before_done(self) -> None:
        await self.session.handle(
            {"t": "intent", "seq": 2, "name": "stand"},
            self.emit,
            self.emit_binary,
        )
        await self.session.wait_until_idle()

        self.assertEqual(self.controls[0], {"t": "ack", "seq": 2})
        self.assertEqual(
            self.controls[-2],
            {
                "t": "cam_meta",
                "res": "XGA",
                "fps": 0,
                "counter_base": 0,
                "origin": "action",
                "origin_id": 2,
            },
        )
        self.assertEqual(self.controls[-1], {"t": "done", "seq": 2})
        self.assertEqual(
            decode_binary_frame(self.frames[-1]).frame_type,
            CAMERA_JPEG_FRAME_TYPE,
        )

    async def test_completed_freestyle_plan_emits_snapshot_before_done(self) -> None:
        await self.session.handle(
            {
                "t": "motion_plan",
                "seq": 3,
                "map": 1,
                "frames": [
                    [300, [9000, 9000, 9000, 9000, 9000, 9000, 9000, 9000]]
                ],
                "end": "hold",
            },
            self.emit,
            self.emit_binary,
        )
        await self.session.wait_until_idle()

        self.assertEqual(self.controls[0], {"t": "ack", "seq": 3})
        self.assertEqual(
            self.controls[-2],
            {
                "t": "cam_meta",
                "res": "XGA",
                "fps": 0,
                "counter_base": 0,
                "origin": "action",
                "origin_id": 3,
            },
        )
        self.assertEqual(self.controls[-1], {"t": "done", "seq": 3})
        self.assertEqual(
            decode_binary_frame(self.frames[-1]).frame_type,
            CAMERA_JPEG_FRAME_TYPE,
        )

    async def test_camera_is_optional_and_audio_streaming_still_works(self) -> None:
        await self.session.close()
        self.core.close()
        self.core = PortableCore(self.library_path)
        self.microphone = QueueMicrophoneSource([
            struct.pack("<320h", *([1200] * 320))
        ])
        self.session = BodySession(
            self.core,
            ImmediateMotionBackend(),
            clock=lambda: self.now,
            microphone_source=self.microphone,
        )
        self.controls.clear()
        self.frames.clear()
        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 2, "profile": "home"}
        )

        self.assertFalse(self.session.status()["camera_ready"])
        await self.session.handle(
            {"t": "snap", "seq": 1},
            self.emit,
            self.emit_binary,
        )
        await self.session.handle(
            {"t": "cam", "seq": 2, "on": True, "fps": 5, "res": "VGA"},
            self.emit,
        )
        await self.session.handle(
            {"t": "mic", "seq": 3, "on": True, "gate": "open"},
            self.emit,
        )
        await self.session.service_media(self.emit, self.emit_binary)

        self.assertEqual(
            self.controls[:2],
            [
                {"t": "nak", "seq": 1, "code": "busy", "msg": "camera unavailable"},
                {"t": "ack", "seq": 2},
            ],
        )
        self.assertEqual(
            decode_binary_frame(self.frames[0]).frame_type,
            MIC_PCM_FRAME_TYPE,
        )

    async def test_camera_stream_respects_state_and_counts_oversize_drop(self) -> None:
        await self.session.handle(
            {"t": "cam", "seq": 1, "on": True, "fps": 5, "res": "VGA"},
            self.emit,
        )
        await self.session.handle(
            {"t": "state", "seq": 2, "name": "idle"},
            self.emit,
        )
        await self.session.service_media(self.emit, self.emit_binary)
        self.assertEqual(self.frames, [])

        await self.session.handle(
            {"t": "intent", "seq": 3, "name": "stand"},
            self.emit,
        )
        await self.session.wait_until_idle()
        await self.session.service_media(self.emit, self.emit_binary)
        self.assertEqual(decode_binary_frame(self.frames[0]).frame_type, CAMERA_JPEG_FRAME_TYPE)

        self.now = 1.0
        self.camera.jpeg = bytes(MAX_JPEG_BYTES + 1)
        await self.session.service_media(self.emit, self.emit_binary)
        self.assertEqual(self.session.status()["cam_drops"], 1)
        self.assertEqual(len(self.frames), 1)

    async def test_vad_opens_streams_pcm_and_closes_after_hangover(self) -> None:
        voice = struct.pack("<320h", *([1200] * 320))
        silence = bytes(640)
        self.microphone.append(voice)
        for _ in range(6):
            self.microphone.append(silence)
        await self.session.handle(
            {"t": "mic", "seq": 1, "on": True, "gate": "vad"},
            self.emit,
        )

        for index in range(7):
            self.now = index * 0.021
            await self.session.service_media(self.emit, self.emit_binary)

        self.assertIn(
            {"t": "event", "name": "vad_open", "origin_id": 0},
            self.controls,
        )
        self.assertIn(
            {"t": "event", "name": "vad_close", "origin_id": 0},
            self.controls,
        )
        self.assertIn(
            {
                "t": "cam_meta",
                "res": "XGA",
                "fps": 0,
                "counter_base": 0,
                "origin": "audio",
                "origin_id": 0,
            },
            self.controls,
        )
        decoded = [decode_binary_frame(frame) for frame in self.frames]
        self.assertTrue(decoded)
        microphone = [
            frame for frame in decoded if frame.frame_type == MIC_PCM_FRAME_TYPE
        ]
        snapshots = [
            frame for frame in decoded if frame.frame_type == CAMERA_JPEG_FRAME_TYPE
        ]
        self.assertTrue(microphone)
        self.assertEqual(microphone[0].counter, 0)
        self.assertEqual(len(snapshots), 1)

    async def test_vad_includes_bounded_pre_roll_before_trigger_frame(self) -> None:
        silence = bytes(640)
        voice = struct.pack("<320h", *([1200] * 320))
        self.microphone.append(silence)
        self.microphone.append(silence)
        self.microphone.append(voice)
        await self.session.handle(
            {"t": "mic", "seq": 1, "on": True, "gate": "vad"},
            self.emit,
        )

        for index in range(3):
            self.now = index * 0.021
            await self.session.service_media(self.emit, self.emit_binary)

        decoded = [decode_binary_frame(frame) for frame in self.frames]
        self.assertEqual([frame.counter for frame in decoded], [0, 1, 2])
        self.assertEqual(self.frames[0][5:], silence)
        self.assertEqual(self.frames[1][5:], silence)
        self.assertEqual(self.frames[2][5:], voice)

    async def test_microphone_is_suspended_during_tts_and_rearms_after_cooldown(self) -> None:
        voice = struct.pack("<320h", *([1200] * 320))
        self.microphone.append(voice)
        await self.session.handle(
            {"t": "mic", "seq": 1, "on": True, "gate": "open"},
            self.emit,
        )
        await self.session.handle(
            {"t": "tts", "seq": 2, "op": "start"},
            self.emit,
        )
        await self.session.handle_binary(
            encode_binary_frame(SPEAKER_PCM_FRAME_TYPE, 0, bytes(640)),
            self.emit,
        )
        await self.session.service_media(self.emit, self.emit_binary)
        self.assertEqual(self.frames, [])

        await self.session.handle(
            {"t": "tts", "seq": 3, "op": "end"},
            self.emit,
        )
        self.now = 0.79
        await self.session.service_media(self.emit, self.emit_binary)
        self.assertEqual(self.frames, [])
        self.now = 0.81
        await self.session.service_media(self.emit, self.emit_binary)

        self.assertEqual(len(self.frames), 1)
        self.assertEqual(decode_binary_frame(self.frames[0]).frame_type, MIC_PCM_FRAME_TYPE)

    async def test_tether_allows_streaming_open_mic_and_xga_snap(self) -> None:
        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 2, "profile": "tether"}
        )
        await self.session.handle(
            {"t": "cam", "seq": 1, "on": True, "fps": 1, "res": "QVGA"},
            self.emit,
        )
        await self.session.handle(
            {"t": "cam", "seq": 2, "on": True, "fps": 0, "res": "VGA"},
            self.emit,
        )
        await self.session.handle(
            {"t": "mic", "seq": 3, "on": True, "gate": "open"},
            self.emit,
        )
        await self.session.handle(
            {"t": "snap", "seq": 4},
            self.emit,
            self.emit_binary,
        )

        self.assertEqual(self.controls[0], {"t": "ack", "seq": 1})
        self.assertEqual(self.controls[2], {"t": "ack", "seq": 2})
        self.assertEqual(self.controls[4], {"t": "ack", "seq": 3})
        self.assertEqual(self.controls[6]["res"], "XGA")
        self.assertEqual(self.camera.captures[-1], "XGA")

    async def test_camera_counter_wraps_without_affecting_lifecycle(self) -> None:
        self.session._camera_counter = MAX_BINARY_COUNTER  # acceptance hook
        await self.session.handle(
            {"t": "snap", "seq": 1},
            self.emit,
            self.emit_binary,
        )
        await self.session.handle(
            {"t": "snap", "seq": 2},
            self.emit,
            self.emit_binary,
        )
        self.assertEqual(
            [decode_binary_frame(frame).counter for frame in self.frames],
            [MAX_BINARY_COUNTER, 0],
        )

    async def test_bandwidth_pressure_drops_camera_before_microphone(self) -> None:
        microphone_payload = struct.pack("<320h", *([1200] * 320))
        await self.session.close()
        self.core.close()
        self.core = PortableCore(self.library_path)
        self.camera = FixtureCameraSource(b"\xff\xd8" + bytes(596) + b"\xff\xd9")
        self.microphone = QueueMicrophoneSource([microphone_payload])
        self.session = BodySession(
            self.core,
            ImmediateMotionBackend(),
            clock=lambda: self.now,
            camera_source=self.camera,
            microphone_source=self.microphone,
            media_bytes_per_second=1024,
        )
        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 10, "profile": "home"}
        )
        await self.session.handle(
            {"t": "mic", "seq": 1, "on": True, "gate": "open"}, self.emit
        )
        await self.session.handle(
            {"t": "cam", "seq": 2, "on": True, "fps": 10, "res": "VGA"},
            self.emit,
        )

        await self.session.service_media(self.emit, self.emit_binary)

        self.assertEqual(len(self.frames), 1)
        self.assertEqual(decode_binary_frame(self.frames[0]).frame_type, MIC_PCM_FRAME_TYPE)
        self.assertEqual(self.session.status()["cam_drops"], 1)

    async def test_oversize_camera_fault_is_one_shot_and_counted(self) -> None:
        faults = EmulatorFaultController()
        faults.request_oversize_camera()
        await self.session.close()
        self.core.close()
        self.core = PortableCore(self.library_path)
        self.session = BodySession(
            self.core,
            ImmediateMotionBackend(),
            clock=lambda: self.now,
            camera_source=self.camera,
            faults=faults,
        )
        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 10, "profile": "home"}
        )
        await self.session.handle(
            {"t": "cam", "seq": 1, "on": True, "fps": 10, "res": "VGA"},
            self.emit,
        )

        await self.session.service_media(self.emit, self.emit_binary)
        self.now = 0.11
        await self.session.service_media(self.emit, self.emit_binary)

        self.assertEqual(self.session.status()["cam_drops"], 1)
        self.assertEqual(len(self.frames), 1)


class EnergyVadTests(unittest.TestCase):
    def test_rejects_wrong_pcm_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "640"):
            EnergyVad().process(bytes(639))


if __name__ == "__main__":
    unittest.main()
