"""Offline examples of adapting a wave after loss of joint progress.

These are synthetic teaching targets, not physically qualified demonstrations.
No runtime selects these programs from a keyword or event.
"""
import hashlib
import copy
from .compact_wire import ProgramEncoding, model_query
from .runtime import JOINTS, compact
from .migrate_targets import CONTRACT, STAND, standing_pose


def tracking_recovery_examples(state, evaluation=False):
    """Measured tracking failures teach retreat, not escalation of the error.

    Error sign, joint and request vary independently. A no-progress report is
    not proof of an obstruction; the response uses the measured shaft rather
    than treating the missed commanded endpoint as a new oscillation center.
    All generated outcomes remain synthetic and physically unqualified.
    """
    from .curriculum import example
    offsets=(27.,41.) if evaluation else (23.,35.,47.)
    requests=('Continue the gesture after correcting the reported tracking failure.',
              'Recover this joint.')
    for index,joint in enumerate(JOINTS):
        for direction in (-1,1):
            for number,offset in enumerate(offsets):
                obs=copy.deepcopy(state)
                measured=obs['joints'][joint]['model_deg']
                missed=measured+direction*offset
                retreat=direction*(7. if evaluation else 8.)
                obs['joints'][joint].update(commanded_model_deg=missed,velocity_deg_s=0.,
                    feedback_usable=True,feedback_faults=[],in_calibrated_range=True)
                obs['feedback'].update(stalled_joints=1<<index)
                action={'name':'move','arguments':{'joint':joint,'angle_deg':missed,
                    'reference':'absolute','speed_pct':50}}
                program=[{'name':'move','arguments':{'joint':joint,'angle_deg':-retreat,
                    'reference':'current','speed_pct':50}}, standing_pose()]
                yield example(requests[number%len(requests)],obs,program,'tracking_failure_retreat',
                    event={'type':'servo_stall','joints':[{'id':index,'name':joint}],
                        'reason':'no_position_progress','outputs_released':False},
                    history=[{'interrupted_action':action}],
                    teacher='reviewed direction of tracking error: retreat from measured shaft; no obstruction claim',
                    qualification_basis='synthetic tracking error and unexecuted correction',
                    split='evaluation' if evaluation else 'train')


def calibrated_fault_examples(state, nominal, evaluation=False):
    """Learn changed calibration domains and fault evidence, not a joint name.

    Synthetic narrower calibration intervals isolate the distinction between
    known shaft positions and extrapolation. The recovery target is the last
    known nominal angle, not an extrapolated reading. Outcomes remain unknown
    until measured arrival. These labels do not claim measured mechanical limits.
    """
    from .curriculum import example
    widths=(11,17) if evaluation else (8,14,20)
    for index,joint in enumerate(JOINTS):
        for direction in (-1,1):
            for width in widths:
                obs=copy.deepcopy(state)
                center=nominal[index]
                measured=center+direction*(width+3)
                obs['joints'][joint].update(model_deg=measured,commanded_model_deg=measured,
                    feedback_range_deg=[center-width,center+width],feedback_usable=False,
                    feedback_faults=['below_calibration' if direction<0 else 'above_calibration'],
                    in_calibrated_range=False,velocity_deg_s=0.)
                event={'type':'servo_feedback_fault','joints':[{'id':index,'name':joint,
                    'reasons':obs['joints'][joint]['feedback_faults']}],'outputs_released':False}
                prior={'name':'move','arguments':{'joint':joint,'angle_deg':measured,
                    'reference':'absolute','speed_pct':50}}
                program=[{'name':'move','arguments':{'joint':joint,'angle_deg':center,
                    'reference':'absolute','speed_pct':50}}, standing_pose()]
                yield example('Continue my gesture and finish standing.',obs,program,'feedback_domain_recovery',
                    history=[{'joints':{joint:center}}, {'interrupted_action':prior}],event=event,
                    split='evaluation' if evaluation else 'train',
                    qualification_basis='synthetic_calibration_domain_and_unexecuted_retreat',
                    teacher='calibration-domain fault: return the affected shaft to its last trusted angle',
                    calibration_origin='synthetic narrower interval, not a measured physical limit')


def examples(evaluation=False):
    encoding=ProgramEncoding(CONTRACT)
    finish_stand=[standing_pose()]
    retreats=(3,5) if evaluation else (2,4,6)
    expressions=('angry','confused','sad')
    for side,joint in (('left',6),('right',9)):
        for direction in (-1,1):
            for n,retreat in enumerate(retreats):
                for finish in ('stand','raised'):
                    measured=direction*(48 if evaluation else 50)
                    request=f'Wave to the audience with your front-{side} foot. '+(
                        'Return to standing afterwards.' if finish=='stand' else 'Keep that foot raised afterwards.')
                    joints={j:{'model_deg':v,'commanded_model_deg':v,'home_deg':v,
                        'calibrated':True,'in_calibrated_range':True} for j,v in STAND.items()}
                    for index,j in enumerate(JOINTS):joints[j]['home_deg']=[0,-30.87,-117.68][index%3]
                    joints[JOINTS[joint]].update(model_deg=measured,commanded_model_deg=measured+direction*20,
                                               velocity_deg_s=0.)
                    current={'name':'move','arguments':{'joint':JOINTS[joint],
                        'angle_deg':measured+direction*20,'reference':'absolute','speed_pct':20}}
                    remaining=[{'name':'oscillate','arguments':{'joint':JOINTS[joint],
                        'amplitude_deg':12,'cycles':3,'speed_pct':20}}]
                    if finish=='stand':remaining.extend(copy.deepcopy(finish_stand))
                    query={'request':request,'event':{'type':'servo_stall','joints':[joint],
                        'reason':'no_position_progress','outputs_released':False},
                        'observation':{'joints':joints,'joint_speed_limit_deg_s':180,
                            'feedback':{'enabled':True,'no_progress_ms':3000,'stalled_joints':1<<joint},
                            'imu':{'available':True,'fresh':True,'orientation_wxyz':[1,0,0,0]}},
                        'history':[{'interrupted_action':current,'remaining_program':remaining}]}
                    # Back away from the failed direction, then use a smaller
                    # sweep whose extreme stays inside the observed obstruction.
                    program=[{'name':'face','arguments':{'expr':expressions[n%len(expressions)]}},
                        {'name':'move','arguments':{'joint':JOINTS[joint],'angle_deg':-direction*retreat,
                            'reference':'current','speed_pct':20}},
                        {'name':'face','arguments':{'expr':'wave'}},
                        {'name':'oscillate','arguments':{'joint':JOINTS[joint],
                            'amplitude_deg':retreat/2,'cycles':3,'speed_pct':20}}]
                    if finish=='stand':program.extend(copy.deepcopy(finish_stand))
                    query=compact(model_query(query,encoding));answers=encoding.encode(program)
                    digest=hashlib.sha256(compact([query,answers]).encode()).hexdigest()
                    yield {'id':digest[:16],'family':'adaptive_wave_recovery',
                        'title':f'{side.title()} wave recovery: back off {retreat} degrees, finish {finish} ({direction:+})',
                        'query':query,'answers':answers,'source_id':'adaptive-wave:'+digest[:16],
                        'source_hash':digest,'synthetic':True,'physical_qualification':False,
                        'qualification_basis':'authored_adaptation_not_physically_reviewed',
                        'teacher':'Target-based recovery curriculum; measured obstruction, retreat and reduced sweep',
                        'composition_group':'adaptive-wave-'+('evaluation' if evaluation else 'training')}
