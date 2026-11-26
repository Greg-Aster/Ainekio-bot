"""Compact read-only projection of recent robot episodes for owner and agent review.

Aggregates action receipts (`environment-actions.sqlite`), Freestyle execution/body
telemetry (`freestyle-recordings.sqlite`), and Freestyle generator metadata
(`freestyle-inference.sqlite`) without duplicating storage or blocking the control loop.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Any, Mapping
import zlib

from protocol.joints_v2 import JOINT_LABELS as V2_JOINT_LABELS

SCHEMA_VERSION = "ainekio_recent_episodes_v1"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MOTION_TYPES = ("move", "requestMotion", "freestyle", "stop")
DEFAULT_EXCLUDED_TYPES = ("faceExpression",)


def _open_ro(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _decode_zlib_json(blob: bytes | memoryview | str | None) -> dict[str, Any] | None:
    if blob is None:
        return None
    try:
        if isinstance(blob, str):
            return json.loads(blob)
        return json.loads(zlib.decompress(bytes(blob)).decode("utf-8"))
    except Exception:
        return None


def _decode_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else None
    except Exception:
        return None


def _iso_utc(ts_seconds: float | None) -> str | None:
    if ts_seconds is None or not math.isfinite(ts_seconds):
        return None
    return datetime.fromtimestamp(ts_seconds, tz=timezone.utc).isoformat()


def _parse_iso_seconds(value: str | None) -> float | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return None


def _quat_to_rpy_deg(wxyz: object) -> list[float] | None:
    if not isinstance(wxyz, (list, tuple)) or len(wxyz) != 4:
        return None
    try:
        w, x, y, z = (float(v) for v in wxyz)
    except (TypeError, ValueError):
        return None
    roll = math.degrees(math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)))
    sinp = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    pitch = math.degrees(math.asin(sinp))
    yaw = math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))
    return [round(roll, 2), round(pitch, 2), round(yaw, 2)]


def _summarize_program_step(step: Mapping[str, Any]) -> str:
    name = str(step.get("name") or "unknown")
    args = step.get("arguments") if isinstance(step.get("arguments"), Mapping) else {}
    if name == "face":
        return f"face({args.get('expr', '')})"
    if name == "hold":
        return f"hold({args.get('seconds', 0)}s)"
    if name == "stand":
        return "stand()"
    if name == "gait":
        parts = [str(args.get("command") or "forward")]
        if "cycles" in args:
            parts.append(f"cycles={args['cycles']}")
        if "speed_pct" in args:
            parts.append(f"speed={args['speed_pct']}%")
        return f"gait({', '.join(parts)})"
    if name == "pose":
        joints = args.get("joints") if isinstance(args.get("joints"), list) else []
        spd = args.get("speed_pct")
        suffix = f", speed={spd}%" if spd is not None else ""
        return f"pose({len(joints)}j{suffix})"
    if name == "move":
        return f"move({args.get('joint', '?')}->{args.get('angle_deg', '?')}deg)"
    if name in ("oscillate", "feet", "body"):
        spd = args.get("speed_pct")
        suffix = f"speed={spd}%" if spd is not None else ""
        return f"{name}({suffix})"
    return name


def _round_joints(joints: Mapping[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(joints, Mapping) or not joints:
        return None
    out: dict[str, float] = {}
    for k, v in joints.items():
        val = v.get("filtered_model_deg", v.get("model_deg")) if isinstance(v, Mapping) else v
        if isinstance(val, (int, float)) and math.isfinite(val):
            out[str(k)] = round(float(val), 2)
    return out or None


def _summarize_telemetry_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize IMU attitude, unwrapped yaw turn, fourth-wire tracking lag, and stalls."""
    start_rpy: list[float] | None = None
    end_rpy: list[float] | None = None
    prev_yaw: float | None = None
    net_turn_deg = 0.0
    stalled_mask = 0
    stall_released = False
    max_lag_deg: dict[str, float] = {}
    imu_samples = 0
    start_joints: dict[str, float] | None = None
    end_joints: dict[str, float] | None = None

    for ev in events:
        ev_t = ev.get("t")
        if ev_t == "imu":
            imu = ev.get("imu") if isinstance(ev.get("imu"), Mapping) else {}
            rpy = _quat_to_rpy_deg(imu.get("orientation_wxyz"))
            if rpy is not None:
                imu_samples += 1
                if start_rpy is None:
                    start_rpy = rpy
                end_rpy = rpy
                yaw = rpy[2]
                if prev_yaw is not None:
                    delta = (yaw - prev_yaw + 180.0) % 360.0 - 180.0
                    net_turn_deg += delta
                prev_yaw = yaw
            jf = imu.get("joint_feedback") if isinstance(imu.get("joint_feedback"), Mapping) else None
            if jf is not None:
                stalled_mask |= int(jf.get("stalled_joints") or 0)
                usable_mask = int(jf.get("usable_mask") or 0)
                measured = jf.get("filtered_model_deg")
                commanded = jf.get("commanded_model_deg")
                labels = ("R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4") if jf.get("map") == 1 else V2_JOINT_LABELS
                if isinstance(measured, list) and isinstance(commanded, list):
                    snap: dict[str, float] = {}
                    for idx, label in enumerate(labels):
                        if idx < len(measured) and isinstance(measured[idx], (int, float)):
                            snap[label] = round(float(measured[idx]), 2)
                        if (
                            (usable_mask & (1 << idx))
                            and idx < len(measured)
                            and idx < len(commanded)
                            and isinstance(measured[idx], (int, float))
                            and isinstance(commanded[idx], (int, float))
                        ):
                            lag = abs(float(commanded[idx]) - float(measured[idx]))
                            if lag > max_lag_deg.get(label, 0.0):
                                max_lag_deg[label] = round(lag, 2)
                    if snap:
                        if start_joints is None:
                            start_joints = snap
                        end_joints = snap
        elif ev_t == "servo_feedback":
            data = ev.get("data") if isinstance(ev.get("data"), Mapping) else {}
            stalled_mask |= int(data.get("stalled_joints") or 0)
        elif ev_t == "event" and ev.get("name") == "body_event":
            data = ev.get("data") if isinstance(ev.get("data"), Mapping) else {}
            if data.get("kind") == "servo_stall" and data.get("outputs_released"):
                stall_released = True

    stalled_names = [
        V2_JOINT_LABELS[idx]
        for idx in range(len(V2_JOINT_LABELS))
        if stalled_mask & (1 << idx)
    ]
    top_lag = dict(sorted(max_lag_deg.items(), key=lambda kv: kv[1], reverse=True)[:4])
    summary: dict[str, Any] = {
        "telemetry_samples": imu_samples,
        "stalled_joints_mask": stalled_mask,
        "servo_stall_released": stall_released,
    }
    if stalled_names:
        summary["stalled_joints"] = stalled_names
    if start_rpy is not None:
        summary["start_rpy_deg"] = start_rpy
        summary["end_rpy_deg"] = end_rpy
        summary["net_turn_deg"] = round(net_turn_deg, 2)
    if top_lag:
        summary["max_tracking_error_deg"] = top_lag
    if start_joints is not None and end_joints is not None:
        max_travel = {
            k: round(end_joints[k] - start_joints[k], 2)
            for k in start_joints
            if k in end_joints and abs(end_joints[k] - start_joints[k]) >= 1.0
        }
        if max_travel:
            summary["net_joint_delta_deg"] = max_travel
    return summary


def _load_sequence_telemetry(
    rec_conn: sqlite3.Connection | None,
    robot_id: str | None,
    epoch: int | None,
    sequences: list[int],
    *,
    max_rows_per_seq: int = 400,
) -> list[dict[str, Any]]:
    if rec_conn is None or not robot_id or type(epoch) is not int or not sequences:
        return []
    out: list[dict[str, Any]] = []
    for seq in sequences[:16]:
        rows = rec_conn.execute(
            "SELECT payload FROM evidence WHERE robot_id=? AND epoch=? AND sequence=? AND kind='body_event' "
            "ORDER BY time_ns ASC LIMIT ?",
            (robot_id, epoch, seq, max_rows_per_seq),
        ).fetchall()
        for r in rows:
            decoded = _decode_zlib_json(r["payload"])
            if decoded is not None:
                out.append(decoded)
    return out


def _load_freestyle_job_summary(
    rec_conn: sqlite3.Connection | None,
    inf_conn: sqlite3.Connection | None,
    job_id: str,
    *,
    include_steps: bool = False,
) -> dict[str, Any] | None:
    if rec_conn is None:
        return None
    rows = rec_conn.execute(
        "SELECT time_ns, kind, robot_id, epoch, sequence, payload FROM evidence WHERE job_id=? ORDER BY time_ns ASC",
        (job_id,),
    ).fetchall()
    if not rows:
        return None

    started_ns = rows[0]["time_ns"]
    ended_ns = rows[-1]["time_ns"]
    robot_id = rows[0]["robot_id"]
    epoch = rows[0]["epoch"]
    request_text: str | None = None
    source: Any = None
    state = "running"
    error: str | None = None
    program: list[dict[str, Any]] = []
    sequences: list[int] = []
    op_completed: list[dict[str, Any]] = []
    first_obs: dict[str, Any] | None = None
    last_obs: dict[str, Any] | None = None

    for r in rows:
        kind = r["kind"]
        seq = r["sequence"]
        if type(seq) is int and seq not in sequences:
            sequences.append(seq)
        payload = _decode_zlib_json(r["payload"]) or {}
        if kind == "job_started":
            request_text = payload.get("request") if isinstance(payload.get("request"), str) else request_text
            source = payload.get("source")
            state = str(payload.get("state") or state)
        elif kind in ("generation_requested", "correction_trial_requested"):
            req = payload.get("request") if isinstance(payload.get("request"), Mapping) else {}
            if request_text is None and isinstance(req.get("request"), str):
                request_text = req["request"]
            if first_obs is None and isinstance(req.get("observation"), Mapping):
                first_obs = dict(req["observation"])
        elif kind in ("generation_completed", "correction_trial_program"):
            res = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
            if isinstance(res.get("program"), list):
                program = list(res["program"])
        elif kind == "command_receipt":
            r_seq = payload.get("seq")
            if type(r_seq) is int and r_seq not in sequences:
                sequences.append(r_seq)
        elif kind == "operation_completed":
            op_completed.append(payload)
            after = payload.get("after") if isinstance(payload.get("after"), Mapping) else None
            if after is not None:
                last_obs = dict(after)
                for rec in after.get("receipts") or []:
                    if isinstance(rec, Mapping) and type(rec.get("seq")) is int and rec["seq"] not in sequences:
                        sequences.append(rec["seq"])
        elif kind == "job_error":
            error = str(payload.get("error") or error or "")
        elif kind == "job_finished":
            state = str(payload.get("state") or state)
            if payload.get("error"):
                error = str(payload["error"])

    generator_meta: dict[str, Any] | None = None
    if inf_conn is not None:
        inf_row = inf_conn.execute(
            "SELECT payload FROM evidence WHERE job_id=? AND kind IN ('inference_completed','inference_failed') "
            "ORDER BY time_ns DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        if inf_row is not None:
            inf = _decode_zlib_json(inf_row["payload"]) or {}
            gen = inf.get("generator") if isinstance(inf.get("generator"), Mapping) else {}
            adapter_path = str(gen.get("adapter_path") or "")
            adapter_name = Path(adapter_path).parent.name if adapter_path else gen.get("model_alias")
            usage = inf.get("usage") if isinstance(inf.get("usage"), Mapping) else {}
            generator_meta = {
                "model_alias": gen.get("model_alias"),
                "adapter": adapter_name,
                "adapter_sha256_prefix": str(gen.get("configured_adapter_sha256") or "")[:12] or None,
                "elapsed_ms": round(float(inf["elapsed_s"]) * 1000) if isinstance(inf.get("elapsed_s"), (int, float)) else None,
                "tokens": usage.get("total_tokens"),
            }
            if inf.get("error") and not error:
                error = str(inf["error"])

    events = _load_sequence_telemetry(rec_conn, robot_id, epoch, sequences)
    motion_summary = _summarize_telemetry_events(events)

    if "start_rpy_deg" not in motion_summary and first_obs is not None:
        rpy0 = _quat_to_rpy_deg((first_obs.get("imu") or {}).get("orientation_wxyz"))
        if rpy0 is not None:
            motion_summary["start_rpy_deg"] = rpy0
    if "end_rpy_deg" not in motion_summary and last_obs is not None:
        rpy1 = _quat_to_rpy_deg((last_obs.get("imu") or {}).get("orientation_wxyz"))
        if rpy1 is not None:
            motion_summary["end_rpy_deg"] = rpy1
            if "start_rpy_deg" in motion_summary:
                dyaw = (rpy1[2] - motion_summary["start_rpy_deg"][2] + 180.0) % 360.0 - 180.0
                motion_summary.setdefault("net_turn_deg", round(dyaw, 2))

    if "net_joint_delta_deg" not in motion_summary and first_obs is not None and last_obs is not None:
        j0 = _round_joints(first_obs.get("joints"))
        j1 = _round_joints(last_obs.get("joints"))
        if j0 and j1:
            deltas = {k: round(j1[k] - j0[k], 2) for k in j0 if k in j1 and abs(j1[k] - j0[k]) >= 1.0}
            if deltas:
                motion_summary["net_joint_delta_deg"] = deltas

    out: dict[str, Any] = {
        "job_id": job_id,
        "robot_id": robot_id,
        "epoch": epoch,
        "request": request_text,
        "state": state,
        "started_at_s": started_ns / 1e9,
        "ended_at_s": ended_ns / 1e9,
        "duration_ms": max(0, round((ended_ns - started_ns) / 1e6)),
        "operation_count": len(program),
        "completed_operations": len(op_completed),
        "program_summary": [_summarize_program_step(s) for s in program],
        "sequences": sequences,
        "motion_summary": motion_summary,
    }
    if source is not None:
        out["source"] = source
    if error:
        out["error"] = error
    if generator_meta is not None:
        out["generator"] = generator_meta
    if include_steps:
        out["program"] = program
        out["operations"] = [
            {
                "action_index": op.get("action_index"),
                "action": (op.get("before") or {}).get("action"),
                "before_rpy_deg": _quat_to_rpy_deg(((op.get("before") or {}).get("imu") or {}).get("orientation_wxyz")),
                "after_rpy_deg": _quat_to_rpy_deg(((op.get("after") or {}).get("imu") or {}).get("orientation_wxyz")),
                "receipts": (op.get("after") or {}).get("receipts"),
            }
            for op in op_completed
        ]
    return out


def _summarize_request_payload(action_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if action_type == "requestMotion":
        return {k: payload[k] for k in ("description",) if k in payload}
    if action_type == "move":
        keys = ("direction", "gait", "speed", "continuous", "amount", "units", "durationMs", "locomotionGoal")
        return {k: payload[k] for k in keys if k in payload}
    if action_type == "speechAudio":
        keys = ("speechId", "durationMs", "pcmBytes", "pcmChars", "pcmSha256")
        out = {k: payload[k] for k in keys if k in payload}
        if "pcm" in payload and isinstance(payload["pcm"], str) and "pcmBytes" not in out:
            out["pcmBytes"] = (len(payload["pcm"]) * 3) // 4
        return out
    if action_type == "faceExpression":
        keys = ("expression", "displayBackground", "displayTimeoutMs", "displayRelease")
        return {k: payload[k] for k in keys if k in payload}
    if action_type == "stop":
        return {"detach": bool(payload.get("detach", False))}
    if action_type == "sendText":
        return {"text": str(payload.get("text") or "")[:240]}
    if action_type == "captureImage":
        return {k: payload[k] for k in ("reason", "correlationId") if k in payload}
    return {k: v for k, v in payload.items() if k not in ("id", "type", "bodyLease", "pcm", "metadata")}


def read_recent_episodes(
    data_dir: str | Path,
    *,
    limit: int = DEFAULT_LIMIT,
    robot_id: str | None = None,
    types: list[str] | tuple[str, ...] | None = None,
    include_faces: bool = False,
    since: str | float | None = None,
    episode_id: str | None = None,
    live_gateway_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return compact, structured summaries of recent robot episodes."""
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {MAX_LIMIT}")
    root = Path(data_dir)
    since_s = since if isinstance(since, (int, float)) else _parse_iso_seconds(since)
    if since is not None and since_s is None:
        raise ValueError("since must be an ISO-8601 timestamp or Unix seconds")

    normalized_types: set[str] | None = None
    if types:
        expanded: set[str] = set()
        for item in types:
            token = item.strip()
            if not token:
                continue
            if token == "all":
                expanded.clear()
                include_faces = True
                break
            if token == "motion":
                expanded.update(MOTION_TYPES)
            else:
                expanded.add(token)
        if expanded:
            normalized_types = expanded

    act_conn = _open_ro(root / "environment-actions.sqlite")
    rec_conn = _open_ro(root / "freestyle-recordings.sqlite")
    inf_conn = _open_ro(root / "freestyle-inference.sqlite")
    try:
        episodes: list[dict[str, Any]] = []
        seen_freestyle_jobs: set[str] = set()

        if act_conn is not None:
            if episode_id:
                rows = act_conn.execute("SELECT * FROM actions WHERE id=?", (episode_id,)).fetchall()
            else:
                sql = "SELECT * FROM actions"
                params: list[Any] = []
                if since_s is not None:
                    sql += " WHERE updated >= ?"
                    params.append(float(since_s))
                sql += " ORDER BY updated DESC LIMIT ?"
                params.append(max(limit * 8, 200))
                rows = act_conn.execute(sql, params).fetchall()

            for row in rows:
                payload = _decode_json(row["payload"]) or {}
                wire = _decode_json(row["wire"]) or {}
                result = _decode_json(row["result"]) or {}
                action_type = str(payload.get("type") or ("cancel" if row["cancellation_only"] else "unknown"))
                if normalized_types is not None and action_type not in normalized_types:
                    continue
                if normalized_types is None and not include_faces and action_type in DEFAULT_EXCLUDED_TYPES and not episode_id:
                    continue

                ep_robot = (
                    wire.get("robotId")
                    or (result.get("data") or {}).get("robotId")
                    if isinstance(result.get("data"), Mapping)
                    else wire.get("robotId")
                )
                if robot_id and ep_robot != robot_id:
                    continue

                created_s = _parse_iso_seconds(payload.get("createdAt") or payload.get("dispatchedAt"))
                result_s = _parse_iso_seconds(result.get("timestamp"))
                updated_s = float(row["updated"])
                end_s = result_s if result_s is not None else updated_s
                duration_ms = (
                    max(0, round((end_s - created_s) * 1000))
                    if created_s is not None and end_s >= created_s
                    else None
                )

                ep: dict[str, Any] = {
                    "id": row["id"],
                    "source": "environment",
                    "type": action_type,
                    "robot_id": ep_robot,
                    "epoch": wire.get("epoch"),
                    "sequence": wire.get("sequence"),
                    "timestamp": _iso_utc(created_s or updated_s),
                    "updated_at": round(updated_s, 3),
                    "duration_ms": duration_ms,
                    "request": _summarize_request_payload(action_type, payload),
                    "outcome": {
                        "state": row["state"],
                        "result_type": result.get("type"),
                        "message": result.get("message"),
                    },
                }
                if isinstance(payload.get("correlationId"), str):
                    ep["execution_id"] = payload["correlationId"]
                elif isinstance((payload.get("bodyLease") or {}).get("executionId"), str):
                    ep["execution_id"] = payload["bodyLease"]["executionId"]

                if isinstance(wire.get("walkUpdate"), Mapping):
                    ep["outcome"]["walk_update"] = dict(wire["walkUpdate"])
                if isinstance(result.get("data"), Mapping) and result["data"].get("playbackTarget"):
                    ep["outcome"]["playback_target"] = result["data"]["playbackTarget"]

                job_id = wire.get("jobId") or (row["id"] if action_type == "requestMotion" else None)
                if isinstance(job_id, str) and job_id:
                    seen_freestyle_jobs.add(job_id)
                    fs = _load_freestyle_job_summary(
                        rec_conn, inf_conn, job_id, include_steps=bool(episode_id)
                    )
                    if fs is not None:
                        ep["freestyle"] = {
                            k: fs[k]
                            for k in (
                                "job_id",
                                "state",
                                "operation_count",
                                "completed_operations",
                                "program_summary",
                                "generator",
                                "error",
                                "program",
                                "operations",
                            )
                            if k in fs
                        }
                        ep["sequences"] = fs["sequences"]
                        ep["motion_summary"] = fs["motion_summary"]
                        if ep["robot_id"] is None:
                            ep["robot_id"] = fs.get("robot_id")
                        if ep["epoch"] is None:
                            ep["epoch"] = fs.get("epoch")
                elif action_type in ("move", "stop") and isinstance(ep_robot, str) and type(wire.get("epoch")) is int and type(wire.get("sequence")) is int:
                    seqs = [int(wire["sequence"])]
                    upd_seq = (wire.get("walkUpdate") or {}).get("sequence")
                    if type(upd_seq) is int and upd_seq not in seqs:
                        seqs.append(upd_seq)
                    events = _load_sequence_telemetry(rec_conn, ep_robot, int(wire["epoch"]), seqs)
                    if events:
                        ep["motion_summary"] = _summarize_telemetry_events(events)

                episodes.append(ep)
                if not episode_id and len(episodes) >= limit * 2:
                    break

        include_freestyle_direct = (
            normalized_types is None
            or "freestyle" in normalized_types
            or "requestMotion" in normalized_types
        )
        if rec_conn is not None and include_freestyle_direct:
            if episode_id and episode_id not in seen_freestyle_jobs:
                job_ids = [episode_id]
            elif not episode_id:
                sql = "SELECT DISTINCT job_id, MAX(time_ns) AS latest_ns FROM evidence WHERE job_id IS NOT NULL"
                params = []
                if since_s is not None:
                    sql += " AND time_ns >= ?"
                    params.append(int(since_s * 1e9))
                sql += " GROUP BY job_id ORDER BY latest_ns DESC LIMIT ?"
                params.append(limit)
                job_ids = [
                    r["job_id"]
                    for r in rec_conn.execute(sql, params).fetchall()
                    if isinstance(r["job_id"], str) and r["job_id"] not in seen_freestyle_jobs
                ]
            else:
                job_ids = []

            for jid in job_ids:
                fs = _load_freestyle_job_summary(rec_conn, inf_conn, jid, include_steps=bool(episode_id))
                if fs is None:
                    continue
                if robot_id and fs.get("robot_id") != robot_id:
                    continue
                episodes.append(
                    {
                        "id": jid,
                        "source": "body_control",
                        "type": "freestyle",
                        "robot_id": fs.get("robot_id"),
                        "epoch": fs.get("epoch"),
                        "sequences": fs.get("sequences", []),
                        "timestamp": _iso_utc(fs["started_at_s"]),
                        "updated_at": round(fs["ended_at_s"], 3),
                        "duration_ms": fs["duration_ms"],
                        "request": {
                            "description": fs.get("request"),
                            **({"source": fs["source"]} if "source" in fs else {}),
                        },
                        "freestyle": {
                            k: fs[k]
                            for k in (
                                "job_id",
                                "state",
                                "operation_count",
                                "completed_operations",
                                "program_summary",
                                "generator",
                                "error",
                                "program",
                                "operations",
                            )
                            if k in fs
                        },
                        "motion_summary": fs["motion_summary"],
                        "outcome": {
                            "state": fs["state"],
                            "result_type": "completed" if fs["state"] in ("completed", "completed_section", "generated") else fs["state"],
                            "message": fs.get("error") or fs["state"],
                        },
                    }
                )

        episodes.sort(key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)
        selected = episodes[:1] if episode_id else episodes[:limit]

        live_robots: dict[str, Any] = {}
        if isinstance(live_gateway_status, Mapping):
            for rid, rinfo in (live_gateway_status.get("robots") or {}).items():
                if not isinstance(rinfo, Mapping):
                    continue
                imu = ((rinfo.get("status") or {}).get("imu") or {}) if isinstance(rinfo.get("status"), Mapping) else {}
                jf = imu.get("joint_feedback") if isinstance(imu.get("joint_feedback"), Mapping) else {}
                live_robots[str(rid)] = {
                    "connected": bool(rinfo.get("connected")),
                    "connection_state": rinfo.get("connection_state"),
                    "model": rinfo.get("model"),
                    "virtual": bool(rinfo.get("virtual")),
                    "epoch": rinfo.get("epoch"),
                    "body_command_sequence": rinfo.get("body_command_sequence"),
                    "rpy_deg": _quat_to_rpy_deg(imu.get("orientation_wxyz")),
                    "stalled_joints_mask": jf.get("stalled_joints"),
                }

        response: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_dir": str(root),
            "count": len(selected),
            "filter": {
                "limit": limit,
                "robot_id": robot_id,
                "types": sorted(normalized_types) if normalized_types is not None else None,
                "excluded_types": (
                    []
                    if (normalized_types is not None or include_faces or episode_id)
                    else list(DEFAULT_EXCLUDED_TYPES)
                ),
                "since": _iso_utc(since_s) if since_s is not None else None,
                "episode_id": episode_id,
            },
            "episodes": selected,
        }
        if live_robots:
            response["live_robots"] = live_robots
        return response
    finally:
        for conn in (act_conn, rec_conn, inf_conn):
            if conn is not None:
                conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read compact recent robot episodes from Body Control stores.")
    parser.add_argument(
        "--data-dir",
        default="build/gateway/physical",
        help="Gateway data directory containing environment-actions.sqlite and freestyle-recordings.sqlite",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Max episodes (1..{MAX_LIMIT})")
    parser.add_argument("--robot-id", default=None, help="Filter by robot_id")
    parser.add_argument(
        "--types",
        default=None,
        help="Comma-separated types (e.g. 'motion', 'all', or 'move,requestMotion,stop')",
    )
    parser.add_argument("--include-faces", action="store_true", help="Include faceExpression actions in default view")
    parser.add_argument("--since", default=None, help="ISO-8601 timestamp or Unix epoch seconds")
    parser.add_argument("--id", dest="episode_id", default=None, help="Inspect a single episode/job ID with step detail")
    parser.add_argument("--compact", action="store_true", help="Emit single-line JSON without indentation")
    args = parser.parse_args(argv)

    types_list = [t for t in args.types.split(",") if t.strip()] if args.types else None
    payload = read_recent_episodes(
        args.data_dir,
        limit=args.limit,
        robot_id=args.robot_id,
        types=types_list,
        include_faces=args.include_faces,
        since=args.since,
        episode_id=args.episode_id,
    )
    if args.compact:
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
