"""Measure exact native tokenization and prepare the existing trainer's config.

This loads a tokenizer, not model weights. The caller supplies the shared text
trainer path; the experiment never edits MetaHuman or its model assignments.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from runtime import compact


def prepare(dataset, trainer_path, base, revision):
    from transformers import AutoTokenizer
    spec = importlib.util.spec_from_file_location("freestyle_shared_trainer", trainer_path)
    trainer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trainer)
    tokenizer = AutoTokenizer.from_pretrained(base, revision=revision)
    manifest = json.loads((dataset/"manifest.json").read_text())
    config = {"owner": "freestyle-experiment", "base_model": base,
              "base_model_revision": revision, "training_mode": "lora", "chat_template": "native",
              "train_on_responses_only": True, "load_in_4bit": False, "load_in_16bit": True,
              "dtype": "bfloat16", "lora_rank": 16, "lora_alpha": 32, "lora_dropout": 0,
              "num_train_epochs": 3, "per_device_train_batch_size": 1,
              "per_device_eval_batch_size": 1, "gradient_accumulation_steps": 8,
              "learning_rate": .00012, "optimizer": "paged_adamw_8bit", "seed": 42,
              "gguf_conversion": {"enabled": False}}
    if base != manifest["baseModel"]:
        raise ValueError("Base must match the frozen dataset manifest")
    measurements = []
    splits = [name for name in ('train', 'evaluation', 'test', 'regression-evaluation',
                                'recovery-probe', 'stand-evaluation', 'stand-test')
              if (dataset/(name+'.jsonl')).exists()]
    for split in splits:
        for row in trainer.read_rows(dataset/(split+".jsonl")):
            tokens = trainer.tokenize_row(tokenizer, row, None)
            measurements.append({"id": row["id"], "split": split,
                                 "tokens": len(tokens["input_ids"]),
                                 "response_tokens": sum(v != -100 for v in tokens["labels"])})
    config["max_seq_length"] = max(row["tokens"] for row in measurements)
    # Serialized-artifact evaluation has room for every complete reference;
    # serving requests impose no application token cap.
    config["generation_max_new_tokens"] = config["max_seq_length"]
    trainer.validate_config(config)
    trainer.verify_manifest(dataset/"manifest.json", dataset/"train.jsonl", dataset/"evaluation.jsonl", config)
    (dataset/"training-config.json").write_text(compact(config)+"\n")
    report = {"examples": len(measurements), "max_sequence_tokens": config["max_seq_length"],
              "max_response_tokens": max(row["response_tokens"] for row in measurements),
              "base_revision": revision, "truncated_examples": 0, "records": measurements}
    report['folds'] = {split: {'count': sum(r['split']==split for r in measurements),
                              'max_tokens': max((r['tokens'] for r in measurements if r['split']==split), default=0)}
                       for split in splits}
    (dataset/"token-report.json").write_text(compact(report)+"\n")
    return {k: v for k, v in report.items() if k != "records"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--trainer", type=Path, required=True)
    parser.add_argument("--base", default="unsloth/Qwen3.5-0.8B")
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    print(compact(prepare(args.dataset, args.trainer, args.base, args.revision)))
