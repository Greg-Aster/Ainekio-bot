"""Check grounded posture recordings for planted lateral drag."""
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for name in ('lay_down', 'dead'):
    rows = json.loads((ROOT / f'motions/gestures/{name}/source.json').read_text())['samples']
    assert len(rows) == 841
    assert all(row['body_ground_clearance_mm'] >= -.02 for row in rows)
    assert all(min(row['sole_clearance_mm']) >= -.02 for row in rows)
    assert min(sum(row['contact_active']) for row in rows) == 3
    for leg in range(4):
        assert max(row['sole_clearance_mm'][leg] for row in rows) > 7.9
        for previous, current in zip(rows, rows[1:]):
            if previous['contact_active'][leg] and current['contact_active'][leg]:
                old, new = previous['foot_bolt_world_mm'][leg], current['foot_bolt_world_mm'][leg]
                assert math.dist(old[:2], new[:2]) < .02

    # The default assembly map gives pulse room; installed calibration and
    # loaded tracking still require a physical check.
    first, last = rows[0], rows[-1]
    assert all(first['contact_active']) and all(last['contact_active'])
    assert all(abs(angle[0]) < 1e-5 for angle in first['actuator_angles_rad'])
    assert all(-33 < math.degrees(angle[0]) < -32 for angle in last['actuator_angles_rad'][:2])
    for row in rows:
        for shoulder, carrier, crank in row['actuator_angles_rad']:
            pulses = (1650 + math.degrees(shoulder) * 11.111111,
                      856 + (math.degrees(carrier) - 1.17) * 11.111111,
                      723 + (math.degrees(crank) + 40.41) * 11.111111)
            assert all(400 < pulse < 2900 for pulse in pulses)
