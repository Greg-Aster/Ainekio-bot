"""MoGe-2 depth + feature-map visual odometry, isolated from the gateway.

Depth is a model estimate, not a calibrated range sensor. This is local
odometry, not loop-closing SLAM. Camera-origin motion is reported unless an
explicit measured camera-to-body transform is supplied.
"""
from __future__ import annotations

import base64
from contextlib import redirect_stdout
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

import numpy as np

if __package__:
    from .depth_motion import spatial_depth
else:  # Existing worker launches this file in its own interpreter.
    from depth_motion import spatial_depth


OPTICAL_TO_FORWARD = np.array([[0., 0, 1, 0], [-1., 0, 0, 0],
                               [0., -1., 0, 0], [0., 0, 0, 1]])


def body_pose(world_from_camera, camera_to_body=None):
    """Convert the tracked camera pose with the mounting lever arm retained."""
    body_from_camera = (OPTICAL_TO_FORWARD if camera_to_body is None
                        else np.asarray(camera_to_body, dtype=float))
    return body_from_camera @ world_from_camera @ np.linalg.inv(body_from_camera)


def camera_position(world_from_camera, camera_to_body=None):
    """Convert OpenCV camera axes to body convention; preserve the lever arm."""
    relative = body_pose(world_from_camera, camera_to_body)
    return dict(xMetres=float(relative[0, 3]), yMetres=float(relative[1, 3]),
                zMetres=float(relative[2, 3]),
                headingDegrees=math.degrees(math.atan2(relative[1, 0], relative[0, 0])),
                uncertaintyMetres=None)


def pose_motion(previous, current, seconds):
    """Frame-interval motion estimate, not IMU integration or actuator authority."""
    displacement = current[:3, 3] - previous[:3, 3]
    heading = lambda pose: math.atan2(pose[1, 0], pose[0, 0])
    turn = math.atan2(math.sin(heading(current)-heading(previous)),
                      math.cos(heading(current)-heading(previous)))
    return dict(velocity_body_m_s=(current[:3, :3].T @ displacement / seconds).tolist(),
                yaw_rate_rad_s=turn/seconds, turn_rad=turn,
                travelled_m=float(np.linalg.norm(displacement)))


def quaternion_rotation(value):
    w, x, y, z = np.asarray(value, dtype=float)/np.linalg.norm(value)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def known_rotation_translation(points, pixels, intrinsics, rotation):
    """Known-rotation absolute pose, using 3-D landmarks (not unit translation).

    Same geometric problem as OpenGV absolute_pose::p2p:
    https://laurentkneip.github.io/opengv/namespaceopengv_1_1absolute__pose.html
    Here two-bearing hypotheses solve [I-bb'] t = -[I-bb'] R X;
    inliers refine translation only. Existing PnPRansac defaults are retained:
    100 hypotheses, 8-pixel residual, at least six supported landmarks.
    """
    import cv2
    rotated = np.asarray(points) @ rotation.T
    rays = np.column_stack([pixels,np.ones(len(pixels))]) @ np.linalg.inv(intrinsics).T
    rays /= np.linalg.norm(rays,axis=1)[:,None]
    projectors = np.eye(3)[None]-rays[:,:,None]*rays[:,None,:]
    rhs = -np.einsum('nij,nj->ni',projectors,rotated)
    def fit(indices):
        a = projectors[indices].reshape(-1,3)
        t, _, rank, _ = np.linalg.lstsq(a,rhs[indices].reshape(-1),rcond=None)
        return t if rank == 3 else None
    def errors(t):
        camera = rotated+t
        projected = camera @ intrinsics.T
        predicted = projected[:,:2]/projected[:,2,None]
        return np.where(camera[:,2] > 0, np.linalg.norm(predicted-pixels,axis=1), np.inf)
    rng = np.random.default_rng(0)
    keep, best_error = np.array([],dtype=int), np.inf
    for _ in range(100):
        t = fit(rng.choice(len(points),2,replace=False))
        if t is None:
            continue
        error = errors(t)
        indices = np.flatnonzero(error < 8.)
        score = float(error[indices].sum())
        if len(indices) > len(keep) or (len(indices) == len(keep) and score < best_error):
            keep, best_error = indices, score
    if len(keep) < 6:
        raise ValueError("Camera known-rotation landmark pose fit failed")
    t = fit(keep)
    if t is None:
        raise ValueError("Camera known-rotation translation is unobservable")
    rvec = cv2.Rodrigues(rotation)[0]
    # Reprojection Gauss-Newton with only the three translation columns.
    for _ in range(20):
        predicted, jacobian = cv2.projectPoints(points[keep],rvec,t,intrinsics,None)
        residual = (predicted.reshape(-1,2)-pixels[keep]).reshape(-1)
        step, _, rank, _ = np.linalg.lstsq(jacobian[:,3:6],-residual,rcond=None)
        if rank < 3:
            raise ValueError("Camera known-rotation translation is unobservable")
        t += step
        if np.linalg.norm(step) < 1e-10:
            break
    error = errors(t)
    keep = np.flatnonzero(error < 8.)
    if len(keep) < 6 or not np.isfinite(t).all():
        raise ValueError("Camera known-rotation landmark refinement failed")
    return t, keep, float(np.sqrt(np.mean(error[keep]**2)))


class FeatureMap:
    """Track fixed 3-D landmarks rather than changes in predicted depth.

    Matched landmarks retain their world positions. Newly visible landmarks
    use model depth aligned to the retained landmarks' scale. This avoids
    interpreting independent per-image depth changes as camera translation.
    The map contains the current image's features, not an ever-growing atlas.
    """
    def __init__(self):
        import cv2
        self.detector = cv2.SIFT_create(nfeatures=2000)
        self.descriptors = None
        self.points = None

    def process(self, rgb, depth, intrinsics, camera_rotation):
        import cv2
        keypoints, descriptors = self.detector.detectAndCompute(
            cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), None)
        if descriptors is None or len(keypoints) < 6:
            raise ValueError("Insufficient image features for camera pose")
        pixels = np.array([p.pt for p in keypoints], np.float64)
        indices = np.rint(pixels).astype(int)
        z = depth[indices[:, 1], indices[:, 0]]
        valid = np.isfinite(z) & (z > 0)
        pixels, descriptors, z = pixels[valid], descriptors[valid], z[valid]
        if len(pixels) < 6:
            raise ValueError("Insufficient depth-supported landmarks for camera pose")
        rays = np.column_stack([pixels, np.ones(len(pixels))]) @ np.linalg.inv(intrinsics).T
        pose = np.eye(4)
        pose[:3,:3] = camera_rotation
        quality = {"matches": 0, "inliers": 0, "reprojectionPixels": None}
        retained = None
        scale = 1.
        if self.descriptors is not None:
            pairs = cv2.BFMatcher().knnMatch(self.descriptors, descriptors, k=2)
            matches = [p[0] for p in pairs if len(p) == 2 and p[0].distance < .75*p[1].distance]
            # Multiple source landmarks cannot all own the same image feature.
            unique = {m.trainIdx: m for m in sorted(matches, key=lambda m: m.distance, reverse=True)}
            matches = list(unique.values())
            if len(matches) < 6:
                raise ValueError("Insufficient matched landmarks for camera pose")
            old = np.array([m.queryIdx for m in matches])
            new = np.array([m.trainIdx for m in matches])
            points, observed = self.points[old], pixels[new]
            rotation = camera_rotation.T
            translation, keep, reprojection = known_rotation_translation(points, observed, intrinsics, rotation)
            camera_from_world = np.eye(4)
            camera_from_world[:3, :3] = rotation
            camera_from_world[:3, 3] = translation
            pose = np.linalg.inv(camera_from_world)
            predicted = points[keep] @ rotation.T + translation
            scale = float(np.median(predicted[:, 2]/z[new[keep]]))
            if not np.isfinite(pose).all() or not math.isfinite(scale) or scale <= 0:
                raise ValueError("Camera landmark fit has invalid depth")
            quality = dict(matches=len(matches), inliers=len(keep), reprojectionPixels=reprojection,
                           rotationSource="capture-aligned-p4-fused-attitude")
            retained = (new[keep], points[keep])
        world = (rays*(z*scale)[:, None]) @ pose[:3, :3].T + pose[:3, 3]
        if retained is not None:
            world[retained[0]] = retained[1]
        self.points, self.descriptors = world, descriptors
        return pose, quality


class Estimator:
    def __init__(self):
        import torch
        from safetensors.torch import load_file
        root = Path(os.environ.get("AINEKIO_DEPTH_COMFY_ROOT", Path.home()/"ComfyUI"))
        sys.path.insert(0, str(root))
        from comfy.ldm.moge.model import MoGeModel
        path = Path(os.environ.get("AINEKIO_DEPTH_MODEL",
                    root/"models/geometry_estimation/moge_2_vitl_normal_fp16.safetensors"))
        self.model_id = hashlib.sha256(path.read_bytes()).hexdigest()
        self.model = MoGeModel(load_file(str(path)))
        if self.model.version != "v2":
            raise ValueError("Metric camera motion requires MoGe-2 metric-scale weights")
        self.torch = torch
        self.states = {}
        self.optics = {}

    def depth(self, rgb, level, intrinsics):
        """Use the installed network and geometry solver, with fixed optics.

        The ComfyUI convenience infer() has a silent 60-degree FOV fallback.
        Here failed focal fitting is reported instead. No fabricated optics.
        """
        import comfy.model_management
        from comfy.ldm.moge.geometry import recover_focal_shift, intrinsics_from_focal_center
        torch = self.torch
        model = self.model
        comfy.model_management.load_model_gpu(model.patcher)
        image = torch.from_numpy(rgb.copy()).permute(2, 0, 1)[None].float().to(model.load_device)/255
        h, w = rgb.shape[:2]
        aspect = w/h
        lo, hi = model.num_tokens_range
        with torch.inference_mode():
            raw = model.model.forward(image, num_tokens=int(lo+(level/9)*(hi-lo)))
            points = raw["points"].float()
            mask = raw["mask"] > model.mask_threshold
            focal = None if intrinsics is None else torch.tensor(
                [2*intrinsics[0, 0]/w*aspect/math.sqrt(1+aspect**2)],
                device=points.device, dtype=points.dtype)
            focal, shift = recover_focal_shift(points, mask, focal=focal)
            if not bool((torch.isfinite(focal) & (focal > 0)).all()):
                raise ValueError("MoGe focal estimation failed")
            half = torch.tensor(.5, device=points.device, dtype=points.dtype)
            diag = focal/2*math.sqrt(1+aspect**2)
            k = intrinsics_from_focal_center(diag/aspect, diag, half, half)[0].cpu().numpy()
            k[0] *= w
            k[1] *= h
            depth = (points[..., 2]+shift[:, None, None])*raw["metric_scale"][:, None, None]
            depth = depth[0].cpu().numpy()
            mask = mask[0].cpu().numpy() & np.isfinite(depth) & (depth > 0)
        if not mask.any():
            raise ValueError("MoGe produced no finite positive depth")
        return np.where(mask, depth, 0).astype(np.float32), k

    def process(self, request):
        import cv2
        started = time.perf_counter()
        rgb = cv2.imdecode(np.frombuffer(base64.b64decode(request["jpeg"]), np.uint8), cv2.IMREAD_COLOR)
        if rgb is None:
            raise ValueError("Invalid camera JPEG")
        rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
        config = request["config"]
        robot = request["robot"]
        key = (request["instance"], request["epoch"], rgb.shape[:2],
               json.dumps(config, sort_keys=True))
        optics_key = (request["instance"], rgb.shape[:2], json.dumps(config, sort_keys=True))
        cached_optics = self.optics.get((robot, optics_key))
        state = self.states.get(robot)
        if state is None or state["key"] != key:
            # A high-resolution still temporarily replaces preview frames.
            # Keep each mode's optics so returning to preview does not invent
            # a new calibration and discard its accumulated gait evidence.
            optics = cached_optics or {"intrinsics": None}
            state = dict(key=key, reference=uuid4().hex, pose=np.eye(4),
                         tracker=FeatureMap(), optics_key=optics_key, **optics)
            self.states[robot] = state
        depth, intrinsics = self.depth(rgb, config["resolution_level"], state["intrinsics"])
        if state["intrinsics"] is None:
            state["intrinsics"] = intrinsics
            state["calibration_id"] = hashlib.sha256(json.dumps(
                ["imu-known-rotation-landmark-odometry-v2", self.model_id, config, intrinsics.tolist()], sort_keys=True).encode()).hexdigest()
            self.optics[(robot, optics_key)] = {k: state[k] for k in ("intrinsics", "calibration_id")}
        quality = {"matches": 0, "inliers": 0, "reprojectionPixels": None}
        tracking_error = None
        attitude = request.get("attitude") or {}
        camera_rotation = None
        stamp = attitude.get("frame_completed_us")
        try:
            if not attitude.get("available"):
                raise ValueError(attitude.get("reason", "Camera frame has no capture-aligned IMU attitude"))
            if config.get("cameraToBody") is None:
                raise ValueError("Camera-to-body transform is required for IMU-constrained pose")
            current_rotation = quaternion_rotation(attitude["orientation_wxyz"])
            if state.get("attitude_boot") != attitude["boot_id"]:
                state.update(attitude_boot=attitude["boot_id"], attitude_reference=current_rotation,
                             tracker=FeatureMap(), reference=uuid4().hex, pose=np.eye(4), motion_sample=None)
            reference = state.setdefault("attitude_reference", current_rotation)
            mounting = np.asarray(config["cameraToBody"])[:3,:3]
            camera_rotation = mounting.T @ reference.T @ current_rotation @ mounting
            state["pose"], quality = state["tracker"].process(rgb, depth, state["intrinsics"], camera_rotation)
        except (RuntimeError, ValueError, cv2.error) as error:
            # Approved recovery: the missing interval is unknown. Establish the
            # next local map with this image if it contains usable features.
            tracking_error = str(error)
            state["reference"] = uuid4().hex
            state["pose"] = np.eye(4)
            state["tracker"] = FeatureMap()
            state.pop("attitude_reference", None)
            if camera_rotation is not None:
                state["attitude_reference"] = current_rotation
                try:
                    state["tracker"].process(rgb, depth, state["intrinsics"], np.eye(3))
                except (RuntimeError, ValueError, cv2.error):
                    pass
        motion = None
        if tracking_error is None:
            pose = body_pose(state["pose"], config.get("cameraToBody"))
            previous = state.get("motion_sample")
            if (previous is not None and previous[0] == state["reference"] and
                    stamp > previous[1]):
                motion = pose_motion(previous[2], pose, (stamp-previous[1])/1e6)
                state["path_m"] += motion["travelled_m"]
                state["heading_rad"] += motion["turn_rad"]
            else:
                state["path_m"], state["heading_rad"] = 0., 0.
            state["motion_sample"] = (state["reference"], stamp, pose.copy())
        else:
            state["motion_sample"] = None
            state["path_m"], state["heading_rad"] = 0., 0.
        frame_id = f"ainekio-camera-{request['instance']}-{robot}-{request['epoch']}-{request['counter']}"
        good = depth[depth > 0]
        lo, hi = np.quantile(good, [.02, .98])
        normalized = np.clip((depth-lo)/max(float(hi-lo), np.finfo(float).eps), 0, 1)
        preview = cv2.applyColorMap((normalized*255).astype(np.uint8), cv2.COLORMAP_TURBO)
        preview[depth == 0] = 0
        preview = cv2.resize(preview, (320, round(320*rgb.shape[0]/rgb.shape[1])))
        png = cv2.imencode(".png", preview)[1].tobytes()
        return dict(
            available=tracking_error is None, source="moge2-imu-landmark-odometry", scaleSource="learned-metric-estimate",
            reason="Camera tracking lost; new local reference established" if tracking_error else None,
            trackingError=tracking_error,
            metricAccuracyVerified=False, uncertainty={"metricMetres": None, **quality},
            coordinateOrigin="body" if config.get("cameraToBody") else "camera",
            mounting="configured-transform" if config.get("cameraToBody") else "assumed-forward-upright",
            robotId=robot, epoch=request["epoch"], gatewayInstance=request["instance"],
            frameCounter=request["counter"], frameId=frame_id, frameTimestamp=request["timestamp"],
            observedAt=request["timestamp"], receivedAtMonotonic=request["received"],
            clock="gateway-receipt", attitude=attitude,
            motionClock="device-csi-transfer-completion", exposureAlignmentVerified=False,
            referenceId=state["reference"], calibrationId="estimated-"+state["calibration_id"],
            modelId=self.model_id, referenceKind="local-odometry-no-loop-closure",
            position=camera_position(state["pose"], config.get("cameraToBody")) if tracking_error is None else None,
            velocity_body_m_s=(motion["velocity_body_m_s"]
                if motion is not None and config.get("cameraToBody") else None),
            yaw_rate_rad_s=motion["yaw_rate_rad_s"] if motion is not None else None,
            path_length_m=state["path_m"] if tracking_error is None else None,
            heading_change_rad=state["heading_rad"] if tracking_error is None else None,
            motionIntervalS=((stamp-previous[1])/1e6 if motion is not None else None),
            distanceDefinition="Accumulated 3D odometry displacement within this local reference; estimated metric scale",
            intrinsics=state["intrinsics"].tolist(),
            depth=dict(units="estimated-metres", near=float(lo), far=float(hi),
                       median=float(np.median(good)), validFraction=float((depth > 0).mean())),
            depthSpatial=spatial_depth(depth, state["intrinsics"],
                units="estimated-metres", scale_source="learned-metric-estimate",
                intrinsics_source="model-estimated-per-image-mode",
                camera_to_body=config.get("cameraToBody"),
                extrinsics_source="configured-transform" if config.get("cameraToBody") else "unavailable",
                metric_accuracy_verified=False),
            depthPreview="data:image/png;base64,"+base64.b64encode(png).decode(),
            inferenceMs=(time.perf_counter()-started)*1000)


def main():
    estimator = None
    # Libraries can print to stdout during loading. Reserve stdout for JSON.
    for line in sys.stdin:
        try:
            with redirect_stdout(sys.stderr):
                request = json.loads(line)
                if "reset" in request:
                    if estimator is not None:
                        estimator.states.pop(request["reset"], None)
                    result = {"reset": True}
                else:
                    if estimator is None:
                        estimator = Estimator()
                    result = estimator.process(request)
            print(json.dumps(result, allow_nan=False), flush=True)
        except Exception as error:
            print(json.dumps({"error": str(error)}), flush=True)


if __name__ == "__main__":
    main()
