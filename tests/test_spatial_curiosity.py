from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
import unittest

from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
from gateway.plugins import CameraAnalysis
from gateway.perception import RecognitionResult, RecognizedObject
from gateway.spatial_curiosity import SpatialCuriosityTracker, normalize_heading_deg, sector_for_heading


def _yaw_quaternion(yaw_deg: float) -> list[float]:
    half = math.radians(yaw_deg) * 0.5
    return [math.cos(half), 0.0, 0.0, math.sin(half)]


class SpatialCuriosityUnitTests(unittest.TestCase):
    def test_sector_binning_wraps_across_360(self) -> None:
        self.assertEqual(sector_for_heading(0.0), 0)
        self.assertEqual(sector_for_heading(22.4), 0)
        self.assertEqual(sector_for_heading(-22.4), 0)
        self.assertEqual(sector_for_heading(22.6), 1)
        self.assertEqual(sector_for_heading(90.0), 2)
        self.assertEqual(sector_for_heading(180.0), 4)
        self.assertEqual(sector_for_heading(-45.0), 7)
        self.assertEqual(normalize_heading_deg(-15.0), 345.0)
        self.assertEqual(normalize_heading_deg(359.99), 0.0)

    def test_stationary_person_does_not_reset_human_inactivity_repeatedly(self) -> None:
        tracker = SpatialCuriosityTracker()
        robot = {"epoch": 1, "active_walk": None}
        yaw = {"available": True, "degrees": 0.0}

        tracker.snapshot("r1", robot, now=100.0, yaw_measurement=yaw)
        # Person enters view at t=100 -> resets human activity
        tracker.record_camera_observation(
            "r1",
            1,
            100.0,
            recognition={
                "objects": [
                    {
                        "label": "person",
                        "box": {"x": 0.4, "y": 0.2, "width": 0.2, "height": 0.5},
                        "identity": {"state": "face_match", "personId": "greg", "name": "Greg", "faceAgeMs": 0, "similarity": 0.9},
                    }
                ]
            },
        )
        snap1 = tracker.snapshot("r1", robot, now=100.0, yaw_measurement=yaw)
        assert snap1 is not None
        self.assertEqual(snap1["secondsSinceHumanActivity"], 0.0)

        # Same person still sitting quietly at t=750 (650s later) -> must NOT reset to 0!
        tracker.record_camera_observation(
            "r1",
            1,
            750.0,
            recognition={
                "objects": [
                    {
                        "label": "person",
                        "box": {"x": 0.41, "y": 0.2, "width": 0.2, "height": 0.5},
                        "identity": {"state": "tracked", "personId": "greg", "name": "Greg", "faceAgeMs": 500},
                    }
                ]
            },
        )
        snap2 = tracker.snapshot("r1", robot, now=750.0, yaw_measurement=yaw)
        assert snap2 is not None
        self.assertEqual(snap2["secondsSinceHumanActivity"], 650.0)

        # Voice utterance at t=760 -> resets to 0
        tracker.record_human_activity("r1", 760.0)
        snap3 = tracker.snapshot("r1", robot, now=765.0, yaw_measurement=yaw)
        assert snap3 is not None
        self.assertEqual(snap3["secondsSinceHumanActivity"], 5.0)

    def test_object_sector_projection_inspection_and_pickup_reset(self) -> None:
        tracker = SpatialCuriosityTracker()
        robot = {"epoch": 3, "active_walk": None}
        yaw = {"available": True, "degrees": 90.0}
        locomotion = {"position": {"available": True, "freeFloorMeters": 1.45}}

        tracker.snapshot("r1", robot, now=10.0, yaw_measurement=yaw, locomotion_measurement=locomotion)
        tracker.record_camera_observation(
            "r1",
            3,
            10.0,
            recognition={
                "objects": [
                    {"label": "backpack", "trackId": "obj-4", "box": {"x": 0.45, "y": 0.3, "width": 0.1, "height": 0.1}}
                ]
            },
            close_capture=False,
        )
        snap = tracker.snapshot("r1", robot, now=22.0, yaw_measurement=yaw, locomotion_measurement=locomotion)
        assert snap is not None
        self.assertEqual(snap["currentSector"], 2)
        self.assertEqual(snap["sectors"][2]["freeFloorMeters"], 1.45)
        self.assertEqual(snap["sectors"][2]["lastSeenSecAgo"], 12.0)
        self.assertIsNone(snap["sectors"][0]["lastSeenSecAgo"])
        self.assertEqual(len(snap["trackedObjects"]), 1)
        self.assertFalse(snap["trackedObjects"][0]["inspected"])

        # Explicit markInspected marks obj-4 inspected
        marked = tracker.mark_inspected("r1", ["obj-4"])
        self.assertEqual(marked, ["obj-4"])
        snap_inspected = tracker.snapshot("r1", robot, now=23.0, yaw_measurement=yaw)
        assert snap_inspected is not None
        self.assertTrue(snap_inspected["trackedObjects"][0]["inspected"])

        # Pickup / tipped reset clears sectors and trackedObjects while preserving human activity recency
        tracker.record_human_activity("r1", 20.0)
        tracker.reset_placement("r1", 3, 25.0)
        snap_reset = tracker.snapshot("r1", robot, now=30.0, yaw_measurement=yaw)
        assert snap_reset is not None
        self.assertEqual(snap_reset["trackedObjects"], [])
        self.assertIsNone(snap_reset["sectors"][2]["lastSeenSecAgo"])
        self.assertEqual(snap_reset["secondsSinceHumanActivity"], 10.0)


class AdapterSpatialCuriosityIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_environment_adapter_observation_emits_spatial_curiosity_and_resets_on_tipped(self) -> None:
        now_mono = 50.0
        now_utc = datetime(2026, 11, 13, 22, 0, 0, tzinfo=timezone.utc)

        class StubGateway:
            instance_id = "gw-curiosity"

            def __init__(self) -> None:
                self.events = []

            def clock(self) -> float:
                return now_mono

            def subscribe_events(self, cb):
                self.events.append(cb)

            def subscribe_external_speech(self, cb):
                pass

            def subscribe_frames(self, cb):
                pass

            def subscribe_transcripts(self, cb):
                pass

            def status(self):
                return {
                    "robots": {
                        "ainekio-p4": {
                            "connected": True,
                            "connection_state": "online",
                            "epoch": 2,
                            "model": "v2-12servo",
                            "features": ["locomotion_v1", "command_deadline_v1"],
                            "capabilities": {"speaker": True, "microphone": True},
                            "active_walk": None,
                            "status": {
                                "camera_ready": True,
                                "imu": {
                                    "available": True,
                                    "fresh": True,
                                    "frame": "body_nominal",
                                    "orientation_wxyz": _yaw_quaternion(45.0),
                                    "received_at": now_utc.isoformat(),
                                    "timestamp_us": 1000,
                                    "boot_id": "b1",
                                },
                            },
                        }
                    }
                }

        gw = StubGateway()
        adapter = EnvironmentAdapter(
            gw,  # type: ignore[arg-type]
            EnvironmentAdapterConfig(
                token="secret-token",
                session_id="ainekio-01",
                receipt_path=":memory:",
            ),
            clock=lambda: now_mono,
            utcnow=lambda: now_utc,
        )
        adapter._bridge_ready = True

        analysis = CameraAnalysis(
            robot_id="ainekio-p4",
            epoch=2,
            counter=10,
            received_at=now_mono,
            completed_at=now_mono,
            jpeg=b"\xff\xd8\xff\xd9",
            result=RecognitionResult(
                backend="yoloe",
                model="yoloe-v8",
                summary="mug on floor",
                objects=(RecognizedObject(label="mug", score=0.9, box=(0.4, 0.4, 0.2, 0.2), track_id="t-mug"),),
                uncertainties=(),
            ),
        )
        await adapter.publish_camera_analysis(analysis, max_frame_age_s=5.0)
        now_mono = 54.0

        obs = adapter._observation()
        sc = obs["state"]["spatialCuriosity"]
        self.assertEqual(sc["headingDeg"], 45.0)
        self.assertEqual(sc["currentSector"], 1)
        self.assertEqual(sc["sectors"][1]["lastSeenSecAgo"], 4.0)
        self.assertEqual(sc["sectors"][1]["objects"], ["mug"])
        self.assertEqual(sc["trackedObjects"][0]["trackId"], "t-mug")
        self.assertFalse(sc["trackedObjects"][0]["inspected"])

        # Mark inspected through _read_camera_visual
        sent: list[dict[str, object]] = []

        async def capture_send(payload, *, websocket=None):
            sent.append(payload)
            return True

        adapter._send = capture_send  # type: ignore[method-assign]
        await adapter._read_camera_visual(
            {"version": 1, "sessionId": "ainekio-01", "requestId": "req-1", "operation": "markInspected", "trackIds": ["t-mug"]}
        )
        self.assertEqual(sent[-1]["vision"]["markedTrackIds"], ["t-mug"])
        self.assertTrue(adapter._observation()["state"]["spatialCuriosity"]["trackedObjects"][0]["inspected"])

        # Tipped body_event resets sector novelty map
        import inspect

        event_payload = {
            "t": "event",
            "name": "body_event",
            "robot_id": "ainekio-p4",
            "epoch": 2,
            "event_id": "ev-1",
            "data": {"kind": "tipped"},
        }
        for cb in gw.events:
            res = cb(event_payload)
            if inspect.isawaitable(res):
                await res
        reset_sc = adapter._observation()["state"]["spatialCuriosity"]
        self.assertEqual(reset_sc["trackedObjects"], [])
        self.assertIsNone(reset_sc["sectors"][1]["lastSeenSecAgo"])


if __name__ == "__main__":
    unittest.main()
