"""External request bank and repeatable, generation-only motion trials.

Kinematic replay predicts paths. It does not measure contact, stability or task
success. Reviews attach independent trajectory criteria and corrected examples;
neither valid JSON nor the model's own opinion constitutes a successful trial.
"""
import argparse
import csv
import hashlib
import json
import math
import random
import re
import zipfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .generator import Generator
from .kinematics import ROOT, foot_positions, mechanism
from .program import compile_motion
from .runtime import JOINTS, compact


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_rows(path, rows):
    with Path(path).open('x') as stream:
        for row in rows:
            stream.write(compact(row)+'\n')


def normalized(text):
    return ' '.join(re.findall(r'[a-z0-9]+', text.lower()))


def import_bank(source, output):
    """Keep original clips, crop siblings, mirrors and duplicate captions together."""
    with (source/'index.csv').open() as stream:
        index = {Path(r['new_name']).stem:r for r in csv.DictReader(stream)}
    rows, parent, phrases = [], {}, {}

    def root(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    with zipfile.ZipFile(source/'texts.zip') as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith('texts/') or not name.endswith('.txt'):
                continue
            clip = Path(name).stem
            original = clip[1:] if clip.startswith('M') else clip
            metadata = index[original]
            group = metadata['source_path']
            root(group)
            for number, line in enumerate(archive.read(name).decode().splitlines()):
                description, tags, start, end = line.rsplit('#', 3)
                phrase = normalized(description)
                if phrase in phrases:
                    parent[root(group)] = root(phrases[phrase])
                phrases[phrase] = group
                rows.append({'id':f'humanml3d:{clip}:{number}', 'clip':clip,
                             'source_motion':group, 'description':description,
                             'tags':tags,
                             'segment_s':[float(v) if math.isfinite(float(v)) else None for v in (start,end)],
                             'source_segment_text':[start,end],
                             'source_frames':[int(metadata['start_frame']), int(metadata['end_frame'])],
                             'mirrored':clip.startswith('M')})
    for row in rows:
        row['holdout_group'] = hashlib.sha256(root(row['source_motion']).encode()).hexdigest()[:20]
        row['exposure'] = 'external_candidate_not_yet_audited_against_training'
    output.mkdir(parents=True, exist_ok=False)
    write_rows(output/'bank.jsonl', rows)
    manifest = {'source':'https://github.com/EricGuo5513/HumanML3D',
                'revision':'9176e8fb446b71c7d2a725eb5cf6fec1ae3b3c23',
                'annotations':len(rows), 'original_clips':len({r['clip'] for r in rows if not r['mirrored']}),
                'holdout_groups':len({r['holdout_group'] for r in rows}),
                'source_files':{p.name:digest(p) for p in source.iterdir() if p.is_file()},
                'bank_sha256':digest(output/'bank.jsonl'),
                'motion_coordinates_downloaded':False,
                'note':'External text references, not retargeted robot demonstrations. Semantic-family novelty requires a training audit.'}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


def draw(bank, previous, count, seed):
    used = {r['holdout_group'] for path in previous for r in read_rows(path)}
    groups = {}
    for row in read_rows(bank):
        if row['holdout_group'] not in used and not row['mirrored']:
            groups.setdefault(row['holdout_group'], []).append(row)
    rng = random.Random(seed)
    selected = rng.sample(sorted(groups), count)
    rows = [dict(rng.choice(groups[group])) for group in selected]
    for row in rows:
        row['request'] = 'Act out this motion with your body: '+row['description']
    return rows


def replay(program, observation, native_gait=None):
    """Use the same compiler as Body Control, then independently measure FK paths."""
    positions = {j:observation['joints'][j]['model_deg'] for j in JOINTS}
    home = {j:observation['joints'][j]['home_deg'] for j in JOINTS}
    time_s, samples, completed = 0., [], 0
    gait_segments = []
    face_events = []

    def gait_evidence():
        return {**({'native_gait_segments':gait_segments} if gait_segments else {}),
                **({'face_events':face_events} if face_events else {}),
                'timing_scope':'nominal travel at commanded joint rate plus explicit holds; measured arrival unmodeled'}

    def sample(index):
        samples.append({'time_s':time_s, 'action_index':index, 'joints_deg':dict(positions),
                        'feet_body_mm':foot_positions(positions, fk_model)})

    try:
        # One independent FK model per replay. IK compilation mutates its own
        # models; concurrent trials must not share their body-pose state.
        fk_model = mechanism()
        sample(-1)
        for index, action in enumerate(program):
            name = action['name']
            if name == 'face':
                from .face_contract import available_faces
                expression=action['arguments']['expr']
                if expression not in available_faces():
                    raise ValueError(f'Unknown renderer face expression: {expression}')
                face_events.append({'time_s':time_s,'action_index':index,'expr':expression})
                sample(index)
                completed += 1
                continue
            if name == 'gait' and native_gait is not None:
                from .gait_replay import sample_gait
                result = sample_gait(action['arguments'], observation['joint_speed_limit_deg_s'], native_gait)
                for segment in result['segments']:
                    native_samples = segment['samples']
                    start_time = time_s
                    entry_delta = (max(abs(q-positions[j]) for j,q in zip(JOINTS,native_samples[0]['model_deg']))
                                   if native_samples else None)
                    gait_segments.append({**segment, 'action_index':index, 'start_time_s':start_time,
                        'entry_target_jump_deg':entry_delta,
                        'scope':'Command-relative nominal body path; contact and actual chassis travel unmeasured.'})
                    # The body sends the gait entry target directly. Record its
                    # discontinuity instead of inventing an entry interpolation.
                    for point in native_samples:
                        positions = dict(zip(JOINTS,point['model_deg']))
                        time_s = start_time + point['time_us']/1e6
                        sample(index)
                if result['status'] != 'replayed':
                    return {'status':result['status'], 'operation':name,
                            'completed_actions':completed, 'samples':samples,
                            'reason':result.get('reason'), 'error':result.get('error'), **gait_evidence()}
                completed += 1
                continue
            if name == 'hold':
                time_s += action['arguments']['seconds']
                sample(index)
                completed += 1
                continue
            if name in ('feet', 'body', 'move', 'pose', 'oscillate'):
                current = {**observation, 'joints': {
                    j:{**observation['joints'][j], 'model_deg':positions[j],
                       'commanded_model_deg':positions[j]} for j in JOINTS}}
                frames = compile_motion(action, current, positions)['frames']
            else:
                return {'status':'not_fully_replayed', 'operation':name,
                        'completed_actions':completed, 'samples':samples,
                        'reason':'This kinematic replay has no configured replay for this operation.', **gait_evidence()}
            for speed_cd_s, angles in frames:
                start = dict(positions)
                duration = max(abs(angles[k]/100-start[j]) for k,j in enumerate(JOINTS))/(speed_cd_s/100)
                # This is a geometric replay, not a time-stepped dynamics engine.
                # Sample intermediate joint configurations independently of speed.
                steps = max(1, math.ceil(max(abs(angles[k]/100-start[j]) for k,j in enumerate(JOINTS))/.25))
                for i in range(1, steps+1):
                    # The emitted endpoint is exact centidegree wire data.
                    # Interpolation roundoff (e.g. 3e-15 instead of zero) can
                    # corrupt relative finite differences in the next IK call.
                    positions = ({j:angles[k]/100 for k,j in enumerate(JOINTS)} if i==steps else
                                 {j:start[j]+(angles[k]/100-start[j])*i/steps for k,j in enumerate(JOINTS)})
                    time_s += duration/steps
                    sample(index)
            completed += 1
    except (ValueError, KeyError, TypeError, ZeroDivisionError, OverflowError) as error:
        return {'status':'compile_or_replay_error', 'error':str(error),
                'completed_actions':completed, 'samples':samples, **gait_evidence()}
    return {'status':'replayed', 'completed_actions':completed, 'samples':samples,
            'sampling':('native gait targets at 50 Hz; other operations at most 0.25 degrees between linear joint samples'
                        if gait_segments else 'at most 0.25 degrees between linear joint samples; all packet endpoints retained'),
            **gait_evidence()}


def trajectory_metrics(trace):
    """Numerical evidence only; no task-success label is inferred from movement."""
    samples = trace['samples']
    metrics = {'duration_s':samples[-1]['time_s']-samples[0]['time_s'] if samples else 0}
    if not samples:
        return metrics
    paths = {f'joint.{j}':[s['joints_deg'][j] for s in samples] for j in JOINTS}
    for leg in samples[0]['feet_body_mm']:
        points = [s['feet_body_mm'][leg] for s in samples]
        metrics[f'foot.{leg}.return_error'] = math.dist(points[0],points[-1])
        metrics[f'foot.{leg}.max_displacement'] = max(math.dist(points[0],p) for p in points)
        for plane,a,b in [('xy',0,1),('xz',0,2),('yz',1,2)]:
            closed = points+[points[0]]
            metrics[f'foot.{leg}.{plane}.signed_area'] = sum(p[a]*q[b]-p[b]*q[a] for p,q in zip(closed,closed[1:]))/2
        for axis, name in enumerate('xyz'):
            paths[f'foot.{leg}.{name}'] = [s['feet_body_mm'][leg][axis] for s in samples]
    for name, values in paths.items():
        metrics[name+'.range'] = max(values)-min(values)
        metrics[name+'.end_delta'] = values[-1]-values[0]
        metrics[name+'.peak_delta'] = max(values)-values[0]
        metrics[name+'.trough_delta'] = min(values)-values[0]
        metrics[name+'.travel'] = sum(abs(b-a) for a,b in zip(values, values[1:]))
    # Unspecified hand means either front leg, not an invented right-hand rule.
    if 'front_left' in samples[0]['feet_body_mm'] and 'front_right' in samples[0]['feet_body_mm']:
        for suffix in ('max_displacement','x.range','y.range','z.range'):
            values=[metrics[f'foot.front_{side}.{suffix}'] for side in ('left','right')]
            metrics['front.any.'+suffix]=max(values)
            metrics['front.both.'+suffix]=min(values)
    return metrics


def assess(metrics, criteria, trace=None):
    """Criteria must describe the requested outcome before generation is inspected."""
    checks = []
    for criterion in criteria:
        value = metrics.get(criterion['metric'])
        if criterion['metric'].endswith('.excursions') and trace and trace['samples']:
            _,leg,axis,_ = criterion['metric'].split('.')
            values=[s['feet_body_mm'][leg]['xyz'.index(axis)] for s in trace['samples']]
            excursion=criterion['excursion_mm'];sign=1 if excursion>0 else -1
            armed=False;value=0
            for position in values:
                delta=(position-values[0])*sign
                if delta>=abs(excursion):armed=True
                if armed and delta<=criterion['return_tolerance_mm']:
                    value+=1;armed=False
        checks.append({**criterion, 'actual':value,
                       'passed':value is not None and math.isfinite(value) and
                       criterion.get('min', -math.inf) <= value <= criterion.get('max', math.inf)})
    return {'checks':checks, 'criteria_passed':all(c['passed'] for c in checks) if checks else None,
            'physical_success':None,
            'scope':'kinematic criteria only; no balance, contact, collision or recovery proof'}


def query_identity(query):
    try:
        return json.dumps(json.loads(query), sort_keys=True, separators=(',', ':'))
    except ValueError:
        return query


def exposure(row, state, training_queries, training_groups):
    query = compact({'request':row['request'], 'event':None, 'observation':state, 'history':[]})
    exact = query_identity(query) in training_queries
    group_seen = row.get('holdout_group') in training_groups
    original = row.get('evaluation_split', 'unclassified')
    return {'original_evaluation_split':original,
            'evaluation_split':'trained_source_regression' if group_seen else
                               'exact_training_regression' if exact else original,
            'training_exposure':{'exact_query_seen':exact, 'source_group_seen':group_seen,
                'scope':'Supplied fine-tuning files only; no claim about base pretraining or unseen skill semantics.'}}


def run(cases, output, contract, endpoint, model, model_file, state_file, training_files, workers=1, native_gait=None):
    generator = Generator(endpoint, model, contract, model_file)
    state = json.loads(state_file.read_text())
    replay_inputs = {'replay_code_sha256':Path(__file__),
                     'compiler_sha256':Path(__file__).with_name('kinematics.py'),
                     'geometry_sha256':ROOT/'geometry.json',
                     'mechanism_sha256':ROOT/'motions/walk/reference.py'}
    if native_gait is not None:
        replay_inputs.update(native_gait_binary_sha256=Path(native_gait),
                             native_gait_wrapper_sha256=Path(__file__).with_name('gait_replay.py'))
    identity = {'model_sha256':digest(model_file), 'contract_sha256':digest(contract/'system.txt'),
                'tools_sha256':digest(contract/'tools.json'), 'state_sha256':digest(state_file),
                'cases_sha256':digest(cases), 'training_files':{str(p):digest(p) for p in training_files},
                **{key:digest(path) for key,path in replay_inputs.items()}}
    training_queries, training_groups = set(), set()
    for path in training_files:
        for row in read_rows(path):
            training_queries.add(query_identity(row['query']))
            if row.get('holdout_group'):training_groups.add(row['holdout_group'])
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    def generate(row):
        item = {**row, **identity, **exposure(row,state,training_queries,training_groups),
                'observation':state, 'execution':'kinematic_prediction', 'hardware_dispatched':False}
        try:
            item.update(generator.generate(row['request'], state))
        except Exception as error:
            item['error'] = str(error)
            if hasattr(error,'evidence'):
                item['incomplete_generation']=error.evidence
        return item

    def trial(item):
        if 'error' in item:return item
        try:
            trace = replay(item['program'], state, native_gait)
            metrics = trajectory_metrics(trace)
            trace_file = output/(item['id'].replace(':','_')+'.trace.json')
            trace_file.write_text(compact(trace)+'\n')
            item.update(replay_status=trace['status'], metrics=metrics,
                        trace_file=trace_file.name, trace_sha256=digest(trace_file),
                        assessment=assess(metrics, item.get('criteria', []),trace))
            if trace['status'] != 'replayed':
                item['assessment']['criteria_passed'] = False if item.get('criteria') else None
            if 'error' in trace:item['replay_error'] = trace['error']
        except Exception as error:
            item['error'] = str(error)
        return item
    completed = []
    with (output/'trials.jsonl').open('x') as results, (output/'generations.jsonl').open('x') as generations, \
            ThreadPoolExecutor(max_workers=workers) as inference, ThreadPoolExecutor(max_workers=workers) as simulations:
        pending = []
        for future in as_completed([inference.submit(generate,row) for row in read_rows(cases)]):
            item = future.result()
            generations.write(compact(item)+'\n'); generations.flush()
            pending.append(simulations.submit(trial,item))
        for future in as_completed(pending):
            item = future.result()
            completed.append(item)
            results.write(compact(item)+'\n'); results.flush()
            print(compact({k:item.get(k) for k in ('id','elapsed_s','replay_status','error')}), flush=True)
    report = {'cases':len(completed), 'workers':workers, 'wall_seconds':time.perf_counter()-started,
              'fully_replayed':sum(r.get('replay_status')=='replayed' for r in completed),
              'criteria_passed':sum(r.get('assessment',{}).get('criteria_passed') is True for r in completed),
              'unscored':sum(r.get('assessment',{}).get('criteria_passed') is None for r in completed),
              'physical_trials':0, 'model_sha256':identity['model_sha256'],
              'trained_source_cases':sum(r['training_exposure']['source_group_seen'] for r in completed),
              'exact_training_queries':sum(r['training_exposure']['exact_query_seen'] for r in completed),
              'replay_inputs_unchanged':all(digest(path)==identity[key] for key,path in replay_inputs.items())}
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(compact(report),flush=True)


def corrections(trials_file, reviews_file, output):
    """Export evidence-linked corrected targets; failed model output is never its target."""
    trials = {r['id']:r for r in read_rows(trials_file)}
    rows = []
    for review in read_rows(reviews_file):
        trial = trials[review['id']]
        # These are dataset-integrity requirements, never robot execution gates.
        if not review.get('evidence') or not review.get('reviewer') or not review.get('corrected_program'):
            raise ValueError('A correction needs a reviewer, evidence and its corrected program')
        evidence_path = reviews_file.parent/review['evidence']
        evidence_hash = digest(evidence_path)
        query = compact({'request':trial['request'], 'event':None,
                         'observation':trial['observation'], 'history':[]})
        source_hash = hashlib.sha256(compact([trial, review, evidence_hash]).encode()).hexdigest()
        rows.append({'id':source_hash[:16], 'family':review['motion_family'], 'query':query,
                     'answers':review['corrected_program'], 'source_id':'reviewed-trial:'+trial['id'],
                     'source_hash':source_hash, 'holdout_group':trial['holdout_group'],
                     'synthetic':True, 'physical_qualification':False,
                     'evidence_sha256':evidence_hash, 'review':review,
                     'exposure':'training_and_regression_after_this_round'})
    write_rows(output, rows)
    return {'corrections':len(rows), 'retired_from_unseen_groups':sorted({r['holdout_group'] for r in rows})}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('import'); p.add_argument('--source', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = commands.add_parser('draw'); p.add_argument('--bank', type=Path, required=True); p.add_argument('--previous', type=Path, nargs='*', default=[])
    p.add_argument('--count', type=int, required=True); p.add_argument('--seed', type=int, required=True); p.add_argument('--output', type=Path, required=True)
    p = commands.add_parser('run')
    for name in ('cases','output','contract','model-file','state-file'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--training-files', type=Path, nargs='+', required=True)
    p.add_argument('--endpoint', required=True); p.add_argument('--model', required=True)
    p.add_argument('--workers', type=int, default=1)
    p.add_argument('--native-gait', type=Path, help='Offline native_gait executable for finite P4 gait targets')
    p = commands.add_parser('corrections')
    for name in ('trials','reviews','output'): p.add_argument('--'+name, type=Path, required=True)
    a = parser.parse_args()
    if a.command == 'import': print(compact(import_bank(a.source, a.output)))
    elif a.command == 'draw': write_rows(a.output, draw(a.bank, a.previous, a.count, a.seed))
    elif a.command == 'run': run(a.cases,a.output,a.contract,a.endpoint,a.model,a.model_file,a.state_file,a.training_files,a.workers,a.native_gait)
    else: print(compact(corrections(a.trials,a.reviews,a.output)))
