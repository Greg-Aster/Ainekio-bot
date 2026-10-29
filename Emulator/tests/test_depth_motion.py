import asyncio
import base64
import json
import importlib.util
import math
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from gateway.depth_motion import settings, spatial_depth, worker_environment
from gateway.depth_motion_worker import Estimator, FeatureMap, camera_position, OPTICAL_TO_FORWARD
from gateway.dashboard.server import DashboardHttpServer
from gateway.plugins import CameraFramePlugin, _CameraInput


@unittest.skipUnless(importlib.util.find_spec("mujoco"), "Use the gait-training environment for optical simulation")
class SimulatedDepthTests(unittest.TestCase):
    def setUp(self):
        import mujoco
        from gateway.neural_gait.depth import DepthCamera
        self.mujoco = mujoco
        self.model = mujoco.MjModel.from_xml_string('''<mujoco><worldbody>
          <geom name="wall" type="box" pos="0 0 2.5" size="3 3 .5"/>
          <geom name="inactive" type="box" pos="0 0 1" size="3 3 .1" rgba="1 1 1 0"/>
          <body name="torso"><freejoint/><geom type="sphere" size=".2"/>
            <body pos="0 0 .6"><geom type="sphere" size=".3"/></body>
          </body></worldbody></mujoco>''')
        self.data = mujoco.MjData(self.model)
        mujoco.mj_forward(self.model,self.data)
        self.profile = dict(cameraMatrix=[[4,0,4],[0,4,4],[0,0,1]],imageSize=[8,8],
            cameraToBody=np.eye(4).tolist(),capture_hz=2.,latency_s=.2,
            dropout_probability=0.,noise_std_m=0.,provenance={"kind":"test fixture"})
        self.camera = DepthCamera(self.profile)
        self.rng = np.random.default_rng(4)

    def capture(self, time):
        self.data.time = time
        return self.camera.update(self.model,self.data,self.rng,robot_id="robot",epoch=2,gateway_instance="fixture")

    def test_actual_optical_z_rays_exclude_robot_and_preserve_capture_latency(self):
        from gateway.neural_gait.depth import project_depth
        self.assertFalse(self.capture(0)["frameCurrent"])
        self.assertFalse(self.capture(.1)["frameCurrent"])
        first = self.capture(.2)
        np.testing.assert_allclose(first["depthSpatial"]["values"],2.)
        self.assertEqual(first["receivedAtMonotonic"],0.)
        self.assertEqual(first["deliveryAtSimulationS"],.2)
        projected = project_depth(first,.2,"robot",2)
        self.assertTrue(projected["depth_available"])
        self.assertAlmostEqual(projected["age_s"],.2)
        self.assertFalse(first["available"], "Depth does not invent odometry")
        self.data.qpos[2] = .5
        self.mujoco.mj_forward(self.model,self.data)
        held = self.capture(.5)
        self.assertEqual(held["frameId"],first["frameId"])
        second = self.capture(.7)
        np.testing.assert_allclose(second["depthSpatial"]["values"],1.5)
        self.assertNotEqual(second["frameId"],first["frameId"])
        self.assertAlmostEqual(project_depth(second,.7,"robot",2)["age_s"],.2)
        self.assertFalse(project_depth(second,.7,"robot",3)["depth_available"])
        self.assertFalse(project_depth({**second,"frameCurrent":False},.7,"robot",2)["depth_available"])

    def test_dropout_missing_rays_and_seeded_noise_do_not_create_fake_ranges(self):
        from gateway.neural_gait.depth import DepthCamera, project_depth
        camera = DepthCamera({**self.profile,"latency_s":0,"dropout_probability":1.})
        missing = camera.update(self.model,self.data,self.rng,robot_id="robot",epoch=2,gateway_instance="fixture")
        self.assertEqual(missing["depthSpatial"]["valid"],[False]*64)
        self.assertFalse(project_depth(missing,0,"robot",2)["depth_available"])
        camera = DepthCamera({**self.profile,"latency_s":0})
        missing = camera.update(self.model,self.data,self.rng,robot_id="robot",epoch=2,gateway_instance="fixture",
            geom_mask=np.zeros(self.model.ngeom,dtype=bool))
        self.assertEqual(missing["depthSpatial"]["values"],[None]*64)
        profile = {**self.profile,"latency_s":0,"noise_std_m":.01,"dropout_probability":.2}
        one = DepthCamera(profile).update(self.model,self.data,np.random.default_rng(5),robot_id="r",epoch=1,gateway_instance="s")
        two = DepthCamera(profile).update(self.model,self.data,np.random.default_rng(5),robot_id="r",epoch=1,gateway_instance="s")
        self.assertEqual(one,two)
        self.assertNotEqual(one["depthSpatial"]["values"],[2.]*64)
        json.dumps(one,allow_nan=False)
        expiring = DepthCamera({**self.profile,"max_frame_age_s":.3})
        for now in (0,.2,.4):
            latest = expiring.update(self.model,self.data,self.rng,robot_id="r",epoch=1,
                gateway_instance="s",now_s=now)
        self.assertFalse(latest["frameCurrent"])
        self.assertAlmostEqual(project_depth(latest,.4,"r",1)["age_s"],.4)
        self.assertFalse(project_depth(latest,.4,"r",1)["depth_available"])

    def test_assumed_ray_pose_does_not_publish_unknown_physical_extrinsics(self):
        from gateway.neural_gait.depth import DepthCamera, project_depth
        from gateway.neural_gait.contract import spatial_features
        transform = np.eye(4)
        transform[2,3] = .25
        camera = DepthCamera({**self.profile,"latency_s":0,
            "cameraToBody":transform.tolist(),"publish_camera_to_body":False})
        measurement = camera.update(self.model,self.data,self.rng,
            robot_id="robot",epoch=2,gateway_instance="fixture")
        grid = measurement["depthSpatial"]
        np.testing.assert_allclose(grid["values"],1.75)
        self.assertIsNone(grid["cameraToBody"])
        self.assertEqual(grid["extrinsicsSource"],"unavailable")
        features = spatial_features(project_depth(measurement,0,"robot",2))
        self.assertEqual(features[-15:-3],[0.]*12)
        self.assertEqual(features[-3:],[1.,0.,0.])
        self.assertEqual(self.camera._encode()["cameraToBody"],np.eye(4).tolist())


class DepthGeometryTests(unittest.TestCase):
    def test_spatial_projection_uses_camera_freshness_identity_and_receipt_age(self):
        from gateway.neural_gait.depth import project_depth
        grid = spatial_depth(np.ones((8,8)),np.eye(3),units="estimated-metres",
            scale_source="learned-metric-estimate",intrinsics_source="model-estimated")
        measurement = dict(depthSpatial=grid,robotId="robot",epoch=2,frameCurrent=True,
            receivedAtMonotonic=10.,available=False)
        result = project_depth(measurement,10.2,"robot",2)
        self.assertTrue(result["depth_available"])
        self.assertAlmostEqual(result["age_s"],.2)
        self.assertEqual(result["depth_min_m"],1.)
        self.assertEqual(result["depthSpatial"]["units"],"estimated-metres")
        for changes in ({"robotId":"other"},{"epoch":3},{"frameCurrent":False},
                        {"receivedAtMonotonic":11.},{"receivedAtMonotonic":float("nan")},
                        {"receivedAtMonotonic":float("inf")},{"receivedAtMonotonic":None}):
            with self.subTest(changes=changes):
                self.assertFalse(project_depth({**measurement,**changes},10.2,"robot",2)["depth_available"])

    def test_spatial_grid_keeps_optical_depth_pixels_and_missing_readings(self):
        depth = np.arange(16*24, dtype=float).reshape(16,24)+1
        depth[1,1], depth[1,4], depth[1,7], depth[1,10] = np.nan, np.inf, 0, -1
        k = np.array([[30.,0,12],[0,31.,8],[0,0,1.]])
        grid = spatial_depth(depth, k, units="estimated-metres",
            scale_source="learned-metric-estimate", intrinsics_source="model-estimated")
        self.assertEqual((grid["rows"],grid["columns"],grid["imageSize"]),(8,8,[24,16]))
        self.assertEqual(grid["samplePixels"][:5], [[1,1],[4,1],[7,1],[10,1],[13,1]])
        self.assertEqual(grid["values"][:4], [None]*4)
        self.assertEqual(grid["valid"][:5], [False]*4+[True])
        self.assertEqual(grid["values"][4], depth[1,13])
        self.assertEqual(grid["values"][-1], depth[15,22])
        np.testing.assert_array_equal(grid["cameraMatrix"], k)
        self.assertIsNone(grid["cameraToBody"])
        self.assertFalse(grid["metricAccuracyVerified"])
        self.assertEqual(grid["depthKind"],"optical-axis-z")
        json.dumps(grid, allow_nan=False)
        missing = spatial_depth(np.zeros((16,24)), k, units="metres",
            scale_source="simulation-geometry", intrinsics_source="explicit-simulation-config")
        self.assertFalse(missing["available"])
        self.assertEqual(missing["values"], [None]*64)

    def test_depth_grid_survives_odometry_failure_with_existing_frame_identity(self):
        import cv2
        estimator = object.__new__(Estimator)
        estimator.states, estimator.optics, estimator.model_id = {}, {}, "test-model"
        k = np.array([[150.,0,80],[0,150.,60],[0,0,1.]])
        estimator.depth = Mock(return_value=(np.full((120,160),2.,np.float32),k))
        jpeg = cv2.imencode('.jpg',np.ones((120,160,3),np.uint8)*100)[1].tobytes()
        request = dict(robot="robot",instance="gateway",epoch=7,counter=42,received=123.,
            timestamp="2026-10-28T10:00:00+00:00", jpeg=base64.b64encode(jpeg).decode(),
            config=settings({"mode":"moge-open3d","cameraToBody":OPTICAL_TO_FORWARD.tolist()}))
        with patch.object(FeatureMap,"process",side_effect=ValueError("tracking lost")):
            result = estimator.process(request)
        self.assertFalse(result["available"], "Odometry remains unavailable")
        self.assertTrue(result["depthSpatial"]["available"], "Independent depth pixels remain observations")
        self.assertEqual(result["depthSpatial"]["values"], [2.]*64)
        self.assertEqual(result["depthSpatial"]["cameraToBody"],OPTICAL_TO_FORWARD.tolist())
        self.assertEqual(result["depthSpatial"]["extrinsicsSource"],"configured-transform")
        self.assertFalse(result["depthSpatial"]["metricAccuracyVerified"])
        self.assertEqual(result["frameCounter"],42)
        self.assertEqual(result["epoch"],7)
        self.assertEqual(result["frameId"],"ainekio-camera-gateway-robot-7-42")
        self.assertEqual(result["receivedAtMonotonic"],123.)
        self.assertEqual(result["observedAt"],request["timestamp"])

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


    async def held_depth(self, *, fail_first=False):
        entered, release = asyncio.Event(), threading.Event()
        self.addCleanup(release.set)
        loop = asyncio.get_running_loop()
        calls = 0
        def process(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(10):
                    raise AssertionError("Test did not release depth inference")
                if fail_first:
                    raise ValueError("Old depth generation failed")
            return {"available": True, "robotId": "robot", "epoch": 1,
                "receivedAtMonotonic": 10., "referenceId": f"reference-{calls}"}
        depth = Mock(process=Mock(side_effect=process))
        self.camera._depth_motion = depth
        self.camera._depth_settings["robot"] = settings({"mode": "moge-open3d"})
        self.camera._metric_frames["robot"] = (_CameraInput("robot", 1, 1, 10., b"jpg"),
            "2026-10-22T00:00:00+00:00")
        result = await self.camera.depth_demand("robot", "recorder", True, wait_for_measurement=False)
        self.assertFalse(result["measurement"]["available"])
        await asyncio.wait_for(entered.wait(), 1)
        return depth, release

    async def test_cancelled_release_still_unloads_after_inflight_inference(self):
        depth, finish_inference = await self.held_depth()
        release = asyncio.create_task(self.camera.depth_demand("robot", "recorder", False))
        await asyncio.sleep(0)
        self.assertFalse(self.camera._metric_consumers)
        self.assertFalse(release.done())
        release.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await release
        depth.close.assert_not_called()
        finish_inference.set()
        await self.camera._metric_queue.join()
        await asyncio.get_running_loop().run_in_executor(self.camera._metric_executor, lambda: None)
        depth.close.assert_called_once()
        self.assertIsNone(self.camera._depth_motion)
        self.assertNotIn("robot", self.camera._metric_latest)

    async def test_old_failed_inference_does_not_resolve_new_navigation_read(self):
        depth, finish_inference = await self.held_depth(fail_first=True)
        await self.camera.depth_demand("robot", "recorder", False, wait_for_measurement=False)
        navigation = asyncio.create_task(self.camera.depth_demand("robot", "navigation", True))
        await asyncio.sleep(0)
        self.assertIn("robot", self.camera._metric_ready)
        with self.assertLogs("gateway.plugins", level="WARNING"):
            finish_inference.set()
            result = await asyncio.wait_for(navigation, 1)
        self.assertTrue(result["measurement"]["available"])
        self.assertEqual(result["measurement"]["referenceId"], "reference-2")
        depth.reset.assert_called_once_with("robot")
        depth.close.assert_not_called()
        self.assertEqual(self.camera._metric_consumers, {"navigation": "robot"})
        await self.camera.depth_demand("robot", "navigation", False)
        depth.close.assert_called_once()

    async def test_passive_release_reports_cleanup_failure(self):
        self.camera._metric_consumers["recorder"] = "robot"
        depth = self.camera._depth_motion = Mock()
        depth.close.side_effect = RuntimeError("Depth unload failed")
        try:
            with self.assertLogs("gateway.plugins", level="ERROR") as observed:
                result = await self.camera.depth_demand("robot", "recorder", False, wait_for_measurement=False)
                await asyncio.get_running_loop().run_in_executor(self.camera._metric_executor, lambda: None)
            self.assertEqual(result, {"enabled": False})
            self.assertFalse(self.camera._metric_consumers)
            self.assertIn("Depth unload failed", observed.output[0])
        finally:
            depth.close.side_effect = None


if __name__ == "__main__":
    unittest.main()
