"""Thin bindings to the same calibration, feedback and IMU code as the P4."""

import ctypes
import fcntl
import math
import json
import threading
from functools import lru_cache
from pathlib import Path
import subprocess
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
WALK_LOCK = threading.RLock()  # Native production speed setting is process-global.
ARRAY = np.ctypeslib.ndpointer(dtype=np.float64, flags="C_CONTIGUOUS")


def finite_array(value, size):
    result = np.ascontiguousarray(value, dtype=np.float64)
    if result.shape != (size,) or not np.isfinite(result).all():
        raise ValueError(f"Expected {size} finite values for native model input")
    return result


@lru_cache(maxsize=1)
def library():
    build = ROOT / "build/neural-gait/native"
    build.mkdir(parents=True, exist_ok=True)
    # Training/evaluation/render workers may initialize together. Share the
    # normal incremental native build rather than racing its generated files.
    with (build / "build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with (build / "build.log").open("w") as log:
            subprocess.run(
                [
                    "cmake",
                    "-S",
                    str(Path(__file__).parent),
                    "-B",
                    str(build),
                    "-DPython3_EXECUTABLE=" + sys.executable,
                    "-DCMAKE_BUILD_TYPE=Release",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
            subprocess.run(
                ["cmake", "--build", str(build), "--target", "gait_native", "-j", "4"],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
    lib = ctypes.CDLL(str(build / "libgait_native.so"))
    lib.simulation_new.argtypes = [ARRAY, ARRAY, ARRAY]
    lib.simulation_new.restype = ctypes.c_void_p
    lib.simulation_free.argtypes = [ctypes.c_void_p]
    lib.simulation_target.argtypes = [
        ctypes.c_void_p,
        ARRAY,
        ARRAY,
        ctypes.c_double,
        ctypes.c_double,
        ARRAY,
    ]
    lib.simulation_feedback.argtypes = [ctypes.c_void_p, ARRAY, ARRAY, ARRAY, ARRAY]
    lib.simulation_feedback.restype = ctypes.c_uint
    lib.simulation_arrival.argtypes = [ctypes.c_void_p, ARRAY, ctypes.c_double, ARRAY]
    lib.simulation_arrival.restype = ctypes.c_int
    lib.simulation_imu.argtypes = [
        ctypes.c_void_p,
        ctypes.c_double,
        ARRAY,
        ARRAY,
        ARRAY,
    ]
    lib.simulation_foot_target.argtypes = [
        ctypes.c_void_p,
        ARRAY,
        ARRAY,
        ARRAY,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ARRAY,
    ]
    lib.simulation_balance_configure.argtypes = [ctypes.c_void_p, ARRAY]
    lib.simulation_balance_configure.restype = None
    lib.simulation_pwm.argtypes = [
        ctypes.c_void_p,
        ARRAY,
        ctypes.c_double,
        ctypes.c_double,
        ARRAY,
    ]
    lib.simulation_imu_status.argtypes = [ctypes.c_void_p, ctypes.c_double, ARRAY]
    lib.simulation_walk_configure.argtypes = [
        ctypes.c_void_p,
        ARRAY,
        ARRAY,
        ctypes.c_int,
    ]
    lib.simulation_walk_accept.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_double,
    ]
    lib.simulation_walk_tick.argtypes = [
        ctypes.c_void_p,
        ctypes.c_double,
        ARRAY,
        ARRAY,
        ctypes.c_int,
        ARRAY,
    ]
    lib.virtual_body_reset.argtypes = [ctypes.c_void_p, ARRAY, ARRAY, ctypes.c_uint64]
    lib.virtual_body_reset.restype = ctypes.c_int
    lib.virtual_body_close.argtypes = []
    lib.virtual_body_close.restype = None
    lib.virtual_body_open.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
    lib.virtual_body_open.restype = None
    lib.virtual_body_connection_lost.argtypes = [ctypes.c_uint64]
    lib.virtual_body_connection_lost.restype = None
    lib.virtual_body_tick.argtypes = [ctypes.c_uint64, ARRAY]
    lib.virtual_body_tick.restype = ctypes.c_int
    text_output = [ctypes.c_void_p, ctypes.c_size_t]
    lib.virtual_body_telemetry.argtypes = [ctypes.c_uint64, *text_output]
    lib.virtual_body_feedback.argtypes = [ctypes.c_uint64, *text_output]
    lib.virtual_body_hello.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint64, *text_output]
    lib.virtual_body_receive.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.c_uint64, *text_output]
    lib.virtual_body_events.argtypes = text_output
    for name in ("telemetry", "hello", "receive", "events", "feedback"):
        getattr(lib, "virtual_body_" + name).restype = ctypes.c_size_t
    return lib


class BodyModel:
    def __init__(self, robot):
        self.robot = robot
        self.lib = library()
        self.state = None
        self.mapping = sorted(robot["calibration"], key=lambda j: j["id"])
        self.feedback = sorted(robot["feedback"]["joints"], key=lambda j: j["id"])
        if [j["id"] for j in self.mapping] != list(range(12)) or [
            j["id"] for j in self.feedback
        ] != list(range(12)):
            raise ValueError(
                "Expected all twelve distinct model joints in calibration and feedback"
            )
        if any(len(j["points"]) != 3 for j in self.feedback):
            raise ValueError("Expected three captured feedback points per joint")
        self.reset()

    def reset(self):
        self.close()
        mapping = np.array(
            [
                [
                    j[k]
                    for k in (
                        "channel",
                        "invert",
                        "home_us",
                        "home_cd",
                        "us_per_degree",
                    )
                ]
                for j in self.mapping
            ],
            dtype=np.float64,
        )
        feedback = np.array(
            [
                [j["channel"]]
                + [p[k] for p in j["points"] for k in ("raw", "pulse_us")]
                for j in self.feedback
            ],
            dtype=np.float64,
        )
        cfg = self.robot["feedback"]
        settings = np.array(
            [
                cfg[k]
                for k in (
                    "tolerance_us",
                    "arrival_tolerance_us",
                    "no_progress_ms",
                    "progress_us",
                    "enabled",
                    "jam_enabled",
                )
            ],
            dtype=np.float64,
        )
        settings = np.append(settings, float(cfg.get("stand_enabled", False)))
        self.state = self.lib.simulation_new(mapping, feedback, settings)
        if not self.state:
            raise ValueError("Invalid captured device calibration or feedback curve")

    def close(self):
        if getattr(self, "_virtual_body", None) is not None:
            raise RuntimeError("Close the virtual P4 executor before resetting its sensor state")
        if self.state:
            self.lib.simulation_free(self.state)
            self.state = None

    def target(self, requested, previous, speed, dt):
        requested = finite_array(requested, 12)
        previous = finite_array(previous, 12)
        if not math.isfinite(speed) or speed <= 0 or not math.isfinite(dt) or dt < 0:
            raise ValueError(
                "Native ramp speed must be positive and sample interval nonnegative"
            )
        out = np.zeros(24, dtype=np.float64)
        ok = self.lib.simulation_target(
            self.state,
            requested,
            previous,
            speed,
            dt,
            out,
        )
        return (out[:12], out[12:]) if ok else None

    def raw_samples(self, angles):
        angles = finite_array(angles, 12)
        result = []
        for angle, m, f in zip(angles, self.mapping, self.feedback):
            pulse = (
                m["home_us"]
                + (-1 if m["invert"] else 1)
                * (angle - m["home_cd"] / 100)
                * m["us_per_degree"]
            )
            points = sorted(f["points"], key=lambda p: p["pulse_us"])
            a, b = points[:2] if pulse <= points[1]["pulse_us"] else points[1:]
            result.append(
                a["raw"]
                + (pulse - a["pulse_us"])
                * (b["raw"] - a["raw"])
                / (b["pulse_us"] - a["pulse_us"])
            )
        return np.array(result)

    def feedback_sample(self, raw, target, timestamps):
        raw = np.ascontiguousarray(raw, dtype=np.float64)
        target = np.ascontiguousarray(target, dtype=np.float64)
        timestamps = np.ascontiguousarray(timestamps, dtype=np.float64)
        if raw.shape != (12,) or target.shape != (12,) or timestamps.shape != (12,):
            raise ValueError(
                "Expected twelve feedback samples, targets and acquisition timestamps"
            )
        if (
            np.isinf(raw).any()
            or ((raw < 0) | (raw > 4095)).any()
            or not np.isfinite(target).all()
            or not np.isfinite(timestamps).all()
        ):
            raise ValueError(
                "Feedback samples must be 12-bit ADC values or NaN for failed acquisition"
            )
        out = np.zeros(36, dtype=np.float64)
        mask = self.lib.simulation_feedback(self.state, raw, target, timestamps, out)
        return out[:12], out[12:24], out[24:].astype(bool), mask

    def sample_times(self, latest_sample_s):
        """Recorded relative scan timing, in joint order, not uniform joint ages.

        The source timestamp differences establish channel skew. Network and
        publication delay remain the environment/transport's responsibility.
        """
        age = np.asarray(
            self.robot["feedback"]["sample_age_from_last_channel_us"], dtype=float
        )
        if age.shape != (12,) or not np.isfinite(age).all() or np.any(age < 0):
            raise ValueError(
                "Expected measured channel ages from a complete feedback scan"
            )
        return np.maximum(0.0, latest_sample_s - age / 1e6)

    def arrival(self, target, commanded_us):
        target = np.ascontiguousarray(target, dtype=np.float64)
        if target.shape != (12,) or not np.isfinite(target).all():
            raise ValueError("Expected twelve finite endpoint angles")
        out = np.zeros(6, dtype=np.float64)
        observed = bool(
            self.lib.simulation_arrival(self.state, target, commanded_us, out)
        )
        keys = (
            "remaining_joints",
            "calibrated_mask",
            "unavailable_mask",
            "clipped_mask",
            "below_calibration_mask",
            "above_calibration_mask",
        )
        return dict(
            observed=observed,
            arrived=bool(observed and out[0] == 0),
            **dict(zip(keys, map(int, out))),
        )

    def imu_sample(self, timestamp_us, accel, gyro):
        if not math.isfinite(timestamp_us) or timestamp_us < 0:
            raise ValueError("IMU acquisition timestamp must be finite and nonnegative")
        out = np.zeros(14, dtype=np.float64)
        self.lib.simulation_imu(
            self.state,
            timestamp_us,
            finite_array(accel, 3),
            finite_array(gyro, 3),
            out,
        )
        return out

    def walk_configure(
        self,
        *,
        speed_deg_s,
        heading_enabled,
        balance_enabled,
        tuning=(1.0, 1.0, 0.0, 0.0),
        model=None,
        amount=1.0,
    ):
        """Reset offline WALK state, with explicit controller settings.

        Optional model is 237 floats in production struct order: phase(60),
        feedback(96), command(48), gait profile(33). This replays the policy
        math only; it does not claim saved-model admission/signature parity.
        """
        settings = finite_array(
            [speed_deg_s, heading_enabled, balance_enabled, *tuning, amount], 8
        )
        coefficients = np.zeros(237) if model is None else finite_array(model, 237)
        with WALK_LOCK:
            valid = self.lib.simulation_walk_configure(
                self.state, settings, coefficients, model is not None
            )
        if not valid:
            raise ValueError("Invalid production WALK settings or gait profile")

    def walk_accept(self, command, now_us):
        """Decode the actual intent wire format and admit/update existing WALK.

        Updates use the last executed clock as body.c does; passing their later
        arrival time never restarts a step or resets the active command owner.
        """
        if not math.isfinite(now_us) or now_us < 0:
            raise ValueError("WALK timestamp must be finite and nonnegative")
        encoded = json.dumps(command, allow_nan=False).encode()
        with WALK_LOCK:
            return bool(self.lib.simulation_walk_accept(self.state, encoded, now_us))

    def walk_tick(
        self, now_us, previous_angles, *, learning_input=None, learning_usable=False
    ):
        """Advance production WALK/balance/optional policy, using estimated IMU.

        previous_angles is the last commanded output, not measured feedback.
        learning_input, when supplied, is 4x8 timestamp-aligned policy features
        from the caller's replay, not simulated true contact/pose information.
        Predicted grounded states follow physical rear-left/rear-right/front-left/front-right
        order (CAD FL/FR/RL/RR, as declared by the existing model.json).
        """
        if not math.isfinite(now_us) or now_us < 0:
            raise ValueError("WALK timestamp must be finite and nonnegative")
        features = (
            np.zeros(32)
            if learning_input is None
            else finite_array(np.asarray(learning_input).reshape(-1), 32)
        )
        out = np.zeros(80)
        with WALK_LOCK:
            valid = self.lib.simulation_walk_tick(
                self.state,
                now_us,
                finite_array(previous_angles, 12),
                features,
                learning_usable,
                out,
            )
        if not valid:
            return None
        result = dict(
            nominal_angles=out[:12],
            balanced_angles=out[12:24],
            applied_angles=out[24:36],
            mapped_angles=out[36:48],
            phase=out[48],
            run_blend=out[49],
            predicted_grounded=out[50:54].astype(bool),
            command_features=out[54:58],
            body_mm=out[74:77],
            euler_rad=out[77:80],
        )
        names = (
            "complete",
            "stopping",
            "failed",
            "clock_scale",
            "heading_active",
            "heading_reduced",
            "balance_usable",
            "balance_reduced",
            "imu_usable",
            "learning_blend",
            "learning_fit",
            "command_sequence",
            "latest_sequence",
            "last_us",
            "heading_error",
            "feedback_turn",
        )
        bool_keys = {
            "complete",
            "stopping",
            "failed",
            "heading_active",
            "heading_reduced",
            "balance_usable",
            "balance_reduced",
            "imu_usable",
        }
        for key, value in zip(names, out[58:74]):
            result[key] = bool(value) if key in bool_keys else float(value)
        return result

    def imu_status(self, timestamp_us):
        """Current production estimator quality and sample age in model body axes.

        calibration_applied records the simulator's initialized identity body
        rotation; it does not qualify the physical robot's mounting calibration.
        Missing/out-of-order acquisition age is None, never fabricated zero age.
        """
        from .contract import IMU_QUALITY_FIELDS

        if not math.isfinite(timestamp_us) or timestamp_us < 0:
            raise ValueError("IMU observation timestamp must be finite and nonnegative")
        out = np.zeros(9)
        self.lib.simulation_imu_status(self.state, timestamp_us, out)
        return dict(
            quality=dict(zip(IMU_QUALITY_FIELDS, map(bool, out[:7]))),
            timestamp_us=int(out[7]) if out[0] else None,
            sample_age_s=float(out[8]) if out[8] >= 0 else None,
        )

    def pwm_output(self, logical_angles, *, oscillator_hz=25000000, frequency_hz=50):
        """Production timer quantization, separate from logical command targets.

        Defaults are board.c's nominal settings, not an oscillator measurement.
        Phase describes per-channel PWM onset in the configured timer period;
        it does not measure network latency or I2C-write-to-latch timing.
        """
        if (
            not isinstance(oscillator_hz, int)
            or not 0 < oscillator_hz <= 0xFFFFFFFF
            or not isinstance(frequency_hz, int)
            or not 0 < frequency_hz <= 65535
        ):
            raise ValueError("Expected integer PCA oscillator/frequency settings")
        out = np.zeros(63)
        valid = self.lib.simulation_pwm(
            self.state,
            finite_array(logical_angles, 12),
            oscillator_hz,
            frequency_hz,
            out,
        )
        if not valid:
            return None
        return dict(
            physical_angles=out[:12],
            logical_pulse_us=out[12:24],
            physical_pulse_us=out[24:36],
            phase_offset_s=out[36:48],
            period_s=float(out[48]),
            tick_us=float(out[49]),
            prescale=int(out[50]),
            enabled=out[51:63].astype(bool),
        )

    def balance_configure(self, *, enabled, tuning=(1.0, 1.0, 0.0, 0.0)):
        """Configure/reset the existing moving-balance owner after body reset.

        Explicit simulation settings, not an estimate of installed settings.
        Tuning is strength, damping, roll degrees, pitch degrees.
        """
        self.lib.simulation_balance_configure(
            self.state, finite_array([enabled, *tuning], 5))

    def foot_target(self, offsets_mm, reference_angles, previous, speed, dt, *, now_us=0.0):
        """Existing per-leg IK fit followed by the production calibrated ramp.

        Accepted offsets describe nominal_goal_angles relative to fitted_reference_angles;
        goal_angles includes configured moving balance using the native IMU at now_us.
        ramped_angles is the intermediate logical output, before PWM tick rounding.
        Physical model leg order is rear-left/rear-right/front-left/front-right.
        """
        offsets = np.asarray(offsets_mm)
        if offsets.shape != (4, 3):
            raise ValueError("Expected four three-dimensional foot offsets")
        if not math.isfinite(speed) or speed <= 0 or not math.isfinite(dt) or dt < 0:
            raise ValueError(
                "Native ramp speed must be positive and sample interval nonnegative"
            )
        if not math.isfinite(now_us) or now_us < 0:
            raise ValueError("Balance observation timestamp must be finite and nonnegative")
        out = np.zeros(70)
        valid = self.lib.simulation_foot_target(
            self.state,
            finite_array(offsets.reshape(-1), 12),
            finite_array(reference_angles, 12),
            finite_array(previous, 12),
            speed,
            dt,
            now_us,
            out,
        )
        if not valid:
            return None
        return dict(
            ramped_angles=out[:12],
            goal_angles=out[12:24],
            applied_offset_mm=out[24:36].reshape(4, 3),
            leg_fit=out[36:40],
            fit=float(out[40]),
            fitted_reference_angles=out[41:53],
            nominal_goal_angles=out[53:65],
            balance_usable=bool(out[65]),
            balance_reduced=bool(out[66]),
            balance_applied_fraction=float(out[67]),
            balance_correction_rad=out[68:70],
        )


class VirtualBody:
    """One real P4 body executor per process, with an external physics plant.

    The platform port supplies deterministic scheduling and a PCA register bus.
    Production code owns admission, movement, feedback arrival, jam observation,
    PWM generations and receipts. Initialization sets an explicit episode pose;
    it does not simulate boot or claim a physical Stand completion. Bus/network
    latency and RTOS preemption are not modeled.
    """

    _active = None

    def __init__(self, body_model, reference_angles, *, joint_speed_deg_s,
                 motion_rate=1., balance=True, heading_feedback=True,
                 balance_tuning=(1., 1., 0., 0.), idle_rest_seconds=0,
                 oscillator_hz=25000000, frequency_hz=50):
        if VirtualBody._active is not None:
            raise RuntimeError("The production P4 executor is a process singleton")
        if "stand_enabled" not in body_model.robot["feedback"]:
            raise ValueError("Virtual P4 requires the explicit saved stand_enabled feedback setting")
        self.body_model = body_model
        self.lib = body_model.lib
        self.closed = True
        self.reference = finite_array(reference_angles, 12)
        self.settings = finite_array([joint_speed_deg_s, motion_rate, balance,
                                     heading_feedback, *balance_tuning,
                                     idle_rest_seconds, oscillator_hz, frequency_hz], 11)
        if not self.lib.virtual_body_reset(body_model.state, self.reference, self.settings, 0):
            self.lib.virtual_body_close()
            raise ValueError("The P4 executor rejected its initial calibration/pose/settings")
        self.closed = False
        self.now_us = 0
        VirtualBody._active = self
        body_model._virtual_body = self

    def _live(self):
        if self.closed:
            raise RuntimeError("Virtual P4 executor is closed")

    def reset(self, now_us=0, connection=1):
        """Open a transport generation; preserve body/PWM state on reconnect."""
        self._live()
        if connection <= 0 or now_us < self.now_us:
            raise ValueError("Connection must be positive and virtual time monotonic")
        self.lib.virtual_body_open(connection, now_us)
        self.now_us = now_us

    def close(self):
        if not self.closed:
            self.lib.virtual_body_close()
            self.closed = True
            self.body_model._virtual_body = None
            VirtualBody._active = None

    def _packet(self, function, *args, optional=False):
        buffer = ctypes.create_string_buffer(32768)
        length = function(*args, buffer, len(buffer))
        if not length:
            if optional:
                return None
            raise RuntimeError("Production P4 serializer could not produce its packet")
        return json.loads(buffer.value)

    def _events(self):
        return self._packet(self.lib.virtual_body_events)

    def hello(self, robot_id, auth_token, now_us):
        self._live()
        return self._packet(self.lib.virtual_body_hello, robot_id.encode(),
                            auth_token.encode(), int(now_us))

    def receive(self, wire_json, connection, now_us):
        self._live()
        if now_us < self.now_us:
            raise ValueError("Virtual device time must be monotonic")
        wire = wire_json if isinstance(wire_json, str) else json.dumps(wire_json)
        packet = self._packet(self.lib.virtual_body_receive, wire.encode(),
                              int(connection), int(now_us), optional=True)
        self.now_us = now_us
        return (packet if isinstance(packet, list) else [packet] if packet is not None else []) + self._events()

    def connection_lost(self, connection):
        self._live()
        self.lib.virtual_body_connection_lost(int(connection))

    def tick(self, now_us):
        self._live()
        out = np.zeros(30)
        if not self.lib.virtual_body_tick(int(now_us), out):
            raise ValueError("Virtual device time must be monotonic")
        self.now_us = now_us
        channels = np.array([m["channel"] for m in self.body_model.mapping])
        channel_enabled = np.array([bool(int(out[24]) & (1 << c)) for c in range(12)])
        def angles(pulses):
            return np.array([m["home_cd"] / 100 +
                             (pulses[m["channel"]] - m["home_us"]) /
                             ((-1 if m["invert"] else 1) * m["us_per_degree"])
                             for m in self.body_model.mapping])
        return dict(logical_pwm_us=out[:12].copy(), physical_pwm_us=out[12:24].copy(),
                    logical_pulse_us=out[:12][channels], physical_pulse_us=out[12:24][channels],
                    logical_angles=angles(out[:12]), physical_angles=angles(out[12:24]),
                    channel_enabled=channel_enabled, joint_enabled=channel_enabled[channels],
                    enabled_mask=int(out[24]), output_generation=int(out[25]), armed=bool(out[26]),
                    execution=dict(sequence=int(out[27]), nominal_sample=int(out[28]),
                                   sampled_us=int(out[29])), messages=self._events())

    def telemetry(self, now_us):
        self._live()
        if now_us < self.now_us:
            raise ValueError("Virtual device time must be monotonic")
        packet = self._packet(self.lib.virtual_body_telemetry, int(now_us))
        self.now_us = now_us
        return packet

    def feedback(self, now_us):
        """Existing /api/servo-feedback read serialization; no output writes."""
        self._live()
        if now_us < self.now_us:
            raise ValueError("Virtual device time must be monotonic")
        value = self._packet(self.lib.virtual_body_feedback, int(now_us))
        self.now_us = now_us
        return value
