"""Import an Orbax checkpoint or exported RTNeural JSON from Pupper MJX training on CPU only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

import numpy as np

from .artifacts import save_json


def load_json(path: str | Path):
    return json.loads(Path(path).read_text())

DEFAULT_NEURAL_GAIT_DIR = Path(__file__).resolve().parents[3] / "build/neural-gait"
DEFAULT_TEMPLATE_RUN = DEFAULT_NEURAL_GAIT_DIR / "pupper-mjx-200m"
DEFAULT_PUPPER_RL_VENV_PYTHON = Path(
    "/home/greggles/Ainekio/build/pupper-v3-upstream/pupperv3-monorepo/ai/rl/.venv/bin/python"
)


def _fold_in_normalization(kernel: np.ndarray, bias: np.ndarray, mean: np.ndarray, std: np.ndarray):
    a_prime = kernel / std[:, np.newaxis]
    b_prime = (bias - (kernel.T @ (mean / std)[:, np.newaxis]).T)[0]
    return a_prime, b_prime


def _restore_orbax_arrays_in_process(checkpoint_dir: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    import jax
    from orbax import checkpoint as ocp

    checkpoint_dir = checkpoint_dir.resolve()
    metadata = json.loads((checkpoint_dir / "_METADATA").read_text())["tree_metadata"]
    sharding = jax.sharding.SingleDeviceSharding(jax.devices("cpu")[0])
    restore_arg = ocp.ArrayRestoreArgs(restore_type=jax.Array, sharding=sharding)
    tree = [{}, {"params": {}}, {"params": {}}]
    for entry in metadata.values():
        keys = [k["key"] for k in entry["key_metadata"]]
        cursor = tree[int(keys[0])]
        for key in keys[1:-1]:
            cursor = cursor.setdefault(key, {})
        cursor[keys[-1]] = restore_arg

    checkpointer = ocp.PyTreeCheckpointer()
    try:
        restored = checkpointer.restore(checkpoint_dir, restore_args=tree)
    finally:
        checkpointer.close()

    mean = np.asarray(restored[0]["mean"], dtype=np.float32)
    std = np.asarray(restored[0]["std"], dtype=np.float32)
    params = {
        layer_name: {
            "kernel": np.asarray(layer_params["kernel"], dtype=np.float32),
            "bias": np.asarray(layer_params["bias"], dtype=np.float32),
        }
        for layer_name, layer_params in restored[1]["params"].items()
    }
    return mean, std, params


def _restore_orbax_arrays(checkpoint_dir: Path, rl_python: Path = DEFAULT_PUPPER_RL_VENV_PYTHON):
    checkpoint_dir = checkpoint_dir.resolve()
    try:
        os.environ.setdefault("JAX_PLATFORMS", "cpu")
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
        return _restore_orbax_arrays_in_process(checkpoint_dir)
    except ImportError:
        if not rl_python.exists():
            raise RuntimeError(f"Orbax is not installed in {sys.executable} and {rl_python} was not found")
        helper = (
            "import json, sys, numpy as np, jax; "
            "from pathlib import Path; "
            "from orbax import checkpoint as ocp; "
            "p = Path(sys.argv[1]).resolve(); "
            "meta = json.loads((p / '_METADATA').read_text())['tree_metadata']; "
            "sharding = jax.sharding.SingleDeviceSharding(jax.devices('cpu')[0]); "
            "arg = ocp.ArrayRestoreArgs(restore_type=jax.Array, sharding=sharding); "
            "tree = [{}, {'params': {}}, {'params': {}}]; "
            "for entry in meta.values():\n"
            "    keys = [k['key'] for k in entry['key_metadata']]\n"
            "    cur = tree[int(keys[0])]\n"
            "    for k in keys[1:-1]: cur = cur.setdefault(k, {})\n"
            "    cur[keys[-1]] = arg\n"
            "ck = ocp.PyTreeCheckpointer(); "
            "r = ck.restore(p, restore_args=tree); ck.close(); "
            "out = {'mean': np.asarray(r[0]['mean'], dtype=np.float32).tolist(), "
            "'std': np.asarray(r[0]['std'], dtype=np.float32).tolist(), "
            "'params': {k: {'kernel': np.asarray(v['kernel'], dtype=np.float32).tolist(), "
            "'bias': np.asarray(v['bias'], dtype=np.float32).tolist()} for k, v in r[1]['params'].items()}}; "
            "print(json.dumps(out))"
        )
        env = dict(os.environ, JAX_PLATFORMS="cpu", CUDA_VISIBLE_DEVICES="")
        proc = subprocess.run(
            [str(rl_python), "-c", helper, str(checkpoint_dir)],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        mean = np.asarray(payload["mean"], dtype=np.float32)
        std = np.asarray(payload["std"], dtype=np.float32)
        params = {
            k: {
                "kernel": np.asarray(v["kernel"], dtype=np.float32),
                "bias": np.asarray(v["bias"], dtype=np.float32),
            }
            for k, v in payload["params"].items()
        }
        return mean, std, params


def export_orbax_checkpoint_to_rtneural(
    checkpoint_dir: str | Path,
    template_policy_path: str | Path,
    *,
    rl_python: Path = DEFAULT_PUPPER_RL_VENV_PYTHON,
) -> dict:
    """Convert an Orbax checkpoint directory into an RTNeural JSON dict on CPU."""
    checkpoint_path = Path(checkpoint_dir).expanduser().resolve()
    template = load_json(Path(template_policy_path).expanduser().resolve())
    mean, std, params_dict = _restore_orbax_arrays(checkpoint_path, rl_python=rl_python)

    activation = template["layers"][0]["activation"] if template.get("layers") else "elu"
    final_activation = template["layers"][-1]["activation"] if template.get("layers") else "tanh"
    layers = []
    items = list(params_dict.items())
    input_size = int(mean.shape[0])
    for index, (_, layer_params) in enumerate(items):
        is_first = index == 0
        is_final = index == len(items) - 1
        kernel = layer_params["kernel"]
        bias = layer_params["bias"]
        if is_first:
            kernel, bias = _fold_in_normalization(kernel, bias, mean, std)
            input_size = int(kernel.shape[0])
        if is_final:
            half = bias.shape[-1] // 2
            bias = bias[:half]
            kernel = kernel[:, :half]
        layers.append(
            {
                "type": "dense",
                "activation": final_activation if is_final else activation,
                "shape": [None, int( len(bias) )],
                "weights": [kernel.tolist(), bias.tolist()],
            }
        )

    return {
        "use_imu": bool(template.get("use_imu", True)),
        "control_orientation": bool(template.get("control_orientation", True)),
        "observation_history": int(template.get("observation_history", 15)),
        "action_scale": template["action_scale"],
        "kp": template["kp"],
        "kd": template["kd"],
        "default_joint_pos": list(template["default_joint_pos"]),
        "joint_upper_limits": list(template["joint_upper_limits"]),
        "joint_lower_limits": list(template["joint_lower_limits"]),
        "maximum_pitch_command": float(template.get("maximum_pitch_command", 6.0)),
        "maximum_roll_command": float(template.get("maximum_roll_command", 6.0)),
        "in_shape": [None, input_size],
        "layers": layers,
    }


def import_pupper_mjx_run(
    source_path: str | Path,
    run_id: str,
    *,
    steps: int,
    neural_gait_dir: str | Path = DEFAULT_NEURAL_GAIT_DIR,
    template_run_dir: str | Path = DEFAULT_TEMPLATE_RUN,
    select: bool = False,
    hot_load_endpoint: str | None = None,
) -> dict:
    """Create or update a Pupper MJX run directory in neural_gait_dir on CPU."""
    source = Path(source_path).expanduser().resolve()
    root = Path(neural_gait_dir).expanduser().resolve()
    template_dir = Path(template_run_dir).expanduser().resolve()
    target_dir = root / run_id
    target_dir.mkdir(parents=True, exist_ok=True)

    template_manifest = load_json(template_dir / "manifest.json")
    template_policy_name = template_manifest.get("policy") or "policy_2026-11-05_20-13-42.json"
    template_policy_path = template_dir / template_policy_name

    for asset_name in ("environment.json", "ainekio-training-hardware.json", "ainekio-training.xml"):
        src_asset = template_dir / asset_name
        dst_asset = target_dir / asset_name
        if src_asset.exists() and src_asset.resolve() != dst_asset.resolve():
            shutil.copy2(src_asset, dst_asset)

    policy_filename = f"policy_step_{int(steps)}.json"
    orbax_name = None
    if source.is_dir() and (source / "_METADATA").exists():
        policy_dict = export_orbax_checkpoint_to_rtneural(source, template_policy_path)
        save_json(target_dir / policy_filename, policy_dict)
        orbax_name = source.name
    elif source.is_file() and source.suffix == ".json":
        policy_dict = load_json(source)
        save_json(target_dir / policy_filename, policy_dict)
    else:
        raise ValueError(f"Unsupported source path {source}: expected Orbax checkpoint directory or policy_*.json")

    checkpoint_id = f"step-{int(steps)}"
    manifest = dict(template_manifest)
    manifest.update(
        policy=policy_filename,
        orbax_checkpoint=orbax_name,
        steps=int(steps),
    )
    save_json(target_dir / "manifest.json", manifest)
    save_json(
        target_dir / "progress.json",
        {"state": "completed", "steps": int(steps), "imitation_updates": 0},
    )
    save_json(
        target_dir / "checkpoints.json",
        [
            {
                "id": checkpoint_id,
                "steps": int(steps),
                "policy": policy_filename,
                **({"orbax_checkpoint": orbax_name} if orbax_name else {}),
            }
        ],
    )

    if select:
        save_json(root / "selected.json", {"model_id": run_id, "checkpoint_id": checkpoint_id})

    hot_load_response = None
    if hot_load_endpoint:
        req = urllib.request.Request(
            f"{hot_load_endpoint.rstrip('/')}/load",
            data=json.dumps({"model_id": run_id, "checkpoint_id": checkpoint_id}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            hot_load_response = json.loads(resp.read().decode("utf-8"))

    return {
        "run_id": run_id,
        "checkpoint_id": checkpoint_id,
        "steps": int(steps),
        "target_dir": str(target_dir),
        "policy": policy_filename,
        "selected": bool(select or hot_load_response is not None),
        "hot_loaded": hot_load_response is not None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Orbax checkpoint directory or policy_*.json path")
    parser.add_argument("--run-id", required=True, help="Target run identifier under build/neural-gait")
    parser.add_argument("--steps", required=True, type=int, help="Total training steps for this checkpoint")
    parser.add_argument("--directory", default=str(DEFAULT_NEURAL_GAIT_DIR), help="Neural gait runs directory")
    parser.add_argument("--template-run", default=str(DEFAULT_TEMPLATE_RUN), help="Template run directory")
    parser.add_argument("--select", action="store_true", help="Write selected.json for this run")
    parser.add_argument("--hot-load", default=None, help="Optional neural gait HTTP endpoint (e.g. http://127.0.0.1:8797)")
    args = parser.parse_args(argv)

    result = import_pupper_mjx_run(
        args.source,
        args.run_id,
        steps=args.steps,
        neural_gait_dir=args.directory,
        template_run_dir=args.template_run,
        select=args.select,
        hot_load_endpoint=args.hot_load,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
