"""ONNX runtime wrapper for the 50 Hz Neural Pose & Emote Policy on host."""
from __future__ import annotations

import os
from pathlib import Path
import numpy as np

from .contract import POSE_FOOT_SCALE_MM, POSE_OBS_SIZE, POSE_SCHEMA, pose_foot_offsets


class NeuralPoseActor:
    """Deterministic ONNX inference for the (512, 256, 128) Neural Pose & Emote MLP."""

    def __init__(self, path: str | Path):
        import onnxruntime as ort

        self.path = Path(path).resolve()
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.environ.get("AINEKIO_POSE_INFERENCE_THREADS", "2"))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(self.path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.input = self.session.get_inputs()[0]
        self.output = self.session.get_outputs()[0]
        metadata = self.session.get_modelmeta().custom_metadata_map
        self.schema = metadata.get("ainekio_schema", POSE_SCHEMA)
        if (
            self.schema != POSE_SCHEMA
            or list(self.input.shape) != [1, POSE_OBS_SIZE]
            or list(self.output.shape) != [1, 12]
        ):
            raise ValueError(
                f"Neural pose ONNX {self.path} mismatch: schema={self.schema}, "
                f"in={self.input.shape}, out={self.output.shape}"
            )
        scale_str = metadata.get("ainekio_foot_scale_mm")
        if scale_str:
            self.foot_scale_mm = tuple(float(x) for x in scale_str.split(","))
        else:
            self.foot_scale_mm = POSE_FOOT_SCALE_MM

    def predict(self, observations, deterministic: bool = True):
        if not deterministic:
            raise ValueError("Exported NeuralPoseActor is deterministic")
        values = np.asarray(observations, dtype=np.float32)
        single = values.ndim == 1
        batch = values[None, :] if single else values
        if batch.ndim != 2 or batch.shape[1] != POSE_OBS_SIZE or not np.isfinite(batch).all():
            raise ValueError(f"Expected finite observation of width {POSE_OBS_SIZE}")
        outputs = np.concatenate(
            [self.session.run([self.output.name], {self.input.name: row[None, :]})[0] for row in batch],
            axis=0,
        )
        outputs = np.clip(outputs, -1.0, 1.0)
        return (outputs[0] if single else outputs), None

    def infer_feet_mm(self, observation_vec) -> tuple[list[float], list[float]]:
        action, _ = self.predict(observation_vec, deterministic=True)
        act_list = action.tolist()
        return act_list, pose_foot_offsets(act_list, self.foot_scale_mm)
