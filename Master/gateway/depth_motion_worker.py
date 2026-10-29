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


def camera_position(world_from_camera, camera_to_body=None):
    """Convert OpenCV camera axes to body convention; preserve the lever arm."""
    body_from_camera = (OPTICAL_TO_FORWARD if camera_to_body is None
                        else np.asarray(camera_to_body, dtype=float))
    relative = body_from_camera @ world_from_camera @ np.linalg.inv(body_from_camera)
    return dict(xMetres=float(relative[0, 3]), yMetres=float(relative[1, 3]),
                zMetres=float(relative[2, 3]),
                headingDegrees=math.degrees(math.atan2(relative[1, 0], relative[0, 0])),
                uncertaintyMetres=None)


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

    def process(self, rgb, depth, intrinsics):
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
            found, rotation, translation, inliers = cv2.solvePnPRansac(
                points, observed, intrinsics, None, flags=cv2.SOLVEPNP_EPNP)
            if not found or inliers is None or len(inliers) < 6:
                raise ValueError("Camera landmark pose fit failed")
            keep = inliers.ravel()
            rotation, translation = cv2.solvePnPRefineLM(
                points[keep], observed[keep], intrinsics, None, rotation, translation)
            camera_from_world = np.eye(4)
            camera_from_world[:3, :3] = cv2.Rodrigues(rotation)[0]
            camera_from_world[:3, 3] = translation.ravel()
            pose = np.linalg.inv(camera_from_world)
            predicted = points[keep] @ camera_from_world[:3, :3].T + translation.ravel()
            scale = float(np.median(predicted[:, 2]/z[new[keep]]))
            if not np.isfinite(pose).all() or not math.isfinite(scale) or scale <= 0:
                raise ValueError("Camera landmark fit has invalid depth")
            projected = cv2.projectPoints(points[keep], rotation, translation, intrinsics, None)[0].reshape(-1, 2)
            quality = dict(matches=len(matches), inliers=len(keep),
                           reprojectionPixels=float(np.sqrt(np.mean(np.sum((projected-observed[keep])**2, axis=1)))))
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
                ["landmark-odometry-v1", self.model_id, config, intrinsics.tolist()], sort_keys=True).encode()).hexdigest()
            self.optics[(robot, optics_key)] = {k: state[k] for k in ("intrinsics", "calibration_id")}
        quality = {"matches": 0, "inliers": 0, "reprojectionPixels": None}
        tracking_error = None
        try:
            state["pose"], quality = state["tracker"].process(rgb, depth, state["intrinsics"])
        except (RuntimeError, ValueError, cv2.error) as error:
            # Approved recovery: the missing interval is unknown. Establish the
            # next local map with this image if it contains usable features.
            tracking_error = str(error)
            state["reference"] = uuid4().hex
            state["pose"] = np.eye(4)
            state["tracker"] = FeatureMap()
            try:
                state["tracker"].process(rgb, depth, state["intrinsics"])
            except (RuntimeError, ValueError, cv2.error):
                pass
        frame_id = f"ainekio-camera-{request['instance']}-{robot}-{request['epoch']}-{request['counter']}"
        good = depth[depth > 0]
        lo, hi = np.quantile(good, [.02, .98])
        normalized = np.clip((depth-lo)/max(float(hi-lo), np.finfo(float).eps), 0, 1)
        preview = cv2.applyColorMap((normalized*255).astype(np.uint8), cv2.COLORMAP_TURBO)
        preview[depth == 0] = 0
        preview = cv2.resize(preview, (320, round(320*rgb.shape[0]/rgb.shape[1])))
        png = cv2.imencode(".png", preview)[1].tobytes()
        return dict(
            available=tracking_error is None, source="moge2-landmark-odometry", scaleSource="learned-metric-estimate",
            reason="Camera tracking lost; new local reference established" if tracking_error else None,
            trackingError=tracking_error,
            metricAccuracyVerified=False, uncertainty={"metricMetres": None, **quality},
            coordinateOrigin="body" if config.get("cameraToBody") else "camera",
            mounting="measured-transform" if config.get("cameraToBody") else "assumed-forward-upright",
            robotId=robot, epoch=request["epoch"], gatewayInstance=request["instance"],
            frameCounter=request["counter"], frameId=frame_id, frameTimestamp=request["timestamp"],
            observedAt=request["timestamp"], receivedAtMonotonic=request["received"],
            clock="gateway-receipt", referenceId=state["reference"], calibrationId="estimated-"+state["calibration_id"],
            modelId=self.model_id, referenceKind="local-odometry-no-loop-closure",
            position=camera_position(state["pose"], config.get("cameraToBody")) if tracking_error is None else None,
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
