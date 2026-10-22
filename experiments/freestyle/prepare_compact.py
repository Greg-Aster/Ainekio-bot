"""Freeze identical compact-program examples in each trainer's native format."""
import argparse
import hashlib
import json
from pathlib import Path

from compact import SYSTEM, TOOLS, sha
from prepare import prepare
from runtime import compact


def export_shared(source, output, base, revision, trainer):
    output.mkdir(parents=True, exist_ok=False)
    system = (source/'system.txt').read_text() if (source/'system.txt').exists() else SYSTEM
    manifest = {'version': 2, 'supervision': 'final-assistant-only', 'baseModel': base,
                'systemPrompt': system, 'settings': {'objective': 'assistant-continuation'},
                'sourceHashes': {}, 'generatorManifestSha256': sha(source/'manifest.json')}
    for split in ('train', 'evaluation'):
        originals = [json.loads(line) for line in (source/(split+'.jsonl')).read_text().splitlines()]
        rows = []
        for r in originals:
            manifest['sourceHashes'][r['source_id']] = r['source_hash']
            rows.append({'id': r['id'], 'messages': [
                {'role': 'system', 'content': system}, {'role': 'user', 'content': r['query']},
                {'role': 'assistant', 'content': compact(r['answers'])}],
                'metadata': {'sourceIds': [r['source_id']], 'sourceHashes': {r['source_id']: r['source_hash']},
                             'objective': 'assistant-continuation', 'targetAuthor': 'assistant',
                             'mode': 'freestyle-compact', 'family': r['family'], 'synthetic': True}})
        path = output/(split+'.jsonl')
        path.write_text(''.join(compact(row)+'\n' for row in rows))
        manifest[split] = {'count': len(rows), 'sha256': sha(path),
                           'sourceIds': sorted({r['source_id'] for r in originals})}
    manifest['datasetId'] = hashlib.sha256(compact(manifest).encode()).hexdigest()
    (output/'manifest.json').write_text(compact(manifest)+'\n')
    return prepare(output, trainer, base, revision)


def export_needle(source, output):
    from needle.model.finetune import render_example, get_tokenizer
    output.mkdir(parents=True, exist_ok=False)
    tokenizer = get_tokenizer(8192)
    largest = 0
    for split in ('train', 'evaluation', 'test', 'benchmark'):
        rows = []
        for line in (source/(split+'.jsonl')).read_text().splitlines():
            r = json.loads(line)
            row = {'query': r['query'], 'tools': TOOLS, 'answers': r['answers'], 'reasoning': ''}
            prompt, target = render_example(row)
            largest = max(largest, len(tokenizer.encode(prompt))+len(tokenizer.encode(target))+2)
            rows.append(row)
        (output/(split+'.jsonl')).write_text(''.join(compact(r)+'\n' for r in rows))
    report = {'max_sequence_tokens': largest, 'reasoning_targets': False,
              'source_manifest_sha256': sha(source/'manifest.json')}
    (output/'token-report.json').write_text(compact(report)+'\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--base')
    p.add_argument('--revision')
    p.add_argument('--trainer', type=Path)
    p.add_argument('--needle', action='store_true')
    a = p.parse_args()
    print(compact(export_needle(a.source, a.output) if a.needle else
                  export_shared(a.source, a.output, a.base, a.revision, a.trainer)))
