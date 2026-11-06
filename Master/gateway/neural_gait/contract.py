"""Shared physical/simulation observations, in body axes and model joint order.

No PWM, inferred ground contact, or invented current/torque measurements.
Missing vision is explicitly represented, not reported as zero displacement.
"""

import math
import base64
import struct
import zlib
from collections import deque

SCHEMA = "ainekio-neural-gait-v3"
DEPTH_SCHEMA = "ainekio-neural-gait-v4-depth"
HISTORY_SCHEMA = "ainekio-neural-gait-v5-history"
PENDING_SCHEMA = "ainekio-neural-gait-v6-pending"
PROPRIO_SCHEMA = "ainekio-neural-gait-v7-proprio"
PROPRIO_CAMERA_SCHEMA = "ainekio-neural-gait-v8-proprio-camera"
PROPRIO_SCHEMAS = frozenset((PROPRIO_SCHEMA, PROPRIO_CAMERA_SCHEMA))
PROPRIO_FEATURES = 48
PROPRIO_SAMPLES = 15
PROPRIO_SIZE = PROPRIO_FEATURES * PROPRIO_SAMPLES
HISTORY_SCHEMAS = frozenset((HISTORY_SCHEMA, PENDING_SCHEMA))
DEPTH_SCHEMAS = frozenset((DEPTH_SCHEMA, PROPRIO_CAMERA_SCHEMA, *HISTORY_SCHEMAS))
SCHEMAS = frozenset((SCHEMA, *DEPTH_SCHEMAS, *PROPRIO_SCHEMAS))
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
# Ten past sensor snapshots spanning the reward's one-second pace window.
# This is a model input layout, not an inference wait or movement deadline.
HISTORY_INTERVAL_S = .1
HISTORY_SAMPLES = 10
HISTORY_FEATURES = 124  # v3 without the 24 static joint-limit coordinates
HISTORY_ROW_SIZE = HISTORY_FEATURES + 2  # actual age and availability
HISTORY_START = OBSERVATION_SIZE + SPATIAL_FEATURES + 2  # sin/cos heading error
CRITIC_FEATURES = 5  # simulator pace xyz and reward-reference heading sin/cos
HISTORY_SIZE = HISTORY_START + HISTORY_SAMPLES * HISTORY_ROW_SIZE + CRITIC_FEATURES



def recorded_observation(observation):
    """Lossless float32 policy inputs without duplicating verbose sensor history."""
    values = vector(observation)
    result = dict(schema=observation['schema'], encoding='float32-le-zlib-base64',
                values=base64.b64encode(zlib.compress(struct.pack('<%df' % len(values), *values))).decode())
    if observation['schema'] == PENDING_SCHEMA:
        result['pending_actions'] = pending_rows(observation['pending_actions'])
    return result


def pending_rows(value):
    """Ordered, uncapped sent requests: action[12], source age, signed send time.

    Send time is relative to the current sensor receipt, not a claimed physical
    output time. A positive value means the send followed that sensor receipt.
    """
    if not isinstance(value, (list, tuple)):
        raise ValueError('Expected pending action rows')
    result = []
    for row in value:
        if (len(row) != 14 or any(type(x) not in (int, float) or not math.isfinite(x) for x in row)
                or any(abs(x) > 1.000001 for x in row[:12]) or row[12] < 0):
            raise ValueError('Expected finite pending action[12], nonnegative source age and signed send time')
        result.append([float(x) for x in row])
    return result


def observation_size(schema=SCHEMA):
    if schema not in SCHEMAS:
        raise ValueError("Neural gait observation schema mismatch")
    if schema in HISTORY_SCHEMAS:
        return HISTORY_SIZE
    if schema in PROPRIO_SCHEMAS:
        return PROPRIO_SIZE + (SPATIAL_FEATURES if schema == PROPRIO_CAMERA_SCHEMA else 0)
    return OBSERVATION_SIZE + (SPATIAL_FEATURES if schema in DEPTH_SCHEMAS else 0)


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
    if observation.get("schema") in PROPRIO_SCHEMAS:
        rows = observation["proprio_history"]
        if len(rows) != PROPRIO_SAMPLES or any(len(row) != PROPRIO_FEATURES for row in rows):
            raise ValueError("Expected fifteen measured proprioceptive snapshots")
        values = [float(value) for row in rows for value in row]
        if observation["schema"] == PROPRIO_CAMERA_SCHEMA:
            values += spatial_features(observation.get("vision", {}))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Nonfinite proprioceptive observation")
        return values

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
    if observation["schema"] in DEPTH_SCHEMAS:
        values += spatial_features(vision)
    values += numbers("previous_action", 12)
    if observation["schema"] in HISTORY_SCHEMAS:
        error = float(observation["heading_error_rad"])
        values += [math.sin(error), math.cos(error)]
        history = observation["sensor_history"]
        if len(history) != HISTORY_SAMPLES or any(len(row) != HISTORY_ROW_SIZE for row in history):
            raise ValueError("Expected ten timestamped proprioceptive history rows")
        values += [float(value) for row in history for value in row]
        # Simulation supplies these to the value estimator only. The actor
        # explicitly excludes these columns in GaitPPOPolicy, including predict.
        critic = observation.get("training_critic", [0.0] * CRITIC_FEATURES)
        if len(critic) != CRITIC_FEATURES:
            raise ValueError("Expected five training-only critic coordinates")
        values += [float(value) for value in critic]
    if len(values) != size or not all(math.isfinite(x) for x in values):
        raise ValueError("Invalid neural gait observation")
    if observation['schema'] == PENDING_SCHEMA:
        pending_rows(observation['pending_actions'])
    return values


class ObservationHistory:
    """Per-walk sensor history shared by physical and virtual Body Control.

    Samples are selected causally by device time, not by inference call count.
    Repeated timestamps replace the current snapshot; command changes preserve
    history and the continuous Walk heading reference, like the P4. No simulator
    velocity, contact or position enters this projection.
    """

    def __init__(self):
        self.samples = deque()
        self.time = self.command = self.reference_heading = None

    def project(self, observation):
        if observation["schema"] in PROPRIO_SCHEMAS:
            now = observation.get("observation_time_s")
            if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
                raise ValueError("Expected a finite nonnegative observation_time_s")
            w,x,y,z = observation["orientation_wxyz"]
            gravity = [2*(x*z-w*y),2*(y*z+w*x),2*(w*w+z*z)-1]
            rad = math.pi/180
            row = ([value*rad for value in observation["joint_deg"]] +
                   [value*rad for value in observation["joint_velocity_deg_s"]] +
                   list(observation["angular_rate_rad_s"]) +
                   [value/9.81 for value in observation["acceleration_m_s2"]] +
                   [-value for value in gravity] + list(observation["command"]) +
                   list(observation["previous_action"]))
            if self.time is None or now < self.time:
                self.samples.clear()
            self.time = now
            if self.samples and self.samples[-1][0] == now:
                self.samples.pop()
            self.samples.append((now,row))
            while len(self.samples)>1 and self.samples[1][0]<now-PROPRIO_SAMPLES*.02:
                self.samples.popleft()
            result=dict(observation,proprio_history=[])
            for index in range(PROPRIO_SAMPLES):
                past=next((values for stamp,values in reversed(self.samples)
                           if stamp<=now-index*.02+1e-9),None)
                result["proprio_history"].append(past if past is not None else [0.]*PROPRIO_FEATURES)
            return result
        if observation["schema"] not in HISTORY_SCHEMAS:
            return observation
        now = observation.get("observation_time_s")
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError("History observations require finite nonnegative device time")
        w, x, y, z = observation["orientation_wxyz"]
        yaw = math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))
        command = list(observation["command"])
        if self.time is None or now < self.time:
            self.samples.clear()
            self.reference_heading = yaw
        else:
            self.reference_heading += self.command[2] * (now-self.time)
        self.time, self.command = now, command
        error = self.reference_heading-yaw
        result = dict(observation, heading_error_rad=math.atan2(math.sin(error), math.cos(error)))
        base = vector({**observation, "schema": SCHEMA})
        features = base[:36] + base[60:]
        if self.samples and self.samples[-1][0] == now:
            self.samples.pop()
        self.samples.append((now, features))
        oldest = now-HISTORY_SAMPLES*HISTORY_INTERVAL_S
        while len(self.samples) > 1 and self.samples[1][0] <= oldest:
            self.samples.popleft()
        result["sensor_history"] = []
        for index in range(1, HISTORY_SAMPLES+1):
            target = now-index*HISTORY_INTERVAL_S
            past = next(((time, row) for time, row in reversed(self.samples)
                         if time <= target+1e-9), None)
            result["sensor_history"].append(
                [*past[1], now-past[0], 1.] if past is not None
                else [0.] * HISTORY_ROW_SIZE)
        return result


def foot_offsets(action, scale_mm):
    if len(action) != 12 or len(scale_mm) != 3:
        raise ValueError("Expected twelve foot actions and three axis scales")
    if any(not math.isfinite(float(x)) or x <= 0 for x in scale_mm):
        raise ValueError("Foot exploration scales must be finite and positive")
    if any(not math.isfinite(float(x)) or abs(x) > 1.000001 for x in action):
        raise ValueError("Policy action outside its normalized output contract")
    return [float(x)*scale_mm[i%3] for i,x in enumerate(action)]
