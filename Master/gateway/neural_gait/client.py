"""Neural inference and sensor projection; GatewayConnection owns execution."""

import asyncio
import json
import math
import os
from pathlib import Path
import urllib.error
import urllib.request

from .contract import IMU_QUALITY_FIELDS, SCHEMA, JOINTS, ObservationHistory, vector


class Client:
    def __init__(self, endpoint=None):
        self.endpoint = (
            endpoint
            or os.environ.get("AINEKIO_NEURAL_GAIT_ENDPOINT", "http://127.0.0.1:8796")
        ).rstrip("/")

    def request(self, path, payload=None, binary=False):
        body = (
            json.dumps(payload, allow_nan=False).encode()
            if payload is not None
            else None
        )
        request = urllib.request.Request(
            self.endpoint + path, body, {"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            raise ValueError(
                json.loads(error.read()).get("error", str(error))
            ) from error
        except urllib.error.URLError as error:
            raise ValueError(
                f"Neural gait service unavailable: {error.reason}"
            ) from error
        return data if binary else json.loads(data)

    async def call(self, path, payload=None):
        return await asyncio.to_thread(self.request, path, payload)


def sample_age(observed_us, sampled_us):
    """Age at the supplied device snapshot; missing/inconsistent clocks are unknown.

    This is not network latency. A later asynchronously acquired IMU timestamp
    cannot be assigned an age relative to an earlier feedback snapshot.
    """
    if (
        not isinstance(observed_us, (int, float))
        or isinstance(observed_us, bool)
        or not isinstance(sampled_us, (int, float))
        or isinstance(sampled_us, bool)
        or not math.isfinite(observed_us)
        or not math.isfinite(sampled_us)
        or sampled_us <= 0
        or observed_us < sampled_us
    ):
        return None
    return (observed_us - sampled_us) / 1e6


def walking_profile(value):
    """Explicit requested SI speeds at 100%; these are not measured maxima."""
    if not isinstance(value, dict) or value.get("source") not in {"native", "neural"}:
        raise ValueError("Choose native or neural walking source")
    if value["source"] == "native":
        return {"source": "native"}
    names = ("forward_m_s", "lateral_m_s", "yaw_rad_s")
    if any(type(value.get(key)) not in (int, float) or not math.isfinite(value[key])
           or value[key] <= 0 for key in names):
        raise ValueError("Supply positive finite forward/lateral m/s and yaw rad/s at 100%")
    return {"source": "neural", **{key: float(value[key]) for key in names}}


def walking_twist(command, profile):
    if "stride" in command or "rate" in command:
        raise ValueError("Neural walking uses requested speed and steering; select native for stride/rate controls")
    directions = {"fwd": (100,0,0), "back": (-100,0,0), "turn_l": (0,0,100),
                  "turn_r": (0,0,-100), "side_l": (0,100,0), "side_r": (0,-100,0)}
    forward, lateral, turn = directions[command.get("dir", "fwd")]
    if any(key in command for key in ("forward", "turn", "lateral")):
        forward, lateral, turn = command.get("forward", 0), command.get("lateral", 0), command.get("turn", 0)
    speed = command.get("speed", 100)/100
    return [speed*value/100*profile[key] for value, key in
            zip((forward,lateral,turn), ("forward_m_s","lateral_m_s","yaw_rad_s"))]


def walking_reference(status):
    environment = status.get("environment")
    if not status.get("model_id") or not environment:
        raise ValueError("Select a neural gait checkpoint before starting neural walking")
    path = Path(__file__).resolve().parents[3]/"Slave/software/models/v2-12servo/motions/walk/manifest.json"
    return {"geometry": json.loads(path.read_text())["geometry_id"],
            "reference_cd": [value*100 for value in environment["reference_joint_deg"]]}


def _relative_orientation(quaternion, yaw, sign):
    """Change the world reference only; gyro and acceleration are body-frame."""
    w, x, y, z = quaternion
    c, s = math.cos(yaw/2), math.sin(yaw/2)
    return [sign*value for value in (c*w+s*z, c*x+s*y, c*y-s*x, c*z-s*w)]


def walking_orientation_reference(quaternion):
    """Match simulation reset yaw/sign once, without resetting measured tilt."""
    w, x, y, z = quaternion
    yaw = math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))
    relative = _relative_orientation(quaternion, yaw, 1)
    return yaw, (1 if relative[0] >= 0 else -1)


def observation(source, environment, command, *, vision=None, previous_action=None,
                orientation_reference=None, history=None):
    """Use the gateway sensor observation's calibrated model coordinates.

    The policy action domain stays the domain it trained on. Servo feedback
    calibration ranges remain evidence, never silently become mechanical stops.
    """
    joints = [source["joints"][name] for name in JOINTS]
    imu = source.get("imu") or {}
    if any(
        key not in imu
        for key in ("orientation_wxyz", "angular_rate_rad_s", "acceleration_m_s2")
    ):
        raise ValueError("No IMU observation available for this policy preview")
    # Simulator and deployed policy both consume the production servo filter.
    # Raw model_deg remains available to diagnostic/Freestyle consumers.
    measured = [joint.get("filtered_model_deg") for joint in joints]
    usable = [
        joint.get("feedback_usable", False) and isinstance(angle, (float, int))
        for joint, angle in zip(joints, measured)
    ]
    measured = [
        float(angle) if isinstance(angle, (float, int)) else 0.0 for angle in measured
    ]
    target = [joint.get("commanded_model_deg") for joint in joints]
    target = [
        value if value is not None else angle for value, angle in zip(target, measured)
    ]
    limits = environment["target_limits_deg"]
    device_us = source.get("feedback", {}).get("device_us")
    result = dict(
        schema=environment.get("observation_schema", SCHEMA),
        joint_deg=measured,
        joint_velocity_deg_s=[joint.get("velocity_deg_s") or 0.0 for joint in joints],
        target_deg=target,
        target_limits_deg=limits,
        joint_usable=usable,
        orientation_wxyz=(_relative_orientation(imu["orientation_wxyz"], *orientation_reference)
            if orientation_reference is not None else imu["orientation_wxyz"]),
        angular_rate_rad_s=imu["angular_rate_rad_s"],
        acceleration_m_s2=imu["acceleration_m_s2"],
        command=command,
        events={"jam": bool(source.get("feedback", {}).get("stalled_joints"))},
        vision=vision or {"available": False},
        # Preview starts at zero; execution supplies the device-consumed action.
        previous_action=list(previous_action) if previous_action is not None else [0.0]*12,
        joint_sample_age_s=[
            sample_age(
                source.get("feedback", {}).get("device_us"), joint.get("sampled_us")
            )
            for joint in joints
        ],
        imu_sample_age_s=sample_age(
            source.get("feedback", {}).get("device_us"), imu.get("timestamp_us")
        ),
        imu_quality={key: imu.get(key) for key in IMU_QUALITY_FIELDS},
        observation_time_s=device_us/1e6 if type(device_us) in (int, float) else None,
    )
    result = (history if history is not None else ObservationHistory()).project(result)
    vector(result)
    return result
