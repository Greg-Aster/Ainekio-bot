"""Offline migration of reviewed labels to the single target/speed contract."""
import copy
import json
import re

from .curriculum import signature
from .program import compile_motion
from .runtime import JOINTS, compact


def timing_intent(request):
    text = request.lower()
    for word, value in [('half a', '.5'), ('half', '.5'), ('one', '1'), ('two', '2'), ('three', '3')]:
        text = re.sub(r'\b' + word + r'(?=\s+seconds?\b)', value, text)
    # Holds retain their seconds field, so they do not imply slow travel.
    text = re.sub(r'\b(?:hold|pause|wait|stay)\b[^.;!?]*?\d+(?:\.\d+)?\s*(?:seconds?|secs?|s)\b', '', text)
    values = [float(x) for x in re.findall(r'(?<![\w.])(\d*\.?\d+)\s*(?:seconds?|secs?|s)\b', text)]
    ambiguous = bool(re.search(r'\b(?:slowly|slow|gentle|gently|leisurely)\b', text)) and not values
    return values, ambiguous


def migrate_history(value):
    if isinstance(value, list):
        return [migrate_history(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: migrate_history(v) for k, v in value.items()}
    if 'period_s' in result and isinstance(result.get('name'), str) and 'arguments' not in result:
        # Synthetic interrupted-emote metadata used this older timing field
        # outside the call arguments. Keep its source in original_query too.
        result.pop('period_s')
        result.setdefault('speed_pct', 50)
    if result.get('name') in ('feet', 'body', 'oscillate') and isinstance(result.get('arguments'), dict):
        args = result['arguments']
        if 'seconds' in args or 'period_s' in args:
            # Old history remains preserved in original_query; the normalized
            # action is context, not a claim about historical actuator speed.
            args.pop('seconds', None);args.pop('period_s', None)
            args.setdefault('speed_pct', 50)
    return result


def migrate(row, preserve_durations=False):
    """Normalize labels, or preserve every authored duration for offline comparison.

    The latter is for comparing old-contract generated programs. It does not
    infer speed intent from wording or change serving behavior.
    """
    result = copy.deepcopy(row);query = json.loads(result['query'])
    values, ambiguous = timing_intent(query['request'])
    legacy = any(a['name'] in ('feet', 'body', 'oscillate') and
                 ('seconds' in a['arguments'] or 'period_s' in a['arguments']) for a in row['answers'])
    if ambiguous and legacy and not preserve_durations:
        return result, {'accepted': False, 'reason': 'ambiguous_requested_slow_travel'}
    observation = query['observation'];planned = None;changes = []
    program = []
    for index, action in enumerate(result['answers']):
        a = copy.deepcopy(action);args = a['arguments'];duration = None
        old = args.get('seconds') if a['name'] in ('feet', 'body') else args.get('period_s') if a['name'] == 'oscillate' else None
        if old is not None:
            explicit = preserve_durations or any(abs(old-v) < 1e-6 for v in values)
            args.pop('seconds', None);args.pop('period_s', None);args['speed_pct'] = 50
            if explicit:
                duration = old
            changes.append({'action_index': index, 'source_duration_s': old,
                            'intent': 'explicit_duration_to_nominal_rate' if explicit else 'unspecified_travel_50_percent'})
        if (values or preserve_durations) and a['name'] in ('move', 'pose', 'oscillate', 'feet', 'body'):
            try:
                compiled = compile_motion(a, observation, planned)
                if duration:
                    previous = compiled['start'];distance = 0.
                    for _, angles in compiled['frames']:
                        end = dict(zip(JOINTS, [x/100 for x in angles]))
                        distance += max(abs(end[j]-previous[j]) for j in JOINTS)
                        previous = end
                    if a['name'] == 'oscillate':
                        distance /= args['cycles']
                    args['speed_pct'] = round(100*distance/duration/observation['joint_speed_limit_deg_s'], 6) if distance else 50
                    compiled = compile_motion(a, observation, planned)
                planned = compiled['end']
            except (ValueError, KeyError, TypeError) as error:
                return result, {'accepted': False, 'reason': 'explicit_timing_compile_error', 'error': str(error)}
        program.append(a)
    if changes or migrate_history(query) != query:
        result['original_query'] = result['query']
        result['original_answers'] = result['answers']
        result['query'] = compact(migrate_history(query));result['answers'] = program
        result['duration_migration'] = changes
        result['prior_kinematic_evidence'] = result.pop('kinematic_evidence', None)
        result['teacher'] = result.get('teacher', 'retained reviewed teacher') + '; current target/speed vocabulary'
        value = signature([result['query'], result['answers']])
        result.update(id=value[:16], source_id='speed-migration:' + value, source_hash=value)
    return result, {'accepted': True, 'changes': len(changes), 'explicit_travel_timing': bool(values)}
