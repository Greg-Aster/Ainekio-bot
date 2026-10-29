"""Optical sampling of the existing physics plant, using the host depth schema.

This is a simulated camera measurement, not another depth network or navigation
controller. Camera calibration and acquisition/noise assumptions are explicit.
"""

from collections import deque
from copy import deepcopy
import math

import numpy as np

from gateway.depth_motion import rigid, spatial_depth


def project_depth(measurement, now_s, robot_id, epoch):
    """Project existing camera identity/freshness without requiring odometry."""
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
    return dict(depthSpatial=deepcopy(grid), depth_available=bool(available and values),
        depth_min_m=min(values) if values else None, age_s=age,
        depth_frame_id=measurement.get("frameId"), depth_source=measurement.get("source"))


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
        self.dropout = float(profile["dropout_probability"])
        self.noise = float(profile["noise_std_m"])
        self.max_age = profile.get("max_frame_age_s")
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
        self.latest = None
        self.counter = 0

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
            self.pending.append((now+self.latency,measurement))
        while self.pending and self.pending[0][0] <= now+1e-10:
            _, self.latest = self.pending.popleft()
        if self.latest is None:
            return dict(available=False, frameCurrent=False, robotId=robot_id,epoch=epoch,
                        reason="No delivered simulated depth capture")
        result = deepcopy(self.latest)
        result["frameCurrent"] = self.max_age is None or now-result["receivedAtMonotonic"] <= self.max_age
        return result
