from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Slave.software.tools.package_micro_wake_word import package_model


class PackageMicroWakeWordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.model = self.root / "trained.tflite"
        self.model.write_bytes(b"\x1c\x00\x00\x00TFL3" + bytes(2040))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def package(self, **overrides: object) -> Path:
        arguments: dict[str, object] = {
            "model": self.model,
            "output_dir": self.root / "package",
            "model_id": "ainekio",
            "wake_word": "Ainekio",
            "author": "local owner",
            "license_name": "CC0-1.0",
            "training_revision": "local-test-1",
            "trained_languages": ["en"],
            "probability_cutoff": 0.97,
            "feature_step_size": 10,
            "sliding_window_size": 5,
            "tensor_arena_size": 26080,
        }
        arguments.update(overrides)
        return package_model(**arguments)  # type: ignore[arg-type]

    def test_writes_bounded_manifest_and_unchanged_model(self) -> None:
        manifest_path = self.package()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], "ainekio-microwakeword-v1")
        self.assertEqual(manifest["id"], "ainekio")
        self.assertEqual(manifest["wake_word"], "Ainekio")
        self.assertEqual(manifest["trained_languages"], ["en"])
        self.assertEqual(manifest["micro"]["feature_step_size"], 10)
        self.assertEqual(
            (manifest_path.parent / manifest["model"]).read_bytes(),
            self.model.read_bytes(),
        )

    def test_rejects_non_tflite_input(self) -> None:
        self.model.write_bytes(bytes(2048))
        with self.assertRaisesRegex(ValueError, "TFL3"):
            self.package()

    def test_refuses_accidental_overwrite(self) -> None:
        self.package()
        with self.assertRaises(FileExistsError):
            self.package()
        self.package(replace=True)


if __name__ == "__main__":
    unittest.main()
