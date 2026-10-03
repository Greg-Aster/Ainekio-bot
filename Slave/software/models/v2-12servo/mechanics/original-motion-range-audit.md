# Motion range conflicts

This report measures the original recorded motion library through the retained provisional mapping. Joint curves and authored timing remain unchanged. Physical parity is unresolved; whole-library range centering changed the leg poses and was removed.

Selected reference: [1650, 856, 723] µs. Arithmetic midpoint: 1650 µs. Reported span: 300–3000 µs. Conversion assumes 243° of unmeasured shaft travel. Endpoints remain reference data; firmware retains the PWM timer capacity check.

Non-inverted mounting offsets at [1650, 856, 723] µs: shoulder 0°, carrier 1.17°, crank -40.41°. Carrier/crank angle references are retained from the pre-centering configuration; they are not measured installed angles.

| Joint type | Combined recorded model range | Span | Pulse range with selected mounting |
| --- | --- | ---: | --- |
| h_Part002 | -87.02…27.54° | 114.56° | 683.14…1956.02 µs |
| alpha_Part006 | -89.13…135.37° | 224.50° | -147.35…2347.12 µs |
| theta_Part005 | -128.11…101.29° | 229.41° | -251.49…2297.50 µs |

The owner reports 300–2900 µs travel. The 11.111111 µs/degree conversion remains provisional. The audit reports excursions without clipping motion.

The retained modeled Home closes the four-bar. This does not establish its physical association with the saved pulse. The separate provisional mesh envelope still reports conflicts in some original poses; those modeled observations are not measured hardware limits. Sampled ranges do not establish loaded clearance or servo tracking.

| Demonstration | Computed minimum µs | Maximum µs | Outside 300–2900 reference | Outside PWM capacity | Modeled collision envelope conflict |
| --- | ---: | ---: | --- | --- | --- |
| bow | 783.96 | 2297.50 | no | no | no |
| celebrate | 559.32 | 1650.00 | no | no | no |
| crouch | 422.81 | 1650.00 | no | no | no |
| curious | 528.85 | 1796.00 | no | no | no |
| cute | 559.32 | 1650.00 | no | no | no |
| dance | 496.19 | 1846.52 | no | no | no |
| dead | 864.34 | 2174.98 | no | no | no |
| freaky | 445.89 | 1717.55 | no | no | no |
| lay_down | 864.34 | 1893.25 | no | no | no |
| nod | 122.10 | 1721.50 | yes | no | yes |
| point | -251.49 | 2347.12 | yes | yes | yes |
| pushup | -147.35 | 1650.00 | yes | yes | yes |
| rest | 541.36 | 1650.00 | no | no | yes |
| sad | 742.09 | 1698.41 | no | no | no |
| shake | 475.81 | 1650.00 | no | no | no |
| shrug | 265.79 | 1670.54 | yes | no | yes |
| sit | 459.31 | 1650.00 | no | no | no |
| stretch | 785.37 | 1863.63 | no | no | no |
| surprised | 556.38 | 1650.00 | no | no | no |
| swim | 555.11 | 1650.00 | no | no | no |
| upright | -189.31 | 1738.89 | yes | yes | yes |
| wave | 459.31 | 1650.00 | no | no | no |
| worm | 272.97 | 1650.00 | yes | no | yes |
| crab | 592.15 | 1650.00 | no | no | no |
| crab_backward | 592.15 | 1650.00 | no | no | no |
| crab_forward | 592.15 | 1650.00 | no | no | no |
| crab_right | 592.15 | 1650.00 | no | no | no |
| crab_turn_left | 463.07 | 1650.00 | no | no | no |
| crab_turn_right | 459.49 | 1650.00 | no | no | no |
| crawl_backward | 133.69 | 1660.58 | yes | no | yes |
| crawl_forward | 123.69 | 1660.59 | yes | no | yes |
| crawl_turn_left | 238.37 | 1720.26 | yes | no | yes |
| crawl_turn_right | 236.55 | 1726.74 | yes | no | yes |
| walk_backward | -49.36 | 1745.94 | yes | yes | yes |
| walk_forward | -42.71 | 1698.29 | yes | yes | yes |
| walk_turn_left | 584.87 | 1733.79 | no | no | no |
| walk_turn_right | 585.87 | 1733.79 | no | no | no |
| run | -132.11 | 1911.98 | yes | yes | yes |
| turn_left_15 | 620.12 | 1774.61 | no | no | no |
| turn_left_180 | 501.39 | 1956.02 | no | no | no |
| turn_left_45 | 577.67 | 1862.86 | no | no | no |
| turn_left_90 | 516.27 | 1956.02 | no | no | no |
| turn_right_15 | 620.12 | 1774.61 | no | no | no |
| turn_right_180 | 501.39 | 1956.02 | no | no | no |
| turn_right_45 | 577.67 | 1862.86 | no | no | no |
| turn_right_90 | 516.27 | 1956.02 | no | no | no |
| walk | -43.53 | 1698.26 | yes | yes | yes |

## Sampled joint speed

Provisional 4.8 V rating: 545.455°/s. Flag threshold: 681.818°/s (125%). These offline rating flags do not change runtime timing. The owner-selected joint speed limit retains control of the shared clock. These are commanded shaft speeds using the provisional pulse conversion; loaded tracking is unmeasured.

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
