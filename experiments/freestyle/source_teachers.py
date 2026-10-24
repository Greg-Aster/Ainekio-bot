"""Offline compact joint-path candidates from complete authored gesture sources.

Preserves source phase boundaries, explicit holds and significant retraced
motion. Travel uses the requested joint percentage, not source timing/easing.
The error budget is an offline approximation measurement, never a robot limit.
Candidates still need kinematic and semantic review before training export.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from .challenge import digest, replay
from .kinematics import ROOT
from .runtime import JOINTS, compact
from .semantic_teachers import call


def simplify(points, mandatory, tolerance):
    keep=set(mandatory)
    def split(a,b):
        if b-a<2:return
        values=points[a:b+1];direction=points[b]-points[a]
        denominator=float(direction@direction)
        progress=np.clip((values-points[a])@direction/denominator,0,1) if denominator else np.zeros(len(values))
        error=np.max(np.abs(values-(points[a]+progress[:,None]*direction)),axis=1)
        index=int(np.argmax(error))
        if error[index]>tolerance:
            middle=a+index;keep.add(middle);split(a,middle);split(middle,b)
            return
        # A curve can retrace the same straight line several times with zero
        # chord error. Retain the backtracking extrema so cycles do not vanish.
        reversal=(np.maximum.accumulate(progress)-progress)*np.max(np.abs(direction))
        low=int(np.argmax(reversal))
        if reversal[low]>tolerance:
            high=int(np.argmax(progress[:low+1]))
            boundaries=sorted({a,a+high,a+low,b})
            keep.update(boundaries)
            for start,end in zip(boundaries,boundaries[1:]):split(start,end)
    ordered=sorted(keep)
    for a,b in zip(ordered,ordered[1:]):split(a,b)
    return sorted(keep)


def candidate(source_file, observation, tolerance=.25, speed_pct=50):
    source=json.loads(source_file.read_text());samples=source['samples']
    times=np.array([s['time_s'] for s in samples])
    angles=np.rad2deg(np.array([s['actuator_angles_rad'] for s in samples])).reshape(-1,12)
    boundaries={0,len(samples)-1};phases=[]
    for phase in source['phases']:
        a,b=[int(np.argmin(np.abs(times-t))) for t in (phase['start'],phase['end'])]
        phases.append({**phase,'start_index':a,'end_index':b})
        boundaries.update((a,b))
    selected=simplify(angles,boundaries,tolerance)
    quantized=np.round(angles,2)
    program=[call('pose',joints=list(JOINTS),angles_deg=quantized[0].tolist(),reference='absolute',speed_pct=speed_pct)]
    segments=[];phase_map=[];current=quantized[0]
    for phase in phases:
        start_action=len(program);a,b=phase['start_index'],phase['end_index']
        indexes=[i for i in selected if a<=i<=b]
        if 'hold' in phase['kind'].lower():
            # Keep the authored pause. Record any source numerical drift below.
            program.append(call('hold',seconds=round(phase['end']-phase['start'],9)))
            segments.append({'source_start':a,'source_end':b,'action_index':len(program)-1,
                             'start_deg':current.tolist(),'end_deg':current.tolist(),'hold':True})
        else:
            for first,last in zip(indexes,indexes[1:]):
                target=quantized[last];joints=[j for j in range(12) if current[j]!=target[j]]
                action_index=None
                if joints:
                    program.append(call('pose',joints=[JOINTS[j] for j in joints],
                        angles_deg=[float(target[j]) for j in joints],reference='absolute',speed_pct=speed_pct))
                    action_index=len(program)-1
                segments.append({'source_start':first,'source_end':last,'action_index':action_index,
                                 'start_deg':current.tolist(),'end_deg':target.tolist(),'hold':False})
                current=target
        phase_map.append({**phase,'action_start':start_action,'action_end':len(program)})
    worst=0.;range_loss=0.;backtrack=0.
    for segment in segments:
        values=angles[segment['source_start']:segment['source_end']+1]
        begin=np.asarray(segment['start_deg']);end=np.asarray(segment['end_deg']);direction=end-begin
        denominator=float(direction@direction)
        progress=np.clip((values-begin)@direction/denominator,0,1) if denominator else np.zeros(len(values))
        worst=max(worst,float(np.max(np.abs(values-(begin+progress[:,None]*direction)))))
        range_loss=max(range_loss,float(np.max(np.maximum(values.max(0)-np.maximum(begin,end),np.minimum(begin,end)-values.min(0)))))
        backtrack=max(backtrack,float(np.max(np.maximum.accumulate(progress)-progress)*np.max(np.abs(direction))))
    trace=replay(program,observation)
    return {'source_sha256':digest(source_file),'source_file':str(source_file),
            'teacher_sha256':digest(Path(__file__)),'observation':observation,
            'program':program,'trace':trace,'source_phases':phase_map,'source_segments':segments,
            'source_samples':len(samples),'selected_source_points':len(selected),
            'joint_speed_pct':speed_pct,'approximation_budget_deg':tolerance,
            'measured_max_source_to_chord_error_deg':worst,
            'measured_max_joint_range_loss_deg':range_loss,
            'measured_max_omitted_backtracking_deg':backtrack,
            'source_duration_s':float(times[-1]),
            'authored_hold_seconds':sum(p['end']-p['start'] for p in phases if 'hold' in p['kind'].lower()),
            'physical_qualification':False,'training_exported':False,
            'scope':'Complete phase/cycle candidate with measured joint-path approximation; source travel timing, easing, contact and stability are not reproduced or physically qualified.'}


def spatial_candidate(source_file, observation, tolerance=.25, speed_pct=50,
                      spatial_tolerance_mm=.25, spatial_tolerance_deg=.25):
    """Express torso changes as kinematics, retaining joint-only stroke paths."""
    from scipy.spatial.transform import Rotation
    source=json.loads(source_file.read_text());samples=source['samples']
    times=np.array([s['time_s'] for s in samples])
    angles=np.rad2deg(np.array([s['actuator_angles_rad'] for s in samples])).reshape(-1,12)
    body_translation=np.array([s['body_translation_world_mm'] for s in samples])
    body_rotation=np.rad2deg([s['body_rotation_euler_xyz_rad'] for s in samples])
    world_feet=np.array([s['foot_bolt_world_mm'] for s in samples]).reshape(-1,12)
    spatial_path=np.concatenate((body_translation/spatial_tolerance_mm,
                                 body_rotation/spatial_tolerance_deg,
                                 world_feet/spatial_tolerance_mm),axis=1)
    quantized=np.round(angles,2)
    program=[call('pose',joints=list(JOINTS),angles_deg=quantized[0].tolist(),reference='absolute',speed_pct=speed_pct)]
    segments=[];phase_map=[];current=quantized[0]
    transitions={i for i in range(1,len(samples)) if samples[i]['phase']!=samples[i-1]['phase']}
    legs=['rear_left','rear_right','front_left','front_right']
    for phase in source['phases']:
        a,b=[int(np.argmin(np.abs(times-t))) for t in (phase['start'],phase['end'])]
        start_action=len(program)
        if 'hold' in phase['kind'].lower():
            program.append(call('hold',seconds=round(phase['end']-phase['start'],9)))
            segments.append({'source_start':a,'source_end':b,'action_start':len(program)-1,'action_end':len(program),'method':'hold'})
        else:
            knots=sorted({a,b}|{i for i in transitions if a<i<b})
            # Source torso/contact solutions can curve or reverse within one
            # phase. Preserve that geometry before translating relative body
            # commands; endpoint-only conversion can erase lifts and arcs.
            refined=set(knots)
            for first,last in zip(knots,knots[1:]):
                body_moves=(np.ptp(body_translation[first:last+1],axis=0).max()>.001
                            or np.ptp(body_rotation[first:last+1],axis=0).max()>.001)
                if body_moves:
                    refined.update(first+i for i in simplify(
                        spatial_path[first:last+1],{0,last-first},1.))
            knots=sorted(refined)
            for first,last in zip(knots,knots[1:]):
                old,new=samples[first],samples[last]
                old_rotation=Rotation.from_euler('xyz',old['body_rotation_euler_xyz_rad']).as_matrix()
                new_rotation=Rotation.from_euler('xyz',new['body_rotation_euler_xyz_rad']).as_matrix()
                translation=old_rotation.T@(np.array(new['body_translation_world_mm'])-old['body_translation_world_mm'])
                rotation=Rotation.from_matrix(old_rotation.T@new_rotation).as_euler('xyz',degrees=True)
                begin_action=len(program)
                if max(np.max(abs(translation)),np.max(abs(rotation)))>.001:
                    offsets=(np.array(new['foot_bolt_world_mm'])-old['foot_bolt_world_mm'])@old_rotation
                    program.append(call('body',translation_mm=np.round(translation,6).tolist(),
                        rotation_deg=np.round(rotation,6).tolist(),legs=legs,
                        foot_offsets_mm=np.round(offsets,6).tolist(),seconds=round(float(times[last]-times[first]),9)))
                    current=quantized[last];method='body'
                else:
                    selected=simplify(angles[first:last+1],{0,last-first},tolerance)
                    for index in selected[1:]:
                        target=quantized[first+index];moving=[j for j in range(12) if current[j]!=target[j]]
                        if moving:
                            program.append(call('pose',joints=[JOINTS[j] for j in moving],
                                angles_deg=[float(target[j]) for j in moving],reference='absolute',speed_pct=speed_pct))
                        current=target
                    method='joint_path'
                segments.append({'source_start':first,'source_end':last,'action_start':begin_action,
                                 'action_end':len(program),'method':method})
        phase_map.append({**phase,'action_start':start_action,'action_end':len(program)})
    trace=replay(program,observation);errors=[]
    for segment in segments:
        endpoints=[s for s in trace['samples'] if s['action_index']==segment['action_end']-1]
        if endpoints:
            q=np.array([endpoints[-1]['joints_deg'][j] for j in JOINTS])
            errors.append({'source_index':segment['source_end'],'method':segment['method'],
                           'max_joint_error_deg':float(np.max(abs(q-angles[segment['source_end']])) )})
    return {'source_file':str(source_file),'source_sha256':digest(source_file),
            'teacher_sha256':digest(Path(__file__)),'observation':observation,
            'program':program,'trace':trace,'source_phases':phase_map,'source_segments':segments,
            'endpoint_errors':errors,'source_samples':len(samples),
            'joint_speed_pct':speed_pct,'joint_path_budget_deg':tolerance,
            'spatial_path_budget_mm':spatial_tolerance_mm,
            'spatial_rotation_budget_deg':spatial_tolerance_deg,
            'authored_hold_seconds':sum(p['end']-p['start'] for p in source['phases'] if 'hold' in p['kind'].lower()),
            'physical_qualification':False,'training_exported':False,
            'scope':'Candidate using relative torso/foot transforms and joint paths. Body phase durations and holds follow the source; joint travel uses the requested percentage. Requires full-path review; endpoint agreement is insufficient for contact/stability.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--motions',nargs='+',required=True)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tolerance-deg',type=float,default=.25)
    parser.add_argument('--speed-pct',type=float,default=50)
    parser.add_argument('--spatial',action='store_true')
    parser.add_argument('--spatial-tolerance-mm',type=float,default=.25)
    parser.add_argument('--spatial-tolerance-deg',type=float,default=.25)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    observation=json.loads(args.state.read_text());results=[]
    for name in args.motions:
        builder=spatial_candidate if args.spatial else candidate
        options=({'spatial_tolerance_mm':args.spatial_tolerance_mm,
                  'spatial_tolerance_deg':args.spatial_tolerance_deg} if args.spatial else {})
        result=builder(ROOT/'motions/gestures'/name/'source.json',observation,args.tolerance_deg,args.speed_pct,**options)
        path=args.output/(name+'.json');path.write_text(compact(result)+'\n')
        report={key:result[key] for key in ('source_samples','selected_source_points',
            'measured_max_source_to_chord_error_deg','measured_max_joint_range_loss_deg',
            'measured_max_omitted_backtracking_deg','authored_hold_seconds') if key in result}
        report.update(name=name,actions=len(result['program']),replay_status=result['trace']['status'],
                      replay_error=result['trace'].get('error'),evidence_sha256=digest(path))
        results.append(report);print(compact(report),flush=True)
    (args.output/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
