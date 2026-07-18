from __future__ import annotations

import json
import math
import re
import unittest
from pathlib import Path
from typing import Any

from protocol.binary_helpers import (
    AUDIO_PAYLOAD_BYTES,
    CAMERA_JPEG_FRAME_TYPE,
    HEADER_BYTES,
    MAX_BINARY_COUNTER,
    MAX_JPEG_BYTES,
    MIC_PCM_FRAME_TYPE,
    SPEAKER_PCM_FRAME_TYPE,
    BinaryFrameError,
    decode_binary_frame,
    encode_binary_frame,
)
from protocol.control_v1 import (
    MAX_SEQUENCE,
    MOTION_PLAN_JOINTS,
    MOTION_PLAN_MAX_CENTIDEGREES,
    MOTION_PLAN_MAX_FRAMES,
    MOTION_PLAN_JOINT_MAP,
    PROTOCOL_VERSION,
    VALIDATORS,
    validate_control_message,
)


SOFTWARE_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_ROOT = SOFTWARE_ROOT / "protocol"
SCHEMA_ROOT = PROTOCOL_ROOT / "schemas"
FIXTURE_ROOT = PROTOCOL_ROOT / "fixtures"


class SchemaMismatch(AssertionError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _same_json_value(left: object, right: object) -> bool:
    if type(left) is not type(right) and isinstance(left, (bool, int)) and isinstance(right, (bool, int)):
        return False
    return left == right


def _resolve(root: dict[str, Any], reference: str) -> object:
    if not reference.startswith("#/"):
        raise SchemaMismatch(f"unsupported reference: {reference}")
    value: object = root
    for segment in reference[2:].split("/"):
        if not isinstance(value, dict) or segment not in value:
            raise SchemaMismatch(f"unresolved reference: {reference}")
        value = value[segment]
    return value


def assert_matches_schema(instance: object, schema: object, root: dict[str, Any]) -> None:
    if schema is True:
        return
    if schema is False:
        raise SchemaMismatch("forbidden value")
    if not isinstance(schema, dict):
        raise SchemaMismatch("schema node is not an object")

    if "$ref" in schema:
        assert_matches_schema(instance, _resolve(root, schema["$ref"]), root)

    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                assert_matches_schema(instance, option, root)
            except SchemaMismatch:
                continue
            matches += 1
        if matches != 1:
            raise SchemaMismatch(f"oneOf matched {matches} alternatives")

    expected_type = schema.get("type")
    if expected_type == "object" and not isinstance(instance, dict):
        raise SchemaMismatch("expected object")
    if expected_type == "array" and not isinstance(instance, list):
        raise SchemaMismatch("expected array")
    if expected_type == "string" and not isinstance(instance, str):
        raise SchemaMismatch("expected string")
    if expected_type == "boolean" and type(instance) is not bool:
        raise SchemaMismatch("expected boolean")
    if expected_type == "integer" and type(instance) is not int:
        raise SchemaMismatch("expected integer")
    if expected_type == "number":
        if type(instance) not in {int, float} or not math.isfinite(instance):
            raise SchemaMismatch("expected finite number")

    if "const" in schema and not _same_json_value(instance, schema["const"]):
        raise SchemaMismatch("const mismatch")
    if "enum" in schema and not any(_same_json_value(instance, value) for value in schema["enum"]):
        raise SchemaMismatch("enum mismatch")

    if type(instance) in {int, float}:
        if "minimum" in schema and instance < schema["minimum"]:
            raise SchemaMismatch("below minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise SchemaMismatch("above maximum")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise SchemaMismatch("string too short")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            raise SchemaMismatch("string too long")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            raise SchemaMismatch("pattern mismatch")

    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                raise SchemaMismatch(f"missing property: {name}")
        for name, property_schema in schema.get("properties", {}).items():
            if name in instance:
                assert_matches_schema(instance[name], property_schema, root)

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise SchemaMismatch("array too short")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise SchemaMismatch("array too long")

        prefix_items = schema.get("prefixItems", [])
        for index, item_schema in enumerate(prefix_items):
            if index < len(instance):
                assert_matches_schema(instance[index], item_schema, root)

        item_schema = schema.get("items")
        if item_schema is False and len(instance) > len(prefix_items):
            raise SchemaMismatch("additional array item")
        if isinstance(item_schema, dict):
            start = len(prefix_items) if prefix_items else 0
            for item in instance[start:]:
                assert_matches_schema(item, item_schema, root)

    for rule in schema.get("x-ainekio-rules", []):
        if rule == "ordered-limits":
            if not isinstance(instance, dict) or not instance["min"] <= instance["center"] <= instance["max"]:
                raise SchemaMismatch("unordered limits")
        elif rule == "unique-servo-ids":
            if not isinstance(instance, dict):
                raise SchemaMismatch("pose is not an object")
            servo_ids = [target[0] for target in instance["servos"]]
            if len(servo_ids) != len(set(servo_ids)):
                raise SchemaMismatch("duplicate servo id")
        elif rule == "unique-items":
            if not isinstance(instance, list) or len(instance) != len(set(instance)):
                raise SchemaMismatch("duplicate array item")
        elif rule == "motion-plan-total-duration":
            if not isinstance(instance, dict):
                raise SchemaMismatch("motion plan is not an object")
            frames = instance.get("frames")
            if not isinstance(frames, list) or any(
                not isinstance(frame, list) or not frame or type(frame[0]) is not int
                for frame in frames
            ):
                raise SchemaMismatch("motion plan frame duration is malformed")
            if sum(frame[0] for frame in frames) > 10000:
                raise SchemaMismatch("motion plan duration exceeds limit")
        else:
            raise SchemaMismatch(f"unknown semantic rule: {rule}")


class ControlSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_ROOT / "control-v1.schema.json")

    def test_schema_covers_exactly_the_runtime_message_types(self) -> None:
        definitions = self.schema["$defs"]
        schema_types = {
            definition["x-ainekio-message-type"]
            for definition in definitions.values()
            if isinstance(definition, dict) and "x-ainekio-message-type" in definition
        }
        self.assertEqual(schema_types, set(VALIDATORS))

    def test_every_valid_fixture_matches_the_schema(self) -> None:
        fixture = load_json(FIXTURE_ROOT / "control-valid-v1.json")
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                assert_matches_schema(case["message"], self.schema, self.schema)

    def test_every_invalid_fixture_is_rejected_by_the_schema(self) -> None:
        fixture = load_json(FIXTURE_ROOT / "control-invalid-v1.json")
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                with self.assertRaises(SchemaMismatch):
                    assert_matches_schema(case["message"], self.schema, self.schema)

    def test_invalid_fixtures_cover_every_known_message_type(self) -> None:
        fixture = load_json(FIXTURE_ROOT / "control-invalid-v1.json")
        covered = {
            case["message"].get("t")
            for case in fixture["cases"]
            if isinstance(case["message"], dict) and case["message"].get("t") in VALIDATORS
        }
        self.assertEqual(covered, set(VALIDATORS))

    def test_maximum_frame_count_motion_plan_fits_control_limit(self) -> None:
        message = {
            "t": "motion_plan",
            "seq": MAX_SEQUENCE,
            "map": MOTION_PLAN_JOINT_MAP,
            "frames": [
                [312, [MOTION_PLAN_MAX_CENTIDEGREES] * MOTION_PLAN_JOINTS]
                for _ in range(MOTION_PLAN_MAX_FRAMES)
            ],
            "end": "neutral",
        }
        validate_control_message(message)
        encoded = json.dumps(message, separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(encoded), 4096)


class BinaryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(SCHEMA_ROOT / "binary-v1.json")

    def test_manifest_matches_helper_constants(self) -> None:
        self.assertEqual(self.contract["protocol"], PROTOCOL_VERSION)
        self.assertEqual(self.contract["headerBytes"], HEADER_BYTES)
        self.assertEqual(self.contract["header"][1]["wrapsAt"] - 1, MAX_BINARY_COUNTER)

        frame_types = {entry["id"]: entry for entry in self.contract["frameTypes"]}
        self.assertEqual(set(frame_types), {MIC_PCM_FRAME_TYPE, CAMERA_JPEG_FRAME_TYPE, SPEAKER_PCM_FRAME_TYPE})
        self.assertEqual(frame_types[MIC_PCM_FRAME_TYPE]["payload"]["exactBytes"], AUDIO_PAYLOAD_BYTES)
        self.assertEqual(frame_types[SPEAKER_PCM_FRAME_TYPE]["payload"]["exactBytes"], AUDIO_PAYLOAD_BYTES)
        self.assertEqual(frame_types[CAMERA_JPEG_FRAME_TYPE]["payload"]["maximumBytes"], MAX_JPEG_BYTES)

    def test_known_frames_round_trip(self) -> None:
        cases = [
            (MIC_PCM_FRAME_TYPE, 0, bytes(AUDIO_PAYLOAD_BYTES)),
            (CAMERA_JPEG_FRAME_TYPE, 1042, b"\xff\xd8\xff\xd9"),
            (SPEAKER_PCM_FRAME_TYPE, MAX_BINARY_COUNTER, bytes(AUDIO_PAYLOAD_BYTES)),
        ]
        for frame_type, counter, payload in cases:
            with self.subTest(frame_type=frame_type, counter=counter):
                encoded = encode_binary_frame(frame_type, counter, payload)
                decoded = decode_binary_frame(encoded)
                self.assertEqual(decoded.frame_type, frame_type)
                self.assertEqual(decoded.counter, counter)
                self.assertEqual(decoded.payload_size, len(payload))
                self.assertTrue(decoded.known_type)

    def test_unknown_frame_round_trip_remains_classifiable(self) -> None:
        decoded = decode_binary_frame(encode_binary_frame(0x7F, 3, b"\x01\x02"))
        self.assertFalse(decoded.known_type)
        self.assertEqual(decoded.payload_size, 2)

    def test_encoder_rejects_invalid_known_payload(self) -> None:
        with self.assertRaises(BinaryFrameError) as raised:
            encode_binary_frame(MIC_PCM_FRAME_TYPE, 1, bytes(AUDIO_PAYLOAD_BYTES - 1))
        self.assertEqual(raised.exception.reason, "length:audio")


if __name__ == "__main__":
    unittest.main()
