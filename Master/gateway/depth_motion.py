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


def frame_attitude(samples, metadata):
    """Interpolate device-clock attitude at CSI completion, never receipt time."""
    import numpy as np
    metadata = metadata or {}
    stamp, boot = metadata.get("frame_completed_us"), metadata.get("boot_id")
    base = dict(available=False, frame_completed_us=stamp, boot_id=boot,
                time_basis="csi-transfer-completion", exposure_alignment_verified=False)
    if type(stamp) is not int or stamp <= 0 or type(boot) is not int or boot < 0:
        return dict(base, reason="Camera has no device frame completion timestamp/boot identity")
    before = after = None
    for sample in samples:
        if sample.get("boot_id") != boot:
            continue
        t = sample.get("timestamp_us")
        if type(t) is not int:
            continue
        if t <= stamp:
            before = sample
        if t >= stamp:
            after = sample
            break
    if before is None or after is None:
        return dict(base, reason="No same-boot IMU samples bracket camera frame completion")
    if any(not s.get("available") for s in (before,after)):
        return dict(base, reason="Camera IMU bracket contains unavailable fused attitude")
    q = np.asarray([s.get("orientation_wxyz") for s in (before,after)], dtype=float)
    if q.shape != (2,4) or not np.isfinite(q).all() or np.any(np.linalg.norm(q,axis=1) == 0):
        return dict(base, reason="Camera IMU bracket has invalid quaternion")
    q /= np.linalg.norm(q,axis=1)[:,None]
    dot = float(q[0] @ q[1])
    if dot < 0:
        q[1] *= -1; dot = -dot
    interval = after["timestamp_us"]-before["timestamp_us"]
    fraction = (stamp-before["timestamp_us"])/interval if interval else 0.
    angle = np.arccos(np.clip(dot,-1,1))
    if abs(np.sin(angle)) < 1e-8:
        value = (1-fraction)*q[0]+fraction*q[1]
    else:
        value = (np.sin((1-fraction)*angle)*q[0]+np.sin(fraction*angle)*q[1])/np.sin(angle)
    value /= np.linalg.norm(value)
    return dict(base, available=True, orientation_wxyz=value.tolist(),
                bracket_us=[before["timestamp_us"],after["timestamp_us"]],
                bracket_quality=[{key:s.get(key) for key in ("fresh","startup","gyro_recovery",
                    "acceleration_recovery","accelerometer_ignored")} for s in (before,after)])


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

    def process(self, robot, epoch, counter, received, jpeg, timestamp, config, attitude=None):
        if self.process_handle is not None and self.process_handle.poll() is not None:
            self.close()
        if self.process_handle is None:
            self.process_handle = subprocess.Popen(
                [os.environ.get("AINEKIO_DEPTH_PYTHON", sys.executable),
                 str(Path(__file__).with_name("depth_motion_worker.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
                env=worker_environment())
        request = dict(robot=robot, epoch=epoch, counter=counter,
                       received=received, timestamp=timestamp, instance=self.instance,
                       jpeg=base64.b64encode(jpeg).decode(), config=config, attitude=attitude)
        proc = self.process_handle
        proc.stdin.write(json.dumps(request, allow_nan=False)+"\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("Depth worker exited before returning a measurement")
        result = json.loads(line)
        if "error" in result:
            raise ValueError(result["error"])
        return result

    def range(self, frame_id, point, source_frame=None):
        if self.process_handle is not None and self.process_handle.poll() is not None:
            self.close()
        if self.process_handle is None:
            return {"available": False, "reason": "Depth worker has no retained camera frame"}
        request = {"range": {"frameId": frame_id, "point": point, "sourceFrame": source_frame, "instance": self.instance}}
        proc = self.process_handle
        proc.stdin.write(json.dumps(request, allow_nan=False)+"\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("Depth worker exited before returning a range measurement")
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
