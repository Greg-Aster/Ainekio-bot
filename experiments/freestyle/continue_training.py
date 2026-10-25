"""Train a fresh or continued Freestyle LoRA using the existing trainer.

This experiment owns its artifacts and never edits the shared trainer, robot
firmware, model assignments or live serving processes.
"""
import argparse
import hashlib
import importlib.util
import json
import time
from contextlib import redirect_stderr, redirect_stdout
from functools import wraps
from pathlib import Path
from types import MethodType


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def align_qwen_mlp(model, torch):
    """Keep Qwen's feed-forward arithmetic aligned with deployed inference.

    The installed Unsloth/Torch compiler fuses this block differently from the
    native and GGUF implementations. On the same persisted weights and token
    prefix this changed a numeric decision from probability 0.000096 to 0.989.
    An eager block restores native predictions while retaining the independent
    fused loss and linear-attention kernels. This affects this process only.
    """
    @torch.compiler.disable
    def forward(self, x):
        return self.down_proj(self.act_fn(self.gate_proj(x)) * self.up_proj(x))

    count = 0
    for module in model.modules():
        if type(module).__name__ == 'Qwen3_5MLP':
            module.forward = MethodType(forward, module)
            count += 1
    return {'qwen_eager_mlp_blocks': count,
            'scope': 'process-local feed-forward arithmetic; other kernels unchanged'}


def loss_only_evaluation(model):
    """Do not retain/cast vocabulary logits that this loss-only evaluator discards.

    Accelerate otherwise makes an additional full FP32 logits tensor. Loss is
    already computed by the model; retain that exact tensor. Training forwards
    and unlabeled generation keep their original outputs.
    """
    forward = model.forward

    @wraps(forward)
    def evaluate(*args, **kwargs):
        result = forward(*args, **kwargs)
        if not model.training and kwargs.get('labels') is not None and result.get('loss') is not None:
            return {'loss': result['loss']}
        return result

    model.forward = evaluate


def train(config, data, evaluation, manifest, adapter, output, shared_trainer):
    spec=importlib.util.spec_from_file_location('freestyle_shared_trainer',shared_trainer)
    shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
    cfg=shared.validate_config(json.loads(config.read_text()))
    provenance=shared.verify_manifest(manifest,data,evaluation,cfg)
    output.mkdir(parents=True,exist_ok=False)
    result={'status':'running','initial_adapter':str(adapter) if adapter else None,
            'initial_adapter_sha256':sha(adapter/'adapter_model.safetensors') if adapter else None,
            'initialization':'continued_adapter' if adapter else 'pretrained_base_with_new_lora',
            'config_sha256':sha(config),'dataset_id':provenance['datasetId'],
            'base_model':cfg['base_model'],'base_revision':cfg['base_model_revision'],
            'shared_trainer_sha256':sha(shared_trainer),'activation':'not-activated'}
    result['continuation_trainer_sha256'] = sha(__file__)
    report=output/'training-result.json'
    def save():report.write_text(json.dumps(result,indent=2)+'\n')
    started=time.time();save()
    try:
        # The shared factory pins the base and creates new LoRA modules. An
        # optional same-architecture adapter supplies continuation weights; a
        # different-sized model starts fresh from its own pretrained base.
        model,tokenizer,torch=shared.load_runtime(cfg,training=True)
        result['runtime_adjustments'] = align_qwen_mlp(model, torch)
        loss_only_evaluation(model)
        result['runtime_adjustments']['loss_only_evaluation'] = True
        if adapter is not None:
            from peft import get_peft_model_state_dict, set_peft_model_state_dict
            from safetensors.torch import load_file
            previous=load_file(str(adapter/'adapter_model.safetensors'))
            expected=get_peft_model_state_dict(model)
            if set(expected)!=set(previous):
                raise ValueError('Continuation adapter tensors do not match the configured LoRA architecture')
            if any(expected[key].shape!=previous[key].shape for key in expected):
                raise ValueError('Continuation adapter shapes do not match the configured LoRA architecture')
            set_peft_model_state_dict(model,previous)
            loaded=get_peft_model_state_dict(model)
            if any(not torch.equal(loaded[key].detach().cpu(),previous[key].to(loaded[key].dtype)) for key in previous):
                raise ValueError('Loaded continuation weights differ from the persisted initial adapter')
            del expected,previous,loaded
            result['initial_weights_verified']=True
        training=shared.tokenize_rows(tokenizer,shared.read_rows(data),cfg)
        testing=shared.tokenize_rows(tokenizer,shared.read_rows(evaluation),cfg)
        result.update(training_samples=len(training),evaluation_samples=len(testing),
                      supervised_tokens=sum(sum(v!=-100 for v in r['labels']) for r in training),
                      template_options={'enable_thinking':False})
        save()
        trainer=shared.make_trainer(model,tokenizer,cfg,output,training,testing)
        result['before_loss']=shared.finite_loss(trainer.evaluate());save()
        torch.cuda.reset_peak_memory_stats()
        trainer.train()
        trainer.save_model(str(output));tokenizer.save_pretrained(output)
        result.update(status='candidate',after_loss=shared.finite_loss(trainer.evaluate()),
                      peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                      adapter_sha256=sha(output/'adapter_model.safetensors'),
                      duration_seconds=time.time()-started,
                      serving_validation='required',physical_trials=0)
        save()
    except BaseException as error:
        result.update(status='failed',error=str(error),duration_seconds=time.time()-started);save()
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('config','data','evaluation','manifest','output','shared-trainer'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--adapter',type=Path,
                   help='Optional same-architecture adapter; omit to train a fresh LoRA on the configured base')
    p.add_argument('--logfile',type=Path)
    arguments=vars(p.parse_args());logfile=arguments.pop('logfile')
    if logfile:
        print('Training log: '+str(logfile),flush=True)
        with logfile.open('x',buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
            train(**arguments)
    else:train(**arguments)
