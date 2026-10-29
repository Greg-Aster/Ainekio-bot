"""Optional host depth/odometry worker. No robot command or movement authority."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

# Capture the launcher allocation before recognition initializes Ultralytics.
# Its CPU device selection mutates CUDA_VISIBLE_DEVICES in the gateway process;
# that must not change the separate depth worker's device allocation.
_LAUNCH_CUDA_VISIBLE_DEVICES = os.environ.get("CUDA_VISIBLE_DEVICES")


def rigid(value):
    """Shared camera-to-body rigid-transform validation; no vision runtime."""
    import numpy as np
    transform = np.asarray(value, dtype=float)
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError("cameraToBody must be a finite (4, 4) array")
    rotation = transform[:3, :3]
    if not np.allclose(transform[3], [0, 0, 0, 1]) or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(rotation), 1):
        raise ValueError("cameraToBody must be a rigid transform: body x forward, y left, z up; camera OpenCV axes")
    return transform


def spatial_depth(depth, intrinsics, *, units, scale_source, intrinsics_source,
                  camera_to_body=None, extrinsics_source="unavailable",
                  metric_accuracy_verified=False):
    """Compact camera observation shared by learned depth and virtual cameras.

    Eight rows by eight columns sample the pixel nearest each image-cell center,
    ordered top-to-bottom then left-to-right. Values are optical-axis Z depths,
    not ray lengths, body heights, nearest obstacles or traversability. Invalid
    readings stay null with an explicit mask; no interpolation fills holes.
    K and samplePixels reconstruct each sampled optical ray. The enclosing
    camera measurement retains frame/epoch/source/receipt-time identity; consumers
    derive age at use from that timestamp, never from repeated reads of the grid.
    """
    import numpy as np
    image = np.asarray(depth)
    k = np.asarray(intrinsics, dtype=float)
    if image.ndim != 2 or not all(image.shape):
        raise ValueError("Spatial depth requires a nonempty image")
    if k.shape != (3, 3) or not np.isfinite(k).all() or k[0, 0] <= 0 or k[1, 1] <= 0:
        raise ValueError("Spatial depth requires finite positive camera intrinsics")
    if camera_to_body is not None:
        camera_to_body = rigid(camera_to_body).tolist()
    height, width = image.shape
    pixels = [(min(width-1, int((col+.5)*width/8)),
               min(height-1, int((row+.5)*height/8)))
              for row in range(8) for col in range(8)]
    samples = [float(image[y, x]) for x, y in pixels]
    valid = [bool(np.isfinite(value) and value > 0) for value in samples]
    return dict(schema="ainekio-depth-grid-v1", rows=8, columns=8,
        frame="camera-optical", depthKind="optical-axis-z", units=units,
        values=[value if ok else None for value, ok in zip(samples, valid)], valid=valid,
        available=any(valid), samplePixels=[list(pixel) for pixel in pixels],
        imageSize=[width, height], cameraMatrix=k.tolist(),
        scaleSource=scale_source, intrinsicsSource=intrinsics_source,
        cameraToBody=camera_to_body, extrinsicsSource=extrinsics_source,
        metricAccuracyVerified=bool(metric_accuracy_verified))


def worker_environment():
    env = os.environ.copy()
    visible = env.get("AINEKIO_DEPTH_CUDA_VISIBLE_DEVICES", _LAUNCH_CUDA_VISIBLE_DEVICES)
    if visible is None:
        env.pop("CUDA_VISIBLE_DEVICES", None)
    else:
        env["CUDA_VISIBLE_DEVICES"] = visible
    return env


def settings(value):
    mode = value.get("mode", "ground-plane")
    if mode not in ("ground-plane", "moge-open3d"):
        raise ValueError("Unknown camera motion source")
    level = value.get("resolution_level", 0)
    if type(level) is not int or not 0 <= level <= 9:
        raise ValueError("MoGe resolution level must be 0–9")
    transform = value.get("cameraToBody")
    if transform is not None:
        transform = rigid(transform).tolist()
    return {"mode": mode, "resolution_level": level, "cameraToBody": transform}


class DepthMotion:
    """Called only on the camera metric executor; inference has no deadline.

    Uses a separate interpreter so Torch/model globals do not enter the gateway.
    The selected interpreter must contain OpenCV and the existing ComfyUI MoGe
    runtime. Its paths are host configuration, never supplied by robot traffic.
    """
    def __init__(self, instance):
        self.instance = instance
        self.process_handle = None

    def process(self, robot, epoch, counter, received, jpeg, timestamp, config):
        if self.process_handle is None:
            self.process_handle = subprocess.Popen(
                [os.environ.get("AINEKIO_DEPTH_PYTHON", sys.executable),
                 str(Path(__file__).with_name("depth_motion_worker.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
                env=worker_environment())
        request = dict(robot=robot, epoch=epoch, counter=counter,
                       received=received, timestamp=timestamp, instance=self.instance,
                       jpeg=base64.b64encode(jpeg).decode(), config=config)
        proc = self.process_handle
        proc.stdin.write(json.dumps(request, allow_nan=False)+"\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("Depth worker exited; disable/re-enable camera depth to reload it")
        result = json.loads(line)
        if "error" in result:
            raise ValueError(result["error"])
        return result

    def reset(self, robot):
        if self.process_handle is not None:
            proc = self.process_handle
            if proc.poll() is not None:
                self.close()
                return
            proc.stdin.write(json.dumps({"reset": robot})+"\n")
            proc.stdin.flush()
            if not proc.stdout.readline():
                raise RuntimeError("Depth worker exited")

    def close(self):
        if self.process_handle is not None:
            proc, self.process_handle = self.process_handle, None
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
            proc.wait()
            proc.stdout.close()
