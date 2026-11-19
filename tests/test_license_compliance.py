"""Automated provenance and commercial license boundary guardrails."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class LicenseComplianceTests(unittest.TestCase):
    def test_microduck_vendor_contains_zero_restricted_stl_meshes(self):
        vendor = REPO_ROOT / "Master/gateway/neural_gait/vendor/microduck_rl"
        stls = list(vendor.rglob("*.stl"))
        self.assertEqual(stls, [], f"Restricted CC-BY-NC-SA-4.0 STL meshes must not exist in vendor: {stls}")
        self.assertFalse((vendor / "LICENSE-MODELS.md").exists())
        pyproject = (vendor / "pyproject.toml").read_text()
        self.assertIn('license = "Apache-2.0"', pyproject)
        self.assertNotIn("CC-BY-NC-SA-4.0", pyproject)
        upstream = json.loads((vendor / "UPSTREAM.json").read_text())
        self.assertIn("src/mjlab_microduck/robot/microduck/assets/*.stl", upstream["omitted"])

    def test_pupper_gpl_patches_and_modules_are_retired(self):
        sim_dir = REPO_ROOT / "Slave/software/models/v2-12servo/simulation"
        self.assertEqual(list(sim_dir.glob("*pupper*")), [])
        ng_dir = REPO_ROOT / "Master/gateway/neural_gait"
        self.assertEqual(list(ng_dir.glob("*pupper*")), [])

    def test_freenove_cc_by_nc_sa_reference_bundle_is_absent(self):
        self.assertFalse((REPO_ROOT / "docs/v1-8servo/reference").exists())

    def test_printable_hardware_tree_is_separated_from_third_party_references(self):
        import subprocess
        tracked = subprocess.check_output(
            ["git", "ls-files", "Slave/hardware"], cwd=str(REPO_ROOT), text=True
        ).splitlines()
        forbidden = [
            rel
            for rel in tracked
            if (REPO_ROOT / rel).exists()
            and any(
                token in Path(rel).name.lower()
                for token in (
                    "novaq",
                    "mg996r",
                    "freecad",
                    "adafruit-mg90d",
                    "mg90s.obj",
                    "mg90s-source-license",
                    "lower housing.stl",
                    "big and small leg",
                    "leg model v2.0",
                    "gy_lsm6ds3_reference",
                    "xiitia_1p9_reference",
                )
            )
        ]
        self.assertEqual(forbidden, [], f"Third-party/reference CAD must stay outside Slave/hardware/: {forbidden}")

        cad_refs = REPO_ROOT / "third_party/cad-references/Servo_Reference_Assets"
        self.assertTrue(cad_refs.is_dir())
        restricted_refs = [
            p for p in cad_refs.iterdir() if any(k in p.name.lower() for k in ("novaq", "mg996r", "sg90", "freecad"))
        ]
        self.assertEqual(restricted_refs, [], f"GPL-3.0 / CC-BY-SA-4.0 servo references must be absent: {restricted_refs}")

    def test_gateway_python_sources_import_zero_agpl_or_apple_research_packages(self):
        gateway_dir = REPO_ROOT / "Master/gateway"
        banned_roots = {"ultralytics", "mobileclip"}
        violations: list[str] = []
        for py_file in sorted(gateway_dir.rglob("*.py")):
            if "vendor" in py_file.parts:
                continue
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0].lower()
                        if root in banned_roots:
                            violations.append(f"{py_file.relative_to(REPO_ROOT)}:{node.lineno} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root = node.module.split(".")[0].lower()
                    if root in banned_roots:
                        violations.append(f"{py_file.relative_to(REPO_ROOT)}:{node.lineno} imports from {node.module}")
        self.assertEqual(violations, [], f"Prohibited AGPL/research imports found:\n" + "\n".join(violations))

    def test_third_party_inventory_and_commercial_manifest_are_valid(self):
        inventory = json.loads((REPO_ROOT / "THIRD_PARTY_INVENTORY.json").read_text())
        manifest = json.loads((REPO_ROOT / "COMMERCIAL_MANIFEST.json").read_text())
        self.assertEqual(inventory["schema"], "ainekio-third-party-inventory-v1")
        self.assertEqual(manifest["schema"], "ainekio-commercial-manifest-v1")
        prohibited = set(manifest["prohibited_spdx_licenses_in_shipped_code_or_cad"])

        for comp in inventory["components"]:
            self.assertNotIn(comp["spdx_license"], prohibited, f"Prohibited license in active component {comp['id']}")
            if "license_file" in comp:
                lf = REPO_ROOT / comp["license_file"]
                self.assertTrue(lf.is_file(), f"Missing license_file {comp['license_file']} for {comp['id']}")


if __name__ == "__main__":
    unittest.main()
