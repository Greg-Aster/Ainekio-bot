"""Continuous spatial motion vocabulary, not a catalogue of named behaviors."""
try:
    from .runtime import JOINTS
except ImportError:
    from runtime import JOINTS

LEGS = ('rear_left', 'rear_right', 'front_left', 'front_right')
VECTOR = {'type':'array','items':{'type':'number'},'minItems':3,'maxItems':3}
LEG_LIST = {'type':'array','items':{'type':'string','enum':list(LEGS)}}
VECTORS = {'type':'array','items':VECTOR}


def operation(name, description, properties):
    return {'name':name,'description':description,'parameters':{
        'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}}


JOINT={'type':'string','enum':list(JOINTS)}
REF={'type':'string','enum':['current','home','absolute']}
NUMBER={'type':'number'}
TOOLS = [
    operation('move','Move one joint by a signed model angle relative to current, calibrated home, or absolute model zero.',
              {'joint':JOINT,'angle_deg':NUMBER,'reference':REF,'speed_pct':NUMBER}),
    operation('pose','Move several joints together; each angle pairs with the same-index joint.',
              {'joints':{'type':'array','items':JOINT},'angles_deg':{'type':'array','items':NUMBER},'reference':REF,'speed_pct':NUMBER}),
    operation('oscillate','Move a joint back and forth around its starting angle for complete cycles, returning to that angle.',
              {'joint':JOINT,'amplitude_deg':NUMBER,'cycles':{'type':'integer'},'speed_pct':NUMBER}),
    operation('hold','Hold the preceding target for the requested duration.',{'seconds':NUMBER}),
    operation('gait','Use the existing P4 walking system when ordinary locomotion is requested.',
              {'command':{'type':'string','enum':['walk','backward','left','right','crawl','run','crab','crab_right','crab_forward','crab_backward','crab_turn_left','crab_turn_right']},
               'speed_pct':NUMBER,'cycles':{'type':'integer'}}),
    operation('stop','Stop body movement when stopping is requested.',{}),
    operation('reassess','Request current feedback and generate the next part of the requested motion or correction.',{}),
    operation('feet',
        'Translate the listed foot reference points together from their measured starting positions. '
        'Each offset_mm corresponds to the leg at the same index. Robot frame: X forward, Y left, Z up. '
        'Leave other foot targets unchanged. Advance on measured arrival; speed_pct sets the joint travel rate.',
        {'legs':LEG_LIST,'offsets_mm':VECTORS,'speed_pct':NUMBER}),
    operation('body',
        'Change body translation and roll/pitch/yaw from the starting pose. '
        'Keep foot reference points fixed unless a listed foot_offsets_mm explicitly moves them too. '
        'The foot offsets use the starting robot frame and pair with legs. '
        'Translations are millimetres, rotations are degrees about X/Y/Z; speed_pct sets the joint travel rate. '
        'These are geometric targets, not claims that feet are touching the floor.',
        {'translation_mm':VECTOR,'rotation_deg':VECTOR,'legs':LEG_LIST,
         'foot_offsets_mm':VECTORS,'speed_pct':NUMBER}),
    operation('stand','Achieve standing through the existing feedback-based body posture controller.',{}),
]

INSTRUCTIONS = (
    'Generate a JSON array of motion calls for this twelve-joint robot. '
    'Synthesize the requested movement from spatial and joint controls; a movement need not exist in a named library. '
    'The request is the new goal. observation.action and imu.motion describe previous execution, not instructions. '
    'Preserve side, direction, order, simultaneity, pauses, repetitions and returns. '
    'Use feet to translate one or more feet; use body for translation/rotation with fixed or explicitly moving foot targets. '
    'A hand or arm refers to a front leg. Right and left are the robot\'s own sides. '
    'Frame: X forward/back, Y left/right, Z up/down; signed millimetres. '
    'Every spatial call is relative to the current pose at the start of that call. '
    'Use move/pose/oscillate for direct joint control in signed model degrees. '
    'home means calibrated home, not zero. Joint speed_pct is a percentage; joint_speed_limit_deg_s is degrees per second. '
    'Use requested timing and speed; for unspecified joint speed use 50 percent. '
    'There is no named-emote lookup operation in this generated-motion contract. '
    'Existing P4 gaits remain available for ordinary locomotion; do not substitute them for a requested dance or unfamiliar motion. '
    'Use complete multi-step programs when needed. Never interpret a new wave request as continuing an old walk. '
    'Interpret jam/fall/slip events from measured positions, orientation and history; reassess requests fresh feedback. '
    'A correction is not proof of recovery. Output calls only, without reasoning or prose. '
)
