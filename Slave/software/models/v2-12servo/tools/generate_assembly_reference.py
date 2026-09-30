"""Write the twelve-joint mounting table from the canonical servo profile."""
from pathlib import Path
import csv,json,math
from audit_mounting_ranges import generate as audit_ranges
ROOT=Path(__file__).resolve().parents[1]

def generate(root=ROOT):
    profile=json.loads((root/'servo_profile.json').read_text());model=json.loads((root/'model.json').read_text());geom=json.loads((root/'geometry.json').read_text())
    audit=audit_ranges(root);recorded=audit['combined_ranges']
    centers=profile['center_degrees'];bounds=profile['joint_bounds_degrees'];scale=profile['us_per_degree'];mid=profile['pulse_reference_us'];p=geom['parameters']
    rows=[]
    for joint in model['joints']:
        i=joint['id'];j=i%3;lo,hi=bounds[j]
        rows.append(dict(id=i,joint=joint['name'],cad_leg=joint['cad_leg'],default_channel=i,recorded_assembly_channel=joint['pca_channel'],actuator=joint['actuator'],home_us=mid,home_model_deg=centers[j],home_cd=round(100*centers[j]),projected_min_model_deg=lo,projected_max_model_deg=hi,provisional_us_per_degree=scale,pulse_at_min_noninverted=round(mid+(lo-centers[j])*scale,3),pulse_at_max_noninverted=round(mid+(hi-centers[j])*scale,3),recorded_min_model_deg=recorded[j]['min_deg'],recorded_max_model_deg=recorded[j]['max_deg'],recorded_pulse_min_us=round(recorded[j]['pulse_min_us'],3),recorded_pulse_max_us=round(recorded[j]['pulse_max_us'],3),direction='non-inverted default; verify installed direction before indexing',limits='carrier/crank coupled; shoulder body sweep unqualified'))
    with (root/'mechanics/servo-mounting-reference.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=rows[0],lineterminator='\n');w.writeheader();w.writerows(rows)
    alpha=math.degrees(p['alpha_neutral'])+centers[1];theta=math.degrees(p['new_theta_neutral'])+centers[2]
    lines=['# V2 servo mounting and calibration','',f"Profile: `{profile['profile_id']}`. This guide describes the current source; it does not flash or qualify hardware.",'',
    f'The owner reports assembling the legs at **{mid} µs**, with the existing carrier/crank matchmarks aligned. The historical 300–2900 µs span and conversion, 2600/234 = 11.111111 µs/degree, remain provisional until actual shaft travel is measured. The arithmetic midpoint of that span is 1600 µs.','',
    'The matchmarks retain their existing model angles. Read [the remaining motion conflicts](mechanics/original-motion-range-audit.md); changing the pulse reference does not establish that the full library fits the installed travel.','',
    '## Mounting reference','', '![Planar CAD neutral and mounting references](mechanics/servo-mounting-reference.svg)','',
    f'Set the unloaded servo to the selected {mid} µs reference, then index its horn so the linkage matches the model offsets below. These offsets use the existing CAD neutral; they are not absolute shaft-angle readings. Shoulder offset 0° keeps Part 003 centered as drawn. Do not add another 90° in firmware.','',
    '| Joint type | Driven part | Pulse reference | Model offset | Combined recorded motion range |',
    '| --- | --- | --- | --- | --- |',
    f'| Shoulder Part 002 | Part 003 | {mid} µs | {centers[0]:g}° | {recorded[0]["min_deg"]:.2f}…{recorded[0]["max_deg"]:.2f}°; shoulder conflict remains |',
    f'| Carrier Part 006 | Part 023 | {mid} µs | {centers[1]:g}° | {recorded[1]["min_deg"]:.2f}…{recorded[1]["max_deg"]:.2f}° |',
    f'| Crank Part 005 | Part 009 | {mid} µs | {centers[2]:g}° | {recorded[2]["min_deg"]:.2f}…{recorded[2]["max_deg"]:.2f}° |','',
    f'At {mid} µs, the historical endpoints imply {(profile["pulse_range_us"][0]-mid)/scale:.1f}° to {(profile["pulse_range_us"][1]-mid)/scale:+.1f}° relative to Home under the provisional non-inverted conversion. This is an arithmetic estimate, not measured coverage. All four legs use the same matchmark offsets in their respective CAD frames. Verify installed direction independently.','',
    f'With this mapping, recorded carrier pulses span {recorded[1]["pulse_min_us"]:.2f}–{recorded[1]["pulse_max_us"]:.2f} µs and crank pulses span {recorded[2]["pulse_min_us"]:.2f}–{recorded[2]["pulse_max_us"]:.2f} µs. Compare these with measured endpoints before executing the complete library.','',
    'The combined Home lies inside the existing coupled envelope. Carrier/crank clearance still depends on both joint angles; use `servo_profile.json` and the range audit for the mechanical constraints. Changing the pulse reference does not resolve the flagged collisions elsewhere in the motions.','',
    f'For a side-view jig in the mechanism local X/Z plane, the O→D carrier vector is {alpha:.3f}° and C→P crank vector is {theta:.3f}°, measured from local +X toward +Z. These angles include the recorded CAD-neutral angles. Use these vectors and the actual part landmarks to make the alignment reference; spline tooth counts are not assumed.','',
    '| ID | Physical joint | CAD leg | Default channel | Model angle at Home |',
    '| --- | --- | --- | --- | --- |']
    lines += [f"| {r['id']} | {r['joint'].replace('_',' ')} | {r['cad_leg']} | {r['default_channel']} | {r['home_model_deg']:g}° |" for r in rows]
    lines += ['', 'Channel numbers are proposed firmware defaults. The model records only front-left channels 6–8 as assigned; verify every connection. Retain confirmed channel assignments and inversion in the device settings. The CAD FL/FR labels identify the physical rear legs; CAD RL/RR identify the physical front legs.','',
    '## Assembly sequence','',
    '1. Support the chassis and leave the horn or linkage unloaded. Connect one identified servo at a time with power off.',
    f'2. In Calibration, establish pulse endpoints and use the selected {mid} µs mounting reference. Actual shaft rotation must be measured.',
    f'3. At {mid} µs, fit the horn to the corresponding model reference. Set the carrier and crank together to the table values when joining their rod; do not sweep either independently across its projected range.',
    '4. Measure a small unloaded movement on either side of the reference to verify direction and calculate µs/degree. If inversion is required, recalculate the mounting reference before joining the linkage; changing Invert alone does not preserve these asymmetric travel windows. Measure additional points to detect nonlinearity.',
    '5. If the nearest spline tooth does not align exactly, measure the actual model offset at the chosen reference pulse and enter that as Model angle at Home. Do not compensate by changing the geometric motion data.',
    '6. Record the verified per-joint Home, channel, direction, model offset and scale. Stage and Save deliberately. Then establish a known reference with Calibration Home/Move before requesting semantic motion.',
    '7. Check small supported motions before testing full trajectories under load. Current tests do not establish cable clearance, shoulder/body collisions, torque, tracking, traction or balance.','',
    '## Existing calibration and commands','',
    'The firmware stores Home, channel, inversion, model angle and scale in `p4_config/joint_mapping`, exposed through `body_calibration_v2`. There are no pulse endpoint fields or old-format importer. Existing saved mappings are retained: updating firmware defaults does not physically re-index horns or overwrite calibration. When adopting these mounting positions, update the measured Home angles and explicitly Stage and Save the mapping. Save disables outputs and does not move a servo. Missing saved mapping leaves automatic startup Home off; explicit calibration is available.',
    '', 'Home is the mounting reference. CAD Neutral is zero model offsets. Stand, Sit and Rest are distinct geometric poses. A commanded pulse is not measured shaft feedback. After outputs are disabled, motion requires an explicit known reference. The reported endpoints remain reference data; they are not motion caps or editable fields in this contract. Automatic pulses are checked against PWM timer capacity. The restored motion library has unresolved electrical and modeled collision conflicts; see the range audit before assembly.',
    '', 'Entry paths coordinate carrier and crank, with exact electrical-extrema preflight and a 1000 µs/s pulse-rate bound. Their internal-leg clearance check does not prove floor clearance or loaded stability during arbitrary pose changes.',
    '', 'The finite library retains its authored gestures. Walk has 92 mm planted sweep and 30 mm rear bias; Crawl has 18 mm sweep, 4 mm rear bias and -35 mm body translation. Continuous gaits share a joint-speed-limited clock; the requested cadence may take longer. See mechanics/original-motion-range-audit.json for recorded range conflicts.',
    '', 'See [the machine-readable mounting table](mechanics/servo-mounting-reference.csv) and [the canonical coupled profile](servo_profile.json).','']
    (root/'SERVO_ASSEMBLY.md').write_text('\n'.join(lines))
if __name__=='__main__':generate()
