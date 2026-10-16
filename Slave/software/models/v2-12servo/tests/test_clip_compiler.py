"""Reject stale or incompatible motion handoffs before generating firmware data."""
import importlib.util
import sys
import math
import json
from pathlib import Path
import shutil
import tempfile
import unittest

MODEL = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODEL / "tools"))
spec = importlib.util.spec_from_file_location("compiler", MODEL / "tools/compile_clips.py")
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


class HandoffValidation(unittest.TestCase):
    def setUp(self):
        self.command = "rest"
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.family = self.root / "motions/gestures"
        self.family.mkdir(parents=True)
        shutil.copy2(MODEL / "model.json", self.root / "model.json")
        shutil.copy2(MODEL / "geometry.json", self.root / "geometry.json")
        shutil.copy2(MODEL / "servo_profile.json", self.root / "servo_profile.json")
        (self.root / "motions/turns").mkdir()
        shutil.copy2(MODEL / "motions/turns/sole-hulls.npz", self.root / "motions/turns/sole-hulls.npz")
        original = MODEL / "motions/gestures"
        shutil.copy2(original / "execution-policy.json", self.family / "execution-policy.json")
        shutil.copytree(original / "rest", self.family / "rest")
        self.catalog = json.loads((original / "catalog.json").read_text())
        self.catalog["commands"] = [e for e in self.catalog["commands"] if e["command"] == "rest"]
        self.write_catalog()

    def write_catalog(self):
        (self.family / "catalog.json").write_text(json.dumps(self.catalog))

    def edit(self, filename, change, rebind=False):
        path = self.family / self.command / filename
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))
        self.catalog["commands"][0]["sha256"][filename] = compiler.digest(path)
        self.write_catalog()
        if rebind:
            if filename == "source.json":
                self.edit("manifest.json", lambda m: m.update(source_sha256=compiler.digest(path)), rebind=True)
            source_path = self.catalog["commands"][0]["handoff"] + "/" + filename
            def bind(contract):
                for record in contract["source_files"]:
                    if record["path"] == source_path:
                        record["sha256"] = compiler.digest(path)
            self.edit("execution-contract.json", bind)

    def load(self):
        return compiler.load_gestures(self.root)

    def use_recovery(self):
        self.command = "freaky"
        original = MODEL / "motions/gestures"
        shutil.copytree(original / "freaky", self.family / "freaky")
        self.catalog = json.loads((original / "catalog.json").read_text())
        self.catalog["commands"] = [e for e in self.catalog["commands"] if e["command"] == "freaky"]
        self.write_catalog()

    def use_wave(self):
        self.command = "wave"
        original = MODEL / "motions/gestures"
        for name in ["sit", "wave"]:
            shutil.copytree(original / name, self.family / name)
        self.catalog = json.loads((original / "catalog.json").read_text())
        self.catalog["commands"] = [e for e in self.catalog["commands"] if e["command"] == "wave"]
        self.write_catalog()

    def test_reviewed_recording_changes_require_regeneration(self):
        original = MODEL / "motions/gestures"
        self.command = "dead"
        shutil.copytree(original / "dead", self.family / "dead")
        shutil.copy2(original / "reviewed-hulls.npz", self.family / "reviewed-hulls.npz")
        self.catalog = json.loads((original / "catalog.json").read_text())
        self.catalog["commands"] = [e for e in self.catalog["commands"] if e["command"] == "dead"]
        self.write_catalog()
        self.assertEqual(len(self.load()), 1)
        with (self.family / "dead/reviewed.json").open("a") as handle: handle.write(" ")
        with self.assertRaisesRegex(ValueError, "reviewed recording changed"): self.load()

    def test_wave_is_broad_seated_and_keeps_bare_supporting_feet_planted(self):
        self.use_wave()
        self.assertEqual(len(self.load()), 1)
        wave = json.loads((self.family / "wave/source.json").read_text())["samples"]
        posture = json.loads((self.family / "wave/posture.json").read_text())
        self.assertEqual(posture['contact_hulls_file'], 'contact-hulls.npz')
        self.assertEqual(wave[-1]['time_s'], 6.2)
        self.assertEqual(len(wave), 745)
        keys = ["actuator_angles_rad", "body_translation_world_mm", "body_rotation_euler_xyz_rad", "contact_active"]
        for i in range(145):
            for key in keys:
                self.assertEqual(wave[720-i][key], wave[i][key])
        for row in wave[144:577]:
            for leg in [0, 1, 3]:
                self.assertEqual(row["actuator_angles_rad"][leg], wave[144]["actuator_angles_rad"][leg])
                self.assertTrue(row["contact_active"][leg])
                self.assertLess(abs(row['sole_clearance_mm'][leg]), .001)
            for key in keys[1:3]:
                self.assertEqual(row[key], wave[144][key])
        shoulders = [row['actuator_angles_rad'][2][0] for row in wave[240:481]]
        self.assertAlmostEqual((max(shoulders)-min(shoulders))*180/3.141592653589793, 84., places=5)
        self.assertGreater(min(row['sole_clearance_mm'][2] for row in wave[240:481]), 40.)
        self.assertGreater(min(row['support_margin_mm'] for row in wave[145:576]), 19.)

    def test_wave_rejects_changed_sit_source(self):
        self.use_wave()
        with (self.family / "sit/source.json").open("a") as handle:
            handle.write(" ")
        with self.assertRaisesRegex(ValueError, "seated motion dependency changed"):
            self.load()

    def test_point_reaches_full_extension_promptly_and_keeps_support(self):
        source = json.loads((MODEL/'motions/gestures/point/source.json').read_text())
        held = [r for r in source['samples'] if r['phase']=='hold_point']
        self.assertLessEqual(held[0]['time_s'], 2.2)
        wave = json.loads((MODEL/'motions/gestures/wave/source.json').read_text())
        seated = wave['samples'][144]
        for row in held:
            for leg in [0, 1]:  # Model FL/FR are the physical rear legs.
                self.assertEqual(row['actuator_angles_rad'][leg], seated['actuator_angles_rad'][leg])
            self.assertEqual(row['body_translation_world_mm'], seated['body_translation_world_mm'])
        self.assertGreater(math.degrees(held[0]['actuator_angles_rad'][2][1]), 110.)
        self.assertGreater(held[-1]['time_s']-held[0]['time_s'], 1.4)
        for row in held:
            self.assertEqual(row['contact_active'], [True, True, False, True])
            self.assertGreater(row['support_margin_mm'], 19.)
            for leg in [0, 1, 3]:
                self.assertLess(abs(row['sole_clearance_mm'][leg]), .001)

    def test_pushup_has_five_deep_grounded_presses(self):
        source = json.loads((MODEL/'motions/gestures/pushup/source.json').read_text())
        rows = source['samples']
        bottoms = [p for p in source['phases'] if p['kind'].endswith('_bottom')]
        self.assertEqual(len(bottoms), 5)
        high = rows[round(source['phases'][0]['end']*120)]['front_body_clearance_mm']
        self.assertGreater(high, 44.)
        self.assertEqual(source['phases'][0]['kind'], 'squat_rear_legs')
        for phase in source['phases']:
            if phase['kind'].endswith(('_down', '_up')):
                self.assertGreaterEqual(phase['end']-phase['start'], 1.09)
        for row in rows:
            if row['phase'].startswith('pushup_'):
                self.assertAlmostEqual(row['rear_body_clearance_mm'], 8., places=6)
        for phase in bottoms:
            row = rows[round(phase['start']*120)]
            self.assertGreaterEqual(row['front_body_clearance_mm'], 2.99)
            self.assertLessEqual(row['front_body_clearance_mm'], 3.01)
            self.assertGreater(high-row['front_body_clearance_mm'], 40.)
        anchors = rows[0]['target_foot_reference_xy_mm']
        for row in rows:
            self.assertEqual(row['contact_active'], [True]*4)
            self.assertGreater(row['support_margin_mm'], 40.)
            for leg in range(4):
                self.assertLess(abs(row['sole_clearance_mm'][leg]), .001)
                for axis in range(2):
                    self.assertLess(abs(row['foot_bolt_world_mm'][leg][axis]-anchors[leg][axis]), .001)

    def test_worm_has_three_brisk_grounded_body_waves(self):
        source = json.loads((MODEL/'motions/gestures/worm/source.json').read_text())
        rows = source['samples']
        self.assertEqual(len([p for p in source['phases'] if p['kind'].startswith('body_wave_')]), 3)
        self.assertLess(rows[-1]['time_s'], 7.)
        pitches = [math.degrees(r['body_rotation_euler_xyz_rad'][1]) for r in rows]
        self.assertGreater(max(pitches)-min(pitches), 39.9)
        for row in rows:
            self.assertEqual(row['contact_active'], [True]*4)
            self.assertGreaterEqual(row['body_ground_clearance_mm'], 3.999)
            for leg in range(4):
                self.assertLess(abs(row['sole_clearance_mm'][leg]), .001)
                for axis in range(2):
                    self.assertLess(abs(row['foot_bolt_world_mm'][leg][axis]-rows[0]['target_foot_reference_xy_mm'][leg][axis]), .001)

    def test_bow_lowers_promptly_and_holds_for_five_seconds(self):
        source = json.loads((MODEL/'motions/gestures/bow/source.json').read_text())
        phase = next(p for p in source['phases'] if p['kind']=='hold_bow')
        self.assertLessEqual(phase['start'], 1.05)
        self.assertAlmostEqual(phase['end']-phase['start'], 5.)
        rows = source['samples'][round(phase['start']*120):round(phase['end']*120)+1]
        for row in rows:
            self.assertEqual(row['contact_active'], [True]*4)
            self.assertLess(row['body_ground_clearance_mm'], 2.1)
            self.assertGreater(row['body_ground_clearance_mm'], 1.9)
            for leg in range(4):
                self.assertLess(abs(row['sole_clearance_mm'][leg]), .001)
                for axis in range(3):
                    self.assertLess(abs(row['actuator_angles_rad'][leg][axis]-rows[0]['actuator_angles_rad'][leg][axis]), 1e-6)

    def test_wave_rejects_changed_sit_posture(self):
        self.use_wave()
        with (self.family / "sit/posture.json").open("a") as handle:
            handle.write(" ")
        with self.assertRaisesRegex(ValueError, "seated motion dependency changed"):
            self.load()

    def test_unchanged_source_and_unknown_limits_remain_research(self):
        clips = self.load()
        self.assertEqual(len(clips), 1)
        self.assertEqual(len(clips[0]["positions"]), 601)
        self.assertFalse(clips[0]["manifest"]["hardware_qualified"])

    def test_modified_source_without_new_hash_rejected(self):
        with (self.family / "rest/source.json").open("a") as handle:
            handle.write(" ")
        with self.assertRaisesRegex(ValueError, "source.json provenance"):
            self.load()

    def test_contract_for_different_source_rejected(self):
        self.edit("execution-contract.json", lambda c: c["source_files"][0].update(sha256="0"*64))
        with self.assertRaisesRegex(ValueError, "bound to a different source"):
            self.load()

    def test_wrong_wire_rejected(self):
        self.edit("manifest.json", lambda m: m.update(wire={"t":"intent","name":"sit"}), rebind=True)
        with self.assertRaisesRegex(ValueError, "command, source or geometry"):
            self.load()

    def test_wrong_geometry_rejected(self):
        self.edit("manifest.json", lambda m: m.update(geometry_sha256="0"*64), rebind=True)
        with self.assertRaisesRegex(ValueError, "geometry"):
            self.load()

    def test_reordered_model_joints_rejected(self):
        path = self.root / "model.json"
        model = json.loads(path.read_text())
        model["joints"].reverse()
        path.write_text(json.dumps(model))
        with self.assertRaisesRegex(ValueError, "model joint order"):
            self.load()

    def test_reordered_joints_rejected(self):
        self.edit("schema.json", lambda s: s["leg_order"].reverse())
        with self.assertRaisesRegex(ValueError, "joint order"):
            self.load()

    def test_missing_joint_rejected(self):
        self.edit("source.json", lambda s: s["samples"][10]["actuator_angles_rad"][0].pop(), rebind=True)
        with self.assertRaisesRegex(ValueError, "twelve joints"):
            self.load()

    def test_nonuniform_clock_rejected(self):
        self.edit("source.json", lambda s: s["samples"][10].update(time_s=0.9), rebind=True)
        with self.assertRaisesRegex(ValueError, "nonuniform"):
            self.load()

    def test_nonfinite_joint_rejected(self):
        self.edit("source.json", lambda s: s["samples"][10]["actuator_angles_rad"][0].__setitem__(0, float('nan')), rebind=True)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            self.load()

    def test_different_terminal_pose_rejected(self):
        self.edit("execution-contract.json", lambda c: c["completion"]["joint_angles_rad"][0].__setitem__(0, 0.5))
        with self.assertRaisesRegex(ValueError, "entry/final"):
            self.load()

    def test_phase_gap_rejected(self):
        self.edit("execution-contract.json", lambda c: c["phases"][1]["source_interval_s"].__setitem__(0, 3.1))
        with self.assertRaisesRegex(ValueError, "phase timing"):
            self.load()

    def test_retimed_demonstration_rejected(self):
        def retime(c):
            c["timing_profiles"]["demonstration"]["duration_s"][c["phases"][0]["id"]] = 1.0
        self.edit("execution-contract.json", retime)
        with self.assertRaisesRegex(ValueError, "phase timing"):
            self.load()

    def test_optional_recovery_is_excluded_from_compiled_command(self):
        self.use_recovery()
        clip = self.load()[0]
        self.assertEqual(clip["duration_s"], 9.2)
        self.assertEqual(len(clip["positions"]), 1105)
        source = json.loads((self.family / self.command / "source.json").read_text())
        expected = [math.degrees(q)*100 for leg in source["samples"][1104]["actuator_angles_rad"] for q in leg]
        self.assertEqual(clip["positions"][-1], expected)
        self.assertNotEqual(clip["positions"][-1], clip["positions"][0])
        self.assertEqual(clip["manifest"]["sample_count"], 1165)  # complete source retained

    def test_semantic_end_must_be_a_source_knot(self):
        self.use_recovery()
        self.edit("manifest.json", lambda m: m.update(semantic_end_seconds=7.4001), rebind=True)
        with self.assertRaisesRegex(ValueError, "semantic completion time"):
            self.load()

    def test_semantic_end_must_match_contract(self):
        self.use_recovery()
        self.edit("execution-contract.json", lambda c: c["completion"].update(semantic_end_s=12.3))
        with self.assertRaisesRegex(ValueError, "semantic completion contract"):
            self.load()

    def test_recovery_cannot_be_relabelled_as_command(self):
        self.use_recovery()
        self.edit("execution-contract.json", lambda c: c["phases"][-1].update(execution_role="command"))
        with self.assertRaisesRegex(ValueError, "execution role"):
            self.load()

    def test_wrong_semantic_terminal_rejected(self):
        self.use_recovery()
        self.edit("manifest.json", lambda m: m.update(semantic_final_actuator_angles_rad=[[0]*3]*4), rebind=True)
        with self.assertRaisesRegex(ValueError, "entry/final"):
            self.load()

    def test_nonfinite_demonstration_duration_rejected(self):
        self.edit("execution-contract.json", lambda c: c["timing_profiles"]["demonstration"]["duration_s"].update(
            {c["phases"][0]["id"]: float("nan")}))
        with self.assertRaisesRegex(ValueError, "phase timing"):
            self.load()

    def test_source_cannot_grant_hardware_readiness(self):
        self.edit("manifest.json", lambda m: m.update(hardware_qualified=True), rebind=True)
        with self.assertRaisesRegex(ValueError, "hardware readiness"):
            self.load()


if __name__ == '__main__':
    unittest.main()
