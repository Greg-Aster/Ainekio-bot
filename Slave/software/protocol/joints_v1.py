"""Frozen logical-joint contract shared by protocol-v1 components."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


JOINT_MAP_VERSION = 1
JOINT_LABELS = ("R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4")
JOINT_COUNT = len(JOINT_LABELS)


def joint_contract() -> dict[str, object]:
    return {
        "version": JOINT_MAP_VERSION,
        "joints": [
            {"id": joint_id, "label": label}
            for joint_id, label in enumerate(JOINT_LABELS)
        ],
    }


def validate_joint_contract(value: object) -> None:
    if not isinstance(value, Mapping) or value.get("version") != JOINT_MAP_VERSION:
        raise ValueError("joint-map version mismatch")
    joints = value.get("joints")
    if not isinstance(joints, Sequence) or isinstance(joints, (str, bytes)):
        raise ValueError("joint map must contain a joint list")
    expected = [
        {"id": joint_id, "label": label}
        for joint_id, label in enumerate(JOINT_LABELS)
    ]
    if list(joints) != expected:
        raise ValueError("joint map is missing, duplicated, unknown, or reordered")
