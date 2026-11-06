"""Compare and replace legacy-motion teaching targets from the native catalog.

Offline dataset maintenance, using semantic_teachers and MotionLibrary rather
than another executor or importer. Raw trials, old datasets and fitted models
are evidence; this command never calls a model or operates the robot.
"""
import argparse
import copy
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .compact_wire import ProgramEncoding, model_query
from .motion_library import MotionLibrary
from .observations import enrich
from .program import compile_motion
from .runtime import JOINTS, compact
from .semantic_teachers import legacy_sources, source_motion


# Identified producers of endpoint-only postures and substitute named gestures.
# Explicit Cartesian commands, face-only requests and independent recovery
# lessons are not selected by a word appearing in the request.
REPLACED_FAMILIES = frozenset({
    'source_posture_sit', 'source_posture_rest', 'source_posture_crouch',
    'source_wave', 'source_joint_wave', 'gesture_ending_wave',
    'gesture_ending_bow', 'gesture_ending_point', 'gesture_ending_shrug',
    'semantic_bowing', 'semantic_shrugging', 'semantic_hand_circle',
    'semantic_swat_then_shrug', 'calibrated_spatial_wave', 'recorded_wave_entry',
    'proposed_recorded_wave_correction', 'recorded_stretch_feedback_recovery',
    'generated_wave_demonstration', 'reviewed_audience_wave',
})
REPLACED_TASKS = frozenset({'bow', 'shrug', 'wave', 'point'})
REASON = ('Superseded legacy-motion substitute or dependent lesson. Complete '
          'catalog-source demonstrations replace these targets; original requests '
          'and targets remain in the alignment evidence, not positive training.')
REQUESTS = {
    'sit':'Sit down.', 'rest':'Rest your body.', 'wave':'Wave hello.',
    'dance':'Dance.', 'swim':'Do the swimming motion.', 'point':'Point.',
    'nod':'Nod.', 'pushup':'Do pushups.', 'bow':'Give a polite bow.',
    'cute':'Do the cute motion.', 'freaky':'Do the freaky motion.',
    'worm':'Do the worm.', 'shake':'Shake your body.', 'shrug':'Shrug.',
    'dead':'Play dead.', 'lay_down':'Lie down.', 'celebrate':'Celebrate.',
    'stretch':'Stand up, stretch, and finish standing.',
    'surprised':'Act surprised.', 'sad':'Act sad.', 'curious':'Act curious.',
    'upright':'Stand upright on your hind legs.', 'crouch':'Crouch down.',
}


def rows_at(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def native_examples(tools, stretch_contexts=()):
    encoding = ProgramEncoding(tools)
    _, sources = legacy_sources()
    result = []
    for name in sources:
        demonstration = source_motion(name)
        observation = {
            'model':'v2-12servo', 'features':['motion_curves_v1'], 'joint_speed_limit_deg_s':180,
            'joints':{joint:{'model_deg':angle, 'commanded_model_deg':angle,
                             'home_deg':None, 'calibrated':None}
                      for joint,angle in zip(JOINTS,demonstration['entry_model_deg'])}}
        program = demonstration['program']
        planned = None
        for action in program:
            if action['name'] in ('pose','move','feet','body','oscillate'):
                planned = compile_motion(action,observation,planned)['end']
        if max(abs(planned[j]-q) for j,q in zip(JOINTS,demonstration['final_model_deg'])) > .005:
            raise ValueError(name+': compiled terminal pose differs from the source')
        query = compact(model_query(enrich({'request':REQUESTS[name], 'event':None,
                                           'history':[], 'observation':observation}),encoding))
        answers = encoding.encode(program)
        identity = hashlib.sha256(compact([query,answers,demonstration['source_sha256']]).encode()).hexdigest()
        evidence = {k:v for k,v in demonstration.items() if k != 'program'}
        example={'id':identity[:16], 'source_hash':identity,
                       'source_id':f"native-source:{name}:{demonstration['source_sha256']}",
                       'family':'legacy_asset_'+name, 'title':REQUESTS[name],
                       'query':query, 'answers':answers, 'split':'train',
                       'synthetic':True, 'physical_qualification':False,
                       'qualification_basis':'compact_source_stages_not_physically_reviewed',
                       'observation_origin':'synthetic canonical source entry; calibration unknown',
                       'teacher':'native twelve-servo catalog source and execution contract',
                       'canonical_source_motion_sha256':demonstration['source_sha256'],
                       'legacy_motion':name, 'source_alignment':evidence}
        if name=='stretch' and stretch_contexts:
            for context in stretch_contexts:
                if context.get('qualification_basis')=='owner_requested_compact_stretch_not_physically_reviewed':
                    result.append(copy.deepcopy(context))
                else:
                    updated=_contextual_source(example,context['query'],tools)
                    result.append({**context,**updated,'observation_origin':context['observation_origin']})
        else:
            result.append(example)
    return result


def contextual_example(source, observation, request, tools):
    """Teach a complete source motion from supplied state, with its entry target.

    This authors offline supervision only. It neither selects runtime behavior
    nor labels a generated or source-derived movement as physically qualified.
    """
    query=compact(model_query(enrich({'request':request,'event':None,'history':[],
                                     'observation':observation}),ProgramEncoding(tools)))
    return _contextual_source(source,query,tools)


def _contextual_source(source, query, tools):
    """Regenerate source targets while preserving the already projected input."""
    encoding=ProgramEncoding(tools)
    program=encoding.decode(source['answers'])
    if source['legacy_motion']!='stretch':
        program.insert(1,{'name':'pose','arguments':{'joints':list(JOINTS),
            'angles_deg':source['source_alignment']['entry_model_deg'],
            'reference':'absolute','speed_pct':100,'taper_deg':0}})
    answers=encoding.encode(program)
    identity=hashlib.sha256(compact([query,answers,source['canonical_source_motion_sha256']]).encode()).hexdigest()
    result=copy.deepcopy(source)
    result.update(id=identity[:16],source_hash=identity,query=query,answers=answers,title=json.loads(query)['request'],
                  source_id='native-context:'+source['legacy_motion']+':'+identity,
                  source_reference_example_id=source['id'],physical_qualification=False,
                  observation_origin='supplied state; recorded or synthetic origin identified by dataset author',
                  qualification_basis='source_curve_and_entry_target_not_physically_reviewed')
    return result


def natural_examples(phrases, tools):
    """Three owner-approved everyday requests per legacy reference program."""
    encoding=ProgramEncoding(tools)
    _,clips=legacy_sources()
    if set(phrases)!=set(clips)|{'stand'}:
        raise ValueError('Phrase list must cover the actual legacy catalog and standing')
    result=[]
    for name,requests in phrases.items():
        if len(requests)!=3 or len(set(requests))!=3:
            raise ValueError('Each motion needs three distinct natural requests')
        if name=='stand':
            owner=Path(__file__).resolve().parents[2]/'Slave/firmware/esp32p4-wifi6/main/body.c'
            reference={'source_sha256':hashlib.sha256(owner.read_bytes()).hexdigest()}
            program=[{'name':'stand','arguments':{}}]
        else:
            reference=source_motion(name);program=reference['program']
        answers=encoding.encode(program)
        for request in requests:
            query=compact({'request':request})
            identity=hashlib.sha256(compact([name,query,answers,reference['source_sha256']]).encode()).hexdigest()
            result.append({'id':identity[:16],'family':'natural_legacy_'+name,'title':request,
                'query':query,'answers':answers,'source_id':'natural-legacy:'+name+':'+identity,
                'source_hash':identity,'synthetic':True,'physical_qualification':False,
                'qualification_basis':'legacy_reference_poses_not_a_physical_trial',
                'teacher':'legacy reference poses, compact movement stages and explicit holds',
                'reference_motion':name,'reference_source_sha256':reference['source_sha256'],
                **{'reference_'+key:reference[key] for key in
                   ('entry_model_deg','final_model_deg','phases') if key in reference},
                **({'native_operation':'stand',
                    'reference_implementation':'Slave/firmware/esp32p4-wifi6/main/body.c',
                    'qualification_basis':'native_stand_selection_not_a_physical_trial',
                    'teacher':'Existing P4 Stand operation; no replacement joint pose'} if name=='stand' else {})})
    return result


def obsolete_rows(rows, replacements):
    """Withdraw identified substitutes and their explicit lineage, not keywords."""
    replacement_ids = {r['id'] for r in replacements}
    selected = {r['id'] for r in rows if r['id'] not in replacement_ids and (
        r['family'] in REPLACED_FAMILIES
        or bool(set(r.get('task_families',[])) & REPLACED_TASKS)
        or r['family'].startswith('legacy_asset_'))}
    aliases = set()
    while True:
        for r in rows:
            if r['id'] in selected:
                aliases.update(v for v in (r['id'],r.get('parent_example_id'),
                                          r.get('source_hash','')[:16]) if v)
        linked = {r['id'] for r in rows if r['id'] not in replacement_ids and any(
            parent in aliases for parent in (r.get('parent_example_id'),
                                            *[p['id'] for p in r.get('parent_examples',[])]))}
        added = linked-selected
        if not added:break
        selected.update(added)
    return selected, aliases


def align(dataset, database, evidence, apply=False):
    dataset, database, evidence = map(Path,(dataset,database,evidence))
    training = rows_at(dataset/'train.jsonl')
    original_tools = json.loads((dataset/'tools.json').read_text())
    from .motion_space import TOOLS
    from .face_contract import face_tool
    tools = [*TOOLS, face_tool()]
    references={p.name:rows_at(p) for p in dataset.glob('*.jsonl') if p.name!='train.jsonl'}
    with sqlite3.connect(f'file:{database}?mode=ro',uri=True) as db:
        stored=list(db.execute('SELECT id,revision,payload FROM examples'))
        current=[json.loads(row[2]) for row in stored]
        revisions={row[0]:row[1] for row in stored}
        live_tools = json.loads(db.execute("SELECT value FROM metadata WHERE key='tools'").fetchone()[0])
        library_references={name[5:]:[json.loads(s) for s in text.splitlines() if s.strip()]
                            for name,text in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'file:%.jsonl'")}
    if live_tools not in (original_tools,tools):
        raise ValueError('Dataset and editable library use different operation contracts')
    contexts=[r for r in training if r.get('family')=='legacy_asset_stretch']
    replacements = native_examples(tools,contexts)
    stretch_source=source_motion('stretch')['source_sha256']
    protected_references=[r for rows in [*references.values(),*library_references.values()] for r in rows
                          if r.get('family')=='legacy_asset_stretch' and (
                              r.get('qualification_basis')=='owner_requested_compact_stretch_not_physically_reviewed'
                              or (r.get('source_id','').startswith('native-context:stretch:')
                                  and r.get('canonical_source_motion_sha256')==stretch_source))]
    selected, aliases = obsolete_rows(training+current+
        [r for rows in [*references.values(),*library_references.values()] for r in rows],replacements+protected_references)
    retired_training = [r for r in training if r['id'] in selected]
    retired_library = [r for r in current if r['id'] in selected]
    retired_references={name:[r for r in rows if r['id'] in selected] for name,rows in references.items()}
    retired_library_references={name:[r for r in rows if r['id'] in selected] for name,rows in library_references.items()}
    # A physical review is tied to the executed program. Keep any conflict
    # visible rather than silently discarding independently accepted evidence.
    if any(r.get('physical_qualification') for r in retired_training+retired_library+
           [r for rows in [*retired_references.values(),*retired_library_references.values()] for r in rows]):
        raise ValueError('A selected source substitute has a physical-success claim; review its identity first')
    native_ids = {r['id'] for r in replacements}
    retained = [r for r in training if r['id'] not in selected and r['id'] not in native_ids]
    updated = retained+replacements
    report = {'source':'native twelve-servo gesture catalog', 'motions':len({r.get('legacy_motion','stretch') for r in replacements}),
              'source_examples':len(replacements),
              'training_before':len(training), 'training_after':len(updated),
              'retired_training_rows':len(retired_training),
              'retired_training_families':dict(Counter(r['family'] for r in retired_training)),
              'library_before':len(current),
              'library_after':len([r for r in current if r['id'] not in selected|native_ids])+len(replacements),
              'retired_library_rows':len(retired_library),
              'retired_reference_rows':{name:len(rows) for name,rows in retired_references.items()},
              'retired_library_reference_rows':{name:len(rows) for name,rows in retired_library_references.items()},
              'training_launched':False, 'model_changed':False, 'physical_trials':0,
              'evidence':str(evidence),
              'assets':[{'motion':r.get('legacy_motion','stretch'),'example_id':r['id'],
                         'actions':len(r['answers']),**r.get('source_alignment',
                            {k:v for k,v in source_motion('stretch').items() if k!='program'})} for r in replacements]}
    if not apply:return report
    evidence.mkdir(parents=True,exist_ok=False)
    shutil.copytree(dataset,evidence/'dataset-before')
    with sqlite3.connect(f'file:{database}?mode=ro',uri=True) as src:
        with sqlite3.connect(evidence/'motion-library-before.sqlite') as backup:src.backup(backup)
    (evidence/'removed-examples.jsonl').write_text(''.join(compact(r)+'\n' for r in retired_training+retired_library))
    (evidence/'removed-references.json').write_text(json.dumps({**retired_references,
        **{'library/'+name:rows for name,rows in retired_library_references.items()}},indent=2)+'\n')
    (evidence/'native-examples.jsonl').write_text(''.join(compact(r)+'\n' for r in replacements))
    (evidence/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    library = MotionLibrary(database)
    with tempfile.TemporaryDirectory(prefix='ainekio-native-dataset-') as temporary:
        staged = Path(temporary)
        shutil.copy2(dataset/'wire.json',staged/'wire.json')
        (staged/'tools.json').write_text(compact(tools)+'\n')
        (staged/'train.jsonl').write_text(''.join(compact(r)+'\n' for r in replacements))
        # Import uses the existing transactional retirement owner. Remember
        # snapshot-only IDs too, so an older export cannot restore bad lessons.
        (staged/'manifest.json').write_text(compact({'discarded_examples':[
            {'id':identifier,'replacement_id':None,'reason':REASON}
            for identifier in sorted(aliases-native_ids)]}))
        library.import_dataset(staged,extend_contract=True,
            expected_revisions={r['id']:revisions[r['id']] for r in retired_library},
            retired_references=selected)
    manifest = json.loads((dataset/'manifest.json').read_text())
    discarded = {r['id']:r for r in manifest.get('discarded_examples',[])}
    for identifier in sorted(aliases-native_ids):
        discarded[identifier] = {'id':identifier,'replacement_id':None,'reason':REASON}
    manifest.update(training_rows=len(updated),training_launched=False,
                    discarded_examples=list(discarded.values()))
    manifest['legacy_source_alignment'] = {
        'updated_at':datetime.now(timezone.utc).isoformat(),
        **{k:v for k,v in report.items() if k != 'assets'},
        'assets':[{k:r[k] for k in ('motion','example_id','source_sha256','execution_contract_sha256',
                                   'semantic_end_s','representation')}
                  for r in report['assets']]}
    (dataset/'train.jsonl').write_text(''.join(compact(r)+'\n' for r in updated))
    (dataset/'tools.json').write_text(compact(tools)+'\n')
    for name,rows in references.items():
        if retired_references[name]:
            (dataset/name).write_text(''.join(compact(r)+'\n' for r in rows if r['id'] not in selected))
    manifest['files'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in dataset.iterdir() if p.is_file() and p.name != 'manifest.json'}
    (dataset/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    if library.list()['total'] != report['library_after']:
        raise ValueError('Library import count differs from the prepared comparison')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    result = align(args.dataset,args.database,args.evidence,args.apply)
    print(compact({k:v for k,v in result.items() if k != 'assets'}))
