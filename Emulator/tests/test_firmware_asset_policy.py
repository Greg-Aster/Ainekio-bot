from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from Slave.software.tools.stage_firmware_assets import stage_assets


ROOT = Path(__file__).resolve().parents[2]
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
MOTION_MANIFEST = ROOT / "Slave" / "software" / "assets" / "seed" / "motions-bin-v1.json"


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


if __name__ == "__main__":
    unittest.main()
