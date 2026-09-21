"""Build execution handoffs from the twelve current immutable motion sources."""
import argparse,copy,hashlib,json,math
from pathlib import Path
import numpy as np

P=Path(__file__).resolve().parent
LEGS=['FL','FR','RL','RR'];AXES=['h_Part002','alpha_Part006','theta_Part005']
PHYSICAL=['rear_left','rear_right','front_left','front_right']

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+'\n')
def rounded(v):return round(float(v),9)

def demands(rows,hz):
    q=np.array([r['actuator_angles_rad'] for r in rows]).reshape(-1,12)
    slope=np.diff(q,axis=0)*hz;velocity=np.zeros_like(q)
    same=slope[:-1]*slope[1:]>0
    denominator=np.where(same,slope[:-1]+slope[1:],1)
    velocity[1:-1]=np.where(same,2*slope[:-1]*slope[1:]/denominator,0)
    c2=3*slope-2*velocity[:-1]-velocity[1:];c3=velocity[:-1]+velocity[1:]-2*slope
    with np.errstate(divide='ignore',invalid='ignore'):u=-c2/(3*c3)
    inside=(u>0)&(u<1);u=np.where(inside,u,0)
    speed=np.maximum(np.maximum(abs(velocity[:-1]),abs(velocity[1:])),np.where(inside,abs(velocity[:-1]+2*c2*u+3*c3*u*u),0))
    acceleration=np.maximum(abs(2*c2*hz),abs((2*c2+6*c3)*hz))
    return q,speed,acceleration

def build(repo):
    specs=[('walk','Slave/software/models/v2-12servo/motions/walk')]
    specs += [(f'turn_{side}_{angle}',f'Slave/software/models/v2-12servo/motions/turns/commands/turn_{side}_{angle}')
              for side in ['left','right'] for angle in [15,45,90,180]]
    specs += [('sit','docs/gait-research/sit-bored-20260915'),('rest','docs/gait-research/rest-20260915'),('wave','docs/gait-research/wave-seated-20260916')]
    policy=dict(schema='ainekio-motion-execution-policy-1',scope='Firmware handoff and offline timing reference; no hardware executor implementation.',
        coordinates=dict(joint_positions='signed geometric radians',speed='radians/second',acceleration='radians/second squared',time='seconds',cartesian_positions='millimeters'),
        coordination=dict(clock='One monotonic trajectory clock for all twelve joints, body pose, foot targets, contacts and face-cue events.',
            groups=[dict(id=l,physical_leg=PHYSICAL[i],joint_indices=list(range(3*i,3*i+3)),rule='Shoulder, carrier and crank share source time; passive links satisfy four-bar closure.') for i,l in enumerate(LEGS)],
            whole_body='All supporting legs and body motion share source time. Preserve contact order and phase boundaries.',
            intentional_joint_trajectory_delay_s=[0.]*12,
            changed_motion_delays='Any nonzero per-joint motion delay is a new trajectory: regenerate evaluated feet, closure, collisions and support checks before accepting it.'),
        hardware_limits=dict(status='unmeasured',calibration_id=None,per_joint=[dict(joint_index=j,position_min_rad=None,position_max_rad=None,
            max_speed_rad_s=None,max_acceleration_rad_s2=None,max_braking_acceleration_rad_s2=None,max_jerk_rad_s3=None) for j in range(12)],
            unknown_limit_behavior='No calibrated hardware profile can be approved from unknown limits. Retiming output remains offline research.',
            limit_violation_behavior='Increase coordinated phase durations or regenerate the path. Do not independently clamp joint positions, velocities or accelerations.'),
        timing=dict(rule='Use one continuous monotone source-time map. Joint positions q(s); velocity q_s*s_dot; acceleration q_ss*s_dot^2 + q_s*s_ddot.',
            uniform_speedup='A factor k multiplies speeds by k and accelerations by k squared.',
            unequal_phase_durations='Use the timing.py C2 time map or an equivalently continuous validated map; do not change clock rate abruptly at nonzero-velocity boundaries.',
            reference_acceleration='The source cubic curves are C1, with possible acceleration jumps. Smooth jerk/acceleration limits require source refinement and revalidation; timing alone does not prove C2 joint motion.',
            playback='Blender inspection playback rate is separate from physical execution timing.',
            retimed_validation=['joint speed and acceleration including interpolation extrema','branch and angle continuity','actual command update cadence and latency','contact/sole errors with actual scheduling','measured balance and torque under load']),
        electrical_scheduling=dict(owner='ESP32-P4 actuator/output scheduler',implementation_status='required_not_implemented_by_this_handoff',
            observed_reference=dict(driver='Slave/firmware/esp32p4-wifi6/components/ainekio_pca9685/pca9685.c',frequency_hz=50,pulse_start_phase='all enabled ON counters are zero'),
            pwm_phase=dict(status='uncalibrated',phase_offsets_us=[None]*12,
                requirement='Provide configurable per-channel phase offsets, preserve pulse width across counter wrap, and calibrate actual pulse-edge/current behavior.',
                candidate_experiment='At 50 Hz an evenly spaced twelve-channel schedule has 20000/12 microseconds between starts. This is an experiment, not a required interval or approved hardware setting.'),
            engagement=dict(status='uncalibrated',enable_order=None,enable_group_interval_ms=None,
                requirement='Controlled initial engagement from a known supported pose; stagger activation/groups according to measured power and support needs. Do not repeatedly detach stance servos during ordinary motion.'),
            power=dict(supply_voltage_min_v=None,peak_total_current_limit_a=None,voltage_sag_limit_v=None,
                measurements_required=['rail voltage and current during initial engagement','concurrent loaded starts/reversals/holds','wiring and regulator transient response'],
                caveat='Pulse staggering is not motor-current scheduling and does not establish brownout protection, especially for internally controlled digital servos.'),
            timing_accuracy=dict(max_inter_joint_tracking_skew_us=None,max_update_latency_us=None,
                requirement='Choose an explicit sample/hold or phase-compensated target policy and measure the realized tracking skew. Preserve coordinated source time; pulse offsets are not arbitrary trajectory delays.')),
        entry_and_interruption=dict(entry_pose_source='Each contract records the exact first twelve angles and contacts.',
            actual_pose='Distinguish commanded/estimated pose from measured pose. With unknown pose, use supported operator recovery rather than claiming the robot is at sample zero.',
            entry='If current pose differs, generate a coordinated contact-aware transition with calibrated speed/acceleration limits; do not jump to the first row.',
            interruption='Brake from the current execution phase with coordinated joints. If a foot is raised, select a supported placement/hold using the current contact state; do not seek directly to the last sample.',
            resume='Resume only through a phase-matched transition from the resulting pose.',
            normal_completion='Hold the recorded terminal pose. A source sampler completing is not physical pose confirmation.',
            emergency='Keep the existing independent emergency-disable path; this handoff does not weaken or replace it.'),
        references=[dict(title='PCA9685 independent pulse timing',url='https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf'),
                    dict(title='Servo control pulses and motor-current behavior',url='https://www.pololu.com/blog/17/servo-control-interface-in-detail')])
    write(P/'execution-policy.json',policy);catalog=[]
    for command,folder in specs:
        base=repo/folder;source=base/'source.json';manifest_path=base/'manifest.json'
        d=json.loads(source.read_text());manifest=json.loads(manifest_path.read_text());rows=d['samples'];meta=d['metadata'];cfg=meta['configuration'];hz=cfg['sample_hz']
        assert meta['leg_order']==LEGS and meta['joint_order']==AXES
        assert sha(source)==manifest['source_sha256']
        assert max(abs(r['time_s']-n/hz) for n,r in enumerate(rows))<1e-7
        q,speed,acceleration=demands(rows,hz)
        raw=d['phases'];sections=[('clip',0.,rows[-1]['time_s'])];loop=None
        if command=='walk':
            sections=[(name,*manifest[f'{name}_source_seconds']) for name in ['entry','loop','exit']]
            sections=[('cycle' if name=='loop' else name,a,b) for name,a,b in sections]
            loop=json.loads((base/'loop-contract.json').read_text())
        phases=[]
        for section,begin,end in sections:
            cuts={rounded(begin),rounded(end)}
            for phase in raw:
                cuts.update(rounded(v) for v in [phase['start'],phase['end']] if begin<v<end)
                if command=='walk' and phase['kind']=='whole_body_wave':
                    # This source phase spans several cycles. Each leg portion is 1 s.
                    step=loop['period_seconds']/4
                    cuts.update(rounded(phase['start']+j*step) for j in range(round((phase['end']-phase['start'])/step)+1)
                                if begin<phase['start']+j*step<end)
            cuts=sorted(cuts)
            for a,b in zip(cuts,cuts[1:]):
                lo,hi=round(a*hz),round(b*hz);mid=rows[(lo+hi)//2]
                name=next(p['kind'] for p in raw if p['start']-1e-8<=(a+b)/2<p['end']+1e-8)
                if name=='whole_body_wave':name=mid['phase']
                masks=sorted(set(tuple(r['contact_active']) for r in rows[lo:hi+1]))
                phases.append(dict(id=f'p{len(phases):03}_{name}',name=name,section=section,
                    source_interval_s=[a,b],source_sample_indices_inclusive=[lo,hi],demonstration_duration_s=rounded(b-a),
                    supporting_legs_throughout=[l for i,l in enumerate(LEGS) if all(mask[i] for mask in masks)],
                    contact_states=[list(mask) for mask in masks],
                    moving_joint_indices=[j for j in range(12) if np.ptp(q[lo:hi+1,j])>1e-9],
                    coordination='whole_body_shared_clock',
                    reference_peak_speed_rad_s=speed[lo:hi].max(0).tolist(),
                    reference_peak_acceleration_rad_s2=acceleration[lo:hi].max(0).tolist()))
        events=[];last=None
        for index,r in enumerate(rows):
            if r['contact_active']!=last:
                events.append(dict(source_time_s=rounded(r['time_s']),sample_index=index,active=r['contact_active']));last=r['contact_active']
        duration={p['id']:p['demonstration_duration_s'] for p in phases}
        origins=[dict(path=f'{folder}/source.json',sha256=sha(source)),dict(path=f'{folder}/manifest.json',sha256=sha(manifest_path))]
        if command.startswith('turn_'):
            mirror=f'docs/gait-research/turn-commands-20260915/commands/{command}/source.json';assert sha(repo/mirror)==sha(source)
            origins.append(dict(path=mirror,sha256=sha(repo/mirror)))
        if loop:origins.append(dict(path=f'{folder}/loop-contract.json',sha256=sha(base/'loop-contract.json')))
        contract=dict(schema='ainekio-motion-execution-contract-1',command=command,gait_id=manifest['gait_id'],wire=manifest['wire'],
            shared_policy='../execution-policy.json',policy_sha256=sha(P/'execution-policy.json'),
            source_files=origins,source_units=dict(angle='radian',position='mm',time='second'),source_sample_hz=hz,
            leg_order=LEGS,joint_order=AXES,physical_leg_order=PHYSICAL,phases=phases,contact_events=events,
            timing_profiles=dict(demonstration=dict(status='recorded_kinematic_timing',duration_s=duration),
                research_candidate=dict(status='offline_unvalidated',duration_s=copy.deepcopy(duration)),
                operating=dict(status='unconfigured_pending_loaded_calibration',duration_s={key:None for key in duration},calibration_id=None)),
            repeat=dict(section='cycle' if loop else None,minimum=1,maximum=manifest.get('steps',{}).get('maximum',1)),
            loop_contract=loop,face_cues=cfg.get('face_cues',[]),
            entry=dict(joint_angles_rad=rows[0]['actuator_angles_rad'],contact_active=rows[0]['contact_active'],body_position_world_mm=rows[0]['body_position_world_mm'],body_orientation_world_quaternion_wxyz=rows[0]['body_orientation_world_quaternion_wxyz'],arbitrary_pose_entry_verified=False),
            completion=dict(behavior=manifest.get('completion','Finish the selected phase-matched exit and hold its terminal pose.'),
                joint_angles_rad=rows[-1]['actuator_angles_rad'],contacts=rows[-1]['contact_active']),
            source_qualification=dict(hardware_qualified=False,minimum_assumed_support_margin_mm=d['validation'].get('minimum_support_margin_mm'),
                collision_checked=d['validation'].get('collision_checked',False),measured_mass_balance_verified=False,
                source_acceleration_continuous=False),
            hardware_ready=False,required_hardware_implementation='Apply execution-policy.json in the canonical calibrated actuator executor; neither this file nor timing.py emits servo commands.')
        if loop:
            contract['loop_retiming']=dict(rule='Retiming must preserve the existing compiler matched entry/loop/exit joint positions and tangents; retain one closing knot without an extra dwell.',
                world_coordinates='Use the existing loop translation rule for repeated body/foot/contact positions and phase-match exit translation to the selected cycle count. timing.py only maps source time.',
                reference_derivative_scope='Phase demand arrays use full-source monotone cubic tangents; recompute exact extrema after compiler seam normalization and retiming.')
        write(P/'contracts'/f'{command}.json',contract)
        catalog.append(dict(command=command,contract=f'contracts/{command}.json',sha256=sha(P/'contracts'/f'{command}.json'),
            phase_count=len(phases),one_cycle_demonstration_duration_s=rounded(sum(duration.values())),
            source_files=origins,hardware_ready=False))
    write(P/'catalog.json',dict(schema='ainekio-execution-handoff-catalog-1',date='2026-09-16',motions=catalog,
        scope='Twelve currently selected commands; historical experiments remain archived.',hardware_ready=False))
    print(json.dumps([dict(command=c['command'],phases=c['phase_count'],seconds=c['one_cycle_demonstration_duration_s']) for c in catalog]))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path,default=Path('/home/greggles/Ainekio'));a=ap.parse_args();build(a.repo)
