#!/usr/bin/env python3
"""Export self-contained MuJoCo V2 MJCF XML + exact physics/firmware config for static web WASM."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from gateway.neural_gait.environment import EnvironmentConfig, GaitEnvironment, build_xml


def export_wasm_assets(out_dir: Path, *, collision_profile: str = "locomotion") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    config = EnvironmentConfig(collision_profile=collision_profile, imu_prehistory_s=0.5)
    xml = build_xml(config, include_assembly=True, include_visuals=False)
    env = GaitEnvironment(config, include_assembly=True, include_visuals=False)
    try:
        env.reset()
        init_qpos = [float(v) for v in env.data.qpos]
        qadr = [int(v) for v in env.qadr]
        vadr = [int(v) for v in env.vadr]
        torso_body_id = int(env.model.body("torso").id)
        foot_geoms = ["rear_left_foot", "rear_right_foot", "front_left_foot", "front_right_foot"]
        foot_geom_ids = [int(env.model.geom(name).id) for name in foot_geoms]
        floor_geom_id = int(env.model.geom("floor").id)
        gyro_adr = int(env.model.sensor_adr[env.model.sensor("gyro").id])
        accel_adr = int(env.model.sensor_adr[env.model.sensor("accel").id])
        robot = config.robot
        bm = env.body_model
        mapping = [
            [
                float(j[k])
                for k in ("channel", "invert", "home_us", "home_cd", "us_per_degree")
            ]
            for j in bm.mapping
        ]
        feedback_table = [
            [float(j["channel"])]
            + [float(p[k]) for p in j["points"] for k in ("raw", "pulse_us")]
            for j in bm.feedback
        ]
        fb_cfg = robot["feedback"]
        feedback_settings = [
            float(fb_cfg[k])
            for k in (
                "tolerance_us",
                "arrival_tolerance_us",
                "no_progress_ms",
                "progress_us",
                "enabled",
                "jam_enabled",
            )
        ] + [float(fb_cfg.get("stand_enabled", False))]
        raw_curve = [
            [[float(p["raw"]), float(p["pulse_us"])] for p in j["points"]]
            for j in bm.feedback
        ]
    finally:
        env.close()

    xml_path = out_dir / "ainekio-v2-locomotion.xml"
    xml_path.write_text(xml, encoding="utf-8")

    payload = {
        "schemaVersion": 1,
        "model": "v2-12servo",
        "collisionProfile": collision_profile,
        "physicsHz": int(config.physics_hz),
        "controlHz": int(config.control_hz),
        "imuHz": 208,
        "imuPrehistoryS": float(config.imu_prehistory_s),
        "referenceJointDeg": [float(v) for v in config.reference_joint_deg],
        "initQpos": init_qpos,
        "qadr": qadr,
        "vadr": vadr,
        "torsoBodyId": torso_body_id,
        "floorGeomId": floor_geom_id,
        "footGeoms": foot_geoms,
        "footGeomIds": foot_geom_ids,
        "gyroSensorAdr": gyro_adr,
        "accelSensorAdr": accel_adr,
        "torqueNm": float(config.torque_nm),
        "motorNoLoadSpeedRadS": math.radians(float(config.motor_no_load_speed_deg_s)),
        "jointSpeedDegS": float(config.joint_speed_deg_s),
        "actuatorDelayS": float(config.actuator_delay_s),
        "pwmOscillatorHz": float(config.pwm_oscillator_hz),
        "pwmFrequencyHz": float(config.pwm_frequency_hz),
        "balanceEnabled": bool(config.balance_enabled),
        "headingFeedbackEnabled": bool(config.heading_feedback_enabled),
        "balanceTuning": [float(v) for v in config.balance_tuning],
        "imuAccelNoiseStd": float(config.imu_accel_noise_std),
        "imuGyroNoiseStd": float(config.imu_gyro_noise_std),
        "feedbackNoiseRawStd": float(config.feedback_noise_raw_std),
        "mapping": mapping,
        "feedbackTable": feedback_table,
        "feedbackSettings": feedback_settings,
        "rawCurve": raw_curve,
    }
    cfg_path = out_dir / "v2-physics-config.json"
    cfg_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Exported {xml_path} ({xml_path.stat().st_size} B) and {cfg_path} ({cfg_path.stat().st_size} B)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export V2 MuJoCo XML + physics config for WASM simulator.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/home/greggles/Ainekio/apps/simulator/public/sim"),
    )
    parser.add_argument("--collision-profile", choices=("locomotion", "assembly"), default="locomotion")
    args = parser.parse_args()
    export_wasm_assets(args.out_dir, collision_profile=args.collision_profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
