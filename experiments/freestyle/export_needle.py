"""Export the pinned Needle checkpoint, optionally merging its local LoRA."""
import argparse
from pathlib import Path


def export(checkpoint, base_archive, output, adapter=None):
    import jax.numpy as jnp
    from needle.model.architecture import ConfidenceHead, effective_kv_window
    from needle.model.checkpoints import read_adapter
    from needle.model.export import read_tokenizer_blob, write_export
    from needle.model.finetune import merge_lora
    from needle.model.quantize import WEIGHT_BITS
    from needle.model.run import load_checkpoint

    params, config = load_checkpoint(str(checkpoint))
    if adapter:
        fitted = read_adapter(str(adapter))
        lora = {tuple(k.split('/')): {n: jnp.asarray(v) for n, v in pair.items()}
                for k, pair in fitted['lora'].items()}
        params = merge_lora(params, lora, fitted['scale'])
    # Local training does not fit this head. Remove it from BOTH comparison
    # exports, following upstream's adapter-export behavior.
    params = {k: v for k, v in params.items() if k != ConfidenceHead.key}
    return write_export(params, config, str(output), bits=WEIGHT_BITS,
                        tokenizer=read_tokenizer_blob(str(base_archive)),
                        kv_window=effective_kv_window(config))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--base-archive', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--adapter', type=Path)
    a = p.parse_args()
    print(export(a.checkpoint, a.base_archive, a.output, a.adapter))
