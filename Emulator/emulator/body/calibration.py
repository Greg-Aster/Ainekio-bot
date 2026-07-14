from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Mapping


CALIBRATION_SCHEMA_VERSION = 1
MAX_CALIBRATION_FILE_BYTES = 64 * 1024


class CalibrationStore:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._committed = self._load()
        self._working = deepcopy(self._committed)

    def stage_limits(self, message: Mapping[str, object]) -> None:
        servo_id = str(int(message["id"]))
        self._working["limits"][servo_id] = {
            "min": float(message["min"]),
            "max": float(message["max"]),
            "invert": bool(message["invert"]),
            "center": float(message["center"]),
        }

    def stage_pose(self, message: Mapping[str, object]) -> None:
        name = str(message["name"])
        self._working["poses"][name] = [
            [int(entry[0]), float(entry[1])]
            for entry in message["servos"]
            if isinstance(entry, list) and len(entry) == 2
        ]

    def target_within_limits(self, servo_id: int, degrees: float) -> bool:
        limits = self._working["limits"].get(str(servo_id))
        if not isinstance(limits, dict):
            return 0.0 <= degrees <= 180.0
        minimum = limits.get("min")
        maximum = limits.get("max")
        return (
            type(minimum) in {int, float}
            and type(maximum) in {int, float}
            and float(minimum) <= degrees <= float(maximum)
        )

    def logical_target_within_limits(self, servo_id: int, degrees: float) -> bool:
        limits = self._working["limits"].get(str(servo_id))
        if not isinstance(limits, dict):
            return 0.0 <= degrees <= 180.0
        minimum = limits.get("min")
        center = limits.get("center")
        maximum = limits.get("max")
        invert = limits.get("invert")
        if (
            type(minimum) not in {int, float}
            or type(center) not in {int, float}
            or type(maximum) not in {int, float}
            or type(invert) is not bool
        ):
            return False
        direction = -1.0 if invert else 1.0
        physical = float(center) + direction * (degrees - 90.0)
        return float(minimum) <= physical <= float(maximum)

    def commit(self) -> None:
        encoded = json.dumps(
            self._working,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > MAX_CALIBRATION_FILE_BYTES:
            raise OSError("calibration data exceeds the bounded emulator store")
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.tmp")
            temporary.write_bytes(encoded)
            os.replace(temporary, self.path)
        self._committed = deepcopy(self._working)

    def snapshot(self) -> dict[str, object]:
        return deepcopy(self._committed)

    def _load(self) -> dict[str, object]:
        empty: dict[str, object] = {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "limits": {},
            "poses": {},
        }
        if self.path is None or not self.path.exists():
            return empty
        raw = self.path.read_bytes()
        if len(raw) > MAX_CALIBRATION_FILE_BYTES:
            raise RuntimeError("emulator calibration file exceeds its size limit")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("emulator calibration file is invalid JSON") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != CALIBRATION_SCHEMA_VERSION
            or not isinstance(value.get("limits"), dict)
            or not isinstance(value.get("poses"), dict)
        ):
            raise RuntimeError("emulator calibration file has an unsupported schema")
        return value
