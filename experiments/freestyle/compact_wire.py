"""Compact learned representation of the existing Freestyle program contract.

This is serialization, not motion selection. Targets, timing, order and face
choices come from the model. The existing program compiler remains the executor.
"""
import copy

from .runtime import JOINTS

FORMAT = 'motion-arrays-v1'
LEGS = tuple(dict.fromkeys(j.rsplit('_', 1)[0] for j in JOINTS))
JOINT_FIELDS = ('model_deg', 'commanded_model_deg', 'home_deg', 'velocity_deg_s',
                'calibrated', 'in_calibrated_range')
# The measurements and their availability/freshness remain model-visible.
# Raw acquisition/transport diagnostics remain in the unmodified recorder input.
IMU_DIAGNOSTICS = {'boot_id', 'accepted_samples', 'rejected_samples', 'gap_restarts',
                   'acquisition', 'received_at', 'face_token'}


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
            if set(names) != set(args):
                raise ValueError('Program arguments do not match the training contract: '+name)
            values = []
            for key in names:
                value = copy.deepcopy(args[key])
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
