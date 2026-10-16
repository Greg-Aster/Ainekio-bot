# WAVEGO-style linkage around Ainekio's fixed shafts

2026-10-14. Numerical design comparison; not printed-part or loaded-robot validation.

The owner clarified that the servo horns set the **minimum** crank and carrier
lengths. Both are treated as at least 20 mm, not fixed at 20 mm. The knee-to-foot
target is 50 mm, with 45–55 mm considered. Neither shaft moves.

## Selected reference for CAD evaluation

| Centre-to-centre dimension | Installed | Reference |
|---|---:|---:|
| Knee to ideal contact point | 55 mm | **50 mm** |
| Carrier shaft to knee | 35 mm | **30 mm** |
| Crank shaft to crank pin | 20 mm | **30 mm** |
| Connecting rod | 38 mm | **52 mm** |
| Knee to rod pickup | 28 mm | **40 mm** |
| Crank shaft offset from carrier, X/Z | −12.5001 / +11.5000 mm | unchanged |

Carrier : crank : rod : pickup = **1 : 1 : 1.7333 : 1.3333**.
The reference is adapted from WAVEGO's arrangement, not an exact scaled copy.
Equal arm lengths are a starting design family, not a proof of equal load.

**The foot attachment changes.** The installed pickup and foot lie on opposite
sides of the knee. In this reference, the pickup is toward the foot. From the
knee, continue straight through the pickup to a bend at 45.9279 mm, then turn
90° for a 19.7643 mm toe segment. The pickup is at 40 mm, so the continuation
beyond it is 5.9279 mm. The resulting straight-line knee-to-contact distance is
50 mm. Its direction differs from knee-to-pickup by 23.2838°. This requires a
new lower-leg shape; shortening the installed Part 027 does not reproduce it.

[Three stance positions and dimensions](wavego-fixed-shafts-50mm.svg).
[Importable calculator design](wavego-fixed-shafts-50mm-calculator.json).
Open `tools/leg-geometry-calculator/index.html`, then import that JSON. The
calculator foot-angle convention gives −156.7162° for this design.

## Same-path comparison

Point foot centred under its carrier shaft; **50 mm planted sweep, 12 mm lift,
70 mm carrier-shaft height** (about 49.54 mm chassis-bottom clearance), 1.8 s
cycle and 80% stance. Mass 566 g, three equal-load supports: 1.850188 N per foot.
Pairs below are **carrier / crank**. Values describe the modeled path, not the
currently deployed firmware. Both geometries close at all 1,920 phases without
changing assembly branch.

| Calculated quantity | Installed | Reference |
|---|---:|---:|
| Peak vertical-support torque | 0.06216 / 0.05341 Nm | **0.04204 / 0.04274 Nm** |
| RMS vertical-support torque during stance | 0.05943 / 0.03272 Nm | **0.03077 / 0.02764 Nm** |
| Full-cycle servo excursion | 50.52° / 91.60° | **57.70° / 58.10°** |
| Peak requested joint speed | 399.73 / 541.16 °/s | **446.94 / 419.32 °/s** |
| Minimum knee-to-foot angle above horizontal in stance | 43.97° | **53.80°** |

The most-loaded actuator's peak torque falls **31.2%** on this benchmark.
Carrier peak demand falls 32.4%; crank falls 20.0%. RMS imbalance falls from
44.9% to 10.2% (difference divided by the larger RMS). This is improved torque
sharing, not measured electrical power sharing or a guaranteed stall margin.
Carrier peak speed increases about 11.8%; crank peak speed falls about 22.5%.
The crank uses **less** angular travel on this path. More servo excursion is not
itself evidence of better leverage or a stronger gait.

Across 622 sampled support/rise positions, with horizontal force −25%, 0 and
+25% of vertical force, maximum carrier/crank demand is **0.06135 / 0.06133 Nm**,
versus installed **0.09668 / 0.07029 Nm**. Positions cover X ±25 mm at heights
60–70 mm and a centred rise from 40 to 70 mm. This checks geometric reach and
external-load demand during a rise; it does not design or prove a startup
sequence from an arbitrary resting posture.

## Range tradeoffs

| Shaft height / sweep | Complete sampled cycle? | Carrier / crank excursion | Lowest other joint/bend above ground* |
|---|---|---:|---:|
| 70 / 50 mm | Yes | 57.70° / 58.10° | 6.70 mm |
| 70 / 60 mm | Yes | 68.10° / 69.70° | 4.50 mm |
| 70 / 70 mm | Yes | 81.09° / 85.14° | 1.69 mm |
| 70 / 82 mm | **No** | Incomplete path | Not a valid cycle |
| 65 / 82 mm | Yes geometrically | 92.22° / 96.02° | **0.77 mm** |

*Excludes the intended contact point. Includes carrier knee, crank pin, pickup
and the right-angle foot bend. Line segments have zero thickness. Real material,
joint heads and contact radius consume this clearance. Thus the 82 mm result is
**not a usable-stride recommendation**. This is also why pure IK reach must not
be advertised as physical walking capability. These are comparison findings,
not new firmware limits.

## Search and selection

The reproducible coarse search evaluated **61,864** designs; 16,650 passed its
sampled closure/branch/excursion checks. Bounds: leg 45/50/55 mm; matched crank
and carrier 20–40 mm by 2; rod 20–56 mm by 2; pickup 20–44 mm by 2; both signs of
the WAVEGO foot bend; both knee and crank branches. Require pickup before the
foot bend. This search is a restricted equal-arm family, not a global optimum
over all independent arm lengths, bend angles, foot placements or trajectories.

A 50 mm leg with 26/26 mm arms, 54 mm rod and 36 mm pickup reduces envelope
peak torque further to about 0.0555 Nm, but needs about 511°/s peak joint speed
and cannot complete the 60 mm sweep at 70 mm height. The selected 30/30 arms
provide more geometric reach and lower peak return-speed demand. The selected
52 mm rod gives particularly close peak torque and excursion at the target
50 mm stride. A 45 mm leg with 30/30 arms loses the 60 mm sweep at 70 mm height;
the 55 mm leg with minimum 20/20 arms needs about 625°/s on the 50 mm benchmark.
Selection is a stated engineering tradeoff, not a universal ideal ratio.

## Reproduction, evidence and remaining work

From the repository root:

```sh
node tools/leg-geometry-calculator/wavego-study.js --report
node tools/leg-geometry-calculator/wavego-study.js > /tmp/wavego-search.json
node tools/leg-geometry-calculator/mechanics.test.js
```

[Dense results](wavego-fixed-shafts-50mm.json) and
[search summary](wavego-fixed-shafts-search-summary.json) record assumptions and
source hash. Geometry source SHA-256 is
`714bdf312f3ba2a1f62d2add2b7fb17e6d329bb5396dc5e41fc46d3486fa773b`.
Nine mechanics tests pass. Independent forward closure and central-difference
Jacobian checks also run across the dense study cycles. These verify the math,
not the mechanical fit.

WAVEGO's source defines equal 40 mm driven arms, a 40 mm rod, 39.8153 mm pickup,
31.775 mm continuation and 30.8076 mm perpendicular toe. Its shaft spacing is
12.2 mm; Ainekio's is about 16.9854 mm with a vertical offset. Source:
[Waveshare ServoCtrl.h](https://github.com/waveshare/WAVEGO/blob/main/Arduino/WAVEGO/ServoCtrl.h#L25-L52),
including the effective foot-vector calculation at lines 124–137.

Before treating this as a print design, the actual fixed housing, horn sweep,
layer spacing, joint heads and ground-contact outline need a CAD sweep check.
This model holds shoulders neutral and omits motor torque-speed curves,
inertia, backlash, compliance, contact friction and whole-body load distribution.
Two equal-load supporting feet would increase the listed support torques by
50%; real loads need not divide equally. No motor stall rating is used as a
continuous operating rating. No firmware, calibration or physical robot state
was changed.
