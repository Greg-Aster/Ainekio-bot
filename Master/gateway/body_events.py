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
    "rapid_cooldown_s": 10.0,
}


def validate_settings(value):
    # Saved settings from before the cooldown control retain their thresholds.
    if isinstance(value, dict):
        value = {"rapid_cooldown_s": DEFAULTS["rapid_cooldown_s"], **value}
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
        self.last_rapid_report = {}
        self.settings = {}
        self.states = {}
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
        w, x, y, z = imu["orientation_wxyz"]
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, 1 - 2*(x*x + y*y)))))
        accel = abs(math.hypot(*imu["acceleration_m_s2"])/9.80665 - 1)
        rotation = math.degrees(math.hypot(*imu["angular_rate_rad_s"]))
        evidence = {"imu": imu, "tilt_degrees": tilt, "acceleration_change_g": accel,
                    "rotation_dps": rotation, "thresholds": config}
        events = []
        if tilt < config["tip_clear_degrees"]:
            state["tipped"] = False
        if tilt > config["tip_degrees"]:
            state.setdefault("tip_since", at)
            if (config["tip_enabled"] and not state["tipped"]
                    and at-state["tip_since"] >= config["tip_hold_ms"]*1000):
                state["tipped"] = True
                events.append(self.event(robot_id, epoch, "tipped", evidence))
        else:
            state.pop("tip_since", None)
        if accel < config["rapid_clear_accel_g"] and rotation < config["rapid_clear_rotation_dps"]:
            state["rapid"] = False
        if (config["rapid_enabled"] and not state["rapid"] and
                (accel > config["rapid_accel_g"] or rotation > config["rapid_rotation_dps"])):
            state["rapid"] = True
            now = self.clock()
            last = self.last_rapid_report.get(robot_id)
            if last is None or now - last >= config["rapid_cooldown_s"]:
                self.last_rapid_report[robot_id] = now
                events.append(self.event(robot_id, epoch, "rapid_movement", evidence))
        return events

    def status(self):
        return {"defaults": dict(DEFAULTS), "robots": deepcopy(self.settings),
                "recent": list(self.recent)}
