"""Editable local training examples and direct-motion library.

SQLite is the working dataset. Training exports are snapshots; importing a newer
batch adds examples without overwriting human edits or restoring discarded targets.
No model or robot is called.
"""
import argparse
import copy
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import time
import zipfile

from jsonschema import Draft202012Validator

from .compact_wire import FORMAT, LEGACY_FORMAT, ProgramEncoding
from .runtime import compact

PAGE_SIZE = 25
SORTS = {
    'name_asc': 'title COLLATE NOCASE ASC,id',
    'name_desc': 'title COLLATE NOCASE DESC,id',
    'added_asc': 'created_ns IS NULL,created_ns ASC,id',
    'added_desc': 'created_ns IS NULL,created_ns DESC,id',
    'edited_asc': 'revision=1,updated_ns ASC,id',
    'edited_desc': 'revision=1,updated_ns DESC,id',
}


def dates(row):
    def iso(value):
        return datetime.fromtimestamp(value/1e9, timezone.utc).isoformat() if value is not None else None
    return {'added_at': iso(row['created_ns']),
            'edited_at': iso(row['updated_ns']) if row['revision'] > 1 else None}


def current_target(row):
    row = copy.deepcopy(row)
    for key in ('original_program', 'previous_kinematic_evidence', 'superseded_kinematic_evidence'):
        row.pop(key, None)
    return row


def request_text(query):
    try:
        value = json.loads(query)
    except (ValueError, TypeError):
        return query
    return value.get('request', query) if isinstance(value, dict) else value


class MotionLibrary:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS examples (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, request TEXT NOT NULL,
                    family TEXT NOT NULL, revision INTEGER NOT NULL, updated_ns INTEGER NOT NULL,
                    payload TEXT NOT NULL, created_ns INTEGER);
                CREATE INDEX IF NOT EXISTS examples_title ON examples(title COLLATE NOCASE, id);
                CREATE TABLE IF NOT EXISTS discarded_examples (
                    id TEXT PRIMARY KEY, replacement_id TEXT, reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (
                    id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(id, revision));
            ''')
            db.execute('BEGIN IMMEDIATE')
            if 'created_ns' not in {row['name'] for row in db.execute('PRAGMA table_info(examples)')}:
                db.execute('ALTER TABLE examples ADD COLUMN created_ns INTEGER')
                # Before the first edit, the existing timestamp is exactly the
                # import time. Otherwise the old version did not retain it.
                db.execute('UPDATE examples SET created_ns=updated_ns WHERE revision=1')
            db.execute('CREATE INDEX IF NOT EXISTS examples_created ON examples(created_ns,id)')
            db.execute('CREATE INDEX IF NOT EXISTS examples_updated ON examples(updated_ns,id)')
        self.path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def tools(self, db):
        row = db.execute("SELECT value FROM metadata WHERE key='tools'").fetchone()
        if row is None:
            raise ValueError('Import the training dataset before using the motion library')
        return json.loads(row[0])

    def validate(self, answers):
        # Same operation/argument vocabulary as training; no motion limits or IK
        # execution here. Invalid command syntax is reported without rewriting it.
        with closing(self.connect()) as db:
            tools = self.tools(db)
        compact(answers)  # Reject non-finite JSON numbers.
        schema = ProgramEncoding(tools).schema(lambda tool: tool['parameters'])
        error = next(Draft202012Validator(schema).iter_errors(answers), None)
        if error:
            location = '.'.join(str(part) for part in error.absolute_path) or 'program'
            raise ValueError(f'Invalid command at {location}: {error.message}')
        return answers

    def execution_program(self, answers):
        """Decode only at the existing robot executor boundary."""
        self.validate(answers)
        with closing(self.connect()) as db:
            return ProgramEncoding(self.tools(db)).decode(answers)

    def import_dataset(self, dataset):
        dataset = Path(dataset)
        tools = json.loads((dataset/'tools.json').read_text())
        encoding = ProgramEncoding(tools)
        wire = dataset/'wire.json'
        if not wire.exists() or json.loads(wire.read_text())['format'] not in (FORMAT, LEGACY_FORMAT):
            raise ValueError('Import the actual compact training dataset with its wire.json contract')
        source = dataset/'train.jsonl'
        inserted = 0
        with closing(self.connect()) as db, db:
            current = db.execute("SELECT value FROM metadata WHERE key='tools'").fetchone()
            if current and json.loads(current[0]) != tools:
                raise ValueError('The imported dataset uses a different command contract')
            db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', ('tools', compact(tools)))
            # Preserve held-out rows as frozen references, never as editable training examples.
            for name in ('system.txt', 'wire.json', 'evaluation.jsonl', 'test.jsonl',
                         'recovery-probe.jsonl', 'regression-evaluation.jsonl'):
                if (dataset/name).exists():
                    db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)',
                               ('file:'+name, (dataset/name).read_text()))
            manifest_path = dataset/'manifest.json'
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
            for retired in manifest.get('discarded_examples', []):
                db.execute('INSERT OR IGNORE INTO discarded_examples VALUES (?,?,?)',
                           (retired['id'], retired.get('replacement_id'), retired['reason']))
            discarded = {r[0] for r in db.execute('SELECT id FROM discarded_examples')}
            for stored in db.execute('SELECT id,payload FROM examples').fetchall():
                old = json.loads(stored['payload'])
                if old['id'] in discarded or old.get('parent_example_id') in discarded:
                    db.execute('DELETE FROM examples WHERE id=?', (stored['id'],))
                    db.execute('DELETE FROM revisions WHERE id=?', (stored['id'],))
            existing_aliases = set()
            for stored in db.execute('SELECT payload FROM examples'):
                current = json.loads(stored[0])
                existing_aliases.update(alias for alias in (current['id'], current.get('parent_example_id')) if alias)
            for line in source.read_text().splitlines():
                if not line.strip():
                    continue
                row = current_target(json.loads(line))
                if row['id'] in discarded or row.get('parent_example_id') in discarded:
                    continue
                if row['id'] in existing_aliases or row.get('parent_example_id') in existing_aliases:
                    continue
                Draft202012Validator(encoding.schema(lambda tool: tool['parameters'])).validate(row['answers'])
                request = request_text(row['query'])
                title = row.get('title') or request
                row['title'] = title
                now = time.time_ns()
                cursor = db.execute('INSERT OR IGNORE INTO examples '
                    '(id,title,request,family,revision,updated_ns,payload,created_ns) VALUES (?,?,?,?,?,?,?,?)',
                    (row['id'], title, request, row['family'], 1, now, compact(row), now))
                if cursor.rowcount:
                    db.execute('INSERT INTO revisions VALUES (?,?,?)', (row['id'], 1, compact(row)))
                    existing_aliases.update(alias for alias in (row['id'], row.get('parent_example_id')) if alias)
                    inserted += 1
        return {'imported': inserted, 'total': self.list()['total']}

    def list(self, page=1, search='', sort='name_asc'):
        if type(page) is not int or page < 1 or not isinstance(search, str):
            raise ValueError('Choose a positive page number and text search')
        if sort not in SORTS:
            raise ValueError('Choose name, date added or last edited sorting')
        pattern = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        where = " WHERE title LIKE ? ESCAPE '\\' OR request LIKE ? ESCAPE '\\' OR family LIKE ? ESCAPE '\\'"
        args = (pattern, pattern, pattern)
        with closing(self.connect()) as db:
            count = db.execute('SELECT count(*) FROM examples'+where, args).fetchone()[0]
            pages = max(1, (count+PAGE_SIZE-1)//PAGE_SIZE)
            page = min(page, pages)
            rows = db.execute('SELECT id,title,family,revision,created_ns,updated_ns FROM examples'+where+
                ' ORDER BY '+SORTS[sort]+' LIMIT ? OFFSET ?', (*args, PAGE_SIZE, (page-1)*PAGE_SIZE))
            return {'items': [{**{key: row[key] for key in ('id', 'title', 'family', 'revision')},
                               **dates(row)} for row in rows], 'page': page, 'pages': pages,
                    'page_size': PAGE_SIZE, 'total': count, 'sort': sort}

    def get(self, identifier):
        with closing(self.connect()) as db:
            stored = db.execute('SELECT * FROM examples WHERE id=?', (identifier,)).fetchone()
        if stored is None:
            raise ValueError('Training example not found')
        row = json.loads(stored['payload'])
        return {'id': identifier, 'title': stored['title'], 'request': stored['request'],
                'family': stored['family'], 'revision': stored['revision'],
                'query': row['query'], 'answers': row['answers'],
                'physical_qualification': row.get('physical_qualification', False),
                'qualification_basis': row.get('qualification_basis'), **dates(stored), 'example': row}

    def save(self, identifier, revision, title, query, answers):
        if not isinstance(title, str) or not title.strip() or not isinstance(query, str) or not query.strip():
            raise ValueError('Title and training input are required')
        request = request_text(query)
        if not isinstance(request, str) or not request.strip():
            raise ValueError('Training input must contain a text request')
        self.validate(answers)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            stored = db.execute('SELECT * FROM examples WHERE id=?', (identifier,)).fetchone()
            if stored is None:
                raise ValueError('Training example not found')
            if type(revision) is not int or stored['revision'] != revision:
                raise ValueError('This example was edited elsewhere. Reopen it before saving your changes.')
            row = current_target(json.loads(stored['payload']))
            changed = answers != row['answers'] or query != row['query']
            row.setdefault('library_origin', {key: row[key] for key in ('id', 'source_id', 'source_hash')})
            row['query'] = query
            row['answers'], row['title'] = answers, title.strip()
            row['library_revision'] = revision+1
            row['source_id'] = f'motion-library:{identifier}:{revision+1}'
            row['source_hash'] = hashlib.sha256(compact([row['query'], answers]).encode()).hexdigest()
            if changed:
                # Edited targets must not inherit a physical-success claim
                # from a different motion.
                for key in ('review', 'job_id', 'review_evidence_id', 'request_evidence_id',
                            'expected_final_angles_deg', 'kinematic_evidence', 'live_trial_wall_seconds',
                            'face_annotation', 'initial_face_annotation_added', 'execution_source',
                            'review_evidence_ids', 'expected_final_model_deg', 'previous_kinematic_evidence',
                            'superseded_kinematic_evidence', 'motion_structure_sha256', 'canonical_source_motion_sha256',
                            'reviewed_request_specification', 'operator_assessment', 'semantic_assessment',
                            'goals', 'spatial_goals', 'returns_to_start', 'ending_policy', 'repair_review',
                            'face_cues', 'rehearsal'):
                    row.pop(key, None)
                row.update(physical_qualification=False, synthetic=True,
                           qualification_basis='user_edited_not_physically_reviewed',
                           teacher='Body Control motion library editor')
            db.execute('UPDATE examples SET title=?,request=?,revision=?,updated_ns=?,payload=? WHERE id=?',
                       (row['title'], request, revision+1, time.time_ns(), compact(row), identifier))
            db.execute('DELETE FROM revisions WHERE id=?', (identifier,))
            db.execute('INSERT INTO revisions VALUES (?,?,?)', (identifier, revision+1, compact(row)))
        return self.get(identifier)

    def discard(self, replacements):
        """Remove superseded targets, retaining IDs only to prevent re-import.

        The owner supplies explicit example IDs and reasons; there is no keyword
        filter or automatic physical-success inference.
        """
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            for identifier, details in replacements.items():
                stored = db.execute('SELECT payload FROM examples WHERE id=?', (identifier,)).fetchone()
                if stored is None:
                    raise ValueError('Training example not found: '+identifier)
                row = json.loads(stored[0])
                aliases = {identifier, row.get('parent_example_id')}
                for alias in aliases - {None}:
                    db.execute('INSERT OR REPLACE INTO discarded_examples VALUES (?,?,?)',
                               (alias, details.get('replacement_id'), details['reason']))
                db.execute('DELETE FROM examples WHERE id=?', (identifier,))
                db.execute('DELETE FROM revisions WHERE id=?', (identifier,))
            # Only the current target is training data. Failed programs attached
            # to old teacher metadata and superseded edit revisions are discarded.
            for stored in db.execute('SELECT id,revision,payload FROM examples').fetchall():
                row = current_target(json.loads(stored['payload']))
                db.execute('UPDATE examples SET payload=? WHERE id=?', (compact(row), stored['id']))
                db.execute('DELETE FROM revisions WHERE id=?', (stored['id'],))
                db.execute('INSERT INTO revisions VALUES (?,?,?)', (stored['id'], stored['revision'], compact(row)))
        return {'discarded': len(replacements), 'total': self.list()['total']}

    def export(self):
        """Export the exact input and target stored in the editor, without rewriting either."""
        with closing(self.connect()) as db, db:
            db.execute('BEGIN')
            tools = self.tools(db)
            rows = [current_target(json.loads(row[0])) for row in db.execute('SELECT payload FROM examples ORDER BY id')]
            discarded = [dict(row) for row in db.execute('SELECT * FROM discarded_examples ORDER BY id')]
            files = {row['key'][5:]: row['value'] for row in db.execute("SELECT * FROM metadata WHERE key LIKE 'file:%'")}
        files['train.jsonl'] = ''.join(compact(row)+'\n' for row in rows)
        files['tools.json'] = compact(tools)+'\n'
        files['system.txt'] = ''
        wire_format = json.loads(files['wire.json'])['format']
        manifest = {'version': wire_format, 'source': 'Body Control editable motion library',
                    'training_rows': len(rows), 'training_launched': False, 'discarded_examples': discarded,
                    'encoding_sha256': hashlib.sha256(Path(__file__).with_name('compact_wire.py').read_bytes()).hexdigest(),
                    'files': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}}
        files['manifest.json'] = json.dumps(manifest, indent=2)+'\n'
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, text in files.items():
                archive.writestr('dataset/'+name, text)
        return output.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('import', 'export'))
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    library = MotionLibrary(args.database)
    if args.operation == 'import':
        if args.dataset is None:
            parser.error('--dataset is required')
        print(compact(library.import_dataset(args.dataset)))
    else:
        if args.output is None:
            parser.error('--output is required')
        with args.output.open('xb') as stream:
            stream.write(library.export())
        print(compact({'output': str(args.output), 'training_launched': False}))
