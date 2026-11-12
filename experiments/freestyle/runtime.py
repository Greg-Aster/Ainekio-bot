"""Canonical V2 joint order, packet frame capacity, and compact JSON serializer."""
from __future__ import annotations

import json

JOINTS = tuple(f"{leg}_{axis}" for leg in
               ("rear_left", "rear_right", "front_left", "front_right")
               for axis in ("shoulder", "carrier", "crank"))
MAX_FRAMES = 32  # Existing motion_plan_v2 packet capacity, not a model token cap.


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
