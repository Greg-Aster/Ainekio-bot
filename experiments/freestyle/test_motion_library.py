import copy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from .compact_wire import FORMAT, ProgramEncoding
from .motion_library import MotionLibrary
from .motion_space import TOOLS
from .face_contract import face_tool


def dataset(root, count=1):
    """Small real-contract fixtures; no robot transport."""
    source = root/'source'
    source.mkdir()
    tools = [*TOOLS, face_tool()]
    encoding = ProgramEncoding(tools)
    program = [{'name': 'face', 'arguments': {'expr': 'happy'}},
               {'name': 'hold', 'arguments': {'seconds': .16}}]
    rows = [{'id': f'example-{i:05}', 'family': 'reviewed_motion',
             'query': json.dumps({'request': f'Wiggle {i:05}', 'observation': {'marker': 'preserve'},
                                  'history': [{'event': 'retain'}]}),
             'answers': encoding.encode(program), 'source_id': f'review:{i}', 'source_hash': f'hash-{i}',
             'physical_qualification': True, 'expected_final_angles_deg': [1, 2],
             'kinematic_evidence': {'trial': 'old'}} for i in range(count)]
    (source/'tools.json').write_text(json.dumps(tools))
    (source/'wire.json').write_text(json.dumps({'format':FORMAT}))
    (source/'system.txt').write_text('')
    (source/'train.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    (source/'evaluation.jsonl').write_text(json.dumps({**rows[0], 'id': 'held-out'})+'\n')
    return source, encoding.encode(program)


class MotionLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.program = dataset(self.root)
        self.library = MotionLibrary(self.root/'library.sqlite')
        self.library.import_dataset(self.source)

    def save(self, example, **kwargs):
        return self.library.save(example['id'], example['revision'], kwargs.get('title', example['title']),
            kwargs.get('query', example['query']), kwargs.get('answers', example['answers']))

    def test_edit_persists_and_export_preserves_context_and_exact_commands(self):
        original = self.library.get('example-00000')
        program = copy.deepcopy(self.program)
        program[0][1] = 'surprised'
        program[1][1] = .08
        query = json.loads(original['query']); query['request'] = 'Wiggle faster'
        edited = self.save(original, title='Fast wiggle', query=json.dumps(query), answers=program)
        self.assertEqual(edited, MotionLibrary(self.library.path).get(original['id']))
        query = json.loads(edited['example']['query'])
        self.assertEqual(query['observation'], {'marker': 'preserve'})
        self.assertEqual(query['history'], [{'event': 'retain'}])
        self.assertFalse(edited['physical_qualification'])
        self.assertNotIn('kinematic_evidence', edited['example'])
        self.assertNotIn('expected_final_angles_deg', edited['example'])
        with sqlite3.connect(self.library.path) as db:
            history = db.execute('SELECT revision,payload FROM revisions').fetchall()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0][0], edited['revision'])
        self.assertEqual(json.loads(history[0][1])['answers'], program)
        with zipfile.ZipFile(io.BytesIO(self.library.export())) as archive:
            self.assertNotIn('canonical/train.jsonl', archive.namelist())
            compact = json.loads(archive.read('dataset/train.jsonl'))
            encoding = ProgramEncoding(json.loads(archive.read('dataset/tools.json')))
            self.assertEqual(compact['answers'], program)
            self.assertEqual(compact['query'], edited['query'])
            self.assertEqual(library_program := self.library.execution_program(program), encoding.decode(program))
            self.assertEqual(compact['source_hash'], edited['example']['source_hash'])
            self.assertEqual(archive.read('dataset/evaluation.jsonl'), (self.source/'evaluation.jsonl').read_bytes())
        self.assertEqual(self.library.import_dataset(self.source)['imported'], 0)
        self.assertEqual(self.library.get(original['id']), edited)

    def test_title_only_edit_retains_physical_qualification(self):
        edited = self.save(self.library.get('example-00000'), title='Approved happy wiggle')
        self.assertTrue(edited['physical_qualification'])

    def test_import_preserves_exact_input_and_target_without_projection(self):
        row = json.loads((self.source/'train.jsonl').read_text())
        stored = self.library.get(row['id'])
        self.assertEqual(stored['query'], row['query'])
        self.assertEqual(stored['answers'], row['answers'])
        self.assertNotIn('program', stored)

    def test_invalid_commands_and_stale_save_do_not_overwrite(self):
        original = self.library.get('example-00000')
        edited = self.save(original, title='New title')
        with self.assertRaisesRegex(ValueError, 'edited elsewhere'):
            self.save(original, title='Lost update')
        for program in (None, [['face', 'nonexistent']], [['hold', float('nan')]],
                        [{'name': 'face', 'arguments': {'expr': 'happy'}}]):
            with self.assertRaises(ValueError):
                self.save(edited, answers=program)
        self.assertEqual(self.library.get(original['id']), edited)

    def test_discarded_targets_and_old_revisions_cannot_return_through_import_or_export(self):
        bulk = self.root/'discard-test'
        bulk.mkdir()
        source, _ = dataset(bulk, 3)
        self.library.import_dataset(source)
        edited = self.save(self.library.get('example-00001'), title='Latest correction')
        result = self.library.discard({'example-00000': {
            'replacement_id': edited['id'], 'reason': 'Owner discarded failed attempt'}})
        self.assertEqual(result, {'discarded': 1, 'total': 2})
        self.assertEqual(self.library.import_dataset(source)['imported'], 0)
        with self.assertRaises(ValueError):
            self.library.get('example-00000')
        with zipfile.ZipFile(io.BytesIO(self.library.export())) as archive:
            self.assertNotIn('example-00000', [json.loads(line)['id'] for line in archive.read('dataset/train.jsonl').splitlines()])
            export = self.root/'export'
            archive.extractall(export)
        second = MotionLibrary(self.root/'second.sqlite')
        second.import_dataset(source)
        second.import_dataset(export/'dataset')
        self.assertEqual(second.list()['total'], 2)
        self.assertEqual(second.import_dataset(source)['imported'], 0)
        with sqlite3.connect(self.library.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM revisions').fetchone()[0], 2)

    def test_import_does_not_restore_an_older_target_under_a_different_encoding_id(self):
        original = json.loads((self.source/'train.jsonl').read_text())
        original['parent_example_id'] = 'shared-original'
        (self.source/'train.jsonl').write_text(json.dumps(original)+'\n')
        other = MotionLibrary(self.root/'lineage.sqlite')
        other.import_dataset(self.source)
        current = other.save('example-00000', 1, 'Refined', 'Wiggle fast', self.program)
        older = copy.deepcopy(original)
        older['id'] = 'old-encoding-id'
        (self.source/'train.jsonl').write_text(json.dumps(older)+'\n')
        self.assertEqual(other.import_dataset(self.source)['imported'], 0)
        older['id'] = 'shared-original'
        older.pop('parent_example_id')
        (self.source/'train.jsonl').write_text(json.dumps(older)+'\n')
        self.assertEqual(other.import_dataset(self.source)['imported'], 0)
        self.assertEqual(other.list()['total'], 1)
        self.assertEqual(other.get(current['id']), current)

    def test_sorting_dates_names_and_edit_time_are_independent(self):
        bulk = self.root/'dated'
        bulk.mkdir()
        source, _ = dataset(bulk, 3)
        self.library.import_dataset(source)
        with sqlite3.connect(self.library.path) as db:
            for i, (title, added, updated, revision) in enumerate([
                    ('Zebra', 30, 50, 2), ('apple', 10, 90, 2), ('Middle', 20, 20, 1)]):
                db.execute('UPDATE examples SET title=?,created_ns=?,updated_ns=?,revision=? WHERE id=?',
                           (title, added*10**9, updated*10**9, revision, f'example-{i:05}'))
        order = lambda sort: [r['id'] for r in self.library.list(sort=sort)['items']]
        expected = {
            'name_asc': [1, 2, 0], 'name_desc': [0, 2, 1],
            'added_asc': [1, 2, 0], 'added_desc': [0, 2, 1],
            'edited_asc': [0, 1, 2], 'edited_desc': [1, 0, 2],
        }
        for sort, ids in expected.items():
            self.assertEqual(order(sort), [f'example-{i:05}' for i in ids])
        fresh = self.library.get('example-00002')
        self.assertIsNone(fresh['edited_at'])
        edited = self.save(fresh, title='Edited title')
        self.assertEqual(edited['added_at'], fresh['added_at'])
        self.assertIsNotNone(edited['edited_at'])
        self.assertEqual(order('edited_desc')[0], fresh['id'])
        with self.assertRaises(ValueError):
            self.library.list(sort='title; DROP TABLE examples')

    def test_legacy_database_migration_preserves_edits_and_unknown_import_dates(self):
        path = self.root/'legacy.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE examples (id TEXT PRIMARY KEY, title TEXT NOT NULL, request TEXT NOT NULL, '
                       'family TEXT NOT NULL, revision INTEGER NOT NULL, updated_ns INTEGER NOT NULL, payload TEXT NOT NULL)')
            for i, revision in enumerate((1, 2)):
                row = self.library.get('example-00000')['example']
                row['id'] = str(i)
                db.execute('INSERT INTO examples VALUES (?,?,?,?,?,?,?)',
                           (str(i), 'Motion', 'Request', 'family', revision, 10**9, json.dumps(row)))
        migrated = MotionLibrary(path)
        self.assertEqual(migrated.get('0')['added_at'], '1970-01-01T00:00:01+00:00')
        self.assertIsNone(migrated.get('0')['edited_at'])
        self.assertIsNone(migrated.get('1')['added_at'])
        self.assertEqual(migrated.get('1')['edited_at'], '1970-01-01T00:00:01+00:00')
        self.assertEqual(migrated.get('1')['revision'], 2)
        self.assertEqual(MotionLibrary(path).get('1'), migrated.get('1'))

    def test_thousands_are_paged_searchable_and_not_returned_as_full_programs(self):
        bulk = self.root/'bulk'
        bulk.mkdir()
        source, _ = dataset(bulk, 2003)
        self.library.import_dataset(source)
        first, last = self.library.list(), self.library.list(999)
        self.assertEqual((first['total'], first['pages'], len(first['items'])), (2003, 81, 25))
        self.assertEqual((last['page'], len(last['items'])), (81, 3))
        self.assertNotIn('program', first['items'][0])
        identifiers = [r['id'] for p in range(1, 82) for r in self.library.list(p)['items']]
        self.assertEqual(len(set(identifiers)), 2003)
        self.assertEqual(self.library.list(search='Wiggle 02002')['items'][0]['id'], 'example-02002')
        self.assertEqual(self.library.list(search='%')['total'], 0)
        self.assertEqual(self.library.list(search="' OR 1=1 --")['total'], 0)


if __name__ == '__main__':
    unittest.main()
