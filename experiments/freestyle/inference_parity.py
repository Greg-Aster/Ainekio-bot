"""Offline serving comparison with identical prompts; never dispatch motions."""
import argparse
import hashlib
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def post(endpoint, path, payload):
    request = urllib.request.Request(endpoint + path, json.dumps(payload).encode(),
                                     {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def run(args):
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.adapter, local_files_only=True)
    system = (args.contract / 'system.txt').read_text()
    tools = json.loads((args.contract / 'tools.json').read_text())
    schema = {'type': 'array', 'items': {'oneOf': [
        {'type': 'object', 'additionalProperties': False, 'required': ['name', 'arguments'],
         'properties': {'name': {'type': 'string', 'const': tool['name']},
                        'arguments': tool['parameters']}} for tool in tools]}}
    rows = [json.loads(line) for line in args.data.read_text().splitlines()]

    def evaluate(row):
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': row['query']}]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False,
                    add_generation_prompt=True, enable_thinking=False)
        ids = tokenizer(prompt, add_special_tokens=False)['input_ids']
        served_prompt = post(args.endpoint, '/apply-template', {
            'messages': messages, 'add_generation_prompt': True,
            'chat_template_kwargs': {'enable_thinking': False}})['prompt']
        served_ids = post(args.endpoint, '/tokenize', {
            'content': served_prompt, 'add_special': False, 'parse_special': True})['tokens']
        if args.mode == 'raw':
            path = '/completion'
            payload = {'prompt': ids, 'temperature': 0, 'cache_prompt': False,
                       'n_predict': -1, 'repeat_penalty': 1.0}
        else:
            path = '/v1/chat/completions'
            payload = {'model': args.model, 'messages': messages, 'temperature': 0,
                       'chat_template_kwargs': {'enable_thinking': False},
                       'repeat_penalty': 1.0, 'cache_prompt': False}
            if args.mode == 'schema':
                payload['response_format'] = {'type': 'json_schema', 'json_schema': {
                    'name': 'motion_program', 'strict': True, 'schema': schema}}
        started = time.perf_counter()
        response = post(args.endpoint, path, payload)
        elapsed = time.perf_counter() - started
        if args.mode == 'raw':
            content = response['content']
            finished = response.get('stop_type') == 'eos' or response.get('stopped_eos', False)
        else:
            content = response['choices'][0]['message']['content']
            finished = response['choices'][0]['finish_reason'] == 'stop'
        try:
            program = json.loads(content)
        except ValueError:
            program = None
        return {'id': row['id'], 'family': row['family'], 'mode': args.mode,
                'prompt_text_equal': prompt == served_prompt, 'prompt_tokens_equal': ids == served_ids,
                'prompt_tokens': len(ids), 'native_prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                'served_prompt_sha256': hashlib.sha256(served_prompt.encode()).hexdigest(),
                'exact': finished and program == row['answers'], 'finished': finished,
                'program': program, 'expected': row['answers'], 'elapsed_s': elapsed,
                'response': response, 'execution': 'not_dispatched'}

    results = []
    with args.output.open('x') as stream, ThreadPoolExecutor(max_workers=args.workers) as pool:
        for item in pool.map(evaluate, rows):
            stream.write(json.dumps(item, separators=(',', ':')) + '\n')
            stream.flush()
            results.append(item)
            print(json.dumps({key: item[key] for key in (
                'family', 'mode', 'exact', 'finished', 'prompt_tokens_equal', 'elapsed_s')}), flush=True)
    with args.model_file.open('rb') as model_stream:
        model_sha256 = hashlib.file_digest(model_stream, 'sha256').hexdigest()
    report = {'mode': args.mode, 'cases': len(results), 'exact': sum(r['exact'] for r in results),
              'all_prompt_tokens_equal': all(r['prompt_tokens_equal'] for r in results),
              'data_sha256': hashlib.sha256(args.data.read_bytes()).hexdigest(),
              'model_sha256': model_sha256,
              'physical_trials': 0}
    args.output.with_suffix('.summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('adapter', 'contract', 'data', 'output', 'model-file'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--model', default='freestyle-parity')
    parser.add_argument('--mode', choices=('raw', 'chat', 'schema'), required=True)
    parser.add_argument('--workers', type=int, default=2)
    run(parser.parse_args())
