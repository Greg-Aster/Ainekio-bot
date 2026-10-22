"""Export source-bound V2 gesture examples without changing production assets."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from runtime import JOINTS, MAX_FRAMES, SYSTEM, compact, messages, validate_packet


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def linear_knots(positions, times, required, tolerance_cd):
    """Fit the wire's linear interpolation, preserving source phase/reversal knots.

    Error is checked at every source sample against rounded integer targets.
    No continuous cubic error bound or physical tracking claim is implied.
    """
    rounded = [[round(v) for v in row] for row in positions]
    knots = set(required) | {0, len(positions)-1}
    ordered = sorted(knots)
    pending = list(zip(ordered, ordered[1:]))
    while pending:
        left, right = pending.pop()
        worst, index = tolerance_cd, None
        for at in range(left+1, right):
            u = (times[at]-times[left])/(times[right]-times[left])
            error = max(abs(rounded[left][j] + u*(rounded[right][j]-rounded[left][j])
                            - positions[at][j]) for j in range(12))
            if error > worst:
                worst, index = error, at
        if index is not None:
            knots.add(index)
            pending.extend(((left, index), (index, right)))
    return sorted(knots), rounded


def frames_for_clip(clip, compiler):
    positions = clip["positions"]
    times = [round(i*1000/120) for i in range(len(positions))]
    required = compiler.gesture_targets(positions, clip["phases"])
    knots, rounded = linear_knots(positions, times, required, .5)
    frames = [[times[b]-times[a], rounded[b]] for a, b in zip(knots, knots[1:])]
    return rounded[0], frames, {"source_samples": len(positions), "linear_targets": len(frames),
                              "phase_reversal_knots": len(required), "duration_ms": times[-1],
                              "source_sample_error_bound_deg": .005,
                              "timestamp_rounding_bound_ms": .5,
                              "continuous_path_equivalence_verified": False}


def load_compiler(root):
    spec = importlib.util.spec_from_file_location("freestyle_source_compiler", root/"tools/compile_clips.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def export(root, destination, evaluation_commands):
    compiler = load_compiler(root)
    clips = compiler.load_gestures(root)  # Existing source hashes, units and order checks.
    names = {clip["command"] for clip in clips}
    if not evaluation_commands or not evaluation_commands < names:
        raise ValueError("Select existing evaluation motions while retaining training motions")
    model = json.loads((root/"model.json").read_text())
    if tuple(j["name"] for j in model["joints"]) != JOINTS:
        raise ValueError("Model and V2 physical joint order disagree")
    body = {"model": model["model"], "geometry_id": model["joint_map"], "joint_map": 2,
            "angle_units": "signed_model_centidegrees", "joint_order": list(JOINTS),
            "joints": [{k: j[k] for k in ("id", "name", "positive_body_axis")} for j in model["joints"]]}
    records = {"train": [], "evaluation": []}
    source_hashes, report = {}, []
    for clip in clips:
        name = clip["command"]
        source = root/"motions/gestures"/name/"source.json"
        source_id = "gesture:"+name
        source_hashes[source_id] = digest(source)
        first, frames, metrics = frames_for_clip(clip, compiler)
        split = "evaluation" if name in evaluation_commands else "train"
        phrases = ["Perform " + name.replace("_", " ") + ".",
                   "Show me the " + name.replace("_", " ") + " movement.",
                   "Please do " + name.replace("_", " ") + "."]
        if name == "lay_down":
            phrases[2] = "Go to sleep."
        for variant, phrase in enumerate(phrases):
            previous, elapsed = first, 0
            for chunk, offset in enumerate(range(0, len(frames), MAX_FRAMES)):
                packet_frames = frames[offset:offset+MAX_FRAMES]
                packet = validate_packet({"frames": packet_frames,
                                          "complete": offset+len(packet_frames) == len(frames), "end": "hold"})
                request = {"request": phrase, "body": body,
                           "observation": {"commanded_joints_cd": previous, "measured_joints_cd": None,
                                           "source": "authored_reference_not_hardware"},
                           "progress": {"packet_index": chunk, "reference_elapsed_ms": elapsed},
                           "event": None}
                records[split].append({"id": f"{name}:{variant}:{chunk}",
                    "messages": messages(request)+[{"role": "assistant", "content": compact(packet)}],
                    "metadata": {"sourceIds": [source_id], "sourceHashes": {source_id: source_hashes[source_id]},
                                 "mode": "freestyle", "objective": "assistant-continuation", "targetAuthor": "assistant",
                                 "motion_family": name, "packet_index": chunk,
                                 "hardware_qualified": False, "recovery_demonstration": False,
                                 "language_variant": "synthetic", "timing": "original_source_not_retimed_firmware"}})
                previous = packet_frames[-1][1]
                elapsed += sum(f[0] for f in packet_frames)
        report.append({"motion": name, "split": split, "packets": (len(frames)+MAX_FRAMES-1)//MAX_FRAMES,
                       **metrics})
    destination.mkdir(parents=True, exist_ok=False)
    for split, rows in records.items():
        (destination/(split+".jsonl")).write_text("".join(compact(row)+"\n" for row in rows))
    manifest = {"version": 2, "supervision": "final-assistant-only",
                "baseModel": "unsloth/Qwen3.5-0.8B", "systemPrompt": SYSTEM,
                "settings": {"objective": "assistant-continuation"}, "sourceHashes": source_hashes,
                "bodyModelSha256": digest(root/"model.json"),
                "splitPolicy": "whole motion family; all paraphrases and packets stay together",
                "scope": "authored motion reproduction; no measured recovery training"}
    for split, rows in records.items():
        manifest[split] = {"count": len(rows), "sha256": digest(destination/(split+".jsonl")),
                           "sourceIds": sorted({i for r in rows for i in r["metadata"]["sourceIds"]})}
    manifest["datasetId"] = hashlib.sha256(compact(manifest).encode()).hexdigest()
    (destination/"manifest.json").write_text(compact(manifest)+"\n")
    (destination/"source-report.json").write_text(json.dumps(report, indent=2)+"\n")
    return {"directory": str(destination), "motions": len(clips),
            "train_examples": len(records["train"]), "evaluation_examples": len(records["evaluation"]),
            "recovery_examples": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New experiment artifact directory")
    parser.add_argument("--evaluation-commands", nargs="+", required=True)
    args = parser.parse_args()
    print(compact(export(args.model_root, args.output, set(args.evaluation_commands))))
