"""Compare frozen compact programs and resident-model latency; never dispatch."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import statistics
import time
import urllib.request
from pathlib import Path

from compact import SYSTEM, TOOLS, sha
from runtime import compact

SCHEMA = {'type': 'array', 'items': {'oneOf': [
    {'type': 'object', 'additionalProperties': False, 'required': ['name','arguments'],
     'properties': {'name': {'const': t['name'], 'type': 'string'}, 'arguments': t['parameters']}}
    for t in TOOLS]}}


def equivalent_program(actual, expected):
    """Only normalize operations whose equivalence follows from this contract."""
    def normalize(program):
        normalized = []
        for call in program:
            if call.get('name') != 'pose':
                normalized.append(call)
                continue
            args = call['arguments']
            if set(call) != {'name', 'arguments'} or set(args) != {'joints', 'angles_deg', 'reference', 'speed_pct'}:
                return None
            joints, angles = args['joints'], args['angles_deg']
            if len(joints) != len(angles) or len(set(joints)) != len(joints):
                return None
            if len(joints) == 1:
                normalized.append({'name': 'move', 'arguments': {
                    'joint': joints[0], 'angle_deg': angles[0],
                    'reference': args['reference'], 'speed_pct': args['speed_pct']}})
            else:
                pairs = sorted(zip(joints, angles))
                normalized.append({'name': 'pose', 'arguments': {
                    **args, 'joints': [j for j, _ in pairs],
                    'angles_deg': [a for _, a in pairs]}})
        return normalized
    try:
        a, b = normalize(actual), normalize(expected)
        return a is not None and b is not None and a == b
    except (KeyError, TypeError, AttributeError):
        return False


def post(url, payload):
    req = urllib.request.Request(url, data=compact(payload).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def run(data, output, endpoint, model, needle=False, workers=1, contract=None, model_file=None):
    contract = contract or data.parent
    system = (contract/'system.txt').read_text() if (contract/'system.txt').exists() else SYSTEM
    tools = json.loads((contract/'tools.json').read_text()) if (contract/'tools.json').exists() else TOOLS
    schema = {'type':'array','items':{'oneOf':[
        {'type':'object','additionalProperties':False,'required':['name','arguments'],
         'properties':{'name':{'type':'string','const':t['name']},'arguments':t['parameters']}} for t in tools]}}
    rows = [json.loads(l) for l in data.read_text().splitlines()]
    results = []
    def evaluate(row):
        if needle:
            post(endpoint+'/reset', {})
            payload = {'input': row['query']}
            url = endpoint+'/complete'
        else:
            payload = {'model':model, 'messages':[{'role':'system','content':system},
                       {'role':'user','content':row['query']}], 'temperature':0,
                       'chat_template_kwargs':{'enable_thinking':False},
                       'response_format':{'type':'json_schema','json_schema':{
                           'name':'motion_program','strict':True,'schema':schema}}}
            url = endpoint+'/v1/chat/completions'
        started = time.perf_counter()
        raw = post(url, payload)
        elapsed = time.perf_counter()-started
        error = None
        try:
            if needle:
                calls = raw['function_calls']
                reasoning = raw.get('reasoning','')
                finished = raw.get('success',False)
            else:
                choice = raw['choices'][0]
                calls = json.loads(choice['message']['content'])
                reasoning = choice['message'].get('reasoning_content','')
                finished = choice.get('finish_reason')=='stop'
            exact = finished and calls == row['answers']
        except (KeyError,TypeError,ValueError) as exc:
            calls, reasoning, finished, exact, error = None, '', False, False, str(exc)
        item = {'id':row['id'],'family':row['family'],'elapsed_s':elapsed,'exact_program':exact,
                'equivalent_program':finished and equivalent_program(calls, row['answers']),
                'finished':finished,'reasoning_emitted':bool(reasoning),'generated':calls,
                'expected':row['answers'],'error':error,'raw':raw,'execution':'not_dispatched'}
        return item
    # Needle's reset endpoint owns one mutable session; Qwen slots are independent.
    with output.open('x') as out, ThreadPoolExecutor(max_workers=1 if needle else workers) as pool:
        for future in as_completed([pool.submit(evaluate,row) for row in rows]):
            item=future.result();results.append(item)
            out.write(compact(item)+'\n');out.flush()
            print(compact({'done':len(results),'total':len(rows),'correct':sum(r['exact_program'] for r in results),
                           'seconds':round(item['elapsed_s'],3)}),flush=True)
    times=sorted(r['elapsed_s'] for r in results)
    report={'model':model,'cases':len(results),'exact_program_accuracy':sum(r['exact_program'] for r in results)/len(results),
            'equivalent_program_accuracy':sum(r['equivalent_program'] for r in results)/len(results),
            'p50_seconds':statistics.median(times),'p95_seconds':times[max(0, int(.95*len(times)+.999)-1)],
            'reasoning_responses':sum(r['reasoning_emitted'] for r in results),
            'dataset_sha256':sha(data),'physical_tests':0, 'output_token_allowance':None, 'workers':1 if needle else workers,
            'model_sha256':sha(model_file) if model_file else None,
            'by_family':{f:{'cases':sum(r['family']==f for r in results),
                            'correct':sum(r['family']==f and r['exact_program'] for r in results)}
                         for f in sorted({r['family'] for r in results})}}
    output.with_suffix('.summary.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--endpoint',required=True)
    p.add_argument('--model',required=True)
    p.add_argument('--needle',action='store_true')
    p.add_argument('--workers',type=int,default=1)
    p.add_argument('--contract',type=Path);p.add_argument('--model-file',type=Path)
    a=p.parse_args();print(compact(run(a.data,a.output,a.endpoint,a.model,a.needle,a.workers,a.contract,a.model_file)))
