"""Merge the text-only Qwen adapter before GGUF quantization; retain provenance."""
import argparse
import hashlib
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory


def export(adapter, base, output, converter, quantizer, compact_artifacts=True, quantization='Q4_K_M'):
    import torch
    from peft import PeftModel
    from transformers import AutoTokenizer, Qwen3_5ForCausalLM
    output.mkdir(parents=True,exist_ok=False)
    def sha(path):
        h=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        return h.hexdigest()
    # Only intermediates created by this export are temporary. Existing runs,
    # adapters and their evidence are never removed by the compact option.
    workspace=TemporaryDirectory(prefix='.export-',dir=output) if compact_artifacts else nullcontext(str(output))
    with workspace as directory:
        work=Path(directory)
        torch.set_num_threads(4)
        model=Qwen3_5ForCausalLM.from_pretrained(base,dtype=torch.float32,device_map='cpu',
                                              attn_implementation='eager',local_files_only=True)
        model=PeftModel.from_pretrained(model,adapter)
        merged=model.merge_and_unload().to(torch.float16)
        merged.save_pretrained(work/'merged-hf')
        AutoTokenizer.from_pretrained(adapter,local_files_only=True).save_pretrained(work/'merged-hf')
        del model,merged
        subprocess.run([sys.executable,str(converter),str(work/'merged-hf'),
                        '--outfile',str(work/'model.F16.gguf'),'--outtype','f16','--no-mtp'],check=True)
        subprocess.run([str(quantizer),str(work/'model.F16.gguf'),str(output/f'model.{quantization}.gguf'),
                        quantization,'4'],check=True)
        intermediate_sha256=sha(work/'model.F16.gguf')
    report={'base':str(base),'adapter':str(adapter),'merge_dtype':'float32','gguf_dtype':'float16','mtp':False,
            'quantization':quantization,
            'intermediate_f16_sha256':intermediate_sha256,'intermediates_retained':not compact_artifacts,
            'adapter_sha256':sha(adapter/'adapter_model.safetensors'),
            'files':{p.name:sha(p) for p in output.glob('*.gguf')}}
    (output/'export.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('adapter','base','output','converter','quantizer'):p.add_argument('--'+key,type=Path,required=True)
    retention=p.add_mutually_exclusive_group()
    retention.add_argument('--compact-artifacts',action='store_true',default=True)
    retention.add_argument('--keep-intermediates',dest='compact_artifacts',action='store_false')
    p.add_argument('--quantization',default='Q4_K_M')
    a=p.parse_args();print(json.dumps(export(**vars(a))))
