import asyncio
import base64
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from gateway.depth_motion import settings, worker_environment
from gateway.depth_motion_worker import Estimator, FeatureMap, camera_position, OPTICAL_TO_FORWARD
from gateway.dashboard.server import DashboardHttpServer
from gateway.plugins import CameraFramePlugin, _CameraInput


class DepthGeometryTests(unittest.TestCase):
    def test_cpu_recognition_cannot_hide_depth_gpu_allocation(self):
        with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": ""}, clear=True):
            with patch("gateway.depth_motion._LAUNCH_CUDA_VISIBLE_DEVICES", None):
                self.assertNotIn("CUDA_VISIBLE_DEVICES", worker_environment())
            with patch("gateway.depth_motion._LAUNCH_CUDA_VISIBLE_DEVICES", "2"):
                self.assertEqual(worker_environment()["CUDA_VISIBLE_DEVICES"], "2")
                os.environ["AINEKIO_DEPTH_CUDA_VISIBLE_DEVICES"] = "1"
                self.assertEqual(worker_environment()["CUDA_VISIBLE_DEVICES"], "1")
            self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "")

    def test_forward_backward_and_turn_signs(self):
        for forward in (.3, -.3):
            # Static world points move toward the camera when it advances.
            world_points_to_current = np.eye(4)
            world_points_to_current[2, 3] = -forward
            p = camera_position(np.linalg.inv(world_points_to_current))
            self.assertAlmostEqual(p["xMetres"], forward)
            self.assertAlmostEqual(p["yMetres"], 0)
        for angle in (.2, -.2):
            body = np.eye(4)
            body[:2, :2] = [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]]
            camera = np.linalg.inv(OPTICAL_TO_FORWARD) @ body @ OPTICAL_TO_FORWARD
            p = camera_position(camera)
            self.assertAlmostEqual(p["headingDegrees"], math.degrees(angle))

    def test_measured_lever_arm_does_not_turn_into_false_body_travel(self):
        mounting = OPTICAL_TO_FORWARD.copy()
        mounting[:3, 3] = [.08, .02, .04]
        body = np.eye(4)
        body[:2, :2] = [[0, -1], [1, 0]]
        camera = np.linalg.inv(mounting) @ body @ mounting
        p = camera_position(camera, mounting)
        np.testing.assert_allclose([p["xMetres"], p["yMetres"], p["zMetres"]], 0, atol=1e-10)
        self.assertAlmostEqual(p["headingDegrees"], 90)
        self.assertNotAlmostEqual(camera_position(camera)["xMetres"], 0)

    def test_settings_preserve_optional_measured_transform(self):
        self.assertEqual(settings({})["mode"], "ground-plane")
        self.assertIsNone(settings({"mode": "moge-open3d"})["cameraToBody"])
        self.assertEqual(settings({"cameraToBody": OPTICAL_TO_FORWARD.tolist()})["cameraToBody"],
                         OPTICAL_TO_FORWARD.tolist())
        for invalid in ({"mode": "automatic-fallback"}, {"resolution_level": 10},
                        {"cameraToBody": np.zeros((4, 4)).tolist()}):
            with self.assertRaises(ValueError):
                settings(invalid)

    def test_landmarks_track_translation_despite_changing_predicted_depth(self):
        import cv2
        rng = np.random.default_rng(4)
        texture = cv2.GaussianBlur(rng.integers(0, 256, (240, 320, 3), dtype=np.uint8), (3, 3), 0)
        k = np.array([[300., 0, 160], [0, 300, 120], [0, 0, 1]])
        tracker = FeatureMap()
        for shift, scale in ((0,1.), (0,1.7), (6,.6), (12,2.)):
            target = cv2.warpAffine(texture, np.array([[1., 0, -shift], [0, 1, 0]]), (320, 240))
            pose, quality = tracker.process(target, np.full((240,320),scale,np.float32), k)
            position = camera_position(pose)
            self.assertAlmostEqual(position["yMetres"], -shift/300., delta=.001)
            self.assertAlmostEqual(position["xMetres"], 0., delta=.001)
            self.assertAlmostEqual(position["headingDegrees"], 0., delta=.1)

    def test_featureless_frame_cannot_report_zero_motion(self):
        with self.assertRaisesRegex(ValueError, "Insufficient image features"):
            FeatureMap().process(np.zeros((120,160,3),np.uint8), np.ones((120,160)), np.eye(3))

    def test_reconnection_resets_position_but_preserves_unchanged_optics(self):
        import cv2
        estimator = object.__new__(Estimator)
        estimator.states, estimator.optics, estimator.model_id = {}, {}, "test-model"
        k = np.array([[150.,0,80],[0,150,60],[0,0,1.]])
        estimator.depth = Mock(return_value=(np.ones((120,160),np.float32),k))
        jpeg=cv2.imencode('.jpg',np.ones((120,160,3),np.uint8)*100)[1].tobytes()
        request=dict(robot="robot",instance="gateway",epoch=1,counter=1,received=1.,timestamp="now",
                     jpeg=base64.b64encode(jpeg).decode(),config=settings({"mode":"moge-open3d"}))
        with patch.object(FeatureMap,"process",return_value=(np.eye(4),{})):
            first=estimator.process(request)
            resumed=estimator.process({**request,"epoch":2})
            np.testing.assert_array_equal(estimator.depth.call_args.args[2],k)
            self.assertNotEqual(first["referenceId"],resumed["referenceId"])
            self.assertEqual(first["calibrationId"],resumed["calibrationId"])
            estimator.process({**request,"epoch":3,"config":settings({"mode":"moge-open3d","resolution_level":1})})
            self.assertIsNone(estimator.depth.call_args.args[2])
            # The preview returns after a still frame/source-mode change.
            estimator.depth.return_value=(np.ones((120,160),np.float32),k*2)
            returned=estimator.process({**request,"epoch":3})
            np.testing.assert_array_equal(estimator.depth.call_args.args[2],k)
            self.assertEqual(first["calibrationId"],returned["calibrationId"])
            estimator.states.pop("robot")  # Reference reset retains optics.
            reset=estimator.process({**request,"epoch":4})
            self.assertEqual(first["calibrationId"],reset["calibrationId"])

    def test_lost_tracking_references_next_image_without_fabricating_gap_distance(self):
        import cv2
        estimator = object.__new__(Estimator)
        estimator.states, estimator.optics, estimator.model_id = {}, {}, "test-model"
        k = np.array([[150.,0,80],[0,150,60],[0,0,1.]])
        estimator.depth = Mock(return_value=(np.ones((120,160),np.float32),k))
        jpeg = cv2.imencode('.jpg',np.ones((120,160,3),np.uint8)*100)[1].tobytes()
        request = dict(robot="robot",instance="gateway",epoch=1,counter=1,received=1.,timestamp="now",
                       jpeg=base64.b64encode(jpeg).decode(),config=settings({"mode":"moge-open3d"}))
        quality = dict(matches=30, inliers=28, reprojectionPixels=.4)
        pose=np.eye(4);pose[2,3]=.02
        fits=[(np.eye(4),quality), ValueError("Camera landmark pose fit failed"),
              (np.eye(4),quality), (pose,quality)]
        with patch.object(FeatureMap,"process",side_effect=fits):
            first = estimator.process(request)
            lost = estimator.process({**request,"counter":2})
            resumed=estimator.process({**request,"counter":3})
        self.assertFalse(lost["available"])
        self.assertIsNone(lost["position"])
        self.assertNotEqual(lost["referenceId"],first["referenceId"])
        self.assertEqual(lost["calibrationId"],first["calibrationId"])
        self.assertTrue(resumed["available"])
        self.assertEqual(resumed["referenceId"],lost["referenceId"])
        self.assertEqual(resumed["calibrationId"],first["calibrationId"])
        self.assertAlmostEqual(resumed["position"]["xMetres"],.02)


class DepthIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.gateway = SimpleNamespace(instance_id="test", subscribe_frames=Mock(),
            unsubscribe_frames=Mock(), clock=lambda: 10.,
            status=lambda: {"robots": {"robot": {"epoch": 1, "connection_state": "online"}}},
            _publish_event=AsyncMock())
        self.camera = CameraFramePlugin(self.gateway, None)
        self.addAsyncCleanup(self.camera.aclose)

    async def test_explicit_source_selection_and_model_release_without_commands(self):
        ground = Mock()
        ground.process.return_value = {"source": "ground"}
        self.camera._ground_plane = ground
        frame = _CameraInput("robot", 1, 1, 10., b"jpg")
        self.assertEqual(self.camera._process_metric(frame, "stamp"), {"source": "ground"})
        depth = Mock()
        depth.process.return_value = {"source": "depth"}
        self.camera._depth_motion = depth
        self.camera._metric_consumers["navigation"] = "robot"
        await self.camera.configure_depth("robot", {"mode": "moge-open3d"})
        self.assertEqual(self.camera._process_metric(frame, "stamp"), {"source": "depth"})
        self.assertEqual(ground.process.call_count, 1)
        await self.camera.configure_depth("other", {"mode": "moge-open3d"})
        self.camera._metric_consumers["other-navigation"] = "other"
        await self.camera.configure_depth("robot", {"mode": "ground-plane"})
        depth.close.assert_not_called()  # Other robot still uses the model.
        await self.camera.configure_depth("other", {"mode": "ground-plane"})
        depth.close.assert_called_once()
        self.assertIsNone(self.camera._depth_motion)

    async def test_depth_errors_are_reported_not_replaced_by_other_source(self):
        self.camera._metric_consumers["navigation"] = "robot"
        self.camera._depth_settings["robot"] = settings({"mode": "moge-open3d"})
        self.camera._depth_motion = Mock()
        self.camera._depth_motion.process.side_effect = ValueError("No image correspondences")
        self.camera._ground_plane = Mock()
        self.camera._metric_queue.put_nowait((_CameraInput("robot", 1, 1, 10., b"jpg"),
                                               "2026-10-20T00:00:00+00:00"))
        self.camera._metric_worker = asyncio.create_task(self.camera._run_metrics())
        await self.camera._metric_queue.join()
        self.camera._ground_plane.process.assert_not_called()
        m = self.camera.locomotion_measurement("robot")
        self.assertFalse(m["available"])
        # Original diagnostic must remain visible to the operator.
        self.assertEqual(self.camera._metric_latest["robot"]["reason"], "No image correspondences")

    async def test_save_depth_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as root:
            server = object.__new__(DashboardHttpServer)
            server.control_settings_path = Path(root)/"settings.json"
            server.control_settings = {"recognition": False, "cameras": {"other": {"on": True}}}
            server.camera_recognition = self.camera
            await server.depth_motion("robot", {"mode": "moge-open3d"})
            saved = json.loads(server.control_settings_path.read_text())
            self.assertEqual(saved["cameras"], {"other": {"on": True}})
            self.assertFalse(saved["recognition"])
            self.assertEqual(saved["depth_motion"]["robot"]["mode"], "moge-open3d")

    async def test_receipt_time_stays_original_and_preview_is_not_logged_in_events(self):
        self.camera._metric_consumers["navigation"] = "robot"
        self.camera._process_metric = Mock(return_value={
            "available": True, "robotId": "robot", "epoch": 1, "receivedAtMonotonic": 10.,
            "scaleSource": "learned-metric-estimate", "depthPreview": "png"})
        self.camera._metric_queue.put_nowait((_CameraInput("robot", 1, 1, 10., b"jpg"),
                                               "2026-10-20T00:00:00+00:00"))
        self.camera._metric_worker = asyncio.create_task(self.camera._run_metrics())
        await self.camera._metric_queue.join()
        event = self.gateway._publish_event.await_args.args[0]["measurement"]
        self.assertNotIn("depthPreview", event)
        self.assertEqual(event["receivedAtMonotonic"], 10.)
        self.assertEqual(event["scaleSource"], "learned-metric-estimate")
        self.assertEqual(self.camera.locomotion_measurement("robot")["depthPreview"], "png")
        self.gateway.clock = lambda: 12.
        self.assertFalse(self.camera.locomotion_measurement("robot")["available"])

    async def test_idle_camera_does_not_process_depth_and_consumers_share_one_lifetime(self):
        from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE
        self.camera._depth_settings["robot"] = settings({"mode": "moge-open3d"})
        self.camera._process_metric = Mock(return_value={"available": True, "robotId": "robot", "epoch": 1,
            "receivedAtMonotonic": 10., "source": "fixture", "observedAt": "2026-10-22T00:00:00+00:00"})
        frame = {"frame_type": CAMERA_JPEG_FRAME_TYPE, "robot_id": "robot", "epoch": 1,
            "counter": 1, "received_at": 10., "payload": b"jpg"}
        await self.camera._handle_frame(frame)
        self.camera._process_metric.assert_not_called()
        self.assertIsNone(self.camera._metric_worker)
        self.assertTrue(self.camera.camera_measurement("robot")["available"])
        depth = Mock()
        self.camera._depth_motion = depth
        first = await self.camera.depth_demand("robot", "task-a", True)
        self.assertTrue(first["measurement"]["available"])
        await self.camera.depth_demand("robot", "task-b", True)
        self.assertEqual(self.camera._process_metric.call_count, 1)
        await self.camera.depth_demand("robot", "task-a", False)
        depth.close.assert_not_called()
        await self.camera.depth_demand("robot", "task-b", False)
        depth.close.assert_called_once()
        self.assertIsNone(self.camera._depth_motion)
        self.assertFalse(self.camera.locomotion_measurement("robot")["available"])
        await self.camera._handle_frame({**frame, "counter": 2})
        self.assertEqual(self.camera._process_metric.call_count, 1)
        await self.camera.depth_demand("robot", "task-c", True)
        self.assertEqual(self.camera._process_metric.call_count, 2, "new demand starts a fresh measurement")
        await self.camera.depth_demand("robot", "task-c", False)

    async def test_dashboard_sample_releases_its_consumer_even_if_measurement_fails(self):
        server = object.__new__(DashboardHttpServer)
        server.camera_recognition = SimpleNamespace(depth_demand=AsyncMock(side_effect=[ValueError("measurement failed"), {"enabled": False}]))
        with self.assertRaisesRegex(ValueError, "measurement failed"):
            await server.depth_motion("robot", {"operation": "sample"})
        calls = server.camera_recognition.depth_demand.await_args_list
        self.assertEqual(calls[0].args[1], calls[1].args[1])
        self.assertEqual([call.args[2] for call in calls], [True, False])

    async def test_body_disconnect_during_first_measurement_finishes_the_read(self):
        self.camera._metric_frames["robot"] = (_CameraInput("robot", 1, 1, 10., b"jpg"),
            "2026-10-22T00:00:00+00:00")
        def process(*args):
            self.gateway.status = lambda: {"robots": {}}
            return {"available": True, "robotId": "robot", "epoch": 1}
        self.camera._process_metric = process
        result = await self.camera.depth_demand("robot", "navigation", True)
        self.assertFalse(result["measurement"]["available"])
        self.assertIn("disconnected", result["measurement"]["reason"])
        self.assertNotIn("robot", self.camera._metric_ready)
        self.assertNotIn("robot", self.camera._metric_latest)
        await self.camera.depth_demand("robot", "navigation", False)


if __name__ == "__main__":
    unittest.main()
