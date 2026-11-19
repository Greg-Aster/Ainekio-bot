from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from Slave.software.tools.stage_firmware_assets import stage_assets


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_CMAKE = ROOT / "Slave" / "firmware" / "esp32s3" / "CMakeLists.txt"
ASSET_STORE_HEADER = (
    ROOT
    / "Slave"
    / "firmware"
    / "esp32s3"
    / "components"
    / "ainekio_platform"
    / "include"
    / "ainekio"
    / "platform"
    / "asset_store.h"
)
ASSET_STORE_SOURCE = (
    ROOT
    / "Slave"
    / "firmware"
    / "esp32s3"
    / "components"
    / "ainekio_platform"
    / "src"
    / "asset_store.c"
)
DEFAULT_FACE_HEADER = (
    ROOT
    / "Slave"
    / "firmware"
    / "esp32s3"
    / "components"
    / "ainekio_platform"
    / "src"
    / "default_face_bitmap.h"
)
SEED_DIR = ROOT / "Slave" / "software" / "assets" / "seed"
FACE_MANIFEST = SEED_DIR / "faces-v1.json"
FACES_DEF = ROOT / "Slave" / "software" / "faces" / "faces.def"
MOTION_MANIFEST = SEED_DIR / "motions-bin-v1.json"
MOTION_SOURCE_MANIFEST = SEED_DIR / "motions-v1.json"


class FirmwareAssetPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.seed = self.root / "seed"
        self.local = self.root / "local"
        self.output = self.root / "output"
        self.seed.mkdir()
        (self.seed / "faces-v1.json").write_text("{}\n", encoding="utf-8")
        (self.seed / "motions-v1.json").write_text("{}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def add_wake_package(self, *, digest: str | None = None) -> bytes:
        package = self.local / "wake" / "ainekio"
        package.mkdir(parents=True)
        model = b"\x1c\x00\x00\x00TFL3" + bytes(2040)
        (package / "ainekio.tflite").write_bytes(model)
        manifest = {
            "schema": "ainekio-microwakeword-v1",
            "engine": "micro_wake_word",
            "id": "ainekio",
            "model": "ainekio.tflite",
            "sha256": digest or hashlib.sha256(model).hexdigest(),
        }
        (package / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return model

    def test_local_wake_package_is_staged_and_emulator_manifest_is_excluded(self) -> None:
        model = self.add_wake_package()

        stage_assets(seed_dir=self.seed, local_dir=self.local, output_dir=self.output)

        self.assertEqual(
            (self.output / "wake" / "ainekio" / "ainekio.tflite").read_bytes(),
            model,
        )
        self.assertTrue((self.output / "faces-v1.json").is_file())
        self.assertFalse((self.output / "motions-v1.json").exists())

    def test_missing_local_overlay_is_allowed(self) -> None:
        stage_assets(seed_dir=self.seed, local_dir=self.local, output_dir=self.output)
        self.assertTrue((self.output / "faces-v1.json").is_file())

    def test_p4_stages_voice_and_verified_wake_without_v1_motion_or_display(self) -> None:
        model = self.add_wake_package()
        (self.seed / "audio").mkdir()
        (self.seed / "audio" / "greeting_1.pcm").write_bytes(b"\x00\x00")
        (self.seed / "audio-v1.json").write_text("{}\n", encoding="utf-8")
        (self.local / "faces-v1.json").write_text("{}\n", encoding="utf-8")
        stage_assets(seed_dir=self.seed, local_dir=self.local, output_dir=self.output, profile="p4")
        self.assertEqual({path.name for path in self.output.iterdir()}, {"audio", "audio-v1.json", "wake"})
        self.assertEqual((self.output / "audio" / "greeting_1.pcm").read_bytes(), b"\x00\x00")
        self.assertEqual((self.output / "wake" / "ainekio" / "ainekio.tflite").read_bytes(), model)

    def test_output_cannot_delete_a_source_ancestor_or_nest_within_source(self) -> None:
        for output in (self.root, self.seed / "build"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "separate"):
                stage_assets(seed_dir=self.seed, local_dir=self.local, output_dir=output)
        self.assertTrue((self.seed / "faces-v1.json").is_file())

    def test_corrupt_local_wake_package_is_rejected(self) -> None:
        self.add_wake_package(digest="0" * 64)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            stage_assets(
                seed_dir=self.seed,
                local_dir=self.local,
                output_dir=self.output,
            )

    def test_normal_firmware_flash_excludes_littlefs(self) -> None:
        cmake = FIRMWARE_CMAKE.read_text(encoding="utf-8")
        littlefs_call = cmake.split("littlefs_create_partition_image(", 1)[1].split(
            ")", 1
        )[0]
        self.assertNotIn("FLASH_IN_PROJECT", littlefs_call)

    def test_firmware_motion_index_fits_the_seed_catalog(self) -> None:
        header = ASSET_STORE_HEADER.read_text(encoding="utf-8")
        marker = "#define AINEKIO_ASSET_MAX_MOTIONS "
        line = next(line for line in header.splitlines() if line.startswith(marker))
        capacity = int(line.removeprefix(marker).removesuffix("U"))
        manifest = json.loads(MOTION_MANIFEST.read_text(encoding="utf-8"))

        self.assertLessEqual(len(manifest["assets"]), capacity)
        self.assertGreaterEqual(capacity - len(manifest["assets"]), 2)

    def test_v1_face_library_is_derived_from_v2_and_fits_firmware_limits(self) -> None:
        from Slave.software.faces.tools.derive_v1_oled import (
            format_default_header,
            parse_faces_def,
        )

        header = ASSET_STORE_HEADER.read_text(encoding="utf-8")
        source = ASSET_STORE_SOURCE.read_text(encoding="utf-8")

        def define_uint(text: str, name: str) -> int:
            prefix = f"#define {name} "
            line = next(l for l in text.splitlines() if l.startswith(prefix))
            return int(line.removeprefix(prefix).removesuffix("U"))

        max_faces = define_uint(header, "AINEKIO_ASSET_MAX_FACES")
        max_frames = define_uint(header, "AINEKIO_ASSET_MAX_FACE_FRAMES")
        frame_bytes = define_uint(header, "AINEKIO_FACE_FRAME_BYTES")
        max_json_bytes = define_uint(source, "INDEX_JSON_MAX_BYTES")

        raw_json = FACE_MANIFEST.read_bytes()
        self.assertLess(len(raw_json), max_json_bytes)

        manifest = json.loads(raw_json.decode("utf-8"))
        self.assertEqual(manifest.get("schema_version"), 1)
        self.assertEqual(manifest.get("derived_from"), "Slave/software/faces/faces.def")
        self.assertNotIn("owner_faces", manifest)

        recipes = parse_faces_def(FACES_DEF)
        expected_names = [r.name for r in recipes]
        faces = manifest["faces"]
        self.assertLessEqual(len(faces), max_faces)
        self.assertEqual([entry["name"] for entry in faces], expected_names)

        referenced_files: set[Path] = set()
        for entry in faces:
            self.assertEqual(
                set(entry.keys()),
                {"name", "width", "height", "fps", "mode", "frames"},
            )
            self.assertEqual((entry["width"], entry["height"]), (128, 64))
            self.assertGreaterEqual(entry["fps"], 1)
            self.assertLessEqual(entry["fps"], 30)
            self.assertIn(entry["mode"], {"once", "loop", "boomerang"})
            frames = entry["frames"]
            self.assertGreaterEqual(len(frames), 1)
            self.assertLessEqual(len(frames), max_frames)
            for idx, rel in enumerate(frames):
                self.assertEqual(rel, f"faces/{entry['name']}/{idx}.bin")
                frame_path = SEED_DIR / rel
                self.assertTrue(frame_path.is_file(), f"Missing {frame_path}")
                data = frame_path.read_bytes()
                self.assertEqual(len(data), frame_bytes)
                self.assertTrue(any(data), f"Blank frame {frame_path}")
                referenced_files.add(frame_path.resolve())

        actual_files = {p.resolve() for p in (SEED_DIR / "faces").rglob("*") if p.is_file()}
        self.assertEqual(actual_files, referenced_files)

        default_frame = (SEED_DIR / "faces" / "default" / "0.bin").read_bytes()
        self.assertEqual(
            DEFAULT_FACE_HEADER.read_text(encoding="utf-8"),
            format_default_header(default_frame),
        )

        motion_source = json.loads(MOTION_SOURCE_MANIFEST.read_text(encoding="utf-8"))
        known_faces = set(expected_names)
        for motion in motion_source["assets"]:
            for cue in motion.get("face_cues", []):
                self.assertIn(cue["name"], known_faces)


if __name__ == "__main__":
    unittest.main()
