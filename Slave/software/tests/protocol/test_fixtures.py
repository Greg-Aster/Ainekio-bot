from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from protocol.control_v1 import (
    PROTOCOL_VERSION,
    VALIDATORS,
    ProtocolValidationError,
    validate_binary_frame,
    validate_control_message,
)


SOFTWARE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = SOFTWARE_ROOT / "protocol" / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURE_ROOT / name).open("r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    if fixture.get("protocol") != PROTOCOL_VERSION:
        raise AssertionError(f"{name} does not target protocol v{PROTOCOL_VERSION}")
    return fixture


def build_binary_frame(spec: dict[str, Any]) -> bytes:
    frame_type = int(spec["type"])
    counter = int(spec["counter"])
    if "payload_hex" in spec:
        payload = bytes.fromhex(spec["payload_hex"])
    else:
        repeated = bytes.fromhex(spec.get("payload_repeat", ""))
        payload = repeated * int(spec.get("payload_count", 0))
    return bytes([frame_type]) + counter.to_bytes(4, "little", signed=False) + payload


class ControlFixtureTests(unittest.TestCase):
    def test_all_valid_control_fixtures_are_accepted(self) -> None:
        fixture = load_fixture("control-valid-v1.json")
        covered_types: set[str] = set()
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                validate_control_message(case["message"])
                covered_types.add(case["message"]["t"])

        self.assertEqual(covered_types, set(VALIDATORS))

    def test_all_invalid_control_fixtures_are_rejected(self) -> None:
        fixture = load_fixture("control-invalid-v1.json")
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                with self.assertRaises(ProtocolValidationError) as raised:
                    validate_control_message(case["message"])
                self.assertEqual(raised.exception.reason, case["reason"])

    def test_fixture_tokens_are_redacted(self) -> None:
        for name in ("control-valid-v1.json", "control-invalid-v1.json"):
            text = (FIXTURE_ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("password", text.lower())
            if '"auth"' in text:
                self.assertIn("REDACTED-TOKEN", text)


class BinaryFixtureTests(unittest.TestCase):
    def test_binary_fixtures_match_expected_classification(self) -> None:
        fixture = load_fixture("binary-v1.json")
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                if "raw_hex" in case:
                    frames = [bytes.fromhex(case["raw_hex"])]
                elif "frames" in case:
                    frames = [build_binary_frame(spec) for spec in case["frames"]]
                else:
                    frames = [build_binary_frame(case["frame"])]

                if case["valid"]:
                    results = [validate_binary_frame(frame) for frame in frames]
                    self.assertTrue(all(result.known_type == case["known_type"] for result in results))
                    if case["name"] == "counter_wrap":
                        self.assertEqual([result.counter for result in results], [0xFFFFFFFF, 0])
                else:
                    with self.assertRaises(ProtocolValidationError) as raised:
                        validate_binary_frame(frames[0])
                    self.assertEqual(raised.exception.reason, case["reason"])


if __name__ == "__main__":
    unittest.main()
