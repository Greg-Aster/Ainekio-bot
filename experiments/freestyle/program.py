"""Translate compact calls to existing V2 packets without trimming sequences."""
import math

from .runtime import JOINTS, MAX_FRAMES


def calibrated_positions(calibration):
    home, commanded = {}, {}
    for item in calibration['joints']:
        joint = JOINTS[item['id']]
        home[joint] = item['home_cd']/100
        commanded[joint] = (home[joint] + (-1 if item['invert'] else 1)*(item['pulse_us']-item['home_us'])/item['us_per_degree']
                            if item['pulse_us'] else None)
    return home, commanded


def target(speed_deg_s, positions):
    if not math.isfinite(speed_deg_s) or speed_deg_s <= 0:
        raise ValueError('Movement speed must be positive degrees per second')
    return [max(1,round(speed_deg_s*100)), [round(positions[j]*100) for j in JOINTS]]


def targets_for(operation, positions, home, speed_deg_s):
    """Targets and speed only. The P4 owns measured arrival, not elapsed time."""
    name, args = operation['name'], operation['arguments']
    speed=speed_deg_s*args['speed_pct']/100
    if name == 'oscillate':
        joint=args['joint'];center=positions[joint]
        for _ in range(args['cycles']):
            for phase in (1,0,-1,0):
                yield target(speed,{**positions,joint:center+phase*args['amplitude_deg']})
        return
    joints=[args['joint']] if name=='move' else args['joints']
    angles=[args['angle_deg']] if name=='move' else args['angles_deg']
    if len(joints)!=len(angles):raise ValueError('Each pose joint needs its corresponding angle')
    goal=dict(positions)
    for joint,angle in zip(joints,angles):
        reference={'current':positions,'home':home,'absolute':dict.fromkeys(JOINTS,0)}[args['reference']]
        goal[joint]=reference[joint]+angle
    yield target(speed,goal)


def packets(frames):
    packet = []
    for value in frames:
        packet.append(value)
        if len(packet) == MAX_FRAMES:
            yield packet
            packet = []
    if packet:
        yield packet


def compile_motion(action, observation, planned=None):
    """Continue authored motion from its previous target, not tracking error.

    The first motion (and motion after reassessment) uses measured positions
    for moving joints. Feedback remains evidence; it does not silently rewrite
    the remaining relative path on every segment.
    """
    name, args = action['name'], action['arguments']
    joints = observation['joints']
    home = {j:v['home_deg'] for j,v in joints.items()}
    moving = (list(JOINTS) if name=='body' else
              [f'{leg}_{axis}' for leg in args['legs'] for axis in ('shoulder','carrier','crank')] if name=='feet' else
              args['joints'] if name=='pose' else [args['joint']])
    if planned is None:
        start = {j:(v['commanded_model_deg'] if v['commanded_model_deg'] is not None else v.get('model_deg'))
                 for j,v in joints.items()}
        start.update({j:joints[j].get('model_deg',joints[j]['commanded_model_deg']) for j in moving})
    else:
        start = dict(planned)
    if name in ('feet','body'):
        from .kinematics import target_for_spatial
        goal=target_for_spatial(action,start)
        frames=[target(observation['joint_speed_limit_deg_s']*args['speed_pct']/100,
                       dict(zip(JOINTS,[v/100 for v in goal])))]
    else:
        frames = list(targets_for(action,start,home,observation['joint_speed_limit_deg_s']))
    end = dict(zip(JOINTS,[v/100 for v in frames[-1][1]])) if frames else dict(start)
    return {'frames':frames,'start':start,'home':home,'moving':moving,'end':end}


def gait_intent(args):
    command = args['command']
    direction = {'backward':'back', 'left':'turn_l', 'right':'turn_r', 'crab':'side_l',
                 'crab_right':'side_r','crab_backward':'back','crab_turn_left':'turn_l',
                 'crab_turn_right':'turn_r'}.get(command, 'fwd')
    gait = 'crab' if command.startswith('crab') else ('crawl' if command=='crawl' else 'walk')
    # The body selects run at speed >100; explicit run is supported by the walk intent.
    if command == 'run':
        gait = 'run'
    return {'dir':direction, 'gait':gait, 'speed':args['speed_pct'], 'steps':args['cycles']}


def gait_intents(args):
    """The existing intent protocol allows 0 (ongoing), or at most 10 cycles."""
    intent = gait_intent(args)
    remaining = args['cycles']
    if remaining == 0:
        yield intent
    while remaining > 0:
        count = min(10, remaining)
        yield {**intent, 'steps':count}
        remaining -= count
