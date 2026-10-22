from __future__ import annotations

import math
import time
from collections import deque
from copy import deepcopy
from uuid import uuid4

DEFAULTS = {
    "wake_enabled": True, "tip_enabled": True, "rapid_enabled": True,
    "tip_degrees": 60.0, "tip_clear_degrees": 45.0, "tip_hold_ms": 300,
    "rapid_accel_g": 0.75, "rapid_clear_accel_g": 0.35,
    "rapid_rotation_dps": 180.0, "rapid_clear_rotation_dps": 90.0,
    "motion_cooldown_s": 10.0,
}


def validate_settings(value):
    # Preserve the owner's existing interval when upgrading rapid-only settings.
    if isinstance(value, dict):
        value = dict(value)
        previous = value.pop("rapid_cooldown_s", DEFAULTS["motion_cooldown_s"])
        value.setdefault("motion_cooldown_s", previous)
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError("Body event settings must contain all event controls")
    for key, default in DEFAULTS.items():
        item = value[key]
        if isinstance(default, bool):
            if type(item) is not bool:
                raise ValueError(f"{key} must be boolean")
        elif type(item) not in (int, float) or not math.isfinite(item) or item < 0:
            raise ValueError(f"{key} must be a finite non-negative number")
    if not 0 <= value["tip_clear_degrees"] < value["tip_degrees"] <= 180:
        raise ValueError("Tilt clear threshold must be below the trigger threshold (up to 180 degrees)")
    for trigger, clear in (("rapid_accel_g", "rapid_clear_accel_g"),
                           ("rapid_rotation_dps", "rapid_clear_rotation_dps")):
        if value[clear] >= value[trigger]:
            raise ValueError(f"{clear} must be below {trigger}")
    return dict(value)


class BodyEvents:
    """Measurements to events only; behavior selection belongs to the OS graph."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last_motion_report = {}
        self.settings = {}
        self.states = {}
        self.feedback_states = {}
        self.recent = deque(maxlen=30)

    def configure(self, robot_id, value):
        self.settings[robot_id] = validate_settings(value)
        self.states.pop(robot_id, None)

    def config(self, robot_id):
        return dict(self.settings.get(robot_id, DEFAULTS))

    def event(self, robot_id, epoch, kind, data, event_id=None):
        event = {"t": "event", "name": "body_event", "robot_id": robot_id,
                 "epoch": epoch, "event_id": event_id or uuid4().hex,
                 "data": {"kind": kind, **deepcopy(data)}}
        self.recent.append(deepcopy(event))
        return event

    def servo_stall(self, robot_id, epoch, message):
        legs = ("rear_left", "rear_right", "front_left", "front_right")
        roles = ("shoulder", "carrier", "crank")
        joints = [{"id": j, "name": f"{legs[j // 3]}_{roles[j % 3]}"}
                  for j in range(12) if message["joint_mask"] & (1 << j)]
        return self.event(robot_id, epoch, "servo_stall", {
            "joints": joints, "joint_mask": message["joint_mask"],
            "command_sequence": message["seq"], "clock_us": message["clock_us"],
            "outputs_released": message["outputs_released"],
            "reason": "no_position_progress",
        }, message["event_id"])

    def observe_feedback(self, robot_id, epoch, health, face_token=""):
        state = self.feedback_states.setdefault(robot_id, {})
        if state.get("epoch") != epoch:
            state.clear()
            state.update(epoch=epoch, reported=False)
        if not health["enabled"]:
            state.clear()
            return []
        # Acquisition can fail without advancing its scan. Episode state below
        # suppresses repeats without hiding a newly unavailable reader.
        reasons = ("unavailable", "clipped", "below_calibration", "above_calibration")
        mask = 0
        for reason in reasons:
            mask |= health[reason + "_mask"]
        fault = bool(mask)
        if fault == state["reported"]:
            return []
        now = self.clock()
        if fault:
            last = self.last_motion_report.get(robot_id)
            if face_token.startswith("be_") or (last is not None and
                    now-last < self.config(robot_id)["motion_cooldown_s"]):
                return []
            self.last_motion_report[robot_id] = now
        state["reported"] = fault
        legs = ("rear_left", "rear_right", "front_left", "front_right")
        roles = ("shoulder", "carrier", "crank")
        return [self.event(robot_id, epoch,
            "servo_feedback_fault" if fault else "servo_feedback_restored", {
                "joint_mask": mask,
                "joints": [{"id": j, "name": f"{legs[j // 3]}_{roles[j % 3]}",
                            "signal_millivolts": health["signal_millivolts"][j],
                            "reasons": [reason for reason in reasons if health[reason + "_mask"] & (1 << j)]}
                           for j in range(12) if mask & (1 << j)],
                "feedback": health,
                "outputs_released": False,
                "motion_policy": "continue_authored_motion",
                "supply_voltage_available": False,
            })]

    def wake(self, robot_id, epoch, reason, event_id=None, clock_us=None):
        if not self.config(robot_id)["wake_enabled"]:
            return None
        return self.event(robot_id, epoch, "wake", {"reason": reason,
            "clock_us": clock_us}, event_id)

    def observe(self, robot_id, epoch, imu):
        config = self.config(robot_id)
        identity = (epoch, imu.get("boot_id"))
        state = self.states.setdefault(robot_id, {})
        if state.get("identity") != identity:
            state.clear()
            state.update(identity=identity, tipped=False, rapid=False)
        # Sensor flags describe measurement availability, not permission to move.
        if not imu.get("available") or not imu.get("fresh"):
            state.pop("tip_since", None)
            return []
        at = imu["timestamp_us"]
        if at <= state.get("last_sample", -1):
            return []
        state["last_sample"] = at
        motion = imu.get("motion")
        if motion is None:
            state.pop("motion", None)
        elif max(motion["started_us"], motion["sampled_us"]) <= at:
            state["motion"] = motion
        else:
            # A just-written target cannot explain an older sensor sample.
            motion = state.get("motion")
        w, x, y, z = imu["orientation_wxyz"]
        actual_up = [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, actual_up[2]))))
        reference = motion.get("expected_up") if motion and imu.get("calibration_applied") else None
        unexpected_tilt = math.degrees(math.acos(max(-1.0, min(1.0,
            sum(a*b for a, b in zip(actual_up, reference)))))) if reference is not None else tilt
        commanded_locomotion = bool(motion and motion["activity"] == "locomotion"
                                    and motion["phase"] in {"entry", "motion"})
        reacting = imu.get("face_token", "").startswith("be_")
        accel = abs(math.hypot(*imu["acceleration_m_s2"])/9.80665 - 1)
        rotation = math.degrees(math.hypot(*imu["angular_rate_rad_s"]))
        evidence = {"imu": imu, "tilt_degrees": tilt, "acceleration_change_g": accel,
                    "unexpected_tilt_degrees": unexpected_tilt, "motion": motion,
                    "rotation_dps": rotation, "thresholds": config}
        candidates = []
        if unexpected_tilt < config["tip_clear_degrees"]:
            state["tipped"] = False
        if unexpected_tilt > config["tip_degrees"]:
            state.setdefault("tip_since", at)
            if (config["tip_enabled"] and not state["tipped"]
                    and at-state["tip_since"] >= config["tip_hold_ms"]*1000):
                state["tipped"] = True
                candidates.append("tipped")
        else:
            state.pop("tip_since", None)
        if accel < config["rapid_clear_accel_g"] and rotation < config["rapid_clear_rotation_dps"]:
            state["rapid"] = False
        if (config["rapid_enabled"] and not state["rapid"] and
                (accel > config["rapid_accel_g"] or rotation > config["rapid_rotation_dps"])):
            state["rapid"] = True
            if not commanded_locomotion:
                candidates.append("rapid_movement")
        # Both detectors keep their rearm state current during suppression.
        # Only emitted notifications start the shared interval; nothing queues.
        events = []
        now = self.clock()
        for kind in candidates:
            last = self.last_motion_report.get(robot_id)
            if not reacting and (last is None or now - last >= config["motion_cooldown_s"]):
                self.last_motion_report[robot_id] = now
                events.append(self.event(robot_id, epoch, kind, evidence))
        return events

    def status(self):
        return {"defaults": dict(DEFAULTS), "robots": deepcopy(self.settings),
                "recent": list(self.recent)}
