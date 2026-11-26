"""Tests for automated 4th-wire and IMU-guided servo calibration."""
from __future__ import annotations

import asyncio
import copy
import math
import unittest

from gateway.auto_calibration import (
    AutoCalibrationManager,
    CalibrationAbortError,
    JOINT_COUNT,
    STAND_LEG_DEG,
    model_deg_to_pulse_us,
    quat_to_roll_pitch_deg,
    solve_balance_trims,
    validate_and_order_feedback_points,
)


def _rp_to_quat(roll_deg: float, pitch_deg: float) -> list[float]:
    r = math.radians(roll_deg) * 0.5
    p = math.radians(pitch_deg) * 0.5
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    return [cr * cp, sr * cp, cr * sp, -sr * sp]


class SimulatedP4RobotTransport:
    """Faithful P4 firmware + low-friction floor physics double for auto-calibration."""

    def __init__(
        self,
        *,
        true_home_offsets_us: dict[int, int] | None = None,
        stuck_adc_joint: int | None = None,
        force_tilt_deg: tuple[float, float] | None = None,
        stand_enabled: bool = True,
        jam_enabled: bool = True,
        slow_move_delay_s: float = 0.0,
    ) -> None:
        self.true_home_offsets_us = dict(true_home_offsets_us or {})
        self.stuck_adc_joint = stuck_adc_joint
        self.force_tilt_deg = force_tilt_deg
        self.slow_move_delay_s = slow_move_delay_s
        self.mode = "normal"
        self.armed = False
        self.detached_count = 0
        self.saved_count = 0
        self.dirty = False
        self.saved = True
        self.scan = 100
        self.revision = 3
        self.fb_enabled = True
        self.stand_enabled = stand_enabled
        self.jam_enabled = jam_enabled
        self.tolerance_us = 30
        self.arrival_tolerance_us = 30
        self.no_progress_ms = 1000
        self.progress_us = 5
        # True physical home pulses for each joint; current configured home_us starts offset.
        self.inverts = [False, True, True, True, False, False, True, True, True, False, False, False]
        self.true_home_us = [1650, 2450, 2580, 1650, 850, 720, 1650, 2450, 2580, 1650, 850, 720]
        self.home_cds = [0, -3087, -11768] * 4
        self.joints = []
        for jid in range(JOINT_COUNT):
            offset = self.true_home_offsets_us.get(jid, 0)
            self.joints.append({
                "id": jid,
                "channel": jid,
                "home_us": self.true_home_us[jid] + offset,
                "invert": self.inverts[jid],
                "home_cd": self.home_cds[jid],
                "us_per_degree": 11.111111,
                "pulse_us": 0,
            })
        self.current_targets_deg = list(STAND_LEG_DEG) * 4
        self.current_pulses = [model_deg_to_pulse_us(j, self.current_targets_deg[i]) for i, j in enumerate(self.joints)]
        # Initial pre-existing 4th-wire curves (valid previously-saved 3-point curves).
        self.fb_points: dict[int, list[dict[str, int] | None]] = {}
        for jid in range(JOINT_COUNT):
            self.fb_points[jid] = [
                {"pulse_us": 600, "raw": self._pulse_to_raw(jid, 600, ignore_stuck=True)},
                {"pulse_us": 1500, "raw": self._pulse_to_raw(jid, 1500, ignore_stuck=True)},
                {"pulse_us": 2600, "raw": self._pulse_to_raw(jid, 2600, ignore_stuck=True)},
            ]

    def _pulse_to_raw(self, jid: int, pulse_us: float, *, ignore_stuck: bool = False) -> int:
        if self.stuck_adc_joint == jid and not ignore_stuck:
            return 2000
        # Alternating potentiometer directions across joints to test both ascending & descending curves.
        if jid % 2 == 0:
            raw = 400.0 + (pulse_us - 400.0) * 1.15
        else:
            raw = 3700.0 - (pulse_us - 400.0) * 1.15
        return max(10, min(4085, int(round(raw))))

    def _is_standing_pose(self) -> bool:
        return all(
            abs(self.current_targets_deg[leg * 3 + 1] - STAND_LEG_DEG[1]) < 6.0
            and abs(self.current_targets_deg[leg * 3 + 2] - STAND_LEG_DEG[2]) < 6.0
            for leg in range(4)
        )

    def _leg_height_errors_us(self) -> list[float]:
        """Signed mechanical carrier extension error (us) relative to true level stand."""
        errs = []
        for leg in range(4):
            jid = leg * 3 + 1
            j = self.joints[jid]
            true_stand_p = model_deg_to_pulse_us({**j, "home_us": self.true_home_us[jid]}, STAND_LEG_DEG[1])
            cmd_p = self.current_pulses[jid]
            sign = -1.0 if j["invert"] else 1.0
            errs.append((cmd_p - true_stand_p) * sign)
        return errs

    def _roll_pitch(self) -> tuple[float, float]:
        if self.force_tilt_deg is not None:
            return self.force_tilt_deg
        h = self._leg_height_errors_us()  # [RL, RR, FL, FR] positive = leg pushed down / taller
        # Left taller -> positive roll (tilts right); Front taller -> positive pitch (nose up).
        roll = 0.045 * ((h[0] + h[2]) - (h[1] + h[3]))
        pitch = 0.040 * ((h[2] + h[3]) - (h[0] + h[1]))
        return roll, pitch

    def _actual_pulse_under_load(self, jid: int) -> float:
        cmd_p = float(self.current_pulses[jid])
        if not self._is_standing_pose():
            return cmd_p
        leg = jid // 3
        part = jid % 3
        if part == 1:
            # Carrier load sag proportional to diagonal/height excess relative to mean leg height.
            h = self._leg_height_errors_us()
            mean_h = sum(h) / 4.0
            # Diagonal twist creates asymmetric weight share; taller legs bear more load -> deflect back.
            sag_mech = 22.0 + 0.45 * (h[leg] - mean_h)
            sign = -1.0 if self.joints[jid]["invert"] else 1.0
            return cmd_p - sag_mech * sign
        if part == 0:
            # Shoulder deflection on low-friction floor proportional to true misalignment from 0 deg.
            true_zero_p = self.true_home_us[jid]
            misalign = cmd_p - true_zero_p
            # Gravity/floor torque pulls misaligned shoulder away from zero (slope = -0.35).
            return cmd_p + 0.35 * misalign
        return cmd_p

    def _fb_calibrated(self, jid: int) -> bool:
        pts = self.fb_points[jid]
        if any(p is None for p in pts):
            return False
        p0, p1, p2 = pts[0], pts[1], pts[2]
        assert p0 and p1 and p2
        if not (0 < p0["pulse_us"] < p1["pulse_us"] < p2["pulse_us"]):
            return False
        asc = p2["raw"] > p0["raw"]
        if asc:
            return p0["raw"] < p1["raw"] < p2["raw"]
        return p0["raw"] > p1["raw"] > p2["raw"]

    def _validate_fb_config(self) -> None:
        if (self.stand_enabled or self.jam_enabled) and not self.fb_enabled:
            raise RuntimeError("ESP_ERR_INVALID_ARG: enabled required")
        for jid in range(JOINT_COUNT):
            pts = self.fb_points[jid]
            if all(p is not None for p in pts) and not self._fb_calibrated(jid):
                raise RuntimeError(f"ESP_ERR_INVALID_ARG: joint {jid} curve invalid")
            if (self.stand_enabled or self.jam_enabled) and not self._fb_calibrated(jid):
                raise RuntimeError(f"ESP_ERR_INVALID_ARG: joint {jid} uncalibrated while stand/jam enabled")

    def _eval_measured_us(self, jid: int, raw: int) -> tuple[float, bool] | None:
        if not self._fb_calibrated(jid):
            return None
        p0, p1, p2 = self.fb_points[jid]
        assert p0 and p1 and p2
        asc = p2["raw"] > p0["raw"]
        hi = 1 if ((raw <= p1["raw"]) if asc else (raw >= p1["raw"])) else 2
        a, b = self.fb_points[jid][hi - 1], self.fb_points[jid][hi]
        assert a and b
        pulse = a["pulse_us"] + (raw - a["raw"]) * (b["pulse_us"] - a["pulse_us"]) / float(b["raw"] - a["raw"])
        in_range = (p0["raw"] <= raw <= p2["raw"]) if asc else (p2["raw"] <= raw <= p0["raw"])
        return pulse, in_range

    async def get_status_entry(self, robot_id: str) -> dict:
        roll, pitch = self._roll_pitch()
        return {
            "connected": True,
            "mode": self.mode,
            "status": {
                "imu": {
                    "available": True,
                    "fresh": True,
                    "orientation_wxyz": _rp_to_quat(roll, pitch),
                }
            },
        }

    async def get_body_calibration(self, robot_id: str) -> dict:
        return {
            "t": "calibration_status",
            "dirty": self.dirty,
            "saved": self.saved,
            "ready": True,
            "joints": copy.deepcopy(self.joints),
        }

    async def set_body_calibration_joint(self, robot_id: str, fields: dict) -> dict:
        if self.mode != "calibrate":
            raise RuntimeError("mode")
        jid = int(fields["id"])
        j = self.joints[jid]
        j["channel"] = int(fields["channel"])
        j["home_us"] = int(fields["home_us"])
        j["invert"] = bool(fields["invert"])
        j["home_cd"] = int(fields["home_cd"])
        j["us_per_degree"] = float(fields["us_per_degree"])
        self.armed = False
        self.dirty = True
        self.saved = False
        return await self.get_body_calibration(robot_id)

    async def save_body_calibration(self, robot_id: str) -> dict:
        if self.mode != "calibrate":
            raise RuntimeError("mode")
        self.armed = False
        self.dirty = False
        self.saved = True
        self.saved_count += 1
        return await self.get_body_calibration(robot_id)

    async def set_calibration_mode(self, robot_id: str, mode: str) -> int:
        if mode == "calibrate" and self.armed:
            raise RuntimeError("busy")
        self.mode = mode
        return 1

    async def move_targets(self, robot_id: str, targets_cd: list[int], speed_cd_s: int) -> None:
        if self.mode != "normal":
            raise RuntimeError("mode")
        if self.slow_move_delay_s > 0:
            await asyncio.sleep(self.slow_move_delay_s)
        self.armed = True
        self.current_targets_deg = [v / 100.0 for v in targets_cd]
        for jid, j in enumerate(self.joints):
            p = model_deg_to_pulse_us(j, self.current_targets_deg[jid])
            self.current_pulses[jid] = p
            j["pulse_us"] = p
        self.scan += 2

    async def detach(self, robot_id: str) -> None:
        self.armed = False
        self.detached_count += 1

    def _fb_json(self) -> dict:
        self.scan += 1
        channels = []
        joints_out = []
        for ch in range(16):
            if ch < JOINT_COUNT:
                actual_p = self._actual_pulse_under_load(ch)
                raw = self._pulse_to_raw(ch, actual_p)
                channels.append({"channel": ch, "valid": self.fb_enabled, "raw": raw, "spread": 2})
            else:
                channels.append({"channel": ch, "valid": False})
        for jid in range(JOINT_COUNT):
            raw = channels[jid]["raw"]
            cmd = self.current_pulses[jid] if self.armed else 0
            entry = {
                "id": jid,
                "channel": jid,
                "output": jid,
                "calibrated": self._fb_calibrated(jid),
                "command_us": cmd,
                "points": copy.deepcopy(self.fb_points[jid]),
            }
            ev = self._eval_measured_us(jid, raw) if self.fb_enabled else None
            if ev is not None:
                measured, in_range = ev
                entry["measured_us"] = measured
                entry["in_calibrated_range"] = in_range
                j = self.joints[jid]
                sign = -1.0 if j["invert"] else 1.0
                entry["model_deg"] = j["home_cd"] / 100.0 + sign * (measured - j["home_us"]) / j["us_per_degree"]
                if cmd:
                    entry["error_us"] = cmd - measured
            joints_out.append(entry)
        return {
            "enabled": self.fb_enabled,
            "stand_enabled": self.stand_enabled,
            "jam_enabled": self.jam_enabled,
            "tolerance_us": self.tolerance_us,
            "arrival_tolerance_us": self.arrival_tolerance_us,
            "no_progress_ms": self.no_progress_ms,
            "progress_us": self.progress_us,
            "scan": self.scan,
            "revision": self.revision,
            "channels": channels,
            "joints": joints_out,
        }

    async def get_servo_feedback(self, robot_id: str) -> dict:
        return self._fb_json()

    async def post_servo_feedback(self, robot_id: str, payload: dict) -> dict:
        op = payload["op"]
        backup = (
            self.fb_enabled, self.stand_enabled, self.jam_enabled, copy.deepcopy(self.fb_points)
        )
        try:
            if op == "configure":
                self.fb_enabled = bool(payload["enabled"])
                self.stand_enabled = bool(payload["stand_enabled"])
                self.jam_enabled = bool(payload.get("jam_enabled", self.jam_enabled))
            elif op == "clear":
                self.fb_points[int(payload["joint"])] = [None, None, None]
            elif op == "capture":
                if int(payload["revision"]) != self.revision:
                    raise RuntimeError("ESP_ERR_INVALID_STATE: revision mismatch")
                if int(payload["scan"]) > self.scan:
                    raise RuntimeError("ESP_ERR_INVALID_STATE: scan in future")
                jid = int(payload["joint"])
                pt = int(payload["point"])
                self.fb_points[jid][pt] = {"pulse_us": int(payload["pulse_us"]), "raw": int(payload["raw"])}
            else:
                raise RuntimeError(f"unknown op {op}")
            self._validate_fb_config()
            self.revision += 1
        except Exception:
            self.fb_enabled, self.stand_enabled, self.jam_enabled, self.fb_points = backup
            raise
        return self._fb_json()


class AutoCalibrationUnitTests(unittest.IsolatedAsyncioTestCase):
    def test_validate_and_order_feedback_points_sorts_inverted_pulses_and_rejects_flat_adc(self):
        ordered = validate_and_order_feedback_points(1, [(2600, 1200), (1500, 2400), (800, 3100)])
        self.assertEqual(ordered, [(800, 3100), (1500, 2400), (2600, 1200)])
        with self.assertRaisesRegex(CalibrationAbortError, "Rear left shoulder"):
            validate_and_order_feedback_points(0, [(1200, 2000), (1650, 2005), (2100, 2002)])

    def test_quat_round_trip(self):
        r, p = quat_to_roll_pitch_deg(_rp_to_quat(7.5, -4.25))
        self.assertAlmostEqual(r, 7.5, places=3)
        self.assertAlmostEqual(p, -4.25, places=3)

    async def test_legs_free_calibrates_all_12_joints_preserving_stand_and_jam_flags(self):
        robot = SimulatedP4RobotTransport(stand_enabled=True, jam_enabled=True)
        mgr = AutoCalibrationManager(robot, settle_delay_s=0.0, settle_polls=2, settle_poll_interval_s=0.0)
        await mgr.start("p4", mode="legs_free")
        await mgr._runs["p4"].task
        snap = mgr.status("p4")
        self.assertEqual(snap["state"], "completed", snap)
        self.assertEqual(snap["after"]["calibrated_joints"], 12)
        self.assertEqual(snap["after"]["in_range_joints"], 12)
        self.assertFalse(snap["can_apply"])
        self.assertTrue(snap["can_restore"])
        self.assertTrue(robot.stand_enabled)
        self.assertTrue(robot.jam_enabled)
        self.assertGreaterEqual(robot.detached_count, 1)
        # All 12 joints have strictly ascending pulse_us curves.
        for jid in range(JOINT_COUNT):
            pts = robot.fb_points[jid]
            self.assertTrue(pts[0]["pulse_us"] < pts[1]["pulse_us"] < pts[2]["pulse_us"])

    async def test_floor_mode_levels_body_balances_legs_trims_shoulder_and_stages_before_save(self):
        # Asymmetric leg heights + 90 us shoulder misalignment on rear-left shoulder.
        offsets = {
            0: +90,   # RL_sh offset
            1: +65,   # RL_ca offset
            4: -55,   # RR_ca offset
            7: -35,   # FL_ca offset
            10: +25,  # FR_ca offset
        }
        robot = SimulatedP4RobotTransport(true_home_offsets_us=offsets, stand_enabled=True, jam_enabled=True)
        jam_during_moves: list[bool] = []
        orig_move = robot.move_targets

        async def _check_jam(rid: str, targets_cd: list[int], speed_cd_s: int) -> None:
            jam_during_moves.append(robot.jam_enabled)
            await orig_move(rid, targets_cd, speed_cd_s)

        robot.move_targets = _check_jam
        mgr = AutoCalibrationManager(robot, settle_delay_s=0.0, settle_polls=2, settle_poll_interval_s=0.0)
        await mgr.start("p4", mode="floor")
        await mgr._runs["p4"].task
        snap = mgr.status("p4")
        self.assertEqual(snap["state"], "ready_to_apply", snap)
        self.assertTrue(jam_during_moves and all(flag is False for flag in jam_during_moves))
        self.assertTrue(robot.jam_enabled, "jam_enabled must be restored after calibration completes")
        self.assertTrue(snap["can_apply"])
        self.assertEqual(robot.saved_count, 0, "must stage in RAM and wait for explicit Apply & save")
        self.assertTrue(robot.dirty)
        self.assertGreater(abs(snap["before"]["roll_deg"]) + abs(snap["before"]["pitch_deg"]), 2.0)
        self.assertLess(abs(snap["after"]["roll_deg"]), 0.5)
        self.assertLess(abs(snap["after"]["pitch_deg"]), 0.5)
        # Carrier load spread across the 4 legs should drop sharply.
        before_spread = max(snap["before"]["carrier_load_us"]) - min(snap["before"]["carrier_load_us"])
        after_spread = max(snap["after"]["carrier_load_us"]) - min(snap["after"]["carrier_load_us"])
        self.assertLess(after_spread, before_spread * 0.25)
        # Rear-left shoulder error should shrink significantly.
        self.assertLess(abs(snap["after"]["shoulder_error_us"][0]), abs(snap["before"]["shoulder_error_us"][0]) * 0.5)

        # Explicit Apply persists to NVS.
        applied = await mgr.apply("p4")
        self.assertEqual(applied["state"], "completed")
        self.assertEqual(robot.saved_count, 1)
        self.assertFalse(robot.dirty)
        self.assertTrue(robot.saved)

    async def test_restore_reverts_staged_home_and_feedback_curves(self):
        offsets = {1: +60, 4: -60}
        robot = SimulatedP4RobotTransport(true_home_offsets_us=offsets)
        original_homes = [j["home_us"] for j in robot.joints]
        original_points = copy.deepcopy(robot.fb_points)
        mgr = AutoCalibrationManager(robot, settle_delay_s=0.0, settle_polls=2, settle_poll_interval_s=0.0)
        await mgr.start("p4", mode="floor")
        await mgr._runs["p4"].task
        self.assertEqual(mgr.status("p4")["state"], "ready_to_apply")
        self.assertNotEqual([j["home_us"] for j in robot.joints], original_homes)

        restored = await mgr.restore("p4")
        self.assertEqual(restored["state"], "aborted")
        self.assertEqual([j["home_us"] for j in robot.joints], original_homes)
        self.assertEqual(robot.fb_points, original_points)

    async def test_non_monotonic_fourth_wire_aborts_detaches_and_preserves_backup(self):
        robot = SimulatedP4RobotTransport(stuck_adc_joint=0)
        original_points = copy.deepcopy(robot.fb_points)
        mgr = AutoCalibrationManager(robot, settle_delay_s=0.0, settle_polls=2, settle_poll_interval_s=0.0)
        await mgr.start("p4", mode="legs_free")
        await mgr._runs["p4"].task
        snap = mgr.status("p4")
        self.assertEqual(snap["state"], "aborted")
        self.assertIn("Rear left shoulder", snap["error"])
        self.assertIn("monotonically", snap["error"])
        self.assertGreaterEqual(robot.detached_count, 1)
        self.assertEqual(robot.fb_points, original_points)

    async def test_excessive_tilt_aborts_floor_calibration_and_detaches(self):
        robot = SimulatedP4RobotTransport(force_tilt_deg=(28.0, 2.0))
        mgr = AutoCalibrationManager(robot, settle_delay_s=0.0, settle_polls=2, settle_poll_interval_s=0.0)
        await mgr.start("p4", mode="floor")
        await mgr._runs["p4"].task
        snap = mgr.status("p4")
        self.assertEqual(snap["state"], "aborted")
        self.assertIn("25°", snap["error"])
        self.assertGreaterEqual(robot.detached_count, 1)
        self.assertTrue(robot.jam_enabled, "jam_enabled must be restored after abort")

    async def test_floor_mode_sweeps_symmetrically_and_captures_uncalibrated_joints(self):
        robot = SimulatedP4RobotTransport(true_home_offsets_us={1: +40, 4: -40}, stand_enabled=False, jam_enabled=False)
        for jid in range(JOINT_COUNT):
            robot.fb_points[jid] = [None, None, None]
        recorded_moves: list[list[int]] = []
        orig_move = robot.move_targets

        async def _track(rid: str, targets_cd: list[int], speed_cd_s: int) -> None:
            recorded_moves.append(list(targets_cd))
            await orig_move(rid, targets_cd, speed_cd_s)

        robot.move_targets = _track
        mgr = AutoCalibrationManager(robot, settle_delay_s=0.0, settle_polls=2, settle_poll_interval_s=0.0)
        await mgr.start("p4", mode="floor")
        await mgr._runs["p4"].task
        snap = mgr.status("p4")
        self.assertIn(snap["state"], ("ready_to_apply", "completed"), snap)
        self.assertEqual(snap["after"]["calibrated_joints"], 12)
        # First 3 moves (Phase 1 sweep) must be symmetric across all 4 legs (no 3-leg tripod lift),
        # and no move in Phase 1 or Phase 2 may command any shoulder inward (> 0 deg).
        for targets in recorded_moves[:3]:
            leg0 = targets[0:3]
            for leg in range(1, 4):
                self.assertEqual(targets[leg * 3 : leg * 3 + 3], leg0)
        for targets in recorded_moves:
            for leg in range(4):
                self.assertLessEqual(targets[leg * 3], 0, f"shoulder {leg} commanded inward: {targets}")

    async def test_operator_stop_cancels_and_detaches(self):
        robot = SimulatedP4RobotTransport(slow_move_delay_s=0.05)
        mgr = AutoCalibrationManager(robot, settle_delay_s=0.02, settle_polls=2, settle_poll_interval_s=0.01)
        await mgr.start("p4", mode="legs_free")
        await asyncio.sleep(0.03)
        snap = await mgr.stop("p4")
        self.assertEqual(snap["state"], "aborted")
        self.assertIn("cancelled", (snap["error"] or "").lower())
        self.assertGreaterEqual(robot.detached_count, 1)


if __name__ == "__main__":
    unittest.main()
