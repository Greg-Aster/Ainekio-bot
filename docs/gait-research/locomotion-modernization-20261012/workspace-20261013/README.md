# Actual linkage workspace, 2026-10-13

The existing Walk was authored as a Cartesian foot path and then fitted to the
linkage. It was not selected by maximizing the installed mechanism's useful
stroke. At 100% it uses a 78 mm planted sweep, shifted 16 mm forward, at body
translation Z = −10 mm. It has a 70% stance fraction, staggered leg phases,
1.8-second base period, and previously used a whole-swing quintic return.
Inverse kinematics matches the compact geometry, but that alone does not make
these trajectory choices appropriate for the loaded robot.

## What was measured

Read the live, unchanged `Wireless` Blender scene. Its linkage parameters are
35 mm carrier, 20 mm crank, 28 mm pickup, 38 mm rod and 55 mm lower leg. The
four current foot-frame transforms agree with the desktop geometry to within
0.000026 mm translation and 0.00000033 per rotation-matrix element. Hidden
alternative boots were excluded from the sole comparison. The visible sole
and compiled contact profile differ by at most 0.152 mm in sampled planar
support height, including the profile's existing allowance.

Sampled 901 × 901 carrier/crank combinations across the existing 400–2900 µs
review interval, using saved 856/723 µs reference values, 1.17/−40.41° model
references and 11.111111 µs/degree. This interval represents 225° of commanded
travel; it is not a measurement of physical stops or an added runtime limit.
The shoulder is held neutral and the body level for this study. The installed
assembly and inverse-crank branch are preserved. Impossible linkage closure is
excluded geometrically. Constant-height contours are split where fore/aft
travel reverses; disconnected or reversed pieces are not counted as one stroke.

The workspace equations and analytic vertical-load moment arms were checked
against the independent desktop forward kinematics and central finite
differences: 546 valid samples from 1,000 deterministic joint pairs, with maximum
position error below 0.000019 mm and moment-arm error below 0.000017 mm.
See `numerical-check.json`.

## Height and stroke result

Clearance here is the lowest **modeled body hull**, not an IMU height reading
or measured carpet clearance. Sole contact is on a level plane. Raw reach and
the subset satisfying the project's pre-existing offline leverage criteria are
shown separately; neither is a collision-qualified or load-qualified gait.

| Modeled body clearance | Longest sampled continuous planted stroke | Stroke satisfying existing review criteria |
| --- | ---: | ---: |
| 40 mm | 96.2 mm | 87.6 mm |
| 45 mm | 92.6 mm | 82.8 mm |
| 50 mm | 87.4 mm | 76.1 mm |
| 60 mm | 72.2 mm | 55.1 mm |

The longest raw strokes approach near-straight rod/pickup geometry: the minimum
output transmission angle is around 3–5° at several endpoint cases. Counting
that reach as useful powered travel would conceal the coupling and torque
tradeoffs. The existing criteria used for the separate comparison are recorded
in `workspace-report.json`; no new restriction was placed on the robot.

At 45 mm modeled clearance, an approximately 78 mm segment with lower peak
vertical-load moment arm runs from front-left reference X ≈ 44.2 to 122.2 mm.
The current nominal 100% stroke runs from X ≈ 51.2 to 129.2 mm at nominal
39.25 mm modeled clearance. This gives a concrete candidate about 5.75 mm taller
and 7 mm farther back, with the same planted travel. It is a **candidate**, not
an adopted or qualified gait. Its modeled carrier/crank excursions are about
88°/104°; increased useful stance height does not require using all 234° of
reported servo rotation.

The baseline native 99% Walk commands roughly 105–109° of carrier travel and
109–112° of crank travel. These are commands, not measured shaft angles. The
owner reports roughly 90° under load and sagging. No current measurement
establishes loaded servo tracking, actual mass, supply voltage or available
joint torque; those fields remain unknown in the source model.

Force capability follows the linkage Jacobian and available motor torque,
not the percentage of the servo's total rotation used. The study computes the
vertical-load component of `tau = Jᵀ F` at the lowest sole point. It does not
include leg mass, horizontal traction, acceleration, friction or servo tracking.
The virtual-work relationship is described in [Modern Robotics, statics](https://modernrobotics.northwestern.edu/nu-gm-book-resource/5-2-statics-of-open-chains/).

## Full trajectory checks expose a separate path problem

Replaying the workspace-derived candidates through the native controller shows
that the old whole-swing easing carries the foot beyond the stance endpoints.
The 78 mm / 45 mm candidate completes the sampled straight, backward and turn
sequences, but its forward/backward reference mapping falls to about 351 µs,
outside the 400 µs review endpoint. Static planted reach alone is insufficient.
Its forward peak commanded joint speed is about 1,182°/s at 100% Walk.

Using the existing Run-style return (constant velocity through most of swing,
short smooth endpoint ramps) on Walk preserves cadence and stride while reducing
that candidate's peak demand to about 578°/s and its minimum reference pulse to
about 390 µs. It still needs further trajectory placement/transition work before
adoption; no pulse window was expanded to declare success. The roughly 83 mm
candidate also dips slightly below the existing stance output-angle criterion
in its full dynamic replay, unlike its level static contour.

The return-shape correction is now implemented for the existing Walk baseline.
At 100%, the front-left return extends only about 0.36 mm beyond its nominal
planted endpoints in a 100 Hz native sample. A regression verifies the steady
return stays within 1% of sweep beyond the endpoints. This is an offline test,
not a runtime clamp. The baseline remains 78 mm with its existing placement and
height pending full path redesign. Separate Crawl/Crab interpolation is unchanged.

No Blender scene, CAD part, installed calibration, or geometry dimension was
changed. `linkage-workspace.png` shows the baseline pre-correction path and
calculated workspace. `trajectory-check.json` and
`trajectory-constant-swing-check.json` retain the candidate replay results.
The separately reproduced combined forward/turn Walk-to-Run failure remains
unresolved; these results do not imply it is fixed.

## Reproduce the workspace

```sh
MPLCONFIGDIR=/tmp/ainekio-mpl OPENBLAS_NUM_THREADS=1 \
/home/greggles/ComfyUI/venv/bin/python \
Slave/software/models/v2-12servo/tools/study_linkage_workspace.py \
  --binary /tmp/ainekio-gait-repair-optimized/v2_model/v2_walk_command \
  --out /tmp/ainekio-workspace-study
```

The optional `--live-geometry` input accepts the read-only Blender snapshot with
four foot transforms, controls and visible sole vertices. Without it, the tool
uses the repository sole hull and omits live-transform parity. Re-running against
a newly built binary samples that binary's trajectory; the checked-in plot shows
the baseline sampled before the Walk return correction.

The subsequent complete-path fit adopts body Z -4.75 mm and bias -12 mm with
the full 78 mm sweep. `adopted-walk-calibrated.json` records the 50/100 Hz
checks using the saved twelve-joint mapping. Unlike the earlier static
candidates, all sixteen sampled command cases complete within 400–2900 us
and the existing leverage review margins at both cadences. This is source
validation; loaded walking and collision clearance remain unqualified.
