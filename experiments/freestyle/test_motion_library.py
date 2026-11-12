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
from .recordings import Recorder


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

    def test_create_new_example_and_category_filter_preserve_contract_and_export(self):
        created = self.library.create(
            'Right hand wave',
            'Raise your right hand and wave.',
            self.library.encode_program([
                {'name': 'face', 'arguments': {'expr': 'wave'}},
                {'name': 'move', 'arguments': {
                    'joint': 'front_right_shoulder', 'angle_deg': 18,
                    'reference': 'current', 'speed_pct': 60, 'taper_deg': 0}},
            ]),
        )
        self.assertEqual(created['family'], 'custom_motion')
        self.assertEqual(json.loads(created['query']), {'request': 'Raise your right hand and wave.'})
        self.assertEqual(created['revision'], 1)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.library.create('Duplicate wave', 'Raise your right hand and wave.', created['answers'])
        recovery = self.library.create(
            'Stall retreat',
            json.dumps({'request': 'Recover from the reported body event using the available observations.',
                        'event': {'type': 'servo_stall', 'joints': [9], 'outputs_released': False},
                        'history': []}),
            created['answers'],
            family='standalone_jam_recovery',
        )
        self.assertEqual(self.library.list(category='ordinary')['total'], 2)
        self.assertEqual(self.library.list(category='recovery')['total'], 1)
        self.assertEqual(self.library.list(category='recovery')['items'][0]['id'], recovery['id'])
        self.assertEqual(self.library.list(category='all')['total'], 3)
        with self.assertRaises(ValueError):
            self.library.list(category='invalid')
        with zipfile.ZipFile(io.BytesIO(self.library.export())) as archive:
            exported = {json.loads(line)['id'] for line in archive.read('dataset/train.jsonl').decode().splitlines()}
        self.assertIn(created['id'], exported)
        self.assertIn(recovery['id'], exported)

    def test_native_alignment_updates_snapshot_and_library_without_reviving_substitutes(self):
        from .legacy_curriculum import align, rows_at
        good = self.library.get('example-00000')['example']
        bad = {**copy.deepcopy(good),'id':'bad-bow','family':'semantic_bowing',
               'source_hash':'bad-bow-source','physical_qualification':False}
        original = rows_at(self.source/'train.jsonl')
        (self.source/'train.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in original+[bad]))
        self.library.import_dataset(self.source)
        snapshot_only = {**bad,'id':'snapshot-only-wave','family':'gesture_ending_wave',
                         'source_hash':'snapshot-wave-source'}
        (self.source/'train.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in original+[bad,snapshot_only]))
        (self.source/'manifest.json').write_text(json.dumps({'training_rows':3,'discarded_examples':[]}))
        held_out = (self.source/'evaluation.jsonl').read_bytes()
        evidence = self.root/'alignment'
        report = align(self.source,self.library.path,evidence,apply=True)
        self.assertEqual(report['motions'],23)
        self.assertEqual(report['retired_training_rows'],2)
        self.assertEqual(report['retired_library_rows'],1)
        self.assertEqual(self.library.list()['total'],24)
        self.assertEqual(self.library.get('example-00000')['example'],good)
        self.assertEqual((self.source/'evaluation.jsonl').read_bytes(),held_out)
        current = rows_at(self.source/'train.jsonl')
        self.assertEqual(len(current),24)
        self.assertEqual(len([r for r in current if r['family'].startswith('legacy_asset_')]),23)
        self.assertFalse(any(r['physical_qualification'] for r in current if r.get('legacy_motion')))
        self.library.import_dataset(evidence/'dataset-before')
        self.assertEqual(self.library.list()['total'],24,'Old exports must not restore retired snapshot-only IDs')
        repeated = align(self.source,self.library.path,self.root/'unused',apply=False)
        self.assertEqual(repeated['retired_training_rows'],0)
        self.assertEqual(repeated['retired_library_rows'],0)
        self.assertFalse((self.root/'unused').exists())

    def test_native_alignment_retains_context_teachers_and_excluded_evaluations(self):
        from .legacy_curriculum import align, rows_at
        from .legacy_curriculum import native_examples, contextual_example
        from .observations import joint_state
        tools=json.loads((self.source/'tools.json').read_text())
        reference=next(row for row in native_examples(tools) if row['family']=='legacy_asset_stretch')
        observation=json.loads(reference['query'])['observation']
        observation={**observation,'joints':joint_state(observation)}
        contexts=[contextual_example(reference,observation,'Please stretch',tools)]
        held=[contextual_example(reference,observation,'Give me a stretch.',tools)]
        original=rows_at(self.source/'train.jsonl')
        (self.source/'train.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in original+contexts))
        (self.source/'regression-evaluation.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in held))
        (self.source/'manifest.json').write_text(json.dumps({'training_rows':len(original+contexts),'discarded_examples':[]}))
        self.library.import_dataset(self.source)
        reference=(self.source/'regression-evaluation.jsonl').read_bytes()
        for attempt in range(2):
            align(self.source,self.library.path,self.root/('alignment-'+str(attempt)),apply=True)
            current=[r for r in rows_at(self.source/'train.jsonl') if r['family']=='legacy_asset_stretch']
            self.assertEqual({r['id']:r for r in current},{r['id']:r for r in contexts})
            self.assertEqual((self.source/'regression-evaluation.jsonl').read_bytes(),reference)
            self.assertEqual(self.library.list()['total'],len(contexts)+23)
            with sqlite3.connect(self.library.path) as db:
                stored=db.execute("SELECT value FROM metadata WHERE key='file:regression-evaluation.jsonl'").fetchone()[0]
            self.assertEqual(stored.encode(),reference)
        with sqlite3.connect(self.library.path) as db:
            imported={row[0] for row in db.execute("SELECT id FROM examples WHERE family='legacy_asset_stretch'")}
        self.assertEqual(imported,{r['id'] for r in contexts})

    def test_training_export_adds_only_latest_approved_trials_and_keeps_library_targets(self):
        recordings=self.root/'freestyle-recordings.sqlite'
        program=[{'name':'hold','arguments':{'seconds':2}}]
        recorder=Recorder(recordings)
        for job,outcome,execute in (('approved','success',True),('wrong','incorrect',True),
                                    ('unreviewed',None,True),('preview','success',False)):
            recorder.record('generation_requested',{'generation_index':0,'execute':execute,
                'request':{'request':'Hold '+job,'observation':{},'history':[]}},job_id=job)
            recorder.record('generation_completed',{'generation_index':0,
                'result':{'program':program}},job_id=job)
            recorder.record('job_finished',{'state':'completed' if execute else 'generated'},job_id=job)
            if outcome:recorder.record('review',{'generation_index':0,'outcome':outcome},job_id=job)
        recorder.close()
        def export_rows():
            with zipfile.ZipFile(io.BytesIO(self.library.export(recordings=recordings))) as archive:
                return [json.loads(line) for line in archive.read('dataset/train.jsonl').splitlines()]
        rows=export_rows()
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0],self.library.get('example-00000')['example'])
        reviewed=next(row for row in rows if row.get('job_id')=='approved')
        self.assertEqual(reviewed['answers'],[['hold',2]])
        self.assertTrue(reviewed['physical_qualification'])
        # Export is a current review snapshot. A later failed review withdraws
        # the former positive instead of appending another training target.
        recorder=Recorder(recordings)
        recorder.record('review',{'generation_index':0,'outcome':'incorrect'},job_id='approved')
        recorder.close()
        self.assertEqual([row['id'] for row in export_rows()],['example-00000'])
        self.assertEqual(self.library.list()['total'],1)

    def test_export_preserves_an_imported_review_and_withdraws_it_after_negative_review(self):
        recordings=self.root/'reviews.sqlite'
        recorder=Recorder(recordings)
        recorder.record('generation_requested',{'generation_index':0,'execute':True,
            'request':{'request':'Hold','observation':{},'history':[]}},job_id='trial')
        recorder.record('generation_completed',{'generation_index':0,
            'result':{'program':[{'name':'hold','arguments':{'seconds':2}}]}},job_id='trial')
        recorder.record('job_finished',{'state':'completed'},job_id='trial')
        recorder.record('review',{'generation_index':0,'outcome':'success'},job_id='trial')
        recorder.close()
        with zipfile.ZipFile(io.BytesIO(self.library.export(recordings=recordings))) as archive:
            exported=self.root/'import-reviewed';archive.extractall(exported)
        self.library.import_dataset(exported/'dataset')
        with zipfile.ZipFile(io.BytesIO(self.library.export(recordings=recordings))) as archive:
            rows=[json.loads(line) for line in archive.read('dataset/train.jsonl').splitlines()]
        self.assertEqual(len(rows),2,'Repeated exports must not duplicate an approved trial')
        recorder=Recorder(recordings)
        recorder.record('review',{'generation_index':0,'outcome':'incorrect'},job_id='trial')
        recorder.close()
        with zipfile.ZipFile(io.BytesIO(self.library.export(recordings=recordings))) as archive:
            rows=[json.loads(line) for line in archive.read('dataset/train.jsonl').splitlines()]
        self.assertEqual([row['id'] for row in rows],['example-00000'])

    def test_dashboard_export_flushes_saved_reviews_and_includes_them(self):
        from types import SimpleNamespace
        from gateway.dashboard.server import DashboardHttpServer
        recordings=self.root/'freestyle-recordings.sqlite'
        recorder=Recorder(recordings)
        self.addCleanup(recorder.close)
        recorder.record('generation_requested',{'generation_index':0,'execute':True,
            'request':{'request':'Hold','observation':{},'history':[]}},job_id='trial')
        recorder.record('generation_completed',{'generation_index':0,
            'result':{'program':[{'name':'hold','arguments':{'seconds':2}}]}},job_id='trial')
        recorder.record('job_finished',{'state':'completed'},job_id='trial')
        recorder.record('review',{'generation_index':0,'outcome':'success'},job_id='trial')
        dashboard=SimpleNamespace(password_store=SimpleNamespace(path=self.root/'password.json'),
            freestyle_recorder=recorder,motion_library=lambda:self.library)
        with zipfile.ZipFile(io.BytesIO(DashboardHttpServer.export_motion_training(dashboard))) as archive:
            rows=[json.loads(line) for line in archive.read('dataset/train.jsonl').splitlines()]
        self.assertEqual(len(rows),2)
        self.assertTrue(any(row.get('job_id')=='trial' for row in rows))

    def test_changed_program_removes_obsolete_source_reference_claims(self):
        keys=('reference_source_sha256','reference_entry_model_deg','reference_final_model_deg','reference_phases')
        with self.library.connect() as db,db:
            row=json.loads(db.execute('SELECT payload FROM examples WHERE id=?',('example-00000',)).fetchone()[0])
            row.update({key:['old reference'] for key in keys})
            db.execute('UPDATE examples SET payload=? WHERE id=?',(json.dumps(row),'example-00000'))
        example=self.library.get('example-00000')
        answers=copy.deepcopy(example['answers']);answers[-1][-1]=.5
        result=self.save(example,answers=answers)
        for key in keys:self.assertNotIn(key,result['example'])
        reopened=MotionLibrary(self.library.path).get(example['id'])
        for key in keys:self.assertNotIn(key,reopened['example'])

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

    def test_editor_replacement_stores_named_pose_as_exact_compact_training_target(self):
        original=self.library.get('example-00000')
        program=[{'name':'pose','arguments':{'joints':['front_left_carrier','front_right_carrier'],
            'angles_deg':[-32.5,-33.25],'reference':'absolute','speed_pct':50,'taper_deg':0}}]
        saved=self.save(original,answers=self.library.encode_program(program))
        reopened=MotionLibrary(self.library.path).get(saved['id'])
        self.assertEqual(self.library.execution_program(reopened['answers']),program)
        self.assertEqual(json.loads(reopened['query'])['observation'],{'marker':'preserve'})
        self.assertFalse(reopened['physical_qualification'])
        with zipfile.ZipFile(io.BytesIO(self.library.export())) as archive:
            row=json.loads(archive.read('dataset/train.jsonl'))
        self.assertEqual(row['answers'],reopened['answers'])

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
