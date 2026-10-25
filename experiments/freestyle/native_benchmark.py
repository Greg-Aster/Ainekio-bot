"""Compare persisted native adapter output with GGUF results; never dispatch."""
import argparse
import importlib.util
import json
import time
from pathlib import Path

from continue_training import align_qwen_mlp


def run(config, adapter, data, contract, output, shared_trainer, context_tokens):
    spec = importlib.util.spec_from_file_location('freestyle_shared_trainer', shared_trainer)
    shared = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shared)
    cfg = shared.validate_config(json.loads(config.read_text()))
    cfg['max_seq_length'] = context_tokens
    model, tokenizer, torch = shared.load_runtime(cfg, adapter)
    from unsloth import FastModel
    underlying = model.get_base_model() if hasattr(model, 'get_base_model') else model
    model.config.architectures = [type(underlying).__name__]
    FastModel.for_inference(model)
    runtime_adjustments = align_qwen_mlp(model, torch)
    system = (contract / 'system.txt').read_text()
    with output.open('x') as stream:
        for line in data.read_text().splitlines():
            row = json.loads(line)
            prompt = tokenizer.apply_chat_template(
                ([{'role':'system','content':system}] if system else [])+[{'role':'user','content':row['query']}],
                tokenize=False, add_generation_prompt=True, enable_thinking=False)
            encoded = tokenizer(prompt, add_special_tokens=False, return_tensors='pt')
            encoded = {key: value.to(model.device) for key, value in encoded.items()}
            length = encoded['input_ids'].shape[1]
            torch.cuda.synchronize()
            started = time.perf_counter()
            with torch.inference_mode():
                tokens = model.generate(**encoded, max_new_tokens=context_tokens-length,
                    do_sample=False, eos_token_id=tokenizer.eos_token_id,
                    pad_token_id=tokenizer.pad_token_id)[0, length:]
            torch.cuda.synchronize()
            elapsed = time.perf_counter()-started
            text = tokenizer.decode(tokens, skip_special_tokens=True)
            try:
                program = json.loads(text)
            except ValueError:
                program = None
            result = {'id': row['id'], 'family': row['family'], 'program': program,
                      'expected': row['answers'], 'exact': program == row['answers'],
                      'raw': text, 'elapsed_s': elapsed, 'output_tokens': len(tokens),
                      'ended_with_eos': bool(len(tokens) and tokens[-1].item() == tokenizer.eos_token_id),
                      'context_capacity_tokens': context_tokens, 'execution': 'not_dispatched',
                      'adapter_sha256': shared.digest(adapter / 'adapter_model.safetensors'),
                      'dataset_sha256': shared.digest(data), 'backend': 'native-unsloth'}
            result['runtime_adjustments'] = runtime_adjustments
            stream.write(json.dumps(result, separators=(',', ':'))+'\n')
            stream.flush()
            print(json.dumps({k: result[k] for k in ('family', 'exact', 'elapsed_s', 'ended_with_eos')}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'adapter', 'data', 'contract', 'output', 'shared-trainer'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--context-tokens', type=int, required=True,
                   help='Same total context capacity as the compared serving slot')
    run(**vars(p.parse_args()))
