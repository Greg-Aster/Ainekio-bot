"""Offline production-gait targets for Freestyle simulation, without hardware.

The caller supplies a separately built native_gait executable. This module is
not imported by Body Control. Feedback, learned gait profiles, contact forces
and actual chassis displacement are not simulated.
"""
import json
import subprocess

from .program import gait_intents
from .runtime import compact


def sample_gait(arguments, joint_speed_deg_s, executable):
    segments = []
    for sequence, intent in enumerate(gait_intents(arguments), 1):
        command = {'t':'intent', 'seq':sequence, 'name':'walk', **intent}
        result = subprocess.run([str(executable), compact(command), str(joint_speed_deg_s)],
                                capture_output=True, text=True)
        samples = [json.loads(line) for line in result.stdout.splitlines()]
        segment = {'command':command, 'samples':samples,
                   'exit_code':result.returncode, 'error':result.stderr.strip() or None}
        segments.append(segment)
        if result.returncode == 4:
            return {'status':'not_fully_replayed', 'segments':segments,
                    'reason':'Ongoing gait has no terminal target without a later external command.'}
        if result.returncode or not samples or not samples[-1]['complete']:
            return {'status':'compile_or_replay_error', 'segments':segments,
                    'error':result.stderr.strip() or 'Native gait did not report completion.'}
    if not segments:
        return {'status':'not_fully_replayed', 'segments':[],
                'reason':'The command translator produced no native gait command to evaluate.'}
    return {'status':'replayed', 'segments':segments,
            'scope':'Nominal native gait targets; no measured travel, dynamics or physical success.'}
