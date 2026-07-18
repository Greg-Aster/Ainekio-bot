from __future__ import annotations

import asyncio
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from time import monotonic

from emulator.body import BodySession, CalibrationStore, PortableCore
from emulator.body.assets import AssetStore, IdleBlinkSchedule
from protocol.binary_helpers import SPEAKER_PCM_FRAME_TYPE, encode_binary_frame
from Emulator.tests.support import build_core_library


class ControlledMotionBackend:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.messages: list[dict[str, object]] = []
        self.failure: Exception | None = None
        self.stop_failure: Exception | None = None
        self.stop_release: asyncio.Event | None = None

    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        self.messages.append(dict(message))
        self.started.set()
        if self.failure is not None:
            raise self.failure
        await self.release.wait()

    async def stop(self, sequence: int, *, session_id: str) -> None:
        self.messages.append({"t": "stop", "seq": sequence})
        if self.stop_failure is not None:
            raise self.stop_failure
        if self.stop_release is not None:
            await self.stop_release.wait()


class ControlledSpeakerSink:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.frames: list[bytes] = []
        self.stop_count = 0

    async def play_pcm(self, payload: bytes) -> None:
        self.frames.append(payload)
        self.started.set()
        await self.release.wait()

    async def stop(self) -> None:
        self.stop_count += 1


class RecordingDisplaySink:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.names: list[str] = []

    async def show_frame(self, name: str, payload: bytes) -> None:
        self.names.append(name)
        if self.fail:
            raise RuntimeError("display unavailable")


class BodySessionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library_path = build_core_library()

    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.calibration_path = Path(self.temporary_directory.name) / "calibration.json"
        self.core = PortableCore(self.library_path)
        self.backend = ControlledMotionBackend()
        self.now = 0.0
        self.session = BodySession(
            self.core,
            self.backend,
            CalibrationStore(self.calibration_path),
            clock=lambda: self.now,
        )
        self.messages: list[dict[str, object]] = []
        await self.session.begin({"t": "welcome", "ver": 1, "epoch": 9, "profile": "home"})

    async def asyncTearDown(self) -> None:
        await self.session.close()
        self.core.close()
        self.temporary_directory.cleanup()

    async def emit(self, message: dict[str, object]) -> None:
        self.messages.append(message)

    async def test_movement_acks_then_completes(self) -> None:
        self.backend.release.set()

        await self.session.handle({"t": "intent", "seq": 1, "name": "stand"}, self.emit)
        await self.session.wait_until_idle()

        self.assertEqual(
            self.messages,
            [{"t": "ack", "seq": 1}, {"t": "done", "seq": 1}],
        )
        self.assertEqual(self.backend.messages[0]["name"], "stand")

    async def test_stop_cancels_active_movement_and_detaches(self) -> None:
        walk = {"t": "intent", "seq": 1, "name": "walk", "dir": "fwd", "steps": 10}
        await self.session.handle(walk, self.emit)
        await self.backend.started.wait()

        await self.session.handle({"t": "stop", "seq": 2}, self.emit)

        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {"t": "ack", "seq": 2},
                {"t": "cancelled", "seq": 1, "code": "stop"},
            ],
        )
        self.assertFalse(self.core.servos_attached)
        self.assertIsNone(self.session.active_sequence)
        self.assertEqual(self.backend.messages[-1], {"t": "stop", "seq": 2})

    async def test_motion_plan_acks_executes_frames_and_completes(self) -> None:
        self.backend.release.set()
        plan = {
            "t": "motion_plan",
            "seq": 1,
            "map": 1,
            "frames": [
                [300, [9500, 8500, 9000, 9000, 8000, 10000, 9000, 9000]],
                [400, [9000, 9000, 9000, 9000, 9000, 9000, 9000, 9000]],
            ],
            "end": "hold",
        }

        await self.session.handle(plan, self.emit)
        await self.session.wait_until_idle()

        self.assertEqual(
            self.messages,
            [{"t": "ack", "seq": 1}, {"t": "done", "seq": 1}],
        )
        rendered = self.backend.messages[0]
        self.assertEqual(rendered["t"], "motion_plan")
        self.assertEqual(rendered["_joint_map_version"], 1)
        self.assertEqual(len(rendered["_motion_plan_frames"]), 2)
        self.assertEqual(
            rendered["_motion_plan_frames"][0]["targets"][0],
            [0, 95.0],
        )

    async def test_motion_plan_limit_rejection_causes_zero_movement(self) -> None:
        await self.session.handle(
            {"t": "mode", "seq": 1, "name": "calibrate"},
            self.emit,
        )
        await self.session.handle(
            {
                "t": "limits",
                "seq": 2,
                "id": 0,
                "min": 80.0,
                "max": 100.0,
                "center": 90.0,
                "invert": False,
            },
            self.emit,
        )
        await self.session.handle(
            {
                "t": "motion_plan",
                "seq": 3,
                "map": 1,
                "frames": [[300, [18000, 9000, 9000, 9000, 9000, 9000, 9000, 9000]]],
                "end": "hold",
            },
            self.emit,
        )

        self.assertEqual(self.messages[-1], {"t": "nak", "seq": 3, "code": "limit"})
        self.assertEqual(self.backend.messages, [])

    async def test_stop_cancels_active_motion_plan(self) -> None:
        await self.session.handle(
            {
                "t": "motion_plan",
                "seq": 1,
                "map": 1,
                "frames": [[1000, [9000, 9000, 9000, 9000, 9000, 9000, 9000, 9000]]],
                "end": "hold",
            },
            self.emit,
        )
        await self.backend.started.wait()
        await self.session.handle({"t": "stop", "seq": 2}, self.emit)

        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {"t": "ack", "seq": 2},
                {"t": "cancelled", "seq": 1, "code": "stop"},
            ],
        )
        self.assertFalse(self.core.servos_attached)

    async def test_renderer_failure_never_reports_done(self) -> None:
        self.backend.failure = RuntimeError("renderer unavailable")

        await self.session.handle({"t": "intent", "seq": 1, "name": "stand"}, self.emit)
        await self.session.wait_until_idle()

        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {"t": "cancelled", "seq": 1, "code": "overflow"},
            ],
        )
        self.assertNotIn({"t": "done", "seq": 1}, self.messages)

    async def test_renderer_failure_cannot_block_or_reject_stop(self) -> None:
        self.backend.stop_failure = RuntimeError("renderer unavailable")

        await self.session.handle({"t": "stop", "seq": 1}, self.emit)

        self.assertEqual(self.messages, [{"t": "ack", "seq": 1}])
        self.assertFalse(self.core.servos_attached)

    async def test_renderer_timeout_cannot_block_stop(self) -> None:
        self.backend.stop_release = asyncio.Event()

        started = monotonic()
        await asyncio.wait_for(
            self.session.handle({"t": "stop", "seq": 1}, self.emit),
            timeout=0.2,
        )
        elapsed = monotonic() - started

        self.assertEqual(self.messages, [{"t": "ack", "seq": 1}])
        self.assertFalse(self.core.servos_attached)
        self.assertLess(elapsed, 0.1)

    async def test_unavailable_capability_is_bounded_and_claims_sequence(self) -> None:
        await self.session.handle(
            {"t": "intent", "seq": 3, "name": "look", "yaw": 10, "pitch": 5},
            self.emit,
        )
        await self.session.handle({"t": "intent", "seq": 3, "name": "stand"}, self.emit)

        self.assertEqual(self.messages[0]["code"], "busy")
        self.assertEqual(self.messages[1], {"t": "nak", "seq": 3, "code": "stale"})

    async def test_unknown_intent_returns_unknown_without_execution(self) -> None:
        await self.session.handle({"t": "intent", "seq": 1, "name": "jump"}, self.emit)

        self.assertEqual(self.messages, [{"t": "nak", "seq": 1, "code": "unknown"}])
        self.assertEqual(self.backend.messages, [])

    async def test_malformed_input_does_not_end_the_session(self) -> None:
        self.backend.release.set()

        await self.session.handle_raw("{not-json", self.emit)
        await self.session.handle_raw(
            '{"t":"intent","seq":1,"name":"stand"}',
            self.emit,
        )
        await self.session.wait_until_idle()

        self.assertEqual(
            self.messages,
            [
                {"t": "nak", "code": "malformed"},
                {"t": "ack", "seq": 1},
                {"t": "done", "seq": 1},
            ],
        )

    async def test_new_epoch_cancels_old_work_and_resets_sequence(self) -> None:
        await self.session.handle(
            {"t": "intent", "seq": 1, "name": "stand"},
            self.emit,
        )
        await self.backend.started.wait()

        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 10, "profile": "home"}
        )
        self.backend.release.set()
        await self.session.handle(
            {"t": "intent", "seq": 1, "name": "stand"},
            self.emit,
        )
        await self.session.wait_until_idle()

        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {"t": "ack", "seq": 1},
                {"t": "done", "seq": 1},
            ],
        )

    async def test_calibration_is_mode_gated_and_persists_only_on_save(self) -> None:
        await self.session.handle(
            {"t": "servo", "seq": 1, "id": 0, "deg": 45.0, "ms": 300},
            self.emit,
        )
        await self.session.handle(
            {"t": "mode", "seq": 2, "name": "calibrate"},
            self.emit,
        )
        await self.session.handle(
            {
                "t": "limits",
                "seq": 3,
                "id": 0,
                "min": 10.0,
                "max": 170.0,
                "invert": False,
                "center": 90.0,
            },
            self.emit,
        )
        await self.session.handle(
            {
                "t": "pose_save",
                "seq": 4,
                "name": "neutral",
                "servos": [[0, 90.0], [1, 91.0]],
            },
            self.emit,
        )

        self.assertEqual(self.messages[0], {"t": "nak", "seq": 1, "code": "mode"})
        self.assertFalse(self.calibration_path.exists())

        await self.session.handle({"t": "cal_save", "seq": 5}, self.emit)

        self.assertEqual(
            self.messages[1:],
            [
                {"t": "ack", "seq": 2},
                {"t": "ack", "seq": 3},
                {"t": "ack", "seq": 4},
                {"t": "ack", "seq": 5},
            ],
        )
        reloaded = CalibrationStore(self.calibration_path).snapshot()
        self.assertEqual(
            reloaded["limits"]["0"],
            {"min": 10.0, "max": 170.0, "invert": False, "center": 90.0},
        )
        self.assertEqual(reloaded["poses"]["neutral"], [[0, 90.0], [1, 91.0]])

    async def test_profiles_states_and_settings_use_portable_core(self) -> None:
        await self.session.handle(
            {"t": "cam", "seq": 1, "on": True, "fps": 5, "res": "VGA"},
            self.emit,
        )
        await self.session.handle(
            {"t": "state", "seq": 2, "name": "doze"},
            self.emit,
        )
        await self.session.handle(
            {"t": "profile", "seq": 3, "name": "tether"},
            self.emit,
        )
        await self.session.handle(
            {"t": "mic", "seq": 4, "on": True, "gate": "open"},
            self.emit,
        )
        await self.session.handle(
            {"t": "state", "seq": 5, "name": "sleep", "sleep_s": 60},
            self.emit,
        )

        self.assertEqual(self.messages[0], {"t": "ack", "seq": 1})
        self.assertEqual(
            self.messages[1],
            {"t": "cam_meta", "res": "VGA", "fps": 5, "counter_base": 0},
        )
        self.assertEqual(self.messages[2], {"t": "ack", "seq": 2})
        self.assertEqual(self.messages[3], {"t": "ack", "seq": 3})
        self.assertEqual(self.messages[4], {"t": "nak", "seq": 4, "code": "profile"})
        self.assertEqual(self.messages[5], {"t": "ack", "seq": 5, "sleep_s": 60})
        self.assertEqual(self.messages[6]["t"], "status")
        self.assertEqual(self.messages[6]["state"], "deep-sleep")
        self.assertEqual(self.messages[7], {"t": "done", "seq": 5})
        self.assertEqual(self.session.camera_settings, {"on": True, "fps": 5, "res": "VGA"})
        self.assertEqual(self.session.microphone_settings, {"on": True, "gate": "vad"})
        self.assertEqual(self.session.profile, "tether")
        self.assertEqual(self.session.sleep_seconds, 60)

    async def test_wake_configuration_is_off_by_default_and_rejects_unready_model(self) -> None:
        self.assertEqual(
            self.session.microphone_settings,
            {"on": True, "gate": "vad"},
        )
        self.assertEqual(
            self.session.wake_settings,
            {"enabled": False, "model": "ainekio", "ready": False},
        )

        await self.session.handle(
            {"t": "wake", "seq": 1, "enabled": False, "model": "ainekio"},
            self.emit,
        )
        await self.session.handle(
            {"t": "wake", "seq": 2, "enabled": True, "model": "ainekio"},
            self.emit,
        )
        await self.session.handle(
            {"t": "wake", "seq": 3, "enabled": False, "model": "other_model"},
            self.emit,
        )
        await self.session.handle(
            {"t": "mic", "seq": 4, "on": True, "gate": "wake"},
            self.emit,
        )

        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {
                    "t": "nak",
                    "seq": 2,
                    "code": "busy",
                    "msg": "wake model unavailable",
                },
                {
                    "t": "nak",
                    "seq": 3,
                    "code": "asset_missing",
                    "msg": "wake model unavailable",
                },
                {
                    "t": "nak",
                    "seq": 4,
                    "code": "busy",
                    "msg": "wake model unavailable",
                },
            ],
        )
        self.assertFalse(self.session.status()["wake_enabled"])
        self.assertEqual(self.session.status()["wake_model"], "ainekio")
        self.assertFalse(self.session.status()["wake_ready"])

        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 10, "profile": "home"}
        )
        self.assertEqual(
            self.session.wake_settings,
            {"enabled": False, "model": "ainekio", "ready": False},
        )

    async def test_calibration_limits_and_idle_timeout_are_enforced(self) -> None:
        await self.session.handle(
            {"t": "mode", "seq": 1, "name": "calibrate"},
            self.emit,
        )
        await self.session.handle(
            {
                "t": "limits",
                "seq": 2,
                "id": 0,
                "min": 10.0,
                "max": 170.0,
                "invert": False,
                "center": 90.0,
            },
            self.emit,
        )
        await self.session.handle(
            {"t": "servo", "seq": 3, "id": 0, "deg": 5.0, "ms": 300},
            self.emit,
        )
        await self.session.handle(
            {
                "t": "pose_save",
                "seq": 4,
                "name": "bad_pose",
                "servos": [[0, 171.0]],
            },
            self.emit,
        )

        self.assertEqual(self.messages[2], {"t": "nak", "seq": 3, "code": "limit"})
        self.assertEqual(self.messages[3], {"t": "nak", "seq": 4, "code": "limit"})

        self.now = 600.0
        await self.session.handle(
            {"t": "servo", "seq": 5, "id": 0, "deg": 90.0, "ms": 300},
            self.emit,
        )
        self.assertEqual(self.messages[4], {"t": "nak", "seq": 5, "code": "mode"})

    async def test_calibration_burst_acks_all_and_coalesces_to_latest_at_20hz(self) -> None:
        await self.session.handle(
            {"t": "mode", "seq": 1, "name": "calibrate"},
            self.emit,
        )
        await self.session.handle(
            {"t": "servo", "seq": 2, "id": 0, "deg": 80.0, "ms": 0},
            self.emit,
        )
        self.now = 0.01
        await self.session.handle(
            {"t": "servo", "seq": 3, "id": 0, "deg": 85.0, "ms": 0},
            self.emit,
        )
        self.now = 0.02
        await self.session.handle(
            {"t": "servo", "seq": 4, "id": 0, "deg": 95.0, "ms": 0},
            self.emit,
        )

        self.assertEqual(self.session.servo_positions[0], 80.0)
        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {"t": "ack", "seq": 2},
                {"t": "ack", "seq": 3},
                {"t": "ack", "seq": 4},
            ],
        )

        self.now = 0.05
        await self.session.service_media(self.emit, lambda _frame: asyncio.sleep(0))
        self.assertEqual(self.session.servo_positions[0], 95.0)

    async def test_settings_do_not_reset_idle_timer_and_intent_exits_doze(self) -> None:
        self.now = 59.0
        await self.session.handle(
            {"t": "cam", "seq": 1, "on": True, "fps": 5, "res": "VGA"},
            self.emit,
        )
        self.now = 60.0
        self.assertEqual(self.session.status()["state"], "idle")

        await self.session.handle(
            {"t": "state", "seq": 2, "name": "doze"},
            self.emit,
        )
        self.assertEqual(self.session.status()["state"], "dozing")

        self.backend.release.set()
        await self.session.handle(
            {"t": "intent", "seq": 3, "name": "stand"},
            self.emit,
        )
        await self.session.wait_until_idle()
        self.assertEqual(self.session.status()["state"], "active")

    async def test_tts_frames_complete_in_order_after_end(self) -> None:
        await self.session.handle(
            {"t": "tts", "seq": 1, "op": "start"},
            self.emit,
        )
        await self.session.handle_binary(
            encode_binary_frame(SPEAKER_PCM_FRAME_TYPE, 0, bytes(640)),
            self.emit,
        )
        await self.session.handle(
            {"t": "tts", "seq": 2, "op": "end"},
            self.emit,
        )

        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {"t": "ack", "seq": 2},
                {"t": "done", "seq": 1},
            ],
        )

    async def test_tts_orphan_event_is_once_per_burst(self) -> None:
        frame = encode_binary_frame(SPEAKER_PCM_FRAME_TYPE, 0, bytes(640))
        await self.session.handle_binary(frame, self.emit)
        await self.session.handle_binary(frame, self.emit)
        await self.session.handle(
            {"t": "tts", "seq": 1, "op": "start"},
            self.emit,
        )
        await self.session.handle(
            {"t": "tts", "seq": 2, "op": "cancel"},
            self.emit,
        )

        self.assertEqual(
            self.messages,
            [
                {"t": "event", "name": "tts_orphan"},
                {"t": "ack", "seq": 1},
                {"t": "ack", "seq": 2},
                {"t": "cancelled", "seq": 1, "code": "stop"},
            ],
        )

    async def test_stop_cancels_speaker_playback(self) -> None:
        speaker = ControlledSpeakerSink()
        await self.session.close()
        self.session = BodySession(
            self.core,
            self.backend,
            CalibrationStore(self.calibration_path),
            clock=lambda: self.now,
            speaker_sink=speaker,
        )
        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 10, "profile": "home"}
        )

        await self.session.handle(
            {"t": "tts", "seq": 1, "op": "start"},
            self.emit,
        )
        await self.session.handle_binary(
            encode_binary_frame(SPEAKER_PCM_FRAME_TYPE, 0, bytes(640)),
            self.emit,
        )
        await speaker.started.wait()
        await self.session.handle({"t": "stop", "seq": 2}, self.emit)

        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {"t": "ack", "seq": 2},
                {"t": "cancelled", "seq": 1, "code": "stop"},
            ],
        )
        self.assertFalse(self.core.servos_attached)

    async def test_speaker_queue_overflow_cancels_whole_utterance(self) -> None:
        speaker = ControlledSpeakerSink()
        await self.session.close()
        self.session = BodySession(
            self.core,
            self.backend,
            CalibrationStore(self.calibration_path),
            clock=lambda: self.now,
            speaker_sink=speaker,
        )
        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 10, "profile": "home"}
        )
        await self.session.handle(
            {"t": "tts", "seq": 1, "op": "start"},
            self.emit,
        )

        await self.session.handle_binary(
            encode_binary_frame(SPEAKER_PCM_FRAME_TYPE, 0, bytes(640)),
            self.emit,
        )
        await speaker.started.wait()
        for counter in range(1, 26):
            await self.session.handle_binary(
                encode_binary_frame(SPEAKER_PCM_FRAME_TYPE, counter, bytes(640)),
                self.emit,
            )

        self.assertEqual(
            self.messages[-2:],
            [
                {"t": "event", "name": "tts_overflow"},
                {"t": "cancelled", "seq": 1, "code": "overflow"},
            ],
        )

    async def test_emote_uses_converted_frames_and_calibrated_limits(self) -> None:
        self.backend.release.set()
        await self.session.handle(
            {"t": "intent", "seq": 1, "name": "emote", "asset": "wave"},
            self.emit,
        )
        await self.session.wait_until_idle()

        rendered = self.backend.messages[0]
        self.assertEqual(rendered["_joint_map_version"], 1)
        self.assertEqual(len(rendered["_motion_asset_frames"]), 12)
        self.assertEqual(self.messages, [{"t": "ack", "seq": 1}, {"t": "done", "seq": 1}])

        await self.session.handle(
            {"t": "mode", "seq": 2, "name": "calibrate"},
            self.emit,
        )
        await self.session.handle(
            {
                "t": "limits",
                "seq": 3,
                "id": 6,
                "min": 0.0,
                "max": 100.0,
                "center": 90.0,
                "invert": False,
            },
            self.emit,
        )
        await self.session.handle(
            {"t": "intent", "seq": 4, "name": "emote", "asset": "wave"},
            self.emit,
        )
        self.assertEqual(self.messages[-1], {"t": "nak", "seq": 4, "code": "limit"})

    async def test_every_seed_motion_is_limit_checked_and_stop_preemptible(self) -> None:
        assets = AssetStore()
        calibration = CalibrationStore(self.calibration_path)
        asset_names = assets.motion_names
        self.assertEqual(len(asset_names), 19)

        sequence = 1
        for asset_name in asset_names:
            asset = assets.motion(asset_name)
            self.assertIsNotNone(asset, asset_name)
            self.assertTrue(
                assets.motion_within_limits(asset, calibration),
                asset_name,
            )
            self.backend.started.clear()
            await self.session.handle(
                {"t": "intent", "seq": sequence, "name": "emote", "asset": asset_name},
                self.emit,
            )
            await self.backend.started.wait()
            await self.session.handle({"t": "stop", "seq": sequence + 1}, self.emit)
            self.assertEqual(
                self.messages[-2:],
                [
                    {"t": "ack", "seq": sequence + 1},
                    {"t": "cancelled", "seq": sequence, "code": "stop"},
                ],
                asset_name,
            )
            self.assertFalse(self.core.servos_attached, asset_name)
            sequence += 2

    async def test_missing_emote_asset_is_explicit(self) -> None:
        await self.session.handle(
            {"t": "intent", "seq": 1, "name": "emote", "asset": "not_installed"},
            self.emit,
        )
        self.assertEqual(
            self.messages,
            [
                {"t": "event", "name": "asset_missing"},
                {"t": "nak", "seq": 1, "code": "asset_missing"},
            ],
        )

    async def test_face_and_say_complete_without_reattaching_after_stop(self) -> None:
        await self.session.handle({"t": "stop", "seq": 1}, self.emit)
        await self.session.handle(
            {"t": "intent", "seq": 2, "name": "face", "expr": "happy"},
            self.emit,
        )
        await self.session.handle(
            {"t": "intent", "seq": 3, "name": "say", "asset": "greeting_1"},
            self.emit,
        )
        await self.session.wait_until_idle()

        self.assertEqual(
            self.messages,
            [
                {"t": "ack", "seq": 1},
                {"t": "ack", "seq": 2},
                {"t": "done", "seq": 2},
                {"t": "ack", "seq": 3},
                {"t": "done", "seq": 3},
            ],
        )
        self.assertFalse(self.core.servos_attached)

    async def test_display_failure_never_fails_face_command(self) -> None:
        display = RecordingDisplaySink(fail=True)
        await self.session.close()
        self.session = BodySession(
            self.core,
            self.backend,
            CalibrationStore(self.calibration_path),
            clock=lambda: self.now,
            display_sink=display,
        )
        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 10, "profile": "home"}
        )
        await self.session.handle(
            {"t": "intent", "seq": 1, "name": "face", "expr": "happy"},
            self.emit,
        )

        self.assertEqual(self.messages, [{"t": "ack", "seq": 1}, {"t": "done", "seq": 1}])
        self.assertEqual(display.names, ["happy"])
        self.assertEqual(self.session.status()["display_failures"], 1)

    async def test_tts_selects_talk_face_restores_and_blocks_say(self) -> None:
        display = RecordingDisplaySink()
        await self.session.close()
        self.session = BodySession(
            self.core,
            self.backend,
            CalibrationStore(self.calibration_path),
            clock=lambda: self.now,
            display_sink=display,
        )
        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 10, "profile": "home"}
        )
        await self.session.handle(
            {"t": "intent", "seq": 1, "name": "face", "expr": "happy"},
            self.emit,
        )
        await self.session.handle({"t": "tts", "seq": 2, "op": "start"}, self.emit)
        await self.session.handle(
            {"t": "intent", "seq": 3, "name": "say", "asset": "greeting_1"},
            self.emit,
        )
        await self.session.handle({"t": "tts", "seq": 4, "op": "end"}, self.emit)

        self.assertEqual(display.names, ["happy", "talk_happy", "happy"])
        self.assertEqual(self.messages[3], {"t": "nak", "seq": 3, "code": "busy"})
        self.assertEqual(self.messages[-1], {"t": "done", "seq": 2})

    async def test_battery_warning_locks_movement_but_allows_neutral(self) -> None:
        self.session.set_simulated_battery(6.9)
        for _ in range(3):
            await self.session.service_media(self.emit, lambda _frame: asyncio.sleep(0))

        await self.session.handle(
            {"t": "intent", "seq": 1, "name": "walk", "dir": "fwd", "steps": 1},
            self.emit,
        )
        self.backend.release.set()
        await self.session.handle(
            {"t": "intent", "seq": 2, "name": "neutral"},
            self.emit,
        )
        await self.session.wait_until_idle()

        self.assertEqual(self.messages.count({"t": "event", "name": "battery_warn"}), 1)
        self.assertIn({"t": "nak", "seq": 1, "code": "unsafe"}, self.messages)
        self.assertIn({"t": "done", "seq": 2}, self.messages)
        self.assertEqual(self.core.power_guard, "move_locked")
        self.assertEqual(self.session.status()["vbat"], 6.9)

    async def test_battery_cutoff_preempts_continuous_walk_and_recovers(self) -> None:
        await self.session.handle(
            {"t": "intent", "seq": 1, "name": "walk", "dir": "fwd", "steps": 10},
            self.emit,
        )
        await self.backend.started.wait()
        self.session.set_simulated_battery(6.7)
        for _ in range(3):
            await self.session.service_media(self.emit, lambda _frame: asyncio.sleep(0))

        self.assertIn({"t": "event", "name": "battery_warn"}, self.messages)
        self.assertIn({"t": "event", "name": "battery_cutoff"}, self.messages)
        self.assertIn({"t": "cancelled", "seq": 1, "code": "stop"}, self.messages)
        self.assertEqual(self.backend.messages[-1], {"t": "stop", "seq": 1})
        self.assertEqual(self.session.status()["state"], "deep-sleep")
        self.assertFalse(self.core.servos_attached)
        self.assertEqual(self.session.take_sleep_request(), 1800)

        await self.session.handle({"t": "stop", "seq": 2}, self.emit)
        self.assertEqual(self.messages[-1], {"t": "nak", "seq": 2, "code": "busy"})

        self.session.set_simulated_battery(7.2)
        for _ in range(3):
            await self.session.service_media(self.emit, lambda _frame: asyncio.sleep(0))

        self.assertEqual(self.messages[-1], {"t": "event", "name": "brownout_recovered"})
        self.assertEqual(self.session.battery_state, "normal")
        self.assertEqual(self.session.status()["state"], "active")
        self.assertEqual(self.core.power_guard, "normal")

    async def test_idle_display_blinks_with_seeded_bounded_double_blink(self) -> None:
        display = RecordingDisplaySink()
        await self.session.close()
        self.session = BodySession(
            self.core,
            self.backend,
            CalibrationStore(self.calibration_path),
            clock=lambda: self.now,
            display_sink=display,
            idle_seed=7,
        )
        await self.session.begin(
            {"t": "welcome", "ver": 1, "epoch": 10, "profile": "home"}
        )
        await self.session.handle({"t": "state", "seq": 1, "name": "idle"}, self.emit)

        schedule = IdleBlinkSchedule(7)
        first_delay = schedule.next_delay_seconds()
        self.assertEqual(schedule.next_blink_count(), 2)
        double_delay = schedule.next_double_delay_seconds()

        await self.session.service_media(self.emit, lambda _frame: asyncio.sleep(0))
        self.assertEqual(display.names, ["idle"])
        self.now = first_delay
        await self.session.service_media(self.emit, lambda _frame: asyncio.sleep(0))
        self.assertEqual(display.names[-1], "idle_blink")

        self.now += 4 / 7
        await self.session.service_media(self.emit, lambda _frame: asyncio.sleep(0))
        self.assertEqual(display.names[-1], "idle")
        self.now += double_delay
        await self.session.service_media(self.emit, lambda _frame: asyncio.sleep(0))
        self.assertEqual(display.names[-1], "idle_blink")


if __name__ == "__main__":
    unittest.main()
