"""Automated 4th-wire and IMU-guided servo calibration for V2 12-servo bodies.

Single gateway-side owner for the 'Calibrate servos' workflow in Joint
calibration. Reuses the existing P4 calibration, servo-feedback, motion-plan,
stop/detach, and IMU status interfaces without duplicating firmware control.
"""
from __future__ import annotations

import asyncio
import copy
import http.client
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from gateway.server.service import GatewayError, GatewayService


JOINT_COUNT = 12
LEG_COUNT = 4
LEG_NAMES = ("rear_left", "rear_right", "front_left", "front_right")
JOINT_NAMES = (
    "Rear left shoulder", "Rear left carrier", "Rear left crank",
    "Rear right shoulder", "Rear right carrier", "Rear right crank",
    "Front left shoulder", "Front left carrier", "Front left crank",
    "Front right shoulder", "Front right carrier", "Front right crank",
)

# Exact closed-chain feasible V2 Study A (28-16-31-37) poses (0.00 deg 4-bar
# closure error, strictly inside [500..2800 us] across all calibrated servos).
# Shoulders sweep strictly outward-to-neutral (<= 0 deg) so no joint enters the
# tight rear chassis inward stops (RL/RR +13.5 deg from 1650 us; RL +3.6 deg at 1760 us).
STAND_LEG_DEG = (0.0, -5.46, -62.08)
FREE_SWEEP_LEG_DEG = (
    (-24.0, -19.75, -45.93),
    (-12.0, -5.46, -62.08),
    (0.0, 11.68, -99.22),
)
# Symmetric 4-leg floor sweep (used only if any joint lacks 4th-wire calibration):
# keeps all 4 feet planted above belly clearance and shoulders outward-to-neutral.
FLOOR_SWEEP_LEG_DEG = (
    (-16.0, -15.06, -50.05),
    (-8.0, -5.46, -62.08),
    (0.0, 6.43, -83.84),
)

DEFAULT_SWEEP_SPEED_CD_S = 5500
DEFAULT_PROBE_SPEED_CD_S = 4000
DEFAULT_TILT_LIMIT_DEG = 25.0
DEFAULT_MIN_MONOTONIC_ADC_DELTA = 15
DEFAULT_PROBE_US = 50
DEFAULT_MAX_CARRIER_TRIM_US = 150
DEFAULT_MAX_SHOULDER_TRIM_US = 120


class CalibrationAbortError(RuntimeError):
    """Raised when an authorized calibration guard or user stop aborts the run."""


def quat_to_roll_pitch_deg(wxyz: list[float] | tuple[float, ...]) -> tuple[float, float]:
    """Convert IMU quaternion [w, x, y, z] to (roll_deg, pitch_deg)."""
    if len(wxyz) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in wxyz):
        raise ValueError("invalid IMU quaternion")
    w, x, y, z = (float(v) for v in wxyz)
    sin_r = 2.0 * (w * x + y * z)
    cos_r = 1.0 - 2.0 * (x * x + y * y)
    roll = math.degrees(math.atan2(sin_r, cos_r))
    sin_p = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    pitch = math.degrees(math.asin(sin_p))
    return roll, pitch


def attitude_from_status(entry: dict[str, Any] | None) -> tuple[float, float] | None:
    """Extract (roll_deg, pitch_deg) from a gateway robot status entry."""
    if not isinstance(entry, dict):
        return None
    imu = (entry.get("status") or {}).get("imu") or entry.get("imu")
    if not isinstance(imu, dict) or not imu.get("available"):
        return None
    wxyz = imu.get("orientation_wxyz")
    if not isinstance(wxyz, (list, tuple)) or len(wxyz) != 4:
        return None
    try:
        return quat_to_roll_pitch_deg(wxyz)
    except ValueError:
        return None


def model_deg_to_pulse_us(joint: dict[str, Any], deg: float) -> int:
    """Authoritative pulse mapping matching joint_calibration.c."""
    home_us = float(joint["home_us"])
    home_cd = float(joint.get("home_cd", 0))
    scale = float(joint.get("us_per_degree", 11.111111))
    invert = bool(joint.get("invert", False))
    delta_deg = deg - home_cd / 100.0
    pulse = home_us + (-delta_deg if invert else delta_deg) * scale
    return int(round(pulse))


def validate_and_order_feedback_points(
    joint_id: int,
    samples: list[tuple[int, int]],
    *,
    min_raw_delta: int = DEFAULT_MIN_MONOTONIC_ADC_DELTA,
) -> list[tuple[int, int]]:
    """Order 3 (pulse_us, raw) points ascending in pulse_us and verify monotonic ADC."""
    if len(samples) != 3:
        raise CalibrationAbortError(f"{JOINT_NAMES[joint_id]}: expected 3 sweep samples, got {len(samples)}")
    ordered = sorted(((int(p), int(r)) for p, r in samples), key=lambda pair: pair[0])
    pulses = [p for p, _ in ordered]
    raws = [r for _, r in ordered]
    if not (0 < pulses[0] < pulses[1] < pulses[2] <= 65535):
        raise CalibrationAbortError(
            f"{JOINT_NAMES[joint_id]}: commanded sweep pulses {pulses} are not strictly ascending"
        )
    if any(r < 0 or r > 4095 for r in raws):
        raise CalibrationAbortError(f"{JOINT_NAMES[joint_id]}: ADC readings {raws} out of 0..4095 range")
    d0 = raws[1] - raws[0]
    d1 = raws[2] - raws[1]
    ascending = d0 >= min_raw_delta and d1 >= min_raw_delta
    descending = d0 <= -min_raw_delta and d1 <= -min_raw_delta
    if not (ascending or descending):
        raise CalibrationAbortError(
            f"{JOINT_NAMES[joint_id]}: 4th-wire ADC did not move monotonically across sweep "
            f"(pulses={pulses}, raw={raws}, min step={min_raw_delta} counts)"
        )
    return ordered


def _solve_linear_system(a: list[list[float]], b: list[float]) -> list[float]:
    """Solve small dense NxN linear system with partial pivoting (pure Python)."""
    n = len(b)
    mat = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(mat[r][col]))
        if abs(mat[pivot][col]) < 1e-12:
            return [0.0] * n
        mat[col], mat[pivot] = mat[pivot], mat[col]
        diag = mat[col][col]
        for j in range(col, n + 1):
            mat[col][j] /= diag
        for r in range(n):
            if r == col:
                continue
            factor = mat[r][col]
            if factor:
                for j in range(col, n + 1):
                    mat[r][j] -= factor * mat[col][j]
    return [mat[i][n] for i in range(n)]


def solve_balance_trims(
    baseline_roll: float,
    baseline_pitch: float,
    baseline_carrier_load_us: list[float],
    j_roll: list[float],
    j_pitch: list[float],
    j_load: list[list[float]],
    *,
    carrier_signs: list[float] | None = None,
    shoulder_baseline_err_us: list[float] | None = None,
    shoulder_slopes: list[float] | None = None,
    max_carrier_trim_us: int = DEFAULT_MAX_CARRIER_TRIM_US,
    max_shoulder_trim_us: int = DEFAULT_MAX_SHOULDER_TRIM_US,
    w_attitude: float = 10.0,
    w_load: float = 0.02,
    w_mean: float = 1.0,
    damping: float = 1e-5,
) -> dict[int, int]:
    """Compute bounded home_us trims for carriers (and shoulders if probed).

    j_roll[k] = d(roll_deg)/d(u_k) where u_k is pulse_us delta on leg k's carrier.
    j_pitch[k] = d(pitch_deg)/d(u_k).
    j_load[m][k] = d(signed_load_err_us[m])/d(u_k) for m, k in 0..3.
    carrier_signs[k] = -1.0 if leg k's carrier is inverted else +1.0, so the
    zero-mean constraint preserves mean mechanical standing height rather than
    fighting roll correction across mirrored left/right servos.
    """
    signs = list(carrier_signs) if carrier_signs is not None else [1.0, 1.0, 1.0, 1.0]
    rows: list[tuple[list[float], float, float]] = [
        (list(j_roll), -baseline_roll, w_attitude),
        (list(j_pitch), -baseline_pitch, w_attitude),
        (signs, 0.0, w_mean),
    ]
    mean_load = sum(baseline_carrier_load_us) / 4.0
    mean_j = [sum(j_load[m][k] for m in range(4)) / 4.0 for k in range(4)]
    for m in range(4):
        rel_j = [j_load[m][k] - mean_j[k] for k in range(4)]
        rel_e = baseline_carrier_load_us[m] - mean_load
        rows.append((rel_j, -rel_e, w_load))

    ata = [[0.0] * 4 for _ in range(4)]
    atb = [0.0] * 4
    for r_vec, target, weight in rows:
        for i in range(4):
            atb[i] += weight * r_vec[i] * target
            for j in range(4):
                ata[i][j] += weight * r_vec[i] * r_vec[j]
    for i in range(4):
        ata[i][i] += damping

    raw_u = _solve_linear_system(ata, atb)
    # Enforce zero mean mechanical height change after clamping.
    clamped = [max(-max_carrier_trim_us, min(max_carrier_trim_us, v)) for v in raw_u]
    mean_h = sum(signs[leg] * clamped[leg] for leg in range(LEG_COUNT)) / 4.0
    trims: dict[int, int] = {}
    for leg in range(LEG_COUNT):
        adjusted = clamped[leg] - signs[leg] * mean_h
        delta = int(round(max(-max_carrier_trim_us, min(max_carrier_trim_us, adjusted))))
        trims[leg * 3 + 1] = delta

    if shoulder_baseline_err_us is not None and shoulder_slopes is not None:
        for leg in range(LEG_COUNT):
            slope = shoulder_slopes[leg]
            err = shoulder_baseline_err_us[leg]
            # Ignore flat/noisy slopes or tiny errors within deadband.
            if abs(slope) < 0.08 or abs(err) < 12.0:
                trims[leg * 3] = 0
                continue
            step = -0.65 * (err / slope)
            delta = int(round(max(-max_shoulder_trim_us, min(max_shoulder_trim_us, step))))
            trims[leg * 3] = delta
    return trims


class RobotCalibrationTransport(Protocol):
    async def get_status_entry(self, robot_id: str) -> dict[str, Any]: ...
    async def get_body_calibration(self, robot_id: str) -> dict[str, Any]: ...
    async def set_body_calibration_joint(self, robot_id: str, fields: dict[str, Any]) -> dict[str, Any]: ...
    async def save_body_calibration(self, robot_id: str) -> dict[str, Any]: ...
    async def set_calibration_mode(self, robot_id: str, mode: str) -> int: ...
    async def move_targets(self, robot_id: str, targets_cd: list[int], speed_cd_s: int) -> None: ...
    async def detach(self, robot_id: str) -> None: ...
    async def get_servo_feedback(self, robot_id: str) -> dict[str, Any]: ...
    async def post_servo_feedback(self, robot_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class GatewayCalibrationTransport:
    """Real robot transport over GatewayService + P4 maintenance HTTP."""

    def __init__(self, gateway: GatewayService, token_provider: Callable[[str], str | None]) -> None:
        self._gateway = gateway
        self._token_provider = token_provider

    async def get_status_entry(self, robot_id: str) -> dict[str, Any]:
        snap = await self._gateway.status_snapshot()
        entry = (snap.get("robots") or {}).get(robot_id)
        if not isinstance(entry, dict) or not entry.get("connected"):
            raise GatewayError(f"Robot {robot_id} is not connected")
        return entry

    async def get_body_calibration(self, robot_id: str) -> dict[str, Any]:
        return await self._gateway.body_calibration("get", {}, robot_id=robot_id)

    async def set_body_calibration_joint(self, robot_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return await self._gateway.body_calibration("set", fields, robot_id=robot_id)

    async def save_body_calibration(self, robot_id: str) -> dict[str, Any]:
        return await self._gateway.body_calibration("save", {}, robot_id=robot_id)

    async def set_calibration_mode(self, robot_id: str, mode: str) -> int:
        conn = self._gateway._connection(robot_id)
        seq = await self._gateway.set_calibration_mode(mode, robot_id=robot_id)
        result = await conn.wait_terminal(seq, timeout=5.0)
        if result.get("t") not in ("ack", "done"):
            raise GatewayError(str(result.get("msg") or result.get("code") or f"failed to enter {mode} mode"))
        return seq

    async def move_targets(self, robot_id: str, targets_cd: list[int], speed_cd_s: int) -> None:
        conn = self._gateway._connection(robot_id)
        seq = await self._gateway.queue_motion_plan(
            [[int(speed_cd_s), [int(v) for v in targets_cd]]],
            end="hold",
            control="targets",
            robot_id=robot_id,
        )
        result = await conn.wait_terminal(seq, timeout=12.0)
        if result.get("t") not in ("done", "ack"):
            raise GatewayError(str(result.get("msg") or result.get("code") or "motion plan did not complete"))

    async def detach(self, robot_id: str) -> None:
        await self._gateway.estop(robot_id=robot_id, detach=True)

    async def _http_servo_feedback(self, robot_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        address = await self._gateway.maintenance_address(robot_id)
        token = self._token_provider(robot_id)
        if not token:
            raise GatewayError("Robot pairing token is unavailable")

        def _do_request() -> dict[str, Any]:
            headers = {"Authorization": f"Bearer {token}", "Connection": "close"}
            conn = http.client.HTTPConnection(address, 80, timeout=10)
            try:
                if payload is None:
                    conn.request("GET", "/api/servo-feedback", headers=headers)
                else:
                    headers["Content-Type"] = "application/json"
                    body = json.dumps(payload, allow_nan=False)
                    conn.request("POST", "/api/servo-feedback", body=body, headers=headers)
                resp = conn.getresponse()
                raw = resp.read(65536).decode("utf-8", errors="replace")
                data = json.loads(raw) if raw else {}
                if resp.status >= 400:
                    raise GatewayError(str(data.get("error") or f"servo-feedback returned HTTP {resp.status}"))
                return data
            finally:
                conn.close()

        return await asyncio.to_thread(_do_request)

    async def get_servo_feedback(self, robot_id: str) -> dict[str, Any]:
        return await self._http_servo_feedback(robot_id, None)

    async def post_servo_feedback(self, robot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._http_servo_feedback(robot_id, payload)


@dataclass
class _CalibrationRun:
    robot_id: str
    mode: str
    state: str = "running"  # running | ready_to_apply | completed | aborted | failed
    phase: str = "init"
    progress: float = 0.0
    message: str = "Starting calibration…"
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    joints: list[dict[str, Any]] = field(default_factory=list)
    backup_calibration: list[dict[str, Any]] = field(default_factory=list)
    backup_feedback: dict[str, Any] | None = None
    staged_trims: dict[int, int] = field(default_factory=dict)
    feedback_written: bool = False
    home_staged: bool = False
    cancel_requested: bool = False
    task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "robot_id": self.robot_id,
            "mode": self.mode,
            "state": self.state,
            "phase": self.phase,
            "progress": round(self.progress, 3),
            "message": self.message,
            "error": self.error,
            "before": copy.deepcopy(self.before),
            "after": copy.deepcopy(self.after),
            "joints": copy.deepcopy(self.joints),
            "can_apply": self.state == "ready_to_apply" and self.home_staged,
            "can_restore": (
                self.state in ("ready_to_apply", "completed")
                and (self.home_staged or self.feedback_written)
            ),
            "updated_at": self.updated_at,
        }


class AutoCalibrationManager:
    """Owns automated 4th-wire + IMU-guided calibration sessions per robot."""

    def __init__(
        self,
        transport: RobotCalibrationTransport,
        *,
        settle_delay_s: float = 0.35,
        settle_polls: int = 12,
        settle_poll_interval_s: float = 0.06,
        tilt_limit_deg: float = DEFAULT_TILT_LIMIT_DEG,
        min_monotonic_adc_delta: int = DEFAULT_MIN_MONOTONIC_ADC_DELTA,
        probe_us: int = DEFAULT_PROBE_US,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._transport = transport
        self._settle_delay_s = settle_delay_s
        self._settle_polls = settle_polls
        self._settle_poll_interval_s = settle_poll_interval_s
        self._tilt_limit_deg = tilt_limit_deg
        self._min_monotonic_adc_delta = min_monotonic_adc_delta
        self._probe_us = probe_us
        self._on_event = on_event
        self._runs: dict[str, _CalibrationRun] = {}

    def _emit_event(self, event: str, run: _CalibrationRun) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(
                event,
                {
                    "robot_id": run.robot_id,
                    "mode": run.mode,
                    "state": run.state,
                    "phase": run.phase,
                    "message": run.message,
                    "error": run.error,
                    "before": run.before,
                    "after": run.after,
                },
            )
        except Exception:
            pass

    def status(self, robot_id: str) -> dict[str, Any]:
        run = self._runs.get(robot_id)
        if run is None:
            return {
                "robot_id": robot_id,
                "mode": None,
                "state": "idle",
                "phase": "idle",
                "progress": 0.0,
                "message": "Ready to calibrate.",
                "error": None,
                "before": None,
                "after": None,
                "joints": [],
                "can_apply": False,
                "can_restore": False,
                "updated_at": time.time(),
            }
        return run.snapshot()

    async def start(self, robot_id: str, *, mode: str = "floor") -> dict[str, Any]:
        if mode not in ("floor", "legs_free"):
            raise ValueError("mode must be 'floor' or 'legs_free'")
        existing = self._runs.get(robot_id)
        if existing is not None and existing.state == "running":
            raise GatewayError("Calibration is already running for this robot")
        run = _CalibrationRun(robot_id=robot_id, mode=mode)
        self._runs[robot_id] = run
        run.task = asyncio.create_task(self._execute(run), name=f"auto-cal-{robot_id}")
        return run.snapshot()

    async def stop(self, robot_id: str) -> dict[str, Any]:
        run = self._runs.get(robot_id)
        if run is None:
            await self._transport.detach(robot_id)
            return self.status(robot_id)
        run.cancel_requested = True
        if run.task is not None and not run.task.done():
            await asyncio.gather(run.task, return_exceptions=True)
        return run.snapshot()

    async def apply(self, robot_id: str) -> dict[str, Any]:
        run = self._runs.get(robot_id)
        if run is None or run.state != "ready_to_apply" or not run.home_staged:
            raise GatewayError("No staged calibration is ready to apply")
        await self._transport.detach(robot_id)
        await self._transport.set_calibration_mode(robot_id, "calibrate")
        try:
            saved = await self._transport.save_body_calibration(robot_id)
        finally:
            try:
                await self._transport.set_calibration_mode(robot_id, "normal")
            except Exception:
                pass
        if not saved.get("saved") or saved.get("dirty"):
            raise GatewayError("Robot did not confirm saving calibration to NVS")
        run.home_staged = False
        run.state = "completed"
        run.phase = "saved"
        run.progress = 1.0
        run.message = "Calibration saved on robot (4th-wire curves and Home trims persisted)."
        run.updated_at = time.time()
        self._emit_event("auto_calibration_saved", run)
        return run.snapshot()

    async def restore(self, robot_id: str) -> dict[str, Any]:
        run = self._runs.get(robot_id)
        if run is None or run.state == "running":
            raise GatewayError("Cannot restore while calibration is running or idle")
        await self._restore_backups(run)
        run.state = "aborted"
        run.phase = "restored"
        run.message = "Previous 4th-wire curves and Home settings restored."
        run.updated_at = time.time()
        return run.snapshot()

    def _update(self, run: _CalibrationRun, *, phase: str, progress: float, message: str) -> None:
        run.phase = phase
        run.progress = max(0.0, min(1.0, progress))
        run.message = message
        run.updated_at = time.time()

    def _check_cancel(self, run: _CalibrationRun) -> None:
        if run.cancel_requested:
            raise CalibrationAbortError("Calibration cancelled by operator")

    async def _check_tilt(self, run: _CalibrationRun) -> tuple[float, float] | None:
        entry = await self._transport.get_status_entry(run.robot_id)
        att = attitude_from_status(entry)
        if run.mode == "floor" and att is not None:
            roll, pitch = att
            if abs(roll) > self._tilt_limit_deg or abs(pitch) > self._tilt_limit_deg:
                raise CalibrationAbortError(
                    f"Body tilt exceeded {self._tilt_limit_deg:.0f}° limit "
                    f"(roll {roll:+.1f}°, pitch {pitch:+.1f}°); outputs released"
                )
        return att

    async def _move_and_settle(
        self,
        run: _CalibrationRun,
        targets_deg: list[float],
        *,
        speed_cd_s: int,
        watch_joints: list[int] | None = None,
    ) -> tuple[dict[str, Any], tuple[float, float] | None]:
        self._check_cancel(run)
        targets_cd = [int(round(v * 100.0)) for v in targets_deg]
        await self._transport.move_targets(run.robot_id, targets_cd, speed_cd_s)
        if self._settle_delay_s > 0:
            await asyncio.sleep(self._settle_delay_s)
        prev_raw: dict[int, int] = {}
        last_fb: dict[str, Any] = {}
        last_att: tuple[float, float] | None = None
        watched = watch_joints if watch_joints is not None else list(range(JOINT_COUNT))
        for _ in range(max(1, self._settle_polls)):
            self._check_cancel(run)
            last_att = await self._check_tilt(run)
            last_fb = await self._transport.get_servo_feedback(run.robot_id)
            ch_map = {int(c["channel"]): c for c in (last_fb.get("channels") or []) if isinstance(c, dict)}
            joints = {int(j["id"]): j for j in (last_fb.get("joints") or []) if isinstance(j, dict)}
            cur_raw: dict[int, int] = {}
            valid = True
            for jid in watched:
                j = joints.get(jid)
                ch = ch_map.get(int(j["channel"])) if j else None
                if not ch or not ch.get("valid"):
                    valid = False
                    break
                cur_raw[jid] = int(ch["raw"])
            if valid and prev_raw and all(abs(cur_raw[jid] - prev_raw[jid]) <= 6 for jid in watched):
                return last_fb, last_att
            if valid:
                prev_raw = cur_raw
            if self._settle_poll_interval_s > 0:
                await asyncio.sleep(self._settle_poll_interval_s)
        return last_fb, last_att

    async def _write_feedback_curves(
        self,
        run: _CalibrationRun,
        ordered_curves: dict[int, list[tuple[int, int]]],
    ) -> dict[str, Any]:
        """Write validated 3-point curves safely without triggering P4 NVS validation errors."""
        fb = await self._transport.get_servo_feedback(run.robot_id)
        had_stand = bool(fb.get("stand_enabled", False))
        had_jam = bool(fb.get("jam_enabled", False))
        base_cfg = {
            "op": "configure",
            "enabled": True,
            "stand_enabled": False,
            "jam_enabled": False,
            "tolerance_us": int(fb.get("tolerance_us", 30)),
            "arrival_tolerance_us": int(fb.get("arrival_tolerance_us", fb.get("tolerance_us", 30))),
            "no_progress_ms": int(fb.get("no_progress_ms", 1000)),
            "progress_us": int(fb.get("progress_us", 5)),
        }
        if not fb.get("enabled") or had_stand or had_jam:
            fb = await self._transport.post_servo_feedback(run.robot_id, base_cfg)
        run.feedback_written = True
        try:
            for jid, pts in sorted(ordered_curves.items()):
                fb = await self._transport.post_servo_feedback(run.robot_id, {"op": "clear", "joint": jid})
                scan = max(1, int(fb.get("scan", 1)))
                for p_idx, (pulse_us, raw) in enumerate(pts):
                    fb = await self._transport.post_servo_feedback(
                        run.robot_id,
                        {
                            "op": "capture",
                            "joint": jid,
                            "point": p_idx,
                            "pulse_us": int(pulse_us),
                            "raw": int(raw),
                            "scan": scan,
                            "revision": int(fb.get("revision", 0)),
                        },
                    )
                    scan = max(1, int(fb.get("scan", scan)))
        finally:
            if had_stand or had_jam:
                try:
                    fb = await self._transport.post_servo_feedback(
                        run.robot_id,
                        {**base_cfg, "stand_enabled": had_stand, "jam_enabled": had_jam},
                    )
                except Exception:
                    pass
        return fb

    async def _restore_backups(self, run: _CalibrationRun) -> None:
        """Best-effort restore of pre-run Home settings and 4th-wire curves."""
        try:
            await self._transport.detach(run.robot_id)
        except Exception:
            pass
        if run.home_staged and run.backup_calibration:
            try:
                await self._transport.set_calibration_mode(run.robot_id, "calibrate")
            except Exception:
                pass
            for j in run.backup_calibration:
                fields = {
                    "id": int(j["id"]),
                    "channel": int(j["channel"]),
                    "home_us": int(j["home_us"]),
                    "invert": bool(j["invert"]),
                    "home_cd": int(j["home_cd"]),
                    "us_per_degree": float(j["us_per_degree"]),
                }
                try:
                    await self._transport.set_body_calibration_joint(run.robot_id, fields)
                except Exception:
                    pass
            try:
                await self._transport.set_calibration_mode(run.robot_id, "normal")
            except Exception:
                pass
            run.home_staged = False
        if run.feedback_written and run.backup_feedback:
            old_curves: dict[int, list[tuple[int, int]]] = {}
            for j in run.backup_feedback.get("joints") or []:
                pts = j.get("points") or []
                if len(pts) == 3 and all(isinstance(p, dict) for p in pts):
                    old_curves[int(j["id"])] = [(int(p["pulse_us"]), int(p["raw"])) for p in pts]
            if old_curves:
                try:
                    await self._write_feedback_curves(run, old_curves)
                except Exception:
                    pass
            run.feedback_written = False

    def _build_joint_report(
        self,
        cal_joints: list[dict[str, Any]],
        ordered_curves: dict[int, list[tuple[int, int]]],
        trims: dict[int, int],
        before_fb: dict[str, Any] | None,
        after_fb: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        before_map = {int(j["id"]): j for j in ((before_fb or {}).get("joints") or []) if isinstance(j, dict)}
        after_map = {int(j["id"]): j for j in ((after_fb or {}).get("joints") or []) if isinstance(j, dict)}
        rows: list[dict[str, Any]] = []
        for j in cal_joints:
            jid = int(j["id"])
            old_home = int(j["home_us"])
            delta = int(trims.get(jid, 0))
            b = before_map.get(jid, {})
            a = after_map.get(jid, {})
            pts = ordered_curves.get(jid) or []
            rows.append({
                "id": jid,
                "name": JOINT_NAMES[jid],
                "home_us_before": old_home,
                "home_us_after": old_home + delta,
                "home_delta_us": delta,
                "points": [{"pulse_us": p, "raw": r} for p, r in pts],
                "error_us_before": b.get("error_us"),
                "error_us_after": a.get("error_us"),
                "model_deg_after": a.get("model_deg"),
                "in_calibrated_range": a.get("in_calibrated_range"),
                "calibrated": a.get("calibrated"),
            })
        return rows

    async def _execute(self, run: _CalibrationRun) -> None:
        paused_jam_cfg: dict[str, Any] | None = None
        try:
            self._update(run, phase="prepare", progress=0.02, message="Reading current robot calibration and feedback…")
            entry = await self._transport.get_status_entry(run.robot_id)
            if entry.get("mode") == "calibrate":
                await self._transport.set_calibration_mode(run.robot_id, "normal")

            cal = await self._transport.get_body_calibration(run.robot_id)
            cal_joints = sorted(cal.get("joints") or [], key=lambda j: int(j["id"]))
            if len(cal_joints) != JOINT_COUNT:
                raise GatewayError("Body calibration did not report all 12 joints")
            run.backup_calibration = copy.deepcopy(cal_joints)

            fb0 = await self._transport.get_servo_feedback(run.robot_id)
            run.backup_feedback = copy.deepcopy(fb0)
            had_jam = bool(fb0.get("jam_enabled", False))
            had_stand = bool(fb0.get("stand_enabled", False))
            base_fb_cfg = {
                "op": "configure",
                "enabled": True,
                "stand_enabled": had_stand,
                "jam_enabled": had_jam,
                "tolerance_us": int(fb0.get("tolerance_us", 30)),
                "arrival_tolerance_us": int(fb0.get("arrival_tolerance_us", fb0.get("tolerance_us", 30))),
                "no_progress_ms": int(fb0.get("no_progress_ms", 1000)),
                "progress_us": int(fb0.get("progress_us", 5)),
            }
            # Owner-authorized: temporarily pause P4 jam_enabled (and stand_enabled so
            # P4 feedback config validation succeeds even if a joint is uncalibrated)
            # during calibration moves; unconditionally restored in finally:.
            if not fb0.get("enabled") or had_jam or had_stand:
                fb0 = await self._transport.post_servo_feedback(
                    run.robot_id,
                    {**base_fb_cfg, "stand_enabled": False, "jam_enabled": False},
                )
                if had_jam or had_stand:
                    paused_jam_cfg = base_fb_cfg

            # -------- Phase 1: 4th-wire range sweep --------
            existing_cal = {int(j["id"]): bool(j.get("calibrated")) for j in (fb0.get("joints") or []) if isinstance(j, dict)}
            uncalibrated_jids = [jid for jid in range(JOINT_COUNT) if not existing_cal.get(jid, False)]
            ordered_curves: dict[int, list[tuple[int, int]]] = {}
            for j in (fb0.get("joints") or []):
                if isinstance(j, dict):
                    pts = j.get("points") or []
                    if len(pts) == 3 and all(isinstance(p, dict) for p in pts):
                        ordered_curves[int(j["id"])] = [(int(p["pulse_us"]), int(p["raw"])) for p in pts]

            need_sweep = run.mode == "legs_free" or bool(uncalibrated_jids)
            if need_sweep:
                collected: dict[int, list[tuple[int, int]]] = {jid: [] for jid in range(JOINT_COUNT)}
                sweep_poses = FREE_SWEEP_LEG_DEG if run.mode == "legs_free" else FLOOR_SWEEP_LEG_DEG
                mode_label = "legs free" if run.mode == "legs_free" else "4-leg floor"
                for p_idx, leg_pose in enumerate(sweep_poses):
                    frac = (0.08 + 0.22 * p_idx) if run.mode == "legs_free" else (0.08 + 0.12 * p_idx)
                    self._update(
                        run,
                        phase="feedback_sweep",
                        progress=frac,
                        message=f"Phase 1 ({mode_label}): sweeping all 12 joints symmetrically to point {p_idx + 1}/3…",
                    )
                    targets = list(leg_pose) * LEG_COUNT
                    fb, _ = await self._move_and_settle(run, targets, speed_cd_s=DEFAULT_SWEEP_SPEED_CD_S)
                    ch_map = {int(c["channel"]): c for c in (fb.get("channels") or [])}
                    j_map = {int(j["id"]): j for j in (fb.get("joints") or [])}
                    for jid in range(JOINT_COUNT):
                        j = j_map[jid]
                        ch = ch_map.get(int(j["channel"]))
                        if not ch or not ch.get("valid"):
                            raise CalibrationAbortError(f"{JOINT_NAMES[jid]}: no valid 4th-wire ADC sample")
                        cmd_us = int(j.get("command_us") or model_deg_to_pulse_us(cal_joints[jid], targets[jid]))
                        collected[jid].append((cmd_us, int(ch["raw"])))

                target_jids = list(range(JOINT_COUNT)) if run.mode == "legs_free" else uncalibrated_jids
                curves_to_write: dict[int, list[tuple[int, int]]] = {}
                for jid in target_jids:
                    pts = validate_and_order_feedback_points(
                        jid, collected[jid], min_raw_delta=self._min_monotonic_adc_delta
                    )
                    ordered_curves[jid] = pts
                    curves_to_write[jid] = pts

                self._update(
                    run,
                    phase="feedback_write",
                    progress=0.48,
                    message=f"Saving validated 3-point 4th-wire curves for {len(curves_to_write)} joint(s)…",
                )
                await self._write_feedback_curves(run, curves_to_write)
            else:
                self._update(
                    run,
                    phase="feedback_verified",
                    progress=0.45,
                    message="All 12 4th-wire curves already calibrated; proceeding directly to floor balance.",
                )

            if run.mode == "legs_free":
                # Verify calibrated readback at neutral mid pose, then detach.
                self._update(run, phase="verify", progress=0.85, message="Verifying 4th-wire range readback at mid pose…")
                verify_fb, verify_att = await self._move_and_settle(
                    run, list(STAND_LEG_DEG) * LEG_COUNT, speed_cd_s=DEFAULT_SWEEP_SPEED_CD_S
                )
                await self._transport.detach(run.robot_id)
                run.before = {"mode": "legs_free"}
                run.after = {
                    "mode": "legs_free",
                    "calibrated_joints": sum(1 for j in (verify_fb.get("joints") or []) if j.get("calibrated")),
                    "in_range_joints": sum(1 for j in (verify_fb.get("joints") or []) if j.get("in_calibrated_range")),
                    "roll_deg": verify_att[0] if verify_att else None,
                    "pitch_deg": verify_att[1] if verify_att else None,
                }
                run.joints = self._build_joint_report(cal_joints, ordered_curves, {}, fb0, verify_fb)
                run.state = "completed"
                run.phase = "completed"
                run.progress = 1.0
                run.message = "Legs-free 4th-wire calibration complete for all 12 joints. Outputs released."
                run.updated_at = time.time()
                self._emit_event("auto_calibration_finished", run)
                return

            # -------- Phase 2: Low-friction Stand & 4-leg balance/leveling --------
            stand_all = list(STAND_LEG_DEG) * LEG_COUNT
            self._update(run, phase="balance_baseline", progress=0.54, message="Phase 2: measuring baseline Stand tilt and 4-leg load…")
            before_fb, before_att = await self._move_and_settle(run, stand_all, speed_cd_s=DEFAULT_PROBE_SPEED_CD_S)
            if before_att is None:
                raise CalibrationAbortError("IMU attitude is unavailable; cannot run floor balance calibration")
            base_roll, base_pitch = before_att

            def _carrier_loads(fb_data: dict[str, Any]) -> list[float]:
                j_map = {int(j["id"]): j for j in (fb_data.get("joints") or [])}
                loads = []
                for leg in range(LEG_COUNT):
                    jid = leg * 3 + 1
                    err = float(j_map[jid].get("error_us", 0.0) or 0.0)
                    # Convert pulse error to mechanical angle-aligned sign so
                    # left (invert=True) and right (invert=False) carriers compare cleanly.
                    sign = -1.0 if cal_joints[jid].get("invert") else 1.0
                    loads.append(err * sign)
                return loads

            def _shoulder_errors(fb_data: dict[str, Any]) -> list[float]:
                j_map = {int(j["id"]): j for j in (fb_data.get("joints") or [])}
                return [float(j_map[leg * 3].get("error_us", 0.0) or 0.0) for leg in range(LEG_COUNT)]

            base_loads = _carrier_loads(before_fb)
            base_sh_err = _shoulder_errors(before_fb)
            run.before = {
                "roll_deg": round(base_roll, 3),
                "pitch_deg": round(base_pitch, 3),
                "carrier_load_us": [round(v, 1) for v in base_loads],
                "shoulder_error_us": [round(v, 1) for v in base_sh_err],
            }

            # Probe carrier height Jacobian for all 4 legs (small +/- probe_us).
            j_roll = [0.0] * LEG_COUNT
            j_pitch = [0.0] * LEG_COUNT
            j_load = [[0.0] * LEG_COUNT for _ in range(LEG_COUNT)]
            for leg in range(LEG_COUNT):
                jid = leg * 3 + 1
                scale = float(cal_joints[jid].get("us_per_degree", 11.111111))
                inv_sign = -1.0 if cal_joints[jid].get("invert") else 1.0
                # +probe_us in pulse corresponds to inv_sign * (probe_us / scale) deg.
                d_deg = inv_sign * (self._probe_us / scale)
                self._update(
                    run,
                    phase="balance_probe",
                    progress=0.58 + 0.05 * leg,
                    message=f"Phase 2: probing {LEG_NAMES[leg]} carrier balance response…",
                )
                plus_targets = list(stand_all)
                plus_targets[jid] += d_deg
                fb_p, att_p = await self._move_and_settle(run, plus_targets, speed_cd_s=DEFAULT_PROBE_SPEED_CD_S)
                minus_targets = list(stand_all)
                minus_targets[jid] -= d_deg
                fb_m, att_m = await self._move_and_settle(run, minus_targets, speed_cd_s=DEFAULT_PROBE_SPEED_CD_S)
                if att_p is None or att_m is None:
                    raise CalibrationAbortError("IMU reading lost during balance probe")
                denom = 2.0 * float(self._probe_us)
                j_roll[leg] = (att_p[0] - att_m[0]) / denom
                j_pitch[leg] = (att_p[1] - att_m[1]) / denom
                loads_p = _carrier_loads(fb_p)
                loads_m = _carrier_loads(fb_m)
                for m in range(LEG_COUNT):
                    j_load[m][leg] = (loads_p[m] - loads_m[m]) / denom

            # Probe shoulder deflection slope strictly outward (sh < 0) from Stand (0 deg)
            # so calibration never drives any shoulder into its inward chassis stop.
            sh_slopes = [0.0] * LEG_COUNT
            for leg in range(LEG_COUNT):
                jid = leg * 3
                scale = float(cal_joints[jid].get("us_per_degree", 11.111111))
                inv_sign = -1.0 if cal_joints[jid].get("invert") else 1.0
                # Outward step in degrees is always negative (-probe_us / scale);
                # corresponding signed pulse delta is -inv_sign * probe_us.
                d_deg_out = -(self._probe_us / scale)
                delta_pulse_out = -inv_sign * float(self._probe_us)
                self._update(
                    run,
                    phase="shoulder_probe",
                    progress=0.78 + 0.03 * leg,
                    message=f"Phase 2: probing {LEG_NAMES[leg]} shoulder alignment (outward)…",
                )
                out_targets = list(stand_all)
                out_targets[jid] += d_deg_out
                fb_out, _ = await self._move_and_settle(
                    run, out_targets, speed_cd_s=DEFAULT_PROBE_SPEED_CD_S, watch_joints=[jid]
                )
                e_out = _shoulder_errors(fb_out)[leg]
                sh_slopes[leg] = (e_out - base_sh_err[leg]) / delta_pulse_out

            carrier_signs = [-1.0 if cal_joints[leg * 3 + 1].get("invert") else 1.0 for leg in range(LEG_COUNT)]
            trims = solve_balance_trims(
                base_roll,
                base_pitch,
                base_loads,
                j_roll,
                j_pitch,
                j_load,
                carrier_signs=carrier_signs,
                shoulder_baseline_err_us=base_sh_err,
                shoulder_slopes=sh_slopes,
            )
            run.staged_trims = trims

            # Stage candidate Home trims in RAM (requires calibrate mode; does not save to NVS yet).
            self._update(run, phase="stage_trims", progress=0.90, message="Staging candidate Home trims on robot (not saved yet)…")
            changed_joints = [j for j in cal_joints if trims.get(int(j["id"]), 0)]
            if changed_joints:
                await self._transport.detach(run.robot_id)
                await self._transport.set_calibration_mode(run.robot_id, "calibrate")
                try:
                    for j in changed_joints:
                        jid = int(j["id"])
                        delta = trims.get(jid, 0)
                        await self._transport.set_body_calibration_joint(
                            run.robot_id,
                            {
                                "id": jid,
                                "channel": int(j["channel"]),
                                "home_us": int(j["home_us"]) + delta,
                                "invert": bool(j["invert"]),
                                "home_cd": int(j["home_cd"]),
                                "us_per_degree": float(j["us_per_degree"]),
                            },
                        )
                        run.home_staged = True
                finally:
                    await self._transport.set_calibration_mode(run.robot_id, "normal")

            # -------- Phase 3: Verification Stand --------
            self._update(run, phase="verify", progress=0.95, message="Phase 3: standing with candidate trims to verify balance…")
            after_fb, after_att = await self._move_and_settle(run, stand_all, speed_cd_s=DEFAULT_PROBE_SPEED_CD_S)
            await self._transport.detach(run.robot_id)

            after_loads = _carrier_loads(after_fb)
            after_sh_err = _shoulder_errors(after_fb)
            run.after = {
                "roll_deg": round(after_att[0], 3) if after_att else None,
                "pitch_deg": round(after_att[1], 3) if after_att else None,
                "carrier_load_us": [round(v, 1) for v in after_loads],
                "shoulder_error_us": [round(v, 1) for v in after_sh_err],
                "calibrated_joints": sum(1 for j in (after_fb.get("joints") or []) if j.get("calibrated")),
                "in_range_joints": sum(1 for j in (after_fb.get("joints") or []) if j.get("in_calibrated_range")),
            }
            run.joints = self._build_joint_report(cal_joints, ordered_curves, trims, before_fb, after_fb)
            if run.home_staged:
                run.state = "ready_to_apply"
                run.phase = "ready_to_apply"
                run.progress = 1.0
                run.message = (
                    f"Calibration verified: roll {base_roll:+.2f}° → {after_att[0]:+.2f}°, "
                    f"pitch {base_pitch:+.2f}° → {after_att[1]:+.2f}°. Review and click Apply & save to robot."
                    if after_att
                    else "Calibration verified. Review and click Apply & save to robot."
                )
            else:
                run.state = "completed"
                run.phase = "completed"
                run.progress = 1.0
                run.message = "4th-wire curves saved; legs were already balanced (no Home trims needed)."
            run.updated_at = time.time()
            self._emit_event("auto_calibration_finished", run)

        except CalibrationAbortError as exc:
            run.error = str(exc)
            run.state = "aborted"
            run.phase = "aborted"
            run.message = f"Aborted: {exc}"
            await self._restore_backups(run)
            run.updated_at = time.time()
            self._emit_event("auto_calibration_aborted", run)
        except Exception as exc:
            run.error = str(exc)
            run.state = "failed"
            run.phase = "failed"
            run.message = f"Calibration failed: {exc}"
            await self._restore_backups(run)
            run.updated_at = time.time()
            self._emit_event("auto_calibration_failed", run)
        finally:
            if paused_jam_cfg is not None:
                try:
                    await self._transport.post_servo_feedback(run.robot_id, paused_jam_cfg)
                except Exception:
                    pass
