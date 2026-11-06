"""Compact learned representation of the existing Freestyle program contract.

This is serialization, not motion selection. Targets, timing, order and face
choices come from the model. The existing program compiler remains the executor.
"""
import copy

from .runtime import JOINTS

FORMAT = 'motion-targets-v1'
LEGACY_FORMAT = 'motion-arrays-v1'
LEGS = tuple(dict.fromkeys(j.rsplit('_', 1)[0] for j in JOINTS))
JOINT_FIELDS = ('model_deg', 'commanded_model_deg', 'home_deg', 'velocity_deg_s',
                'calibrated', 'in_calibrated_range', 'feedback_range_deg',
                'arrival_tolerance_deg', 'feedback_usable', 'feedback_faults',
                'tracking_error_deg', 'within_arrival_tolerance')
# The measurements and their availability/freshness remain model-visible.
# Raw acquisition/transport diagnostics remain in the unmodified recorder input.
IMU_DIAGNOSTICS = {'boot_id', 'accepted_samples', 'rejected_samples', 'gap_restarts',
                   'acquisition', 'received_at', 'face_token'}
RECOVERY_EVENTS = {'servo_stall', 'servo_feedback_fault', 'tipped', 'rapid_movement', 'slip'}


def joint_progress(history, event):
    """Last distinct measured positions for affected shafts, in sample order."""
    ids = []
    for joint in event.get('joints', []):
        if isinstance(joint, dict): joint = joint.get('id', joint.get('name'))
        if joint in JOINTS: joint = JOINTS.index(joint)
        if type(joint) is int and 0 <= joint < len(JOINTS): ids.append(joint)
    if not ids:
        return []
    samples = []
    for item in history or []:
        if not isinstance(item, dict): continue
        candidates = item.get('joint_progress') or [item.get('joints')]
        for candidate in candidates:
            if not isinstance(candidate, dict): continue
            packed = observation({'joints':candidate})['joints']
            positions = dict(zip(packed.get('ids', []), packed.get('model_deg', [])))
            present = [i for i in ids if positions.get(i) is not None]
            if not present: continue
            sample = {'ids':present, 'model_deg':[round(positions[i],2) for i in present]}
            if not samples or sample != samples[-1]: samples.append(sample)
    return samples[-2:]


def latest_correction(history):
    """Retain the most recent measured action/effect pair, not the sensor log."""
    history = history or []
    for index in range(len(history)-1, -1, -1):
        item = history[index]
        if not isinstance(item, dict):
            continue
        if item.get('last_correction'):
            return copy.deepcopy(item['last_correction'])
        delta = item.get('correction_delta_deg')
        if not isinstance(delta, dict) or not delta:
            continue
        after = next((h for h in history[index+1:] if isinstance(h, dict) and h.get('imu')), None)
        if after is None or not item.get('imu'):
            continue
        def attitude(sample):
            imu = observation({'imu':sample['imu']})['imu']
            return {k:imu[k] for k in ('available','fresh','frame','orientation_wxyz',
                'calibration_applied','gyro_recovery','acceleration_recovery','derived_orientation') if k in imu}
        return {'delta_deg':[[JOINTS.index(j),round(value,2)] for j,value in delta.items()],
                'before':attitude(item),'after':attitude(after),
                **({'receipts':copy.deepcopy(after['receipts'])} if 'receipts' in after else {})}
    return None


def recovery_state(value):
    """Current physical state, not acquisition logs or copies of prior packets."""
    if not isinstance(value, dict):
        return value
    state = observation(value)
    result = {k:state[k] for k in ('joints', 'expected_up', 'joint_speed_limit_deg_s', 'shaft_tracking',
                                  'features','trajectory_progress') if k in state}
    imu = state.get('imu')
    if isinstance(imu, dict):
        result['imu'] = {k:imu[k] for k in ('available', 'fresh', 'age_us', 'frame',
            'orientation_wxyz', 'angular_rate_rad_s', 'acceleration_m_s2',
            'calibration_applied', 'gyro_recovery', 'acceleration_recovery', 'accelerometer_ignored',
            'derived_orientation') if k in imu}
    feedback = state.get('feedback')
    if isinstance(feedback, dict):
        result['feedback'] = {k:feedback[k] for k in ('enabled', 'no_progress_ms',
            'waiting_joints', 'last_reported_stalled_joints', 'last_stall_age_ms') if k in feedback}
        if 'stalled_joints' in feedback:
            # P4 retains the last reported stall; it is not a live jam flag.
            result['feedback']['last_reported_stalled_joints']=feedback['stalled_joints']
        if feedback.get('stall_clock_us') and 'device_us' in feedback:
            result['feedback']['last_stall_age_ms']=round(
                (feedback['device_us']-feedback['stall_clock_us'])/1000,1)
    # Servo precision is hundredths of a degree; raw precision remains recorded.
    def rounded(item):
        if isinstance(item, float): return round(item, 2)
        if isinstance(item, list): return [rounded(x) for x in item]
        if isinstance(item, dict): return {k:rounded(v) for k,v in item.items()}
        return item
    if 'joints' in result:
        result['joints'] = rounded(result['joints'])
    return result


def model_query(query, encoding):
    """Shared training/runtime input projection. Full evidence stays in recordings.

    Recovery needs its goal, present state, event and actual operation progress. A copied
    program, packet buffer and historical sensor stream are not new instructions.
    """
    if not isinstance(query, dict):
        return query
    from .observations import enrich
    result = enrich(query)
    event = result.get('event')
    kind = (event.get('type') or event.get('kind')) if isinstance(event, dict) else None
    if kind not in RECOVERY_EVENTS:
        for key in ('observation', 'history', 'event'):
            if key in result: result[key] = observation(result[key])
        return result
    state = result.get('observation')
    result['observation'] = recovery_state(state)
    # Preserve event-specific facts, excluding repeated IMU/transport/configuration data.
    result['event'] = {k:v for k,v in observation(event).items() if k not in (
        'kind', 'imu', 'motion', 'thresholds', 'event_id', 'epoch', 'clock_us',
        'command_sequence', 'joint_mask')}
    result['event']['type'] = kind
    if isinstance(event.get('imu'), dict) and not (isinstance(state, dict) and state.get('imu')):
        result['event']['imu'] = recovery_state({'imu':event['imu']})['imu']
    # Keep completed work distinct from an interrupted operation. An explicit
    # empty remainder is completion evidence, not an unknown pending plan.
    interrupted = next((h for h in reversed(result.get('history') or [])
                        if isinstance(h, dict) and any(k in h for k in (
                            'program_state','interrupted_action','failed_action','completed_action','action','remaining_program','error'))), {})
    current = interrupted.get('interrupted_action') or interrupted.get('action')
    remaining = interrupted.get('remaining_program')
    if remaining is None and isinstance(interrupted.get('interrupted_program'), dict):
        old_program = interrupted['interrupted_program'].get('program', [])
        if current in old_program:
            remaining = old_program[old_program.index(current)+1:]
    if isinstance(current, dict) and current.get('name') in encoding.tools:
        current = encoding.encode([current])[0]
    summary = {}
    if 'program_state' in interrupted:
        summary['program_state'] = interrupted['program_state']
    if current is not None:
        summary['interrupted_action'] = current
    failed = interrupted.get('failed_action')
    if isinstance(failed, dict) and failed.get('name') in encoding.tools:
        failed = encoding.encode([failed])[0]
    if failed is not None:
        summary['failed_action'] = failed
    for key in ('error','error_evidence'):
        if key in interrupted:
            summary[key] = copy.deepcopy(interrupted[key])
    completed = interrupted.get('completed_action')
    if isinstance(completed, dict) and completed.get('name') in encoding.tools:
        completed = encoding.encode([completed])[0]
    if completed is not None:
        summary['completed_action'] = completed
    if isinstance(state, dict) and state.get('pending_actions'):
        remaining = state['pending_actions']
    if remaining is not None:
        summary['remaining_program'] = (encoding.encode(remaining)
            if remaining and isinstance(remaining[0], dict) else remaining)
    goal = result.get('motion_goal')
    if isinstance(goal, dict):
        goal = copy.deepcopy(goal)
        for key in ('interrupted_action','failed_action','completed_action'):
            action = goal.get(key)
            if isinstance(action, dict) and action.get('name') in encoding.tools:
                goal[key] = encoding.encode([action])[0]
        remaining_goal = goal.get('remaining_program')
        if remaining_goal and isinstance(remaining_goal[0], dict):
            goal['remaining_program'] = encoding.encode(remaining_goal)
        result['motion_goal'] = goal
        # The first event's plan is already in the goal. Later corrections
        # retain their own progress without replacing that original objective.
        for key in ('interrupted_action','failed_action','completed_action','remaining_program'):
            if key in goal and summary.get(key) == goal[key]:
                summary.pop(key, None)
    effect = latest_correction(result.get('history'))
    if effect:
        summary['last_correction'] = effect
    progress = joint_progress(result.get('history'), event)
    if progress:
        summary['joint_progress'] = progress
    result['history'] = [summary] if summary else []
    return result


def observation(value):
    """Pack joint columns; preserve unknowns, state flags, events and history."""
    if isinstance(value, list):
        return [observation(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key:observation(item) for key,item in value.items()}
    joints = value.get('joints')
    if isinstance(joints, dict) and joints and all(j in JOINTS for j in joints):
        ids = [i for i,j in enumerate(JOINTS) if j in joints]
        if all(isinstance(joints[JOINTS[i]], dict) for i in ids):
            packed = {'ids':ids}
            for field in JOINT_FIELDS:
                if any(field in joints[JOINTS[i]] for i in ids):
                    packed[field] = [
                        round(joints[JOINTS[i]][field], 5)
                        if isinstance(joints[JOINTS[i]].get(field), float)
                        else joints[JOINTS[i]].get(field) for i in ids]
            extra = {str(i):{k:observation(v) for k,v in joints[JOINTS[i]].items()
                            if k not in (*JOINT_FIELDS, 'command_us')}
                     for i in ids}
            if any(extra.values()):
                packed['extra'] = {k:v for k,v in extra.items() if v}
            result['joints'] = packed
        elif all(isinstance(joints[JOINTS[i]], (int,float)) or joints[JOINTS[i]] is None for i in ids):
            result['joints'] = {'ids':ids, 'model_deg':[
                round(joints[JOINTS[i]],5) if isinstance(joints[JOINTS[i]],float)
                else joints[JOINTS[i]] for i in ids]}
    imu = value.get('imu')
    if isinstance(imu, dict):
        result['imu'] = {k:observation(v) for k,v in imu.items() if k not in IMU_DIAGNOSTICS}
        for key in ('orientation_wxyz', 'acceleration_m_s2', 'angular_rate_rad_s'):
            if isinstance(imu.get(key),list):
                result['imu'][key] = [round(x,6) if isinstance(x,float) else x for x in imu[key]]
    return result


class ProgramEncoding:
    def __init__(self, tools):
        self.tools = {t['name']:t for t in tools}

    def encode(self, program):
        result = []
        for call in program:
            name, args = call['name'], call['arguments']
            names = self.tools[name]['parameters']['required']
            if 'taper_deg' in names:
                args = {'taper_deg':0, **args}
            if set(names) != set(args):
                raise ValueError('Program arguments do not match the training contract: '+name)
            values = []
            for key in names:
                value = copy.deepcopy(args.get(key, 0) if key == 'taper_deg' else args[key])
                if key == 'joint': value = JOINTS.index(value)
                elif key == 'joints': value = [JOINTS.index(j) for j in value]
                elif key == 'legs': value = [LEGS.index(j) for j in value]
                values.append(value)
            result.append([name, *values])
        return result

    def decode(self, program):
        result = []
        for row in program:
            if not isinstance(row,list) or not row or row[0] not in self.tools:
                raise ValueError('Unknown compact motion operation')
            name = row[0]
            names = self.tools[name]['parameters']['required']
            if len(row) != len(names)+1:
                raise ValueError('Wrong compact motion argument count: '+name)
            args = {}
            for key,value in zip(names,row[1:]):
                value = copy.deepcopy(value)
                def identifier(i, table):
                    if type(i) is not int or not 0 <= i < len(table):
                        raise ValueError('Unknown compact joint or leg identifier')
                    return table[i]
                if key == 'joint': value = identifier(value, JOINTS)
                elif key == 'joints': value = [identifier(j, JOINTS) for j in value]
                elif key == 'legs': value = [identifier(j, LEGS) for j in value]
                args[key] = value
            result.append({'name':name, 'arguments':args})
        return result

    def schema(self, argument_schema):
        variants = []
        for name,tool in self.tools.items():
            parameters = argument_schema(tool)
            for params in parameters.get('oneOf', [parameters]):
                fields = []
                for key in params['required']:
                    field = copy.deepcopy(params['properties'][key])
                    field.pop('description', None)
                    if key == 'joint': field = {'type':'integer', 'enum':list(range(len(JOINTS)))}
                    elif key in ('joints','legs'):
                        field['items'] = {'type':'integer','enum':list(range(len(JOINTS if key=='joints' else LEGS)))}
                    fields.append(field)
                variants.append({'type':'array','minItems':len(fields)+1,'maxItems':len(fields)+1,
                                 'prefixItems':[{'type':'string','const':name},*fields]})
        return {'type':'array','items':{'oneOf':variants}}
