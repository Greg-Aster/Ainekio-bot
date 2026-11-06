"""Compile compact target deceleration for the existing P4 cubic player.

The model supplies a target, speed and taper. It never authors curve tables.
Native source import remains offline; playback and receipts keep their owners.
"""
import importlib.util
import math
from functools import lru_cache

from .runtime import JOINTS


@lru_cache(maxsize=1)
def native_compiler():
    from .kinematics import ROOT
    spec=importlib.util.spec_from_file_location('ainekio_curve_math',ROOT/'tools/compile_clips.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tapered_target(start, frame, taper_deg):
    """A linear coordinated target, with body-owned final deceleration."""
    beginning=[round(start[j]*100) for j in JOINTS]
    ending=frame[1]
    delta=[b-a for a,b in zip(beginning,ending)]
    distance=max(abs(v) for v in delta)/100
    if not distance:
        return None
    if not math.isfinite(taper_deg) or taper_deg<0:
        raise ValueError('Deceleration distance must be finite and nonnegative')
    # A target shorter than the requested window starts inside that window.
    return {'times':[0.,1.], 'positions':[beginning,ending],
            'velocities':[delta,delta], 'clock':[[0.,0.,0.,0,max(range(12),key=lambda i:abs(delta[i]))],
                      [1.,distance,0.,0,0]],
            'checkpoints':[0.,1.], 'expected_up':[],
            'taper':min(taper_deg,distance), 'speed_deg_s':frame[0]/100}
