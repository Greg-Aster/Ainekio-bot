"""Regenerate native recordings in isolation and reject incorrect foot targets."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy
    import scipy
except ImportError:
    print("Locomotion regeneration requires NumPy and SciPy.")
    sys.exit(77)

MODEL = Path(__file__).resolve().parents[1]
CLI = Path(sys.argv.pop(1)).resolve()
sys.path.insert(0, str(MODEL / "tools"))
import compile_clips
import generate_locomotion as generator
from validate_locomotion import leverage_report


class LocomotionGeneration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in (
            "model.json", "geometry.json", "servo_profile.json", "motion.c", "walk_kinematics.c",
            "motions/walk/reference.py", "motions/locomotion/config.json",
            "motions/locomotion/contact-hulls.json", "motions/locomotion/sole-profile.json",
            "motions/run/config.json", "motions/turns/sole-hulls.npz",
            "motions/gestures/catalog.json", "motions/gestures/execution-policy.json",
            "motions/gestures/sit/posture-hulls.npz", "motions/gestures/sit/sample_reference.py",
        ):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(MODEL / name, target)

    def test_regenerate_all_demonstrations_and_compile_crouch(self):
        cases = [("crouch", "fwd", True), ("run", "fwd", False)]
        for gait in ("walk", "crawl"):
            for suffix, direction in (("forward", "fwd"), ("backward", "back"),
                                      ("turn_left", "turn_l"), ("turn_right", "turn_r")):
                cases.append((f"{gait}_{suffix}", direction, gait == "crawl"))
        for command, direction, crawl in cases:
            with self.subTest(command=command):
                generator.record(self.root, CLI, command, direction, crawl)
                folder = "motions/gestures/crouch" if command == "crouch" else (
                    "motions/run" if command == "run" else f"motions/locomotion/{command}")
                source = json.loads((self.root / folder / "source.json").read_text())
                report = json.loads((self.root / folder / "validation.json").read_text())
                self.assertEqual(source["validation"], report)
                self.assertGreater(report["full_sole_height_error_mm"][1], .005)
                self.assertFalse(report["hardware_qualified"])
                name = "motions/locomotion/sole-profile.json"
                self.assertEqual(source["metadata"]["native_sources_sha256"][name],
                                 generator.digest(self.root / name))

        # Exercise the compiler's provenance, timing and endpoint checks against
        # the newly generated Crouch handoff, not the retained repository asset.
        catalog_path = self.root / "motions/gestures/catalog.json"
        catalog = json.loads(catalog_path.read_text())
        catalog["commands"] = [c for c in catalog["commands"] if c["command"] == "crouch"]
        catalog_path.write_text(json.dumps(catalog))
        self.assertEqual([c["command"] for c in compile_clips.load_gestures(self.root)], ["crouch"])

    def test_reject_straightened_and_weak_linkages(self):
        cfg = json.loads((MODEL / "geometry.json").read_text())
        margins = json.loads((MODEL / "motions/locomotion/config.json").read_text())["leverage_validation"]
        for crank in (-40.41, -35.):
            q = numpy.deg2rad(numpy.tile([0., 10.050314941406251, crank], (2,4,1)))
            with self.subTest(crank=crank), self.assertRaises(ValueError):
                leverage_report(cfg, q, numpy.ones((2,4), dtype=bool), margins)

    def test_allowance_does_not_hide_xy_error_or_wrong_height(self):
        wire = json.dumps(dict(t="intent", seq=1, name="walk", dir="fwd",
                               gait="crawl", steps=0, speed=0)) + "\n"
        run = subprocess.run([str(CLI), "30000", "120"], input=wire,
                             text=True, capture_output=True, check=True)
        original = [json.loads(line) for line in run.stdout.splitlines()]
        for axis, offset in ((0, .01), (2, .16), (2, -.02)):
            with self.subTest(axis=axis, offset=offset):
                rows = copy.deepcopy(original)
                rows[0]["feet"][0][axis] += offset
                result = subprocess.CompletedProcess(run.args, 0,
                    "\n".join(json.dumps(row) for row in rows), "")
                with patch.object(generator.subprocess, "run", return_value=result):
                    with self.assertRaises(AssertionError):
                        generator.record(self.root, CLI, "crouch", "fwd", True)
                self.assertFalse((self.root / "motions/gestures/crouch/source.json").exists())


if __name__ == "__main__":
    unittest.main()
