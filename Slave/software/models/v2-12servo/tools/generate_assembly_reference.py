"""Write the existing assembly guide from the canonical per-joint profile."""
from pathlib import Path
import csv,json,math
from audit_mounting_ranges import generate as audit_ranges
ROOT=Path(__file__).resolve().parents[1]
def generate(root=ROOT):
    profile=json.loads((root/'servo_profile.json').read_text());model=json.loads((root/'model.json').read_text());audit=audit_ranges(root)
    refs=profile['pulse_reference_us'];centers=profile['center_degrees'];scale=profile['us_per_degree'];rows=[]
    for joint in model['joints']:
        i=joint['id'];j=i%3;lo,hi=profile['joint_bounds_degrees'][j]
        rows.append(dict(id=i,joint=joint['name'],cad_leg=joint['cad_leg'],default_channel=i,recorded_assembly_channel=joint['pca_channel'],actuator=joint['actuator'],home_us=refs[j],home_model_deg=centers[j],home_cd=round(100*centers[j]),projected_min_model_deg=lo,projected_max_model_deg=hi,provisional_us_per_degree=scale,pulse_at_min_noninverted=round(refs[j]+(lo-centers[j])*scale,3),pulse_at_max_noninverted=round(refs[j]+(hi-centers[j])*scale,3)))
    with (root/'mechanics/servo-mounting-reference.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=rows[0],lineterminator='\n');w.writeheader();w.writerows(rows)
    lines=['# V2 servo mounting and calibration','',f"Profile `{profile['profile_id']}`. The original motion geometry and timing are retained. The retained mapping references below are provisional; they do not establish the installed horn angles.",'',
    '| Joint | Part | Default Home reference (non-inverted) | Model angle at that pulse |','| --- | --- | --- | --- |',
    f'| Shoulder | Part 002 / 003 | {refs[0]} µs | {centers[0]:g}° |',f'| Carrier | Part 006 / 023 | {refs[1]} µs | {centers[1]:g}° |',f'| Crank | Part 005 / 009 | {refs[2]} µs | {centers[2]:g}° |','',
    'The owner reports 300–2900 µs crank travel. The original motion curves are retained. The attempted whole-library recentering was removed because it changed the physical leg poses. Home pulse and model angle must describe the same physical joint pose; fitting waveform extrema inside a pulse span does not establish that relationship.','',
    'The mapping assumes non-inverted direction and 11.111111 µs/degree. Actual shaft travel, spline alignment and installed direction remain unmeasured. All four legs use the model angles in their own CAD frame. Physical rear legs are CAD FL/FR; physical front legs are CAD RL/RR.','',
    'Body Control remains the owner of channel, Home pulse, Model angle at Home, inversion and scale. Firmware defaults do not overwrite saved calibration. Physical joint angles at the saved Home pulses remain unmeasured. Correct physical mapping must be established before claiming installed motion parity.','',
    '| ID | Physical joint | CAD leg | Default channel | Home µs | Model angle |','| --- | --- | --- | --- | --- | --- |']
    lines += [f"| {r['id']} | {r['joint'].replace('_',' ')} | {r['cad_leg']} | {r['default_channel']} | {r['home_us']} | {r['home_model_deg']:g}° |" for r in rows]
    g=json.loads((root/'geometry.json').read_text());run=json.loads((root/'motions/run/config.json').read_text())
    lines += ['', '## Motion paths','',f"Full Walk uses {g['continuous_walk']['stance_sweep_100_mm']:g} mm planted sweep. Forward Run retains {run['forward']['sweep_mm']:g} mm, with coordinated body pitch and foot timing. Starts, control changes and Finish follow the same native planner. All original recorded joint curves are retained. Named motions and entry transitions use the same existing affine mapper; numerical curve parity alone does not prove physical motion parity.",'',
    'The internal model includes 4 mm diameter × 1.5 mm shaft screw heads, captured moving linkage meshes and stationary Part 003/005/006 on all four legs. It does not establish cable clearance, print tolerances, torque, tracking or balance. A surface-intersection check is modeled evidence, not a physical collision guarantee.','',
    'The profile records connected carrier/crank limits. These are coupled: independent extrema cannot be combined arbitrarily. Shoulder-to-body and leg-to-leg clearance require separate evidence. The existing PWM capacity and joint-speed policy remain unchanged. No additional runtime limiter is introduced.','',
    'Home is an operator-selected literal pulse; its model association is independently configurable. CAD Neutral, Stand, Sit and Rest remain distinct model poses. Updating source does not flash firmware, change NVS calibration or command physical motion.','',
    'See [the current range audit](mechanics/original-motion-range-audit.md), [the joint table](mechanics/servo-mounting-reference.csv) and [the canonical profile](servo_profile.json).','']
    (root/'SERVO_ASSEMBLY.md').write_text('\n'.join(lines))
if __name__=='__main__':generate()
