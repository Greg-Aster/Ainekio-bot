"""Offline examples of adapting a wave after loss of joint progress.

These are synthetic teaching targets, not physically qualified demonstrations.
No runtime selects these programs from a keyword or event.
"""
import hashlib
from .compact_wire import ProgramEncoding, model_query
from .runtime import JOINTS, compact
from .migrate_targets import CONTRACT, STAND


def examples(evaluation=False):
    encoding=ProgramEncoding(CONTRACT)
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
                    if finish=='stand':remaining.append({'name':'stand','arguments':{}})
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
                    if finish=='stand':program.append({'name':'stand','arguments':{}})
                    query=compact(model_query(query,encoding));answers=encoding.encode(program)
                    digest=hashlib.sha256(compact([query,answers]).encode()).hexdigest()
                    yield {'id':digest[:16],'family':'adaptive_wave_recovery',
                        'title':f'{side.title()} wave recovery: back off {retreat} degrees, finish {finish} ({direction:+})',
                        'query':query,'answers':answers,'source_id':'adaptive-wave:'+digest[:16],
                        'source_hash':digest,'synthetic':True,'physical_qualification':False,
                        'qualification_basis':'authored_adaptation_not_physically_reviewed',
                        'teacher':'Target-based recovery curriculum; measured obstruction, retreat and reduced sweep',
                        'composition_group':'adaptive-wave-'+('evaluation' if evaluation else 'training')}
