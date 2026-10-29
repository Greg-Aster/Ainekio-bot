"""Shared physical/simulation observations, in body axes and model joint order.

No PWM, inferred ground contact, or invented current/torque measurements.
Missing vision is explicitly represented, not reported as zero displacement.
"""

import math

SCHEMA = "ainekio-neural-gait-v3"
DEPTH_SCHEMA = "ainekio-neural-gait-v4-depth"
SCHEMAS = frozenset((SCHEMA, DEPTH_SCHEMA))
LEGS = ("rear_left", "rear_right", "front_left", "front_right")
JOINTS = tuple(
    f"{leg}_{joint}" for leg in LEGS for joint in ("shoulder", "carrier", "crank")
)
IMU_QUALITY_FIELDS = (
    "available",
    "fresh",
    "startup",
    "gyro_recovery",
    "acceleration_recovery",
    "calibration_applied",
    "accelerometer_ignored",
)
OBSERVATION_SIZE = 148
SPATIAL_FEATURES = 64 + 64 + 4 + 12 + 3
COMMAND_SLICE = slice(82, 85)


def observation_size(schema=SCHEMA):
    if schema not in SCHEMAS:
        raise ValueError("Neural gait observation schema mismatch")
    return OBSERVATION_SIZE + (SPATIAL_FEATURES if schema == DEPTH_SCHEMA else 0)


def spatial_features(vision):
    grid = vision.get("depthSpatial")
    if not vision.get("depth_available") or not grid or not grid.get("available"):
        return [0.0] * SPATIAL_FEATURES
    if (grid.get("schema") != "ainekio-depth-grid-v1" or
            grid.get("rows") != 8 or grid.get("columns") != 8 or
            grid.get("units") not in {"metres", "estimated-metres"} or
            grid.get("frame") != "camera-optical" or grid.get("depthKind") != "optical-axis-z"):
        raise ValueError("Expected the shared 8x8 optical depth observation")
    depth, valid = grid["values"], grid["valid"]
    if len(depth) != 64 or len(valid) != 64 or any(type(ok) is not bool for ok in valid):
        raise ValueError("Expected 64 depth samples and validity flags")
    values = []
    for value, ok in zip(depth, valid):
        if ok and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
            raise ValueError("Valid optical depth must be finite and positive")
        values.append(float(value) if ok else 0.0)
    width, height = grid["imageSize"]
    k = grid["cameraMatrix"]
    if (type(width) is not int or type(height) is not int or min(width,height) <= 0
            or len(k) != 3 or any(len(row) != 3 for row in k)
            or not all(math.isfinite(float(v)) for row in k for v in row)
            or k[0][0] <= 0 or k[1][1] <= 0):
        raise ValueError("Invalid spatial depth camera intrinsics")
    values += [float(ok) for ok in valid]
    values += [k[0][0]/width, k[1][1]/height, k[0][2]/width, k[1][2]/height]
    transform = grid.get("cameraToBody")
    if transform is not None:
        from gateway.depth_motion import rigid
        transform = rigid(transform).tolist()
    values += ([float(value) for row in transform[:3] for value in row]
               if transform is not None else [0.0]*12)
    values += [1.0, float(transform is not None), float(bool(grid.get("metricAccuracyVerified")))]
    if len(values) != SPATIAL_FEATURES or not all(math.isfinite(v) for v in values):
        raise ValueError("Invalid spatial depth observation")
    return values


def vector(observation):
    size = observation_size(observation.get("schema"))

    def numbers(key, count, scale=1.0):
        values = observation[key]
        if len(values) != count or any(not math.isfinite(float(x)) for x in values):
            raise ValueError(f"Expected {count} finite {key} values")
        return [float(x) * scale for x in values]

    rad = math.pi / 180.0
    values = numbers("joint_deg", 12, rad) + numbers("joint_velocity_deg_s", 12, rad)
    values += numbers("target_deg", 12, rad)
    limits = observation["target_limits_deg"]
    if len(limits) != 12 or any(
        len(r) != 2 or not all(math.isfinite(float(x)) for x in r) or r[0] >= r[1]
        for r in limits
    ):
        raise ValueError("Expected twelve ordered target ranges")
    values += [float(x) * rad for r in limits for x in r]
    values += numbers("joint_usable", 12)
    values += numbers("orientation_wxyz", 4) + numbers("angular_rate_rad_s", 3)
    values += numbers("acceleration_m_s2", 3, 1 / 9.81) + numbers("command", 3)
    events = observation.get("events", {})
    values += [
        float(bool(events.get(k))) for k in ("jam", "tipped", "slip", "recovering")
    ]
    vision = observation.get("vision", {})
    available = bool(vision.get("available"))
    velocity = vision.get("velocity_body_m_s") if available else None
    if velocity is None:
        velocity = [0.0, 0.0, 0.0]
    if len(velocity) != 3:
        raise ValueError("Expected three visual velocity components")
    values += [float(x) for x in velocity] + [float(available)]
    values += [
        float(vision.get("depth_min_m") or 0.0),
        float(bool(vision.get("depth_available"))),
        float(vision.get("age_s") or 0.0),
    ]
    # Missing acquisition times/flags are unknown, not fresh zero-age readings.
    # Ages exclude unmeasured network transit and host publication latency.
    ages = observation["joint_sample_age_s"]
    if len(ages) != 12:
        raise ValueError("Expected twelve joint sample ages")
    imu_age = observation["imu_sample_age_s"]
    for age in [*ages, imu_age]:
        if age is not None and (
            isinstance(age, bool) or not math.isfinite(float(age)) or age < 0
        ):
            raise ValueError("Sensor ages must be nonnegative seconds or None")
    values += [0.0 if age is None else float(age) for age in ages]
    values += [float(age is not None) for age in ages]
    values += [0.0 if imu_age is None else float(imu_age), float(imu_age is not None)]
    quality = observation["imu_quality"]
    flags = [quality.get(key) for key in IMU_QUALITY_FIELDS]
    if any(flag is not None and not isinstance(flag, bool) for flag in flags):
        raise ValueError("IMU quality flags must be booleans or None")
    values += [float(flag is True) for flag in flags]
    values += [float(flag is not None) for flag in flags]
    if observation["schema"] == DEPTH_SCHEMA:
        values += spatial_features(vision)
    values += numbers("previous_action", 12)
    if len(values) != size or not all(math.isfinite(x) for x in values):
        raise ValueError("Invalid neural gait observation")
    return values


def foot_offsets(action, scale_mm):
    if len(action) != 12 or len(scale_mm) != 3:
        raise ValueError("Expected twelve foot actions and three axis scales")
    if any(not math.isfinite(float(x)) or x <= 0 for x in scale_mm):
        raise ValueError("Foot exploration scales must be finite and positive")
    if any(not math.isfinite(float(x)) or abs(x) > 1.000001 for x in action):
        raise ValueError("Policy action outside its normalized output contract")
    return [float(x)*scale_mm[i%3] for i,x in enumerate(action)]
