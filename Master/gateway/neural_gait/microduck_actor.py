"""MicroDuck-exported Ainekio actor; no mjlab, BAM or simulator imports."""
import os
import numpy as np

from .contract import DEPTH_SCHEMA, OBSERVATION_SIZE, PROPRIO_SCHEMA, observation_size

SENSOR_GROUPS = {
    "joint_feedback": [(0, 24)],
    "imu": [(72, 82)],
    # Change measured motion/depth, never fixed intrinsics or availability flags.
    "camera": [(89, 92), (93, 94), (OBSERVATION_SIZE-12, OBSERVATION_SIZE-12+64)],
}


class MicroduckActor:
    def __init__(self, path):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.environ.get("AINEKIO_GAIT_INFERENCE_THREADS", "1"))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0]
        self.output = self.session.get_outputs()[0]
        metadata = self.session.get_modelmeta().custom_metadata_map
        self.schema = metadata.get("ainekio_schema")
        if (self.schema not in (DEPTH_SCHEMA, PROPRIO_SCHEMA)
                or self.input.shape != [1, observation_size(self.schema)] or self.output.shape != [1, 12]
                or metadata.get("ainekio_action") != "normalized-foot-offsets-v1"):
            raise ValueError("MicroDuck export does not match Ainekio's sensor/foot-action contract")

    def predict(self, observations, deterministic=True):
        if not deterministic:
            raise ValueError("The exported MicroDuck gait actor is deterministic")
        values = np.asarray(observations, np.float32)
        single = values.ndim == 1
        batch = values[None, :] if single else values
        if batch.ndim != 2 or batch.shape[1] != observation_size(self.schema) or not np.isfinite(batch).all():
            raise ValueError("Expected finite observations matching the exported Ainekio schema")
        action = np.concatenate([self.session.run([self.output.name], {self.input.name: row[None, :]})[0]
                                 for row in batch])
        # Exactly the same action-space boundary used by RslRlVecEnvWrapper.
        action = np.clip(action, -1., 1.)
        return (action[0] if single else action), None


def sensor_influence(actor, observations):
    """Counterfactual input sensitivity, not proof of useful physical reactions."""
    observations = np.asarray(observations, np.float32)
    baseline, _ = actor.predict(observations)
    result = {}
    groups = SENSOR_GROUPS
    if actor.schema == PROPRIO_SCHEMA:
        groups = {"joint_feedback": [(0,24)], "imu": [(24,33)]}
    for name, ranges in groups.items():
        differences = []
        for start, stop in ranges:
            for column in range(start, stop):
                changed = observations.copy()
                changed[:, column] += .05
                action, _ = actor.predict(changed)
                differences.append(float(np.max(np.abs(action-baseline))))
        result[name] = max(differences)
    return result
