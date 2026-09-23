"""Report mounting pulse ranges without editing motion sources or servo settings."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from mechanical_limits import Limits

ROOT = Path(__file__).resolve().parents[1]
LEGS = ['FL', 'FR', 'RL', 'RR']


def generate(root=ROOT):
    limits = Limits(root)
    profile = limits.profile
    reference = profile['pulse_reference_us']
    centers = [round(v * 100) / 100 for v in profile['center_degrees']]
    scale = profile['us_per_degree']
    low_pulse, high_pulse = profile['pulse_range_us']
    lows = [[math.inf] * 3 for _ in LEGS]
    highs = [[-math.inf] * 3 for _ in LEGS]
    rows, hashes = [], {}
    for path in sorted((root / 'motions').glob('**/source.json')):
        source = json.loads(path.read_text())
        hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        if 'columns' in source:
            order = source['leg_order']
            samples = source['columns']['q']
        else:
            order = source['metadata']['leg_order']
            samples = [s['actuator_angles_rad'] for s in source['samples']]
        assert sorted(order) == sorted(LEGS), path
        pulse_min, pulse_max = math.inf, -math.inf
        first = None
        outside = [False] * 3
        for sample, angles in enumerate(samples):
            for leg, name in enumerate(LEGS):
                q = [math.degrees(v) for v in angles[order.index(name)]]
                if first is None and not limits.allowed_degrees(q):
                    first = dict(sample=sample, cad_leg=name, q_deg=q)
                for joint, angle in enumerate(q):
                    lows[leg][joint] = min(lows[leg][joint], angle)
                    highs[leg][joint] = max(highs[leg][joint], angle)
                    pulse = reference + (angle - centers[joint]) * scale
                    pulse_min, pulse_max = min(pulse_min, pulse), max(pulse_max, pulse)
                    outside[joint] |= pulse < low_pulse or pulse > high_pulse
        rows.append(dict(command=path.parent.name, pulse_min_us=pulse_min,
                         pulse_max_us=pulse_max, outside_reference_span=any(outside),
                         outside_reference_by_joint_type=outside,
                         outside_pwm_timer_capacity=round(pulse_min) < 3 or round(pulse_max) > 19986,
                         modeled_envelope_conflict=first is not None, first_conflict=first))
    assert rows, 'No motion sources found'
    midpoint = (low_pulse + high_pulse) / 2
    shift = (midpoint - reference) / scale
    spans = [[hi - lo for lo, hi in zip(a, b)] for a, b in zip(lows, highs)]
    combined = []
    for joint, name in enumerate(profile['joint_order']):
        lo, hi = min(q[joint] for q in lows), max(q[joint] for q in highs)
        combined.append(dict(joint=name, min_deg=lo, max_deg=hi, span_deg=hi-lo,
                             home_deg=centers[joint], balanced_noninverted_deg=(lo+hi)/2-shift,
                             pulse_min_us=reference+(lo-centers[joint])*scale,
                             pulse_max_us=reference+(hi-centers[joint])*scale))
    report = dict(status='original_choreography_preserved_mounting_reference_updated',
                  reference_us=reference, mathematical_midpoint_us=midpoint,
                  provisional_travel_deg=profile['provisional_travel_degrees'],
                  travel_measured=profile['travel_measured'], reference_endpoints_enforced=False,
                  mounting_reference_deg=centers, mounting_pose_inside_modeled_envelope=limits.allowed_degrees(centers),
                  profile_sha256=hashlib.sha256((root/'servo_profile.json').read_bytes()).hexdigest(),
                  source_sha256=hashes, model_min_deg=lows, model_max_deg=highs,
                  model_spans_deg=spans, widest_span_deg=max(map(max, spans)),
                  library_balanced_reference_noninverted_deg=[[(a+b)/2-shift for a,b in zip(lo,hi)] for lo,hi in zip(lows,highs)],
                  library_balanced_reference_inverted_deg=[[(a+b)/2+shift for a,b in zip(lo,hi)] for lo,hi in zip(lows,highs)],
                  combined_ranges=combined,
                  mapping_note='Common carrier/crank references balance the union across all recorded legs and commands; firmware rounds Home to centidegrees. Shoulder stays CAD neutral. Non-inverted mapping assumed; installed direction and actual shaft travel require measurement. Per-leg and inverted balanced candidates are electrical calculations, not approved mounting poses. No trajectory edits or pulse caps.',
                  commands=rows, hardware_qualified=False)
    (root/'mechanics/original-motion-range-audit.json').write_text(json.dumps(report, indent=2)+'\n')
    lines = ['# Motion range conflicts', '',
             'The original choreography is unchanged. New Run and Upright demonstrations are included when present. This report recalculates pulses using the selected mounting references; it does not alter joint tracks, amplitudes, timing or gait controls.', '',
             f'Selected reference: {reference} µs. Arithmetic midpoint: {midpoint:g} µs. Reported span: {low_pulse}–{high_pulse} µs. Conversion assumes {profile["provisional_travel_degrees"]}° of unmeasured shaft travel. Endpoints remain reference data; firmware retains the PWM timer capacity check.', '',
             f'Non-inverted mounting offsets at {reference} µs: shoulder {centers[0]:g}°, carrier {centers[1]:g}°, crank {centers[2]:g}°. Carrier/crank centers balance the combined original motion ranges and are rounded to centidegrees.', '',
             '| Joint type | Combined recorded model range | Span | Pulse range with selected mounting |',
             '| --- | --- | ---: | --- |']
    for r in combined:
        lines.append(f'| {r["joint"]} | {r["min_deg"]:.2f}…{r["max_deg"]:.2f}° | {r["span_deg"]:.2f}° | {r["pulse_min_us"]:.2f}…{r["pulse_max_us"]:.2f} µs |')
    lines += ['', 'All recorded carrier/crank positions fit the observed pulse span with this provisional conversion. The widest crank range leaves about 2.30° at each end. Shoulder 0° still leaves Shrug about 1.31° and Surprised about 6.99° beyond its nominal negative travel; these are flagged rather than changed.', '',
              'The combined Home lies inside the existing coupled mechanical envelope. Horn indexing does not remove the modeled collision conflicts elsewhere in the trajectories. These sampled source ranges do not prove every continuous gait setting, transition, loaded clearance or actual servo tracking.', '',
              '| Demonstration | Computed minimum µs | Maximum µs | Outside 300–2900 reference | Outside PWM capacity | Modeled collision envelope conflict |',
              '| --- | ---: | ---: | --- | --- | --- |']
    for r in rows:
        flags = ['yes' if r[k] else 'no' for k in ['outside_reference_span', 'outside_pwm_timer_capacity', 'modeled_envelope_conflict']]
        lines.append(f'| {r["command"]} | {r["pulse_min_us"]:.2f} | {r["pulse_max_us"]:.2f} | '+ ' | '.join(flags) + ' |')
    lines += ['', 'Detailed per-leg extrema, first mechanical conflicts, electrical-only alternative references, and input hashes are in [the JSON audit](original-motion-range-audit.json). Reproduce with `python3 tools/audit_mounting_ranges.py` from the model directory. Hardware remains unqualified.', '']
    (root/'mechanics/original-motion-range-audit.md').write_text('\n'.join(lines))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    result = generate(args.root)
    print(json.dumps(dict(commands=len(result['commands']), centers=result['mounting_reference_deg'],
                          ranges=result['combined_ranges'], home_allowed=result['mounting_pose_inside_modeled_envelope']), indent=2))
