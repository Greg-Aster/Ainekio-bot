"""One-time storage migration to the exact existing compact training export.

This changes representation only, not motion targets or the model contract.
It neither trains a model nor sends a robot command. Current rows and their
single retained revisions are updated together under the SQLite write lock.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3

from .compact_wire import LEGACY_FORMAT, ProgramEncoding, observation
from .runtime import compact


def migrate(database):
    converted = 0
    with sqlite3.connect(database) as db:
        db.execute('BEGIN IMMEDIATE')
        metadata = dict(db.execute('SELECT key,value FROM metadata'))
        encoding = ProgramEncoding(json.loads(metadata['tools']))
        wire = json.loads(metadata['file:wire.json'])
        if wire['format'] != LEGACY_FORMAT:
            raise ValueError('This migration is only for the original expanded library storage')
        digest = hashlib.sha256()
        for identifier, revision, payload in db.execute('SELECT id,revision,payload FROM examples ORDER BY id').fetchall():
            row = json.loads(payload)
            if row['answers'] and isinstance(row['answers'][0], dict):
                original = copy.deepcopy(row['answers'])
                row['answers'] = encoding.encode(original)
                assert encoding.decode(row['answers']) == original
                # Exactly the old export projection, not the new recovery
                # projection. Viewing old training data must not rewrite it.
                try:
                    query = json.loads(row['query'])
                except ValueError:
                    query = row['query']
                if isinstance(query, dict):
                    for key in ('observation', 'history'):
                        if key in query:
                            query[key] = observation(query[key])
                    row['query'] = compact(query)
                payload = compact(row)
                db.execute('UPDATE examples SET payload=? WHERE id=?', (payload, identifier))
                db.execute('DELETE FROM revisions WHERE id=?', (identifier,))
                db.execute('INSERT INTO revisions VALUES (?,?,?)', (identifier, revision, payload))
                converted += 1
            digest.update((compact(row)+'\n').encode())
    return {'converted': converted, 'train_jsonl_sha256': digest.hexdigest(),
            'motion_targets_changed': False, 'training_launched': False, 'robot_execution': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    print(compact(migrate(parser.parse_args().database)))
