import asyncio
import base64
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from gateway.ground_plane import GroundPlane, pose_from_plane, rigid
from gateway.dashboard.server import DashboardHttpServer


class GroundPlaneTests(unittest.TestCase):
    def setUp(self):
        self.owner = GroundPlane('gateway-test')
        self.k = np.array([[600., 0, 320], [0, 600, 240], [0, 0, 1]])
        self.points = np.zeros((30, 3)); self.points[:, :2] = np.mgrid[:6, :5].T.reshape(-1, 2) * .04
        self.initial = np.eye(4)
        self.initial[:3, :3] = cv2.Rodrigues(np.array([.35, -.15, .05]))[0]
        self.initial[:3, 3] = [-.1, -.08, .65]
        self.c = {'id': 'calibration', 'robotId': 'robot', 'cameraMatrix': self.k.tolist(), 'distortion': [0.] * 5,
                  'cameraToBody': [[0, 0, 1, .08], [-1, 0, 0, .02], [0, -1, 0, .1], [0, 0, 0, 1]],
                  'imageSize': [640, 480], 'geometryId': 'fixed-optics', 'reprojectionPixels': .00001}
        self.owner.restore({'robot': self.c})
        self.identity = {'robotId': 'robot', 'epoch': 1, 'frameId': 'frame0', 'observedAt': '2026-01-01T00:00:00Z'}
        self.owner.references['robot'] = {'id': 'reference', 'identity': self.identity, 'initial': self.initial, 'pose': self.initial,
            'pixels': self.project(self.initial), 'points': self.points, 'gray': np.zeros((480, 640), np.uint8)}
        self.owner.frames['robot'] = (np.zeros((480, 640), np.uint8), self.identity)

    def project(self, pose):
        return cv2.projectPoints(self.points, cv2.Rodrigues(pose[:3, :3])[0], pose[:3, 3], self.k, np.zeros(5))[0].reshape(-1, 2)

    def test_metric_scale_and_signed_body_translation(self):
        for displacement in ([.20, 0, 0], [0, -.15, 0], [-.1, 0, 0]):
            body = rigid(self.c['cameraToBody'])
            relative = np.eye(4); relative[:3, 3] = displacement
            current = np.linalg.inv(body) @ np.linalg.inv(relative) @ body @ self.initial
            fitted, quality = pose_from_plane(self.points, self.project(current), self.k, np.zeros(5), .00001)
            self.assertFalse(quality['ambiguous'])
            self.owner._publish('robot', self.identity, fitted, quality)
            result = self.owner.measurements['robot']['position']
            np.testing.assert_allclose([result['xMetres'], result['yMetres']], displacement[:2], atol=1e-6)
            self.assertIsNone(result['uncertaintyMetres'])

    def test_rotation_lever_arm_and_bob(self):
        body = rigid(self.c['cameraToBody'])
        relative = np.eye(4); relative[:3, :3] = cv2.Rodrigues(np.array([.04, -.03, .2]))[0]
        relative[:3, 3] = [0, 0, .025]
        pose = np.linalg.inv(body) @ np.linalg.inv(relative) @ body @ self.initial
        self.owner._publish('robot', self.identity, pose, {'ambiguous': False})
        result = self.owner.measurements['robot']['position']
        np.testing.assert_allclose([result['xMetres'], result['yMetres']], [0, 0], atol=1e-12)
        self.assertAlmostEqual(result['zMetres'], .025)
        self.assertAlmostEqual(result['headingDegrees'], np.degrees(np.arctan2(relative[1, 0], relative[0, 0])))

    def test_measured_rectangle_freeze_capture_and_fit(self):
        owner = GroundPlane('rectangle-test')
        points = np.array([[0., 0, 0], [.24, 0, 0], [.24, .18, 0], [0, .18, 0]])
        for i in range(12):
            rv = np.array([.3*math.sin(i), .4*math.cos(i), .1*i])
            pixels = cv2.projectPoints(points, rv, np.array([-.1, -.08, .65+.01*i]), self.k, np.zeros(5))[0].reshape(-1, 2)
            identity = {**self.identity, 'frameId': str(i)}
            owner.frames['robot'] = (np.zeros((480, 640), np.uint8), identity)
            frozen = owner.calibration('robot', {'operation': 'status', 'includeImage': True})
            self.assertTrue(frozen['image'].startswith('data:image/jpeg;base64,'))
            owner.frames['robot'] = (np.zeros((480, 640), np.uint8), {**identity, 'frameId': 'newer'})
            owner.calibration('robot', {'operation': 'capture', 'pattern': 'rectangle', 'frameId': str(i),
                'pixels': pixels.tolist(), 'widthMetres': .24, 'heightMetres': .18})
        fitted = owner.calibration('robot', {'operation': 'fit', 'frameId': '11',
            'cameraToBody': self.c['cameraToBody'], 'geometryId': 'rectangle-test'})['calibration']
        np.testing.assert_allclose(fitted['cameraMatrix'], self.k, atol=.1)
        self.assertEqual(fitted['patterns'], ['rectangle'])
        self.assertIsNone(fitted['metricUncertaintyMetres'])

    def test_ambiguous_pose_stays_unavailable(self):
        self.owner._publish('robot', self.identity, self.initial, {'ambiguous': True})
        self.assertFalse(self.owner.measurements['robot']['available'])

    def test_explicit_contact_range_and_old_frame_never_reused(self):
        self.owner._publish('robot', self.identity, self.initial, {'ambiguous': False})
        p = self.project(self.initial)[12] / [640, 480]
        result = self.owner.range('frame0', {'x': p[0], 'y': p[1]})
        expected = rigid(self.c['cameraToBody']) @ self.initial @ np.r_[self.points[12], 1]
        self.assertAlmostEqual(result['rangeMetres'], np.linalg.norm(expected[:2]), places=6)
        self.assertEqual(result['referenceFrameId'], 'frame0')
        self.assertFalse(self.owner.range('unretained', {'x': .5, 'y': .5})['available'])
        wrong = self.owner.range('frame0', {'x': .6, 'y': .6}, {'frameId': 'frame0', 'robotId': 'other', 'epoch': 1, 'gatewayInstance': 'gateway-test'})
        self.assertFalse(wrong['available'])

    def test_delayed_retained_selection_tracks_source_into_current_frame(self):
        source = np.zeros((480, 640), np.uint8)
        cv2.rectangle(source, (300, 220), (320, 240), 255, -1)
        current = cv2.warpAffine(source, np.array([[1., 0, 8], [0, 1, 5]]), (640, 480))
        current_id = {**self.identity, 'frameId': 'ainekio-camera-gateway-test-robot-1-20'}
        self.owner.frames['robot'] = (current, current_id)
        self.owner._publish('robot', current_id, self.initial, {'ambiguous': False})
        payload = {'frameId': 'ainekio-camera-gateway-test-robot-1-2', 'robotId': 'robot', 'epoch': 1, 'gatewayInstance': 'gateway-test', 'frameTimestamp': '2026-01-01T00:00:00Z',
                   'jpeg': base64.b64encode(cv2.imencode('.jpg', source)[1]).decode()}
        point = {'x': 300 / 640, 'y': 220 / 480}
        result = self.owner.range(payload['frameId'], point, payload)
        self.assertTrue(result['available'])
        self.assertEqual(result['frameId'], current_id['frameId'])
        self.assertEqual(result['referenceFrameId'], payload['frameId'])
        self.assertEqual(result['referenceFrameTimestamp'], payload['frameTimestamp'])
        np.testing.assert_allclose([result['groundContact']['x'] * 640, result['groundContact']['y'] * 480], [308, 225], atol=.2)
        self.assertEqual(result['referencePoint'], point)
        self.owner.contacts.clear()
        payload['jpeg'] = base64.b64encode(cv2.imencode('.jpg', np.zeros_like(source))[1]).decode()
        lost = self.owner.range(payload['frameId'], point, payload)
        self.assertFalse(lost['available'])
        self.assertNotIn('rangeMetres', lost)

    def test_epoch_or_geometry_loss_is_unavailable_not_zero(self):
        jpeg = cv2.imencode('.jpg', np.zeros((240, 320), np.uint8))[1].tobytes()
        result = self.owner.process('robot', 2, 3, 4., jpeg, '2026-01-01T00:00:01Z')
        self.assertFalse(result['available']); self.assertNotIn('position', result)
        self.assertEqual(result['epoch'], 2)

    def test_new_capture_set_preserves_saved_calibration(self):
        self.owner.samples['robot'] = [{'sample': 'old'}]
        result = self.owner.calibration('robot', {'operation': 'resetSamples'})
        self.assertEqual(result['samples'], 0)
        self.assertEqual(result['calibration'], self.c)
        self.assertEqual(self.owner.calibrations['robot'], self.c)

    def test_no_calibration_defaults_and_rigid_contract(self):
        with self.assertRaises(ValueError): rigid(np.eye(3))
        wrong = dict(self.c, cameraToBody=np.zeros((4, 4)).tolist())
        with self.assertRaises(ValueError): self.owner.restore({'other': wrong})
        self.assertNotIn('other', self.owner.calibrations)

    def test_calibration_status_freezes_exact_source_and_fit_requires_measured_input(self):
        result = self.owner.calibration('robot', {'operation': 'status'})
        self.assertEqual(result['frame']['frameId'], 'frame0')
        self.owner.frames['robot'] = (np.zeros((480, 640), np.uint8), {**self.identity, 'frameId': 'frame1'})
        with self.assertRaisesRegex(ValueError, 'three distinct'):
            self.owner.calibration('robot', {'operation': 'fit', 'frameId': 'frame0'})
        with self.assertRaisesRegex(ValueError, 'exact current'):
            self.owner.calibration('robot', {'operation': 'capture', 'frameId': 'wrong'})

    def test_real_synthetic_checkerboard_capture_fit_and_reference(self):
        owner = GroundPlane('synthetic')
        columns, rows, square = 6, 5, .04
        for index, rv in enumerate(([.2, -.15, 0.], [-.25, .2, .15], [.35, .25, -.15], [-.1, -.3, .1])):
            image = np.full((480, 640), 128, np.uint8)
            for y in range(rows + 1):
                for x in range(columns + 1):
                    world = np.array([[x-1, y-1, 0], [x, y-1, 0], [x, y, 0], [x-1, y, 0]], float) * square
                    polygon = cv2.projectPoints(world, np.array(rv), np.array([-.1, -.08, .7 + index*.025]), self.k, np.zeros(5))[0]
                    cv2.fillConvexPoly(image, np.rint(polygon.reshape(-1, 2)).astype(np.int32), 255 if (x+y)%2 else 0)
            identity = {**self.identity, 'frameId': f'calibration-{index}'}
            owner.frames['robot'] = (image, identity)
            owner.calibration('robot', {'operation': 'status'})
            owner.calibration('robot', {'operation': 'capture', 'frameId': identity['frameId'], 'columns': columns, 'rows': rows, 'squareMetres': square})
        fitted = owner.calibration('robot', {'operation': 'fit', 'frameId': identity['frameId'], 'cameraToBody': self.c['cameraToBody'], 'geometryId': 'synthetic'})['calibration']
        self.assertEqual(fitted['imageSize'], [640, 480])
        self.assertEqual(len(fitted['sampleFrames']), 4)
        self.assertLess(fitted['reprojectionPixels'], 1.0)
        self.assertTrue(np.isfinite(fitted['cameraMatrix']).all())

    def test_selected_contact_tracking_loss_is_not_replaced_by_box_or_zero(self):
        self.owner._publish('robot', self.identity, self.initial, {'ambiguous': False})
        self.owner.range('frame0', {'x': .5, 'y': .5})
        jpeg = cv2.imencode('.jpg', np.zeros((480, 640), np.uint8))[1].tobytes()
        self.owner.process('robot', 1, 2, 10., jpeg, '2026-01-01T00:00:10Z')
        contact = self.owner.range('frame0', {'x': .5, 'y': .5})
        self.assertFalse(contact['available'])
        self.assertNotIn('rangeMetres', contact)
        self.assertEqual(contact['referenceFrameId'], 'frame0')


class CalibrationOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_reference_uses_existing_camera_expiry_and_publication(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from gateway.plugins import CameraFramePlugin
        callbacks = []
        gateway = SimpleNamespace(instance_id='gateway', subscribe_frames=callbacks.append,
            unsubscribe_frames=callbacks.remove, _publish_event=AsyncMock(), clock=lambda: 10.,
            status=lambda: {'robots': {'robot': {'epoch': 1, 'connection_state': 'online'}}})
        camera = CameraFramePlugin(gateway, None, max_frame_age_s=1.5)
        self.addAsyncCleanup(camera.aclose)
        self.assertFalse(camera.recognition_status()['configured'])
        measured = {'available': True, 'robotId': 'robot', 'epoch': 1,
            'observedAt': '2026-01-01T00:00:00+00:00', 'receivedAtMonotonic': 10.}
        camera._metric_call = AsyncMock(return_value={'measurement': measured})
        result = await camera.configure_ground_plane('robot', {'operation': 'reference'})
        self.assertEqual(result['measurement']['expiresAt'], '2026-01-01T00:00:01.500000+00:00')
        self.assertEqual(gateway._publish_event.await_args.args[0]['measurement'], result['measurement'])
        self.assertTrue(camera.locomotion_measurement('robot')['available'])
        gateway.clock = lambda: 12.
        self.assertFalse(camera.locomotion_measurement('robot')['available'])
        gateway.clock = lambda: 10.
        gateway.status = lambda: {'robots': {'robot': {'epoch': 2, 'connection_state': 'online'}}}
        self.assertFalse(camera.locomotion_measurement('robot')['available'])

    async def test_dashboard_fit_persists_existing_settings_without_runtime_frame_reference(self):
        with tempfile.TemporaryDirectory() as root:
            server = object.__new__(DashboardHttpServer)
            server.control_settings_path = Path(root) / 'sensing-controls.json'
            server.control_settings = {'recognition': False, 'cameras': {'other': {'on': True}}}
            class Camera:
                async def configure_ground_plane(self, robot, request):
                    return {'calibration': {'id': 'measured', 'robotId': robot}}
            server.camera_recognition = Camera()
            await server.ground_calibration('robot', {'operation': 'fit'})
            stored = json.loads(server.control_settings_path.read_text())
            self.assertFalse(stored['recognition']); self.assertEqual(stored['cameras'], {'other': {'on': True}})
            self.assertEqual(stored['ground_calibrations']['robot']['id'], 'measured')


import test_gateway_dashboard as dashboard_fixture

class CalibrationHttpTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = dashboard_fixture.GatewayDashboardTests.asyncSetUp
    asyncTearDown = dashboard_fixture.GatewayDashboardTests.asyncTearDown
    _request = dashboard_fixture.GatewayDashboardTests._request
    _raw_request = dashboard_fixture.GatewayDashboardTests._raw_request
    _login = dashboard_fixture.GatewayDashboardTests._login

    async def test_depth_settings_use_authenticated_owner_without_robot_commands(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        config = {"mode": "moge-open3d", "resolution_level": 0, "cameraToBody": None}
        self.server.camera_recognition = SimpleNamespace(configure_depth=AsyncMock(return_value=config))
        payload = {"robot_id": "ainekio-test-01", **config}
        self.assertEqual((await self._request("POST", "/api/camera/depth", payload))[0], 401)
        cookie, csrf = await self._login()
        self.assertEqual((await self._request("POST", "/api/camera/depth", payload, cookie=cookie))[0], 403)
        status, response, _ = await self._request("POST", "/api/camera/depth", payload, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertEqual(response["settings"], config)
        self.assertEqual(self.gateway.calls, [])

    async def test_ground_calibration_uses_existing_authenticated_post_owner(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        camera = SimpleNamespace(configure_ground_plane=AsyncMock(return_value={'samples': 1}))
        self.server.camera_recognition = camera
        payload = {'robot_id': 'ainekio-test-01', 'operation': 'capture', 'frameId': 'exact'}
        self.assertEqual((await self._request('POST', '/api/camera/ground-calibration', payload))[0], 401)
        cookie, csrf = await self._login()
        self.assertEqual((await self._request('POST', '/api/camera/ground-calibration', payload, cookie=cookie))[0], 403)
        status, response, _ = await self._request('POST', '/api/camera/ground-calibration', payload, cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertEqual(response['samples'], 1)
        camera.configure_ground_plane.assert_awaited_once_with('ainekio-test-01', payload)
        self.assertEqual(self.gateway.calls, [])
