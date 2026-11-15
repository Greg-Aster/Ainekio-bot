"""ONNX Runtime wrapper and hot-reload loader for the System 3 Presence Policy."""
from __future__ import annotations

import os
from pathlib import Path
import threading
from typing import Any
import numpy as np

from .contract import (
    EXPRESSION_MODES,
    PRESENCE_ACTION_DIM,
    PRESENCE_COMPLIANCE_DIM,
    PRESENCE_COMPLIANCE_STEP_MM,
    PRESENCE_EXPR_DIM,
    PRESENCE_FOOT_DIM,
    PRESENCE_FOOT_SCALE_MM,
    PRESENCE_OBS_SIZE,
    PRESENCE_SCHEMA,
    presence_foot_offsets,
    presence_model_footprint,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ACTIVE_POLICY = ROOT / "build/gateway/presence/active/policy.onnx"


def resolve_active_presence_policy() -> Path | None:
    override = os.environ.get("AINEKIO_PRESENCE_POLICY")
    if override is not None:
        if override.strip().lower() in ("", "0", "none", "off", "false"):
            return None
        candidate = Path(override)
        return candidate if candidate.exists() else None
    return DEFAULT_ACTIVE_POLICY if DEFAULT_ACTIVE_POLICY.exists() else None


class PresenceActor:
    """Deterministic ONNX inference for the P4-sized (128, 96) Autonomic Presence MLP."""

    def __init__(self, path: str | Path):
        import onnxruntime as ort

        self.path = Path(path).resolve()
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.environ.get("AINEKIO_PRESENCE_THREADS", "1"))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(self.path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.input = self.session.get_inputs()[0]
        self.output = self.session.get_outputs()[0]
        metadata = self.session.get_modelmeta().custom_metadata_map
        self.schema = metadata.get("ainekio_schema", PRESENCE_SCHEMA)
        in_shape = list(self.input.shape)
        out_shape = list(self.output.shape)
        if (
            self.schema != PRESENCE_SCHEMA
            or len(in_shape) != 2
            or in_shape[1] != PRESENCE_OBS_SIZE
            or len(out_shape) != 2
            or out_shape[1] != PRESENCE_ACTION_DIM
        ):
            raise ValueError(
                f"Presence ONNX {self.path} mismatch: schema={self.schema}, "
                f"in={in_shape}, out={out_shape}"
            )
        scale_str = metadata.get("ainekio_foot_scale_mm")
        if scale_str:
            self.foot_scale_mm = tuple(float(x) for x in scale_str.split(","))
        else:
            self.foot_scale_mm = PRESENCE_FOOT_SCALE_MM
        comp_str = metadata.get("ainekio_compliance_step_mm")
        self.compliance_step_mm = float(comp_str) if comp_str else PRESENCE_COMPLIANCE_STEP_MM
        dims_str = metadata.get("ainekio_hidden_dims")
        hidden = tuple(int(x) for x in dims_str.split(",")) if dims_str else (128, 96)
        self.footprint = {
            **presence_model_footprint(PRESENCE_OBS_SIZE, hidden, PRESENCE_ACTION_DIM),
            "onnx_file_bytes": self.path.stat().st_size,
            "policy_path": str(self.path),
        }

    def predict(self, observations) -> np.ndarray:
        values = np.asarray(observations, dtype=np.float32)
        single = values.ndim == 1
        batch = values[None, :] if single else values
        if batch.ndim != 2 or batch.shape[1] != PRESENCE_OBS_SIZE or not np.isfinite(batch).all():
            raise ValueError(f"Expected finite observation of width {PRESENCE_OBS_SIZE}")
        raw = np.concatenate(
            [self.session.run([self.output.name], {self.input.name: row[None, :]})[0] for row in batch],
            axis=0,
        )
        return raw[0] if single else raw

    def infer(self, observation_vec) -> tuple[list[float], list[float], list[float], str, float]:
        """Return (foot_norm_12, foot_offsets_mm_12, compliance_step_mm_12, expression_name, expression_confidence)."""
        out = self.predict(observation_vec)
        foot_norm = np.clip(out[:PRESENCE_FOOT_DIM], -1.0, 1.0).tolist()
        foot_mm = presence_foot_offsets(foot_norm, self.foot_scale_mm)
        comp_start = PRESENCE_FOOT_DIM
        comp_end = comp_start + PRESENCE_COMPLIANCE_DIM
        comp_norm = np.clip(out[comp_start:comp_end], -1.0, 1.0)
        comp_step_mm = (comp_norm * self.compliance_step_mm).tolist()
        logits = np.asarray(out[comp_end : comp_end + PRESENCE_EXPR_DIM], dtype=np.float64)
        shifted = logits - np.max(logits)
        probs = np.exp(shifted)
        probs /= np.sum(probs)
        best_idx = int(np.argmax(probs))
        return foot_norm, foot_mm, comp_step_mm, EXPRESSION_MODES[best_idx], float(probs[best_idx])


_SHARED_MANIFOLD_LOCK = threading.Lock()
_SHARED_MANIFOLDS: dict[str, Any] = {}


def _get_shared_manifold(env_json: Path | None):
    key = str(env_json.resolve()) if (env_json is not None and env_json.exists()) else "__default__"
    with _SHARED_MANIFOLD_LOCK:
        manifold = _SHARED_MANIFOLDS.get(key)
        if manifold is None:
            from experiments.freestyle.neural_pose.goals import PoseManifold

            manifold = PoseManifold(env_json) if (env_json is not None and env_json.exists()) else PoseManifold()
            _SHARED_MANIFOLDS[key] = manifold
        return manifold


class PresenceRuntime:
    """Lazy-cached ONNX presence policy + kinematics manifold with hot-reload on mtime change."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cached_key: tuple[str, int] | None = None
        self._actor: PresenceActor | None = None
        self._manifold = None

    def is_fresh(self) -> bool:
        if self._actor is None or self._manifold is None or self._cached_key is None:
            return False
        policy_path = resolve_active_presence_policy()
        if policy_path is None:
            return False
        try:
            stat = policy_path.resolve().stat()
        except OSError:
            return False
        return self._cached_key == (str(policy_path.resolve()), int(stat.st_mtime_ns))

    def load(self):
        with self._lock:
            policy_path = resolve_active_presence_policy()
            if policy_path is None:
                return None
            resolved = policy_path.resolve()
            stat = resolved.stat()
            key = (str(resolved), int(stat.st_mtime_ns))
            if self._cached_key != key or self._actor is None or self._manifold is None:
                actor = PresenceActor(resolved)
                env_json = resolved.parent / "environment.json"
                manifold = _get_shared_manifold(env_json if env_json.exists() else None)
                self._actor = actor
                self._manifold = manifold
                self._cached_key = key
            return self._actor, self._manifold
