"""Attributed 8-sector spatial curiosity state for Body Control observations.

Tracks observed IMU yaw sectors (8 x 45 deg), recognized objects with inspection
state, measured GroundPlane/depth floor clearance when available, stationary
duration, and human-activity recency (utterances and person-presence transitions).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

SECTOR_COUNT = 8
SECTOR_WIDTH_DEG = 45.0
CAMERA_HFOV_DEG = 65.0
MAX_SECTOR_OBJECTS = 8
MAX_TRACKED_OBJECTS = 24


def normalize_heading_deg(degrees: float) -> float:
    wrapped = float(degrees) % 360.0
    if wrapped >= 359.95:
        return 0.0
    return round(wrapped, 1)


def sector_for_heading(degrees: float) -> int:
    wrapped = float(degrees) % 360.0
    return int(((wrapped + (SECTOR_WIDTH_DEG / 2.0)) % 360.0) // SECTOR_WIDTH_DEG) % SECTOR_COUNT


@dataclass
class _SectorRecord:
    sector: int
    center_deg: int
    last_seen_at: float | None = None
    free_floor_meters: float | None = None
    objects: list[str] = field(default_factory=list)


@dataclass
class _TrackedObjectRecord:
    track_id: str
    label: str
    sector: int
    inspected: bool
    last_seen_at: float


@dataclass
class _RobotSpatialRecord:
    epoch: int | None = None
    heading_deg: float | None = None
    current_sector: int | None = None
    last_motion_at: float = 0.0
    last_human_activity_at: float | None = None
    person_present: bool = False
    person_ids: frozenset[str] = field(default_factory=frozenset)
    sectors: list[_SectorRecord] = field(
        default_factory=lambda: [
            _SectorRecord(sector=i, center_deg=i * 45) for i in range(SECTOR_COUNT)
        ]
    )
    tracked_objects: dict[str, _TrackedObjectRecord] = field(default_factory=dict)

    def reset_spatial(self, epoch: int | None, now: float) -> None:
        self.epoch = epoch
        self.heading_deg = None
        self.current_sector = None
        self.last_motion_at = now
        self.sectors = [_SectorRecord(sector=i, center_deg=i * 45) for i in range(SECTOR_COUNT)]
        self.tracked_objects.clear()


class SpatialCuriosityTracker:
    """Maintains per-robot spatial sector memory without inventing unmeasured geometry."""

    def __init__(self) -> None:
        self._robots: dict[str, _RobotSpatialRecord] = {}

    def _record(self, robot_id: str, epoch: int | None, now: float) -> _RobotSpatialRecord:
        record = self._robots.get(robot_id)
        if record is None:
            record = _RobotSpatialRecord(epoch=epoch, last_motion_at=now)
            self._robots[robot_id] = record
        elif epoch is not None and record.epoch is not None and record.epoch != epoch:
            record.reset_spatial(epoch, now)
        elif epoch is not None and record.epoch is None:
            record.epoch = epoch
        return record

    def reset_placement(self, robot_id: str, epoch: int | None, now: float) -> None:
        record = self._robots.get(robot_id)
        if record is None:
            self._robots[robot_id] = _RobotSpatialRecord(epoch=epoch, last_motion_at=now)
            return
        record.reset_spatial(epoch, now)

    def record_human_activity(self, robot_id: str | None, now: float) -> None:
        if not robot_id:
            for record in self._robots.values():
                record.last_human_activity_at = now
            return
        record = self._record(robot_id, None, now)
        record.last_human_activity_at = now

    def record_motion(self, robot_id: str | None, epoch: int | None, now: float) -> None:
        if not robot_id:
            return
        record = self._record(robot_id, epoch, now)
        record.last_motion_at = now

    def mark_inspected(self, robot_id: str | None, track_ids: list[str]) -> list[str]:
        if not robot_id:
            return []
        record = self._robots.get(robot_id)
        if record is None:
            return []
        marked: list[str] = []
        for raw in track_ids:
            if not isinstance(raw, str):
                continue
            tid = raw.strip()
            target = record.tracked_objects.get(tid)
            if target is not None:
                target.inspected = True
                marked.append(tid)
        return marked

    def record_camera_observation(
        self,
        robot_id: str | None,
        epoch: int | None,
        now: float,
        *,
        recognition: Mapping[str, object] | None = None,
        close_capture: bool = False,
    ) -> None:
        if not robot_id:
            return
        record = self._record(robot_id, epoch, now)
        base_heading = record.heading_deg
        current_sector = record.current_sector
        if current_sector is not None:
            record.sectors[current_sector].last_seen_at = now

        objects = recognition.get("objects") if isinstance(recognition, Mapping) else None
        if not isinstance(objects, list):
            return

        person_now = False
        seen_person_ids: set[str] = set()
        sector_labels: dict[int, list[str]] = {}
        seen_track_ids: set[str] = set()

        for item in objects:
            if not isinstance(item, Mapping):
                continue
            label = item.get("label")
            if not isinstance(label, str) or not label.strip():
                continue
            label = label.strip()
            lowered_label = label.lower()
            if lowered_label in {"unknown", "none", "null", "undefined", "n/a"} or lowered_label.startswith(
                ("unknown_", "unknown-", "unknown ")
            ):
                continue
            score = item.get("score")
            if label != "person" and isinstance(score, (int, float)) and math.isfinite(score) and float(score) < 0.50:
                continue
            box = item.get("box") if isinstance(item.get("box"), Mapping) else None
            cx = 0.5
            area = 0.0
            if box is not None:
                bx = box.get("x")
                bw = box.get("width")
                bh = box.get("height")
                if all(isinstance(v, (int, float)) and math.isfinite(v) for v in (bx, bw, bh)):
                    cx = float(bx) + float(bw) * 0.5
                    area = float(bw) * float(bh)
            if base_heading is not None:
                bearing_deg = base_heading - (cx - 0.5) * CAMERA_HFOV_DEG
                # Note: IMU yaw positive is CCW (left); image x=0 is left, x=1 is right.
                obj_sector = sector_for_heading(bearing_deg)
            elif current_sector is not None:
                obj_sector = current_sector
            else:
                obj_sector = 0

            if label == "person":
                person_now = True
                identity = item.get("identity")
                if isinstance(identity, Mapping) and isinstance(identity.get("personId"), str):
                    seen_person_ids.add(identity["personId"])
            else:
                labels = sector_labels.setdefault(obj_sector, [])
                if label not in labels and len(labels) < MAX_SECTOR_OBJECTS:
                    labels.append(label)

            raw_track = item.get("trackId")
            track_id = (
                raw_track.strip()
                if isinstance(raw_track, str) and raw_track.strip()
                else f"{label}@s{obj_sector}"
            )
            if label != "person":
                seen_track_ids.add(track_id)
                auto_inspected = bool(
                    close_capture and area >= 0.08 and 0.2 <= cx <= 0.8
                )
                existing = record.tracked_objects.get(track_id)
                record.tracked_objects[track_id] = _TrackedObjectRecord(
                    track_id=track_id,
                    label=label,
                    sector=obj_sector,
                    inspected=bool((existing and existing.inspected) or auto_inspected),
                    last_seen_at=now,
                )

        if current_sector is not None:
            record.sectors[current_sector].objects = list(sector_labels.get(current_sector, []))
            for tid in [
                key
                for key, entry in record.tracked_objects.items()
                if entry.sector == current_sector and key not in seen_track_ids
            ]:
                del record.tracked_objects[tid]

        for sec_idx, labels in sector_labels.items():
            sector_entry = record.sectors[sec_idx]
            sector_entry.last_seen_at = now
            if sec_idx == current_sector:
                sector_entry.objects = list(labels)
            else:
                merged = list(labels)
                for prev in sector_entry.objects:
                    if prev not in merged and len(merged) < MAX_SECTOR_OBJECTS:
                        merged.append(prev)
                sector_entry.objects = merged

        if len(record.tracked_objects) > MAX_TRACKED_OBJECTS:
            ordered = sorted(
                record.tracked_objects.values(),
                key=lambda entry: entry.last_seen_at,
                reverse=True,
            )[:MAX_TRACKED_OBJECTS]
            record.tracked_objects = {entry.track_id: entry for entry in ordered}

        frozen_ids = frozenset(seen_person_ids)
        if person_now != record.person_present or (frozen_ids and frozen_ids != record.person_ids):
            record.last_human_activity_at = now
        record.person_present = person_now
        if person_now:
            record.person_ids = frozen_ids
        else:
            record.person_ids = frozenset()

    def snapshot(
        self,
        robot_id: str | None,
        robot: Mapping[str, object] | None,
        *,
        now: float,
        yaw_measurement: Mapping[str, object] | None = None,
        locomotion_measurement: Mapping[str, object] | None = None,
        freestyle_status: Mapping[str, object] | None = None,
    ) -> dict[str, object] | None:
        if not robot_id or robot is None:
            return None
        epoch = robot.get("epoch") if isinstance(robot.get("epoch"), int) else None
        record = self._record(robot_id, epoch, now)

        if (
            isinstance(yaw_measurement, Mapping)
            and yaw_measurement.get("available") is True
            and isinstance(yaw_measurement.get("degrees"), (int, float))
            and math.isfinite(float(yaw_measurement["degrees"]))
        ):
            record.heading_deg = normalize_heading_deg(float(yaw_measurement["degrees"]))
            record.current_sector = sector_for_heading(record.heading_deg)
        else:
            record.heading_deg = None
            record.current_sector = None

        active_walk = robot.get("active_walk")
        freestyle_running = (
            isinstance(freestyle_status, Mapping)
            and freestyle_status.get("active") is True
        )
        if active_walk or freestyle_running:
            record.last_motion_at = now

        if record.current_sector is not None and isinstance(locomotion_measurement, Mapping):
            floor_dist = _extract_free_floor_meters(locomotion_measurement)
            if floor_dist is not None:
                record.sectors[record.current_sector].free_floor_meters = floor_dist

        seconds_stationary = round(max(0.0, now - record.last_motion_at), 1)
        seconds_since_human = (
            round(max(0.0, now - record.last_human_activity_at), 1)
            if record.last_human_activity_at is not None
            else None
        )

        tracked = [
            {
                "trackId": item.track_id,
                "label": item.label,
                "sector": item.sector,
                "inspected": item.inspected,
                "lastSeenSecAgo": round(max(0.0, now - item.last_seen_at), 1),
            }
            for item in sorted(
                record.tracked_objects.values(),
                key=lambda entry: (entry.inspected, -entry.last_seen_at, entry.track_id),
            )
        ]

        return {
            "headingDeg": record.heading_deg,
            "currentSector": record.current_sector,
            "secondsStationary": seconds_stationary,
            "secondsSinceHumanActivity": seconds_since_human,
            "sectors": [
                {
                    "sector": sec.sector,
                    "centerDeg": sec.center_deg,
                    "lastSeenSecAgo": (
                        round(max(0.0, now - sec.last_seen_at), 1)
                        if sec.last_seen_at is not None
                        else None
                    ),
                    "freeFloorMeters": sec.free_floor_meters,
                    "objects": list(sec.objects),
                }
                for sec in record.sectors
            ],
            "trackedObjects": tracked,
        }


def _extract_free_floor_meters(locomotion_measurement: Mapping[str, object]) -> float | None:
    position = locomotion_measurement.get("position")
    if isinstance(position, Mapping):
        if position.get("available") is True:
            for key in ("freeFloorMeters", "forwardClearanceMeters", "maxGroundRangeMeters"):
                val = position.get(key)
                if isinstance(val, (int, float)) and math.isfinite(float(val)) and float(val) >= 0:
                    return round(float(val), 2)
        if position.get("reason") != "measurement_session_changed":
            depth_spatial = position.get("depthSpatial")
            if (
                isinstance(depth_spatial, Mapping)
                and depth_spatial.get("available") is True
                and depth_spatial.get("schema") == "ainekio-depth-grid-v1"
                and depth_spatial.get("rows") == 8
                and depth_spatial.get("columns") == 8
            ):
                values = depth_spatial.get("values")
                valid = depth_spatial.get("valid")
                if isinstance(values, list) and isinstance(valid, list) and len(values) >= 64 and len(valid) >= 64:
                    samples: list[float] = []
                    for row in (3, 4, 5, 6):
                        for col in (2, 3, 4, 5):
                            idx = row * 8 + col
                            val = values[idx]
                            if valid[idx] is True and isinstance(val, (int, float)) and math.isfinite(float(val)) and float(val) > 0:
                                samples.append(float(val))
                    if samples:
                        samples.sort()
                        mid = len(samples) // 2
                        median = samples[mid] if len(samples) % 2 == 1 else (samples[mid - 1] + samples[mid]) * 0.5
                        return round(median, 2)
    target = locomotion_measurement.get("target")
    if isinstance(target, Mapping) and target.get("available") is True:
        val = target.get("distanceMeters", target.get("rangeMeters"))
        if isinstance(val, (int, float)) and math.isfinite(float(val)) and float(val) >= 0:
            return round(float(val), 2)
    return None
