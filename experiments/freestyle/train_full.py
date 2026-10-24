"""Continue a Freestyle checkpoint by updating every Qwen weight.

The starting point is the pinned pretrained model with the selected prior
LoRA merged into it. This keeps the starting weights comparable with the
corresponding LoRA continuation run. Only experimental artifacts are written.
"""

import argparse
import hashlib
import importlib.util
import json
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from continue_training import align_qwen_mlp


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def train(config, data, evaluation, manifest, initial_adapter, output, shared_trainer):
    spec = importlib.util.spec_from_file_location('freestyle_shared_trainer', shared_trainer)
    shared = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shared)
    cfg = shared.validate_config(json.loads(config.read_text()))
    if cfg['training_mode'] not in ('full', 'full_finetune'):
        raise ValueError('Full-weight experiment requires training_mode=full_finetune')
    provenance = shared.verify_manifest(manifest, data, evaluation, cfg)
    output.mkdir(parents=True, exist_ok=False)
    report = output / 'training-result.json'
    result = {
        'status': 'running', 'training_mode': 'full_finetune',
        'initial_adapter': str(initial_adapter),
        'initial_adapter_sha256': sha(initial_adapter / 'adapter_model.safetensors'),
        'initialization': 'pinned_base_with_prior_adapter_merged',
        'config_sha256': sha(config), 'dataset_id': provenance['datasetId'],
        'base_model': cfg['base_model'], 'base_revision': cfg['base_model_revision'],
        'shared_trainer_sha256': sha(shared_trainer), 'trainer_sha256': sha(__file__),
        'activation': 'not-activated', 'physical_trials': 0,
    }

    def save():
        report.write_text(json.dumps(result, indent=2) + '\n')

    started = time.time()
    save()
    try:
        model, tokenizer, torch = shared.load_runtime(cfg, training=True)
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, str(initial_adapter), is_trainable=False)
        model = model.merge_and_unload(safe_merge=True)
        for parameter in model.parameters():
            parameter.requires_grad_(True)
        result['trainable_parameters'] = sum(p.numel() for p in model.parameters() if p.requires_grad)
        result['total_parameters'] = sum(p.numel() for p in model.parameters())
        result['runtime_adjustments'] = align_qwen_mlp(model, torch)
        result['initial_weights'] = 'prior LoRA merged directly into pinned unquantized base'
        training = shared.tokenize_rows(tokenizer, shared.read_rows(data), cfg)
        testing = shared.tokenize_rows(tokenizer, shared.read_rows(evaluation), cfg)
        result.update(training_samples=len(training), evaluation_samples=len(testing),
                      supervised_tokens=sum(sum(label != -100 for label in row['labels'])
                                            for row in training),
                      template_options={'enable_thinking': False})
        save()
        trainer = shared.make_trainer(model, tokenizer, cfg, output, training, testing)
        torch.cuda.reset_peak_memory_stats()
        trainer.train()
        trainer.save_model(str(output))
        tokenizer.save_pretrained(output)
        weights = sorted(output.glob('*.safetensors'))
        if not weights:
            raise RuntimeError('Trainer saved no root full-model safetensors weights')
        result.update(status='candidate', optimizer_steps=trainer.state.global_step,
                      peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                      duration_seconds=time.time() - started,
                      full_model_sha256={p.name: sha(p) for p in weights},
                      serving_validation='required',
                      heldout_loss='not_measured_after_training')
        save()
    except BaseException as error:
        result.update(status='failed', error=str(error), duration_seconds=time.time() - started)
        save()
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'data', 'evaluation', 'manifest', 'initial-adapter',
                 'output', 'shared-trainer'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--logfile', type=Path)
    args = vars(p.parse_args())
    logfile = args.pop('logfile')
    if logfile:
        print('Training log: ' + str(logfile), flush=True)
        with logfile.open('x', buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
            train(**args)
    else:
        train(**args)
