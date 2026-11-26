"""Compile quantized V1 8-DOF MicroDuck policy weights for on-chip ESP32-P4 control.

Standard Python only so both host CMake and ESP-IDF builds run without extra packages.
Imports a trained V1 policy.onnx (540 -> 128 -> 64 -> 32 -> 8, ELU/Tanh) into:
  - Slave/software/models/v1-8servo/motions/microduck/policy.bin
  - Slave/software/models/v1-8servo/motions/microduck/manifest.json
  - Slave/software/models/v1-8servo/motions/microduck/v1_microduck_data.c
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

OBS_SIZE = 304
MAX_H0 = 128
MAX_H1 = 64
MAX_H2 = 32
ACTIONS = 8


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    val = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, pos
        shift += 7


def _parse_fields(buf: bytes):
    pos = 0
    n = len(buf)
    while pos < n:
        tag, pos = _read_varint(buf, pos)
        field, wtype = tag >> 3, tag & 7
        if wtype == 0:
            val, pos = _read_varint(buf, pos)
        elif wtype == 1:
            val = buf[pos : pos + 8]
            pos += 8
        elif wtype == 2:
            ln, pos = _read_varint(buf, pos)
            val = buf[pos : pos + ln]
            pos += ln
        elif wtype == 5:
            val = buf[pos : pos + 4]
            pos += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wtype}")
        yield field, wtype, val


def load_onnx_tensors(
    onnx_path: Path,
) -> tuple[dict[str, tuple[list[int], list[float]]], dict[str, str]]:
    data = onnx_path.read_bytes()
    tensors: dict[str, tuple[list[int], list[float]]] = {}
    meta: dict[str, str] = {}
    for f, _, v in _parse_fields(data):
        if f == 14:  # metadata_props
            k = ""
            val = ""
            for mf, mw, mv in _parse_fields(v):
                if mf == 1 and mw == 2:
                    k = mv.decode("utf-8")
                elif mf == 2 and mw == 2:
                    val = mv.decode("utf-8")
            if k:
                meta[k] = val
        elif f == 7:  # graph
            for gf, _, gv in _parse_fields(v):
                if gf == 5:  # initializer
                    dims: list[int] = []
                    name = ""
                    raw = None
                    floats: list[float] = []
                    for tf, tw, tv in _parse_fields(gv):
                        if tf == 1 and tw == 0:
                            dims.append(int(tv))
                        elif tf == 4 and tw == 2:
                            count = len(tv) // 4
                            floats.extend(struct.unpack(f"<{count}f", tv))
                        elif tf == 4 and tw == 5:
                            floats.append(struct.unpack("<f", tv)[0])
                        elif tf == 8 and tw == 2:
                            name = tv.decode("utf-8")
                        elif tf == 9 and tw == 2:
                            raw = tv
                    if raw is not None:
                        count = len(raw) // 4
                        vals = list(struct.unpack(f"<{count}f", raw))
                    else:
                        vals = floats
                    tensors[name] = (dims, vals)
    return tensors, meta


def quantize_matrix(values: list[float], rows: int, cols: int) -> tuple[bytes, list[float]]:
    if len(values) != rows * cols:
        raise ValueError(f"Expected {rows * cols} weights, got {len(values)}")
    q_bytes = bytearray(rows * cols)
    scales: list[float] = []
    for r in range(rows):
        row = values[r * cols : (r + 1) * cols]
        max_abs = 0.0
        for x in row:
            if not math.isfinite(x):
                raise ValueError("Non-finite weight in V1 MicroDuck ONNX export")
            ax = abs(x)
            if ax > max_abs:
                max_abs = ax
        if max_abs == 0.0:
            scales.append(1.0)
            continue
        scale = max_abs / 127.0
        scales.append(scale)
        base = r * cols
        for c, x in enumerate(row):
            q = int(round(x / scale))
            if q < -127:
                q = -127
            elif q > 127:
                q = 127
            q_bytes[base + c] = q & 0xFF
    return bytes(q_bytes), scales


def _pick_tensor(tensors: dict[str, tuple[list[int], list[float]]], candidates: tuple[str, ...]):
    for key in candidates:
        if key in tensors:
            return tensors[key]
    raise KeyError(f"None of {candidates} found in ONNX initializers: {sorted(tensors.keys())}")


def import_onnx(
    onnx_path: Path,
    root: Path,
    action_scale_deg: tuple[float, float] = (45.0, 90.0),
) -> None:
    tensors, meta = load_onnx_tensors(onnx_path)
    _, obs_mean = _pick_tensor(tensors, ("obs_normalizer._mean", "obs_mean"))
    _, obs_std = _pick_tensor(tensors, ("obs_normalizer._std", "obs_std", "onnx::Div_25"))
    if len(obs_mean) != OBS_SIZE or len(obs_std) != OBS_SIZE:
        raise ValueError(f"Unexpected obs normalizer size {len(obs_mean)}/{len(obs_std)}, expected {OBS_SIZE}")

    w0_dims, w0 = _pick_tensor(tensors, ("mlp.0.weight", "actor.0.weight"))
    _, b0 = _pick_tensor(tensors, ("mlp.0.bias", "actor.0.bias"))
    w1_dims, w1 = _pick_tensor(tensors, ("mlp.2.weight", "actor.2.weight"))
    _, b1 = _pick_tensor(tensors, ("mlp.2.bias", "actor.2.bias"))
    w2_dims, w2 = _pick_tensor(tensors, ("mlp.4.weight", "actor.4.weight"))
    _, b2 = _pick_tensor(tensors, ("mlp.4.bias", "actor.4.bias"))
    w3_dims, w3 = _pick_tensor(tensors, ("mlp.6.weight", "actor.6.weight"))
    _, b3 = _pick_tensor(tensors, ("mlp.6.bias", "actor.6.bias"))

    h0, in0 = w0_dims
    h1, in1 = w1_dims
    h2, in2 = w2_dims
    out3, in3 = w3_dims
    if in0 != OBS_SIZE or in1 != h0 or in2 != h1 or in3 != h2 or out3 != ACTIONS:
        raise ValueError(f"Incompatible MLP dims: {w0_dims} -> {w1_dims} -> {w2_dims} -> {w3_dims}")
    if h0 > MAX_H0 or h1 > MAX_H1 or h2 > MAX_H2:
        raise ValueError(f"Hidden dims ({h0}, {h1}, {h2}) exceed max ({MAX_H0}, {MAX_H1}, {MAX_H2})")

    q0, s0 = quantize_matrix(w0, h0, OBS_SIZE)
    q1, s1 = quantize_matrix(w1, h1, h0)
    q2, s2 = quantize_matrix(w2, h2, h1)
    q3, s3 = quantize_matrix(w3, ACTIONS, h2)

    dest_dir = root / "motions" / "microduck"
    dest_dir.mkdir(parents=True, exist_ok=True)
    bin_path = dest_dir / "policy.bin"
    with bin_path.open("wb") as f:
        f.write(struct.pack(f"<{OBS_SIZE}f", *obs_mean))
        f.write(struct.pack(f"<{OBS_SIZE}f", *obs_std))
        f.write(struct.pack(f"<{h0}f", *s0))
        f.write(struct.pack(f"<{h0}f", *b0))
        f.write(q0)
        f.write(struct.pack(f"<{h1}f", *s1))
        f.write(struct.pack(f"<{h1}f", *b1))
        f.write(q1)
        f.write(struct.pack(f"<{h2}f", *s2))
        f.write(struct.pack(f"<{h2}f", *b2))
        f.write(q2)
        f.write(struct.pack(f"<{ACTIONS}f", *s3))
        f.write(struct.pack(f"<{ACTIONS}f", *b3))
        f.write(q3)

    manifest = {
        "schema": meta.get("ainekio_schema", "ainekio-v1-neural-gait-v2-cpg"),
        "action": meta.get("ainekio_action", "normalized-joint-deg-v1"),
        "source_onnx_sha256": hashlib.sha256(onnx_path.read_bytes()).hexdigest(),
        "policy_bin_sha256": hashlib.sha256(bin_path.read_bytes()).hexdigest(),
        "hidden_dims": [h0, h1, h2],
        "action_scale_deg": [float(action_scale_deg[0]), float(action_scale_deg[1])],
    }
    (dest_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def _fmt_floats(values: list[float] | tuple[float, ...], per_line: int = 12) -> str:
    parts = [f"{v:.9g}" for v in values]
    lines = [",".join(parts[i : i + per_line]) for i in range(0, len(parts), per_line)]
    return "{\n" + ",\n".join(lines) + "\n}"


def _fmt_int8_rows(raw: bytes, rows: int, cols: int) -> str:
    row_strs: list[str] = []
    for r in range(rows):
        vals = struct.unpack_from(f"<{cols}b", raw, r * cols)
        row_strs.append("{" + ",".join(str(x) for x in vals) + "}")
    return "{\n" + ",\n".join(row_strs) + "\n}"


def generate(root: Path, out: Path) -> None:
    src_dir = root / "motions" / "microduck"
    manifest = json.loads((src_dir / "manifest.json").read_text())
    bin_bytes = (src_dir / "policy.bin").read_bytes()
    if hashlib.sha256(bin_bytes).hexdigest() != manifest["policy_bin_sha256"]:
        raise ValueError("policy.bin SHA-256 mismatch with manifest.json")
    h0, h1, h2 = (int(x) for x in manifest["hidden_dims"])
    action_scale = [float(x) for x in manifest["action_scale_deg"]]

    pos = 0
    obs_mean = struct.unpack_from(f"<{OBS_SIZE}f", bin_bytes, pos); pos += OBS_SIZE * 4
    obs_std = struct.unpack_from(f"<{OBS_SIZE}f", bin_bytes, pos); pos += OBS_SIZE * 4
    s0 = struct.unpack_from(f"<{h0}f", bin_bytes, pos); pos += h0 * 4
    b0 = struct.unpack_from(f"<{h0}f", bin_bytes, pos); pos += h0 * 4
    q0 = bin_bytes[pos : pos + h0 * OBS_SIZE]; pos += h0 * OBS_SIZE
    s1 = struct.unpack_from(f"<{h1}f", bin_bytes, pos); pos += h1 * 4
    b1 = struct.unpack_from(f"<{h1}f", bin_bytes, pos); pos += h1 * 4
    q1 = bin_bytes[pos : pos + h1 * h0]; pos += h1 * h0
    s2 = struct.unpack_from(f"<{h2}f", bin_bytes, pos); pos += h2 * 4
    b2 = struct.unpack_from(f"<{h2}f", bin_bytes, pos); pos += h2 * 4
    q2 = bin_bytes[pos : pos + h2 * h1]; pos += h2 * h1
    s3 = struct.unpack_from(f"<{ACTIONS}f", bin_bytes, pos); pos += ACTIONS * 4
    b3 = struct.unpack_from(f"<{ACTIONS}f", bin_bytes, pos); pos += ACTIONS * 4
    q3 = bin_bytes[pos : pos + ACTIONS * h2]; pos += ACTIONS * h2

    c_src = f"""/* Generated by tools/compile_v1_microduck.py. Do not edit by hand.
 * Source ONNX SHA-256: {manifest["source_onnx_sha256"]}
 * Policy BIN SHA-256:  {manifest["policy_bin_sha256"]}
 */
#include "ainekio/v1_model.h"

const ainekio_v1_microduck_model_t ainekio_v1_microduck_default_model = {{
    .h0 = {h0}U,
    .h1 = {h1}U,
    .h2 = {h2}U,
    .trained = true,
    .obs_mean = {_fmt_floats(obs_mean)},
    .obs_std = {_fmt_floats(obs_std)},
    .weight0_q = {_fmt_int8_rows(q0, h0, OBS_SIZE)},
    .scale0 = {_fmt_floats(s0)},
    .bias0 = {_fmt_floats(b0)},
    .weight1_q = {_fmt_int8_rows(q1, h1, h0)},
    .scale1 = {_fmt_floats(s1)},
    .bias1 = {_fmt_floats(b1)},
    .weight2_q = {_fmt_int8_rows(q2, h2, h1)},
    .scale2 = {_fmt_floats(s2)},
    .bias2 = {_fmt_floats(b2)},
    .weight3_q = {_fmt_int8_rows(q3, ACTIONS, h2)},
    .scale3 = {_fmt_floats(s3)},
    .bias3 = {_fmt_floats(b3)},
    .action_scale_deg = {{{action_scale[0]:.9g}, {action_scale[1]:.9g}}},
}};
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(c_src)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--import-onnx", type=Path, help="Import trained V1 ONNX into motions/microduck/")
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--out", type=Path, help="Output C file (defaults to <root>/motions/microduck/v1_microduck_data.c)")
    p.add_argument("--hip-scale-deg", type=float, default=45.0)
    p.add_argument("--knee-scale-deg", type=float, default=90.0)
    args = p.parse_args()
    if args.import_onnx:
        import_onnx(args.import_onnx, args.root, (args.hip_scale_deg, args.knee_scale_deg))
    out = args.out or (args.root / "motions" / "microduck" / "v1_microduck_data.c")
    generate(args.root, out)
    print(f"Generated {out}")


if __name__ == "__main__":
    main()
