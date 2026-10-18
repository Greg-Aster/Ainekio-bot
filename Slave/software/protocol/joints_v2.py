"""P4 Freestyle map 2: signed model angles, before electrical calibration."""

JOINT_MAP_VERSION = 2
JOINT_LABELS = ('rear_left_shoulder', 'rear_left_carrier', 'rear_left_crank', 'rear_right_shoulder', 'rear_right_carrier', 'rear_right_crank', 'front_left_shoulder', 'front_left_carrier', 'front_left_crank', 'front_right_shoulder', 'front_right_carrier', 'front_right_crank')

def joint_contract() -> dict[str, object]:
    return {"version": JOINT_MAP_VERSION, "units": "signed_model_degrees",
            "joints": [{"id": i, "label": label} for i, label in enumerate(JOINT_LABELS)]}
