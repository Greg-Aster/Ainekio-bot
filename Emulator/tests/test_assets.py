from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from emulator.body.assets import (
    AssetError,
    AssetStore,
    FaceAnimator,
    IdleBlinkSchedule,
)
from emulator.body.calibration import CalibrationStore
from emulator.body.display import DisplayController
from protocol.joints_v1 import JOINT_LABELS, JOINT_MAP_VERSION, joint_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "Slave" / "software" / "assets" / "seed"
CONVERTER_PATH = REPO_ROOT / "Slave" / "software" / "tools" / "convert_sesame_assets.py"


class AssetTests(unittest.TestCase):
    def test_all_seed_motions_and_faces_load(self) -> None:
        store = AssetStore(ASSET_ROOT)
        self.assertEqual(len(store.motion_names), 19)
        self.assertEqual(len(store.face_names), 37)
        self.assertIn("walk_forward", store.motion_names)
        self.assertIn("talk_happy", store.face_names)
        audio = store.audio("greeting_1")
        assert audio is not None
        self.assertEqual(len(store.audio_pcm(audio)), 3200)

        calibration = CalibrationStore()
        for name in store.motion_names:
            with self.subTest(name=name):
                asset = store.motion(name)
                assert asset is not None
                self.assertEqual(asset.joint_map_version, JOINT_MAP_VERSION)
                self.assertTrue(store.motion_within_limits(asset, calibration))

    def test_logical_targets_apply_center_and_invert_before_limits(self) -> None:
        calibration = CalibrationStore()
        calibration.stage_limits(
            {
                "id": 0,
                "min": 20.0,
                "center": 95.0,
                "max": 160.0,
                "invert": True,
            }
        )

        self.assertTrue(calibration.logical_target_within_limits(0, 45.0))
        self.assertFalse(calibration.logical_target_within_limits(0, 10.0))
        self.assertTrue(calibration.target_within_limits(0, 45.0))

    def test_converter_output_is_deterministic(self) -> None:
        spec = importlib.util.spec_from_file_location("convert_sesame_assets", CONVERTER_PATH)
        assert spec is not None and spec.loader is not None
        converter = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = converter
        spec.loader.exec_module(converter)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            reference = REPO_ROOT / "docs" / "sesame-robot" / "firmware"
            converter.convert_assets(
                converter.SourcePaths(
                    reference / "movement-sequences.h",
                    reference / "face-bitmaps.h",
                    reference / "sesame-firmware-main.ino",
                ),
                output,
            )
            expected_files = sorted(path.relative_to(ASSET_ROOT) for path in ASSET_ROOT.rglob("*") if path.is_file())
            actual_files = sorted(path.relative_to(output) for path in output.rglob("*") if path.is_file())
            self.assertEqual(actual_files, expected_files)
            for relative in expected_files:
                self.assertEqual((output / relative).read_bytes(), (ASSET_ROOT / relative).read_bytes())

    def test_face_modes_are_deterministic(self) -> None:
        store = AssetStore(ASSET_ROOT)
        rest = store.face("rest")
        assert rest is not None
        animator = FaceAnimator(rest)
        self.assertEqual([animator.frame_index(index) for index in range(7)], [0, 1, 2, 1, 0, 1, 2])

        idle = store.face("idle")
        assert idle is not None
        self.assertEqual(FaceAnimator(idle).frame_index(50), 0)

    def test_idle_blink_schedule_stays_in_bounds_and_is_seeded(self) -> None:
        first = IdleBlinkSchedule(7)
        second = IdleBlinkSchedule(7)
        values = [(first.next_delay_seconds(), first.next_blink_count()) for _ in range(20)]
        self.assertEqual(
            values,
            [(second.next_delay_seconds(), second.next_blink_count()) for _ in range(20)],
        )
        self.assertTrue(all(3.0 <= delay <= 7.0 for delay, _count in values))
        self.assertTrue(all(count in {1, 2} for _delay, count in values))
        double_delays = [first.next_double_delay_seconds() for _ in range(20)]
        self.assertTrue(all(0.120 <= delay <= 0.220 for delay in double_delays))

    def test_joint_contract_rejects_drift_before_asset_execution(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "Slave" / "software" / "protocol" / "schemas" / "joints-v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(schema["joint_map_version"], JOINT_MAP_VERSION)
        self.assertEqual(
            tuple(entry["label"] for entry in schema["joints"]),
            JOINT_LABELS,
        )
        self.assertEqual(joint_contract()["version"], JOINT_MAP_VERSION)

        motion_path = ASSET_ROOT / "motions-v1.json"
        manifest = json.loads(motion_path.read_text(encoding="utf-8"))
        manifest["joint_map"]["joints"][0]["label"] = "WRONG"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "motions-v1.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "faces-v1.json").write_text('{"schema_version":1,"faces":[]}', encoding="utf-8")
            with self.assertRaisesRegex(AssetError, "joint map"):
                AssetStore(root)


class DisplayTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_face_fps_advances_by_elapsed_ticks_without_drift(self) -> None:
        class Sink:
            def __init__(self) -> None:
                self.payloads: list[bytes] = []

            async def show_frame(self, _name: str, payload: bytes) -> None:
                self.payloads.append(payload)

        store = AssetStore(ASSET_ROOT)
        sink = Sink()
        display = DisplayController(store, sink)
        rest = store.face("rest")
        assert rest is not None

        await display.set_face("rest", "boomerang")
        await display.service(0.0)
        await display.service(1.0 / rest.fps)
        await display.service(3.0 / rest.fps)

        self.assertEqual(display.current_tick, 3)
        self.assertEqual(sink.payloads[0], store.face_frame(rest, 0))
        self.assertEqual(sink.payloads[1], store.face_frame(rest, 1))
        self.assertEqual(sink.payloads[2], store.face_frame(rest, 1))


if __name__ == "__main__":
    unittest.main()
