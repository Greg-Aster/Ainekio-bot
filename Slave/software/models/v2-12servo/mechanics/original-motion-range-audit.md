# Motion range conflicts

This report measures the current geometry-remapped library. The audit itself changes no trajectories or calibration. Choreography and gesture timing are preserved except where geometry contact corrections or the explicit speed policy require a change.

Selected reference: 1650 µs. Arithmetic midpoint: 1600 µs. Reported span: 300–2900 µs. Conversion assumes 234° of unmeasured shaft travel. Endpoints remain reference data; firmware retains the PWM timer capacity check.

Non-inverted mounting offsets at 1650 µs: shoulder 0°, carrier 1.17°, crank -40.41°. Carrier/crank matchmark angles are retained and rounded to centidegrees.

| Joint type | Combined recorded model range | Span | Pulse range with selected mounting |
| --- | --- | ---: | --- |
| h_Part002 | -87.02…27.54° | 114.56° | 683.14…1956.02 µs |
| alpha_Part006 | -89.13…135.37° | 224.50° | 646.65…3141.12 µs |
| theta_Part005 | -128.11…101.29° | 229.41° | 675.51…3224.50 µs |

The owner reports shaft travel greater than 234°. The historical 234° conversion and pulse endpoints are provisional references, not enforced travel stops. Excursions outside them are reported without clipping motion.

The combined Home lies inside the existing coupled mechanical envelope. Horn indexing does not remove the modeled collision conflicts elsewhere in the trajectories. These sampled source ranges do not prove every continuous gait setting, transition, loaded clearance or actual servo tracking.

| Demonstration | Computed minimum µs | Maximum µs | Outside 300–2900 reference | Outside PWM capacity | Modeled collision envelope conflict |
| --- | ---: | ---: | --- | --- | --- |
| bow | 1577.96 | 3224.50 | yes | no | yes |
| celebrate | 833.88 | 2168.37 | no | no | yes |
| crouch | 1216.81 | 2103.52 | no | no | yes |
| curious | 1322.85 | 2311.64 | no | no | no |
| cute | 845.09 | 2168.37 | no | no | no |
| dance | 1290.19 | 2170.87 | no | no | no |
| dead | 1251.15 | 3101.98 | yes | no | yes |
| freaky | 866.45 | 2103.93 | no | no | yes |
| lay_down | 1286.14 | 2820.25 | no | no | no |
| nod | 916.10 | 2169.87 | no | no | yes |
| point | 675.51 | 3141.12 | yes | no | yes |
| pushup | 646.65 | 2119.11 | no | no | yes |
| rest | 1335.36 | 2339.83 | no | no | yes |
| sad | 1536.09 | 2446.22 | no | no | no |
| shake | 1269.81 | 2362.12 | no | no | yes |
| shrug | 916.67 | 2432.33 | no | no | yes |
| sit | 1253.31 | 2272.65 | no | no | yes |
| stretch | 1579.37 | 2790.63 | no | no | no |
| surprised | 683.14 | 2168.37 | no | no | no |
| swim | 843.47 | 2266.38 | no | no | yes |
| upright | 737.69 | 2628.96 | no | no | yes |
| wave | 727.78 | 2543.44 | no | no | yes |
| worm | 1066.97 | 2337.29 | no | no | yes |
| crab | 1290.31 | 2125.32 | no | no | no |
| crab_backward | 1341.19 | 2445.71 | no | no | no |
| crab_forward | 1341.13 | 2402.70 | no | no | no |
| crab_right | 1278.82 | 2129.98 | no | no | no |
| crab_turn_left | 1257.07 | 2508.68 | no | no | no |
| crab_turn_right | 1253.49 | 2448.72 | no | no | no |
| crawl_backward | 927.69 | 2173.89 | no | no | yes |
| crawl_forward | 917.69 | 2103.52 | no | no | yes |
| crawl_turn_left | 1032.37 | 2103.52 | no | no | yes |
| crawl_turn_right | 1030.55 | 2103.52 | no | no | yes |
| walk_backward | 877.64 | 2672.94 | no | no | yes |
| walk_forward | 884.29 | 2445.37 | no | no | yes |
| walk_turn_left | 1378.87 | 2252.07 | no | no | no |
| walk_turn_right | 1379.87 | 2251.00 | no | no | no |
| run | 794.89 | 2838.98 | no | no | yes |
| turn_left_15 | 1414.12 | 2160.71 | no | no | no |
| turn_left_180 | 1295.39 | 2405.95 | no | no | yes |
| turn_left_45 | 1371.67 | 2270.38 | no | no | no |
| turn_left_90 | 1309.54 | 2361.34 | no | no | yes |
| turn_right_15 | 1414.12 | 2160.71 | no | no | no |
| turn_right_180 | 1295.39 | 2405.95 | no | no | yes |
| turn_right_45 | 1371.67 | 2270.38 | no | no | no |
| turn_right_90 | 1309.54 | 2361.34 | no | no | yes |
| walk | 883.47 | 2445.97 | no | no | yes |

## Sampled joint speed

Provisional 4.8 V rating: 545.455°/s. Flag threshold: 681.818°/s (125%). Flagged motions are retimed to the rating; geometry paths and amplitudes are retained. Continuous gaits coordinate all joints through one clock. These are commanded shaft speeds using the provisional pulse conversion; loaded tracking is unmeasured.

| Motion | Peak sampled °/s | Rating ratio | Flagged |
| --- | ---: | ---: | --- |
| bow | 156.629 | 0.287 | no |
| celebrate | 232.613 | 0.426 | no |
| crouch | 35.563 | 0.065 | no |
| curious | 47.563 | 0.087 | no |
| cute | 232.613 | 0.426 | no |
| dance | 91.147 | 0.167 | no |
| dead | 308.621 | 0.566 | no |
| freaky | 145.144 | 0.266 | no |
| lay_down | 216.360 | 0.397 | no |
| nod | 232.513 | 0.426 | no |
| point | 529.451 | 0.971 | no |
| pushup | 106.228 | 0.195 | no |
| rest | 170.075 | 0.312 | no |
| sad | 52.193 | 0.096 | no |
| shake | 95.465 | 0.175 | no |
| shrug | 220.673 | 0.405 | no |
| sit | 51.870 | 0.095 | no |
| stretch | 108.654 | 0.199 | no |
| surprised | 258.293 | 0.474 | no |
| swim | 232.613 | 0.426 | no |
| upright | 91.009 | 0.167 | no |
| wave | 133.409 | 0.245 | no |
| worm | 35.351 | 0.065 | no |
| crab | 225.514 | 0.413 | no |
| crab_backward | 490.493 | 0.899 | no |
| crab_forward | 490.847 | 0.900 | no |
| crab_right | 232.327 | 0.426 | no |
| crab_turn_left | 624.071 | 1.144 | no |
| crab_turn_right | 624.079 | 1.144 | no |
| crawl_backward | 619.798 | 1.136 | no |
| crawl_forward | 592.550 | 1.086 | no |
| crawl_turn_left | 372.310 | 0.683 | no |
| crawl_turn_right | 349.861 | 0.641 | no |
| walk_backward | 670.063 | 1.228 | no |
| walk_forward | 658.607 | 1.207 | no |
| walk_turn_left | 302.477 | 0.555 | no |
| walk_turn_right | 292.504 | 0.536 | no |
| run | 676.807 | 1.241 | no |
| turn_left_15 | 121.897 | 0.223 | no |
| turn_left_180 | 239.062 | 0.438 | no |
| turn_left_45 | 179.826 | 0.330 | no |
| turn_left_90 | 239.062 | 0.438 | no |
| turn_right_15 | 121.897 | 0.223 | no |
| turn_right_180 | 239.062 | 0.438 | no |
| turn_right_45 | 179.826 | 0.330 | no |
| turn_right_90 | 239.062 | 0.438 | no |
| walk | 545.455 | 1.000 | no |

Detailed per-leg extrema, first mechanical conflicts, electrical-only alternative references, and input hashes are in [the JSON audit](original-motion-range-audit.json). Reproduce with `python3 tools/audit_mounting_ranges.py` from the model directory. Hardware remains unqualified.
