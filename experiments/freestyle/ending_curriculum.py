"""Explicit ending composition for reviewed programs and Stand examples.

The former v8 named-gesture curriculum builder is superseded by
legacy_curriculum, which reads complete native sources. These helpers retain
explicit ending edits without supplying a substitute motion implementation.
"""
import copy
from .runtime import JOINTS
from .semantic_teachers import call


def final_pose(values, speed=50):
    return call('pose',joints=list(JOINTS),angles_deg=list(values),reference='absolute',speed_pct=speed)


def replace_wave_ending(program, values, establish_seated_shoulders=False):
    result=copy.deepcopy(program)
    if any(a['name']=='trajectory' for a in result):
        result.append(final_pose(values))
        return result
    last=max(i for i,a in enumerate(result) if a['name']=='pose')
    result[last]=final_pose(values,result[last]['arguments']['speed_pct'])
    if establish_seated_shoulders:
        first=next(a for a in result if a['name']=='pose')
        q=dict(zip(first['arguments']['joints'],first['arguments']['angles_deg']))
        q.update({j:0 for j in JOINTS if j.endswith('_shoulder')})
        result[result.index(first)]=final_pose([q[j] for j in JOINTS],first['arguments']['speed_pct'])
    return result
