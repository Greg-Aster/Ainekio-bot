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
        from .ground_plane import rigid
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
