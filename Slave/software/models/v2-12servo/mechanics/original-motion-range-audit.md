# Motion range conflicts

The original choreography is unchanged. New Run and Upright demonstrations are included when present. This report recalculates pulses using the selected mounting references; it does not alter joint tracks, amplitudes, timing or gait controls.

Selected reference: 1300 µs. Arithmetic midpoint: 1600 µs. Reported span: 300–2900 µs. Conversion assumes 234° of unmeasured shaft travel. Endpoints remain reference data; firmware retains the PWM timer capacity check.

Non-inverted mounting offsets at 1300 µs: shoulder 0°, carrier 1.17°, crank -40.41°. Carrier/crank centers balance the combined original motion ranges and are rounded to centidegrees.

| Joint type | Combined recorded model range | Span | Pulse range with selected mounting |
| --- | --- | ---: | --- |
| h_Part002 | -96.99…25.11° | 122.10° | 222.32…1578.98 µs |
| alpha_Part006 | -79.02…135.37° | 214.39° | 408.97…2791.12 µs |
| theta_Part005 | -128.11…101.29° | 229.41° | 325.52…2874.50 µs |

All recorded carrier/crank positions fit the observed pulse span with this provisional conversion. The widest crank range leaves about 2.30° at each end. Shoulder 0° still leaves Shrug about 1.31° and Surprised about 6.99° beyond its nominal negative travel; these are flagged rather than changed.

The combined Home lies inside the existing coupled mechanical envelope. Horn indexing does not remove the modeled collision conflicts elsewhere in the trajectories. These sampled source ranges do not prove every continuous gait setting, transition, loaded clearance or actual servo tracking.

| Demonstration | Computed minimum µs | Maximum µs | Outside 300–2900 reference | Outside PWM capacity | Modeled collision envelope conflict |
| --- | ---: | ---: | --- | --- | --- |
| bow | 1226.42 | 2874.50 | no | no | yes |
| celebrate | 434.57 | 1818.15 | no | no | yes |
| crab | 692.27 | 1753.93 | no | no | yes |
| crouch | 869.56 | 1753.93 | no | no | yes |
| curious | 1006.49 | 1929.59 | no | no | no |
| cute | 451.17 | 1818.15 | no | no | no |
| dance | 843.76 | 1800.60 | no | no | no |
| dead | 433.08 | 1844.25 | no | no | yes |
| freaky | 510.24 | 1753.93 | no | no | yes |
| nod | 541.58 | 1753.93 | no | no | yes |
| point | 325.52 | 2791.12 | no | no | yes |
| pushup | 408.97 | 1753.93 | no | no | yes |
| rest | 1033.44 | 2000.16 | no | no | yes |
| sad | 1169.42 | 2075.65 | no | no | yes |
| shake | 883.22 | 2001.87 | no | no | yes |
| shrug | 285.50 | 1818.15 | yes | no | no |
| sit | 947.78 | 1939.30 | no | no | no |
| stretch | 1227.86 | 2452.45 | no | no | no |
| surprised | 222.32 | 1818.15 | yes | no | no |
| swim | 451.85 | 1924.05 | no | no | yes |
| upright | 429.17 | 2208.77 | no | no | yes |
| wave | 377.78 | 2193.44 | no | no | no |
| worm | 728.18 | 1753.93 | no | no | yes |
| crawl_backward | 582.18 | 1824.91 | no | no | yes |
| crawl_forward | 574.06 | 1753.93 | no | no | yes |
| crawl_turn_left | 717.15 | 1753.93 | no | no | yes |
| crawl_turn_right | 714.92 | 1753.93 | no | no | yes |
| walk_backward | 543.14 | 2278.54 | no | no | yes |
| walk_forward | 554.78 | 2077.45 | no | no | yes |
| walk_turn_left | 1113.74 | 1888.93 | no | no | no |
| walk_turn_right | 1114.53 | 1887.77 | no | no | no |
| run | 375.40 | 2458.91 | no | no | yes |
| turn_left_15 | 1067.02 | 1777.37 | no | no | no |
| turn_left_180 | 952.05 | 1993.86 | no | no | no |
| turn_left_45 | 1027.02 | 1871.50 | no | no | no |
| turn_left_90 | 966.85 | 1988.54 | no | no | no |
| turn_right_15 | 1067.02 | 1777.37 | no | no | no |
| turn_right_180 | 952.05 | 1993.86 | no | no | no |
| turn_right_45 | 1027.02 | 1871.50 | no | no | no |
| turn_right_90 | 966.85 | 1988.54 | no | no | no |
| walk | 552.34 | 2078.17 | no | no | yes |

Detailed per-leg extrema, first mechanical conflicts, electrical-only alternative references, and input hashes are in [the JSON audit](original-motion-range-audit.json). Reproduce with `python3 tools/audit_mounting_ranges.py` from the model directory. Hardware remains unqualified.
