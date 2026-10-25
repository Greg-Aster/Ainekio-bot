"""Compile generated foot/body motion using the repository's four-bar geometry.

No named-motion selection, clipping, collision policy, contact inference or
automatic fallback. Numerical IK failure is reported as a compilation error.
"""
import importlib.util
import json
import math
from functools import lru_cache
from pathlib import Path

from .runtime import JOINTS

ROOT=Path(__file__).resolve().parents[2]/'Slave/software/models/v2-12servo'
CAD_LEGS={'rear_left':'FL','rear_right':'FR','front_left':'RL','front_right':'RR'}


@lru_cache(maxsize=1)
def reference():
    spec=importlib.util.spec_from_file_location('freestyle_four_bar_reference',ROOT/'motions/walk/reference.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def mechanism():
    return reference().Mechanism(json.loads((ROOT/'geometry.json').read_text()))


def foot_positions(positions, model=None):
    """Evaluate foot points, optionally using a caller-owned zero-body-pose model."""
    import numpy as np
    model=mechanism() if model is None else model
    return {leg:model.reference(cad,np.deg2rad([positions[f'{leg}_{axis}'] for axis in ('shoulder','carrier','crank')]),np.zeros(3)).tolist()
            for leg,cad in CAD_LEGS.items()}


def solve_reference(model, leg, seed, body, target):
    """Solve actual reference-point XYZ; seeded continuously on the same linkage."""
    import numpy as np
    from scipy.optimize import least_squares
    def residual(q):
        try:return model.reference(leg,q,body)-target
        except ValueError:return np.ones(3)*1000+np.asarray(q)*.001
    # No research-angle box is reinterpreted as a physical servo limit.
    result=least_squares(residual,seed,xtol=1e-9,ftol=1e-9,gtol=1e-9,diff_step=1e-5)
    error=float(np.linalg.norm(residual(result.x)))
    if not result.success or error>.02:
        raise ValueError(f'{leg} requested foot target has no converged IK solution; residual {error:.5f} mm')
    return result.x


def target_for_spatial(action, positions):
    """Resolve a spatial objective to joint targets; no duration or timed frames."""
    import numpy as np
    model=mechanism();args=action['arguments']
    legs=args['legs'];offsets=args['offsets_mm'] if action['name']=='feet' else args['foot_offsets_mm']
    if len(legs)!=len(offsets) or len(set(legs))!=len(legs):
        raise ValueError('Each named leg needs one corresponding foot offset')
    delta={leg:np.asarray(offset,dtype=float) for leg,offset in zip(legs,offsets)}
    if set(delta)-set(CAD_LEGS):raise ValueError('Unknown physical leg')
    translation=np.asarray(args.get('translation_mm',[0,0,0]),dtype=float)
    rotation=np.deg2rad(args.get('rotation_deg',[0,0,0]))
    q={leg:np.deg2rad([positions[f'{leg}_{axis}'] for axis in ('shoulder','carrier','crank')]) for leg in CAD_LEGS}
    feet={leg:model.reference(cad,q[leg],np.zeros(3)) for leg,cad in CAD_LEGS.items()}
    # Geometric continuation keeps the IK on the same linkage branch. These
    # solver steps are never transmitted as timed movement instructions.
    sections=max(1,math.ceil(np.linalg.norm(translation)/8),
                 math.ceil(float(np.max(np.abs(np.rad2deg(rotation))))/15),
                 *(math.ceil(np.linalg.norm(offset)/8) for offset in delta.values()))
    for step in range(1,sections+1):
        u=step/sections;model.body_euler=u*rotation;body=u*translation
        for leg,cad in CAD_LEGS.items():
            if action['name']=='body' or leg in delta:
                q[leg]=solve_reference(model,cad,q[leg],body,feet[leg]+u*delta.get(leg,np.zeros(3)))
    return [round(float(v)*100) for v in np.rad2deg(np.concatenate(list(q.values())))]
