"""Optical sampling of the existing physics plant, using the host depth schema.

This is a simulated camera measurement, not another depth network or navigation
controller. Camera calibration and acquisition/noise assumptions are explicit.
"""

from collections import deque
from copy import deepcopy
import math

import numpy as np

from gateway.depth_motion import rigid, spatial_depth
from gateway.depth_motion_worker import body_pose, camera_position, pose_motion


def project_depth(measurement, now_s, robot_id, epoch):
    """Project camera odometry and depth with independent validity evidence."""
    measurement = measurement or {}
    grid = measurement.get("depthSpatial")
    stamp = measurement.get("receivedAtMonotonic")
    age = (float(now_s-stamp) if isinstance(stamp, (int,float))
           and math.isfinite(stamp) and now_s >= stamp else None)
    current = (measurement.get("robotId") == robot_id and measurement.get("epoch") == epoch
               and measurement.get("frameCurrent") is True and age is not None)
    available = bool(current and grid and grid.get("available"))
    values = [value for value, valid in zip(grid.get("values",[]),grid.get("valid",[]))
              if valid and value is not None and math.isfinite(value) and value > 0] if available else []
    velocity = measurement.get("velocity_body_m_s")
    motion_available = bool(current and measurement.get("available") and
        measurement.get("coordinateOrigin") == "body" and isinstance(velocity, (list, tuple)) and
        len(velocity) == 3 and all(type(value) in (int, float) and math.isfinite(value) for value in velocity))
    return dict(available=motion_available,
        velocity_body_m_s=list(velocity) if motion_available else None,
        metric_accuracy_verified=bool(measurement.get("metricAccuracyVerified")),
        depthSpatial=deepcopy(grid), depth_available=bool(available and values),
        depth_min_m=min(values) if values else None, age_s=age,
        depth_frame_id=measurement.get("frameId"), depth_source=measurement.get("source"))


class RenderedCamera:
    """Virtual optics only: JPEGs go to the existing Body Control camera owner.

    This never reads root pose, ray depth or a simulator quaternion to produce
    a measurement. The installed MoGe/odometry worker must derive its own depth
    and motion from the images and the firmware-estimated IMU telemetry.
    """
    def __init__(self, profile):
        self.profile = deepcopy(profile)
        self.width, self.height = profile["imageSize"]
        self.capture_hz = float(profile["capture_hz"])
        self.jpeg_quality = int(profile["jpeg_quality"])
        self.renderer = None
        self.reset()

    def reset(self):
        self.next_capture = 0.
        self.counter = 0
        self.pending_frame = None

    def update(self, model, data, rng=None, *, now_s=None, **unused):
        import cv2
        import mujoco
        now = float(data.time if now_s is None else now_s)
        if now + 1e-10 < self.next_capture:
            return None
        self.next_capture = now + 1/self.capture_hz
        if self.renderer is None:
            self.renderer = mujoco.Renderer(model, height=self.height, width=self.width)
        self.renderer.update_scene(data, camera="ainekio_camera")
        rgb = self.renderer.render()
        ok, jpeg = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                               [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            raise RuntimeError("Virtual camera JPEG encoding failed")
        self.counter += 1
        self.pending_frame = dict(counter=self.counter, jpeg=jpeg.tobytes(),
                                  completed_us=round(1+now*1e6))
        return None  # A frame is not a depth/odometry measurement.

    def take_frame(self):
        frame, self.pending_frame = self.pending_frame, None
        return frame

    def close(self):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None


class DepthCamera:
    def __init__(self, profile):
        self.profile = deepcopy(profile)
        size = profile["imageSize"]
        if len(size) != 2 or any(type(value) is not int or value <= 0 for value in size):
            raise ValueError("Camera imageSize must contain positive integer width and height")
        self.width, self.height = size
        self.intrinsics = np.asarray(profile["cameraMatrix"], dtype=float)
        self.body_from_camera = rigid(profile["cameraToBody"])
        self.publish_camera_to_body = profile.get("publish_camera_to_body", True)
        if type(self.publish_camera_to_body) is not bool:
            raise ValueError("publish_camera_to_body must be a boolean")
        self.capture_hz = float(profile["capture_hz"])
        self.latency = float(profile["latency_s"])
        startup = profile.get("startup_latency_s", 0.)
        startup = startup if isinstance(startup, (list, tuple)) else (startup, startup)
        if (len(startup) != 2 or any(type(value) not in (int, float) or
                not math.isfinite(value) or value < 0 for value in startup)
                or startup[1] < startup[0]):
            raise ValueError("Camera startup latency must be nonnegative seconds or [minimum, maximum]")
        self.startup_latency = tuple(float(value) for value in startup)
        self.dropout = float(profile["dropout_probability"])
        self.noise = float(profile["noise_std_m"])
        self.max_age = profile.get("max_frame_age_s")
        self.odometry = deepcopy(profile.get("odometry"))
        if self.odometry is not None:
            for key in ("position_noise_std_m", "rotation_noise_std_rad", "log_scale_std", "dropout_probability"):
                value = self.odometry[key]
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("Odometry error assumptions must be finite nonnegative numbers")
            if self.odometry["dropout_probability"] > 1:
                raise ValueError("Odometry dropout probability must be at most one")
        if (not all(math.isfinite(v) for v in (self.capture_hz,self.latency,self.dropout,self.noise))
                or self.capture_hz <= 0 or self.latency < 0 or not 0 <= self.dropout <= 1 or self.noise < 0
                or self.max_age is not None and (not math.isfinite(self.max_age) or self.max_age <= 0)):
            raise ValueError("Invalid explicit camera cadence, latency, dropout, noise or freshness")
        self.image = np.zeros((self.height,self.width), dtype=float)
        shape = self._encode()
        self.pixels = np.asarray(shape["samplePixels"], dtype=int)
        self.rays = np.column_stack((self.pixels,np.ones(64))) @ np.linalg.inv(self.intrinsics).T
        self.rays /= self.rays[:,2:3]
        self.model = None
        self.reset()

    def _encode(self):
        return spatial_depth(self.image, self.intrinsics, units="metres",
            scale_source="simulation-geometry", intrinsics_source="explicit-simulation-profile",
            camera_to_body=self.body_from_camera if self.publish_camera_to_body else None,
            extrinsics_source="explicit-simulation-profile" if self.publish_camera_to_body else "unavailable",
            metric_accuracy_verified=False)

    def reset(self):
        self.next_capture = 0.
        self.pending = deque()
        self.waiting = None
        self.startup_pending = True
        self.latest = None
        self.counter = 0
        self.odometry_origin = self.odometry_previous = None
        self.odometry_path = self.odometry_heading = 0.
        self.odometry_reference = 0
        self.odometry_scale = None

    def _process_capture(self, measurement, camera_pose, started, rng):
        """One metric worker, using the captured pose rather than the delivery pose."""
        duration = self.latency
        if self.startup_pending and self.startup_latency[1] > 0:
            low, high = self.startup_latency
            duration = low if low == high else float(rng.uniform(low, high))
        self.startup_pending = False
        if self.odometry is not None:
            measurement.update(self._odometry_capture(
                camera_pose, measurement["receivedAtMonotonic"], rng))
            measurement["source"] = "simulation-noisy-optical-odometry-and-depth"
        delivery = started + duration
        measurement["deliveryAtSimulationS"] = delivery
        measurement["inferenceMs"] = duration*1000
        if self.startup_latency[1] > 0:
            measurement["processingStartedAtSimulationS"] = started
        self.pending.append((delivery, measurement))

    def _deliver(self, now, rng):
        while self.pending and self.pending[0][0] <= now+1e-10:
            delivered, self.latest = self.pending.popleft()
            if self.waiting is not None:
                measurement, camera_pose = self.waiting
                self.waiting = None
                self._process_capture(measurement, camera_pose, delivered, rng)

    def _odometry_capture(self, world_from_camera, now, rng):
        """Explicit noisy camera sensor model; never a perfect pose actor input."""
        profile = self.odometry
        if rng.random() < profile["dropout_probability"]:
            self.odometry_origin = self.odometry_previous = None
            self.odometry_reference += 1
            return dict(available=False, reason="Simulated optical tracking loss")
        if self.odometry_origin is None:
            self.odometry_origin = world_from_camera.copy()
            self.odometry_scale = math.exp(rng.normal(0., profile["log_scale_std"]))
            self.odometry_path = self.odometry_heading = 0.
        estimate = np.linalg.inv(self.odometry_origin) @ world_from_camera
        estimate[:3, 3] *= self.odometry_scale
        estimate[:3, 3] += rng.normal(0., profile["position_noise_std_m"], 3)
        from scipy.spatial.transform import Rotation
        estimate[:3, :3] = estimate[:3, :3] @ Rotation.from_rotvec(
            rng.normal(0., profile["rotation_noise_std_rad"], 3)).as_matrix()
        current = body_pose(estimate, self.body_from_camera)
        motion = None
        if self.odometry_previous is not None:
            previous, stamp = self.odometry_previous
            motion = pose_motion(previous, current, now-stamp)
            self.odometry_path += motion["travelled_m"]
            self.odometry_heading += motion["turn_rad"]
        self.odometry_previous = (current.copy(), now)
        return dict(available=motion is not None,
            coordinateOrigin="body" if self.publish_camera_to_body else "camera",
            referenceId=f"simulation-optical-{self.odometry_reference}",
            position=camera_position(estimate, self.body_from_camera),
            velocity_body_m_s=motion["velocity_body_m_s"] if motion is not None and self.publish_camera_to_body else None,
            yaw_rate_rad_s=motion["yaw_rate_rad_s"] if motion is not None else None,
            path_length_m=self.odometry_path, heading_change_rad=self.odometry_heading)

    def _external_geoms(self, model):
        if model is not self.model:
            self.model = model
            self.torso = model.body("torso").id
            robot = set([self.torso])
            for body in range(self.torso+1, model.nbody):
                if model.body_parentid[body] in robot:
                    robot.add(body)
            self.external_geoms = [geom for geom in range(model.ngeom)
                                   if model.geom_bodyid[geom] not in robot]
        return self.external_geoms

    def update(self, model, data, rng, *, robot_id, epoch, gateway_instance,
               now_s=None, geom_mask=None):
        import mujoco
        now = float(data.time if now_s is None else now_s)
        # Historical profiles model fixed delivery latency. An explicit startup
        # profile additionally models the live single worker and latest-frame
        # coalescing; no camera inference delay blocks the body simulation.
        if self.startup_latency[1] > 0:
            self._deliver(now, rng)
        if now + 1e-10 >= self.next_capture:
            self.next_capture = now + 1/self.capture_hz
            geoms = [geom for geom in self._external_geoms(model)
                     if (geom_mask is None or geom_mask[geom]) and model.geom_rgba[geom,3] > 0]
            rotation = data.xmat[self.torso].reshape(3,3)
            position = data.xpos[self.torso] + rotation @ self.body_from_camera[:3,3]
            world_from_camera = rotation @ self.body_from_camera[:3,:3]
            self.image.fill(0)
            for (u,v), ray in zip(self.pixels, self.rays):
                direction = world_from_camera @ ray
                best = math.inf
                for geom in geoms:
                    kind = model.geom_type[geom]
                    if kind == mujoco.mjtGeom.mjGEOM_MESH:
                        distance = mujoco.mj_rayMesh(model,data,geom,position,direction)
                    elif kind == mujoco.mjtGeom.mjGEOM_HFIELD:
                        distance = mujoco.mj_rayHfield(model,data,geom,position,direction)
                    else:
                        distance = mujoco.mju_rayGeom(data.geom_xpos[geom],data.geom_xmat[geom],
                            model.geom_size[geom],position,direction,kind)
                    if distance >= 0:
                        best = min(best,float(distance))
                if math.isfinite(best) and (not self.dropout or rng.random() >= self.dropout):
                    # Rays have optical z=1. Intersection parameter is Z depth,
                    # not Euclidean range, including off-axis image samples.
                    self.image[v,u] = best + (rng.normal(0,self.noise) if self.noise else 0.)
            self.counter += 1
            grid = self._encode()
            grid["provenance"] = deepcopy(self.profile["provenance"])
            measurement = dict(depthSpatial=grid, available=False,
                source="simulation-optical-depth", robotId=robot_id,epoch=epoch,
                gatewayInstance=gateway_instance, frameCounter=self.counter,
                frameId=f"ainekio-camera-{gateway_instance}-{robot_id}-{epoch}-{self.counter}",
                receivedAtMonotonic=now, capturedAtSimulationS=now,
                deliveryAtSimulationS=now+self.latency, clock="simulation-acquisition",
                inferenceMs=self.latency*1000, frameCurrent=True,
                metricAccuracyVerified=False)
            camera_pose = np.eye(4)
            camera_pose[:3, :3] = world_from_camera
            camera_pose[:3, 3] = position
            if self.startup_latency[1] > 0 and self.pending:
                self.waiting = (measurement, camera_pose)
            else:
                self._process_capture(measurement, camera_pose, now, rng)
        self._deliver(now, rng)
        if self.latest is None:
            return dict(available=False, frameCurrent=False, robotId=robot_id,epoch=epoch,
                        reason="No delivered simulated depth capture")
        result = deepcopy(self.latest)
        result["frameCurrent"] = self.max_age is None or now-result["receivedAtMonotonic"] <= self.max_age
        return result
