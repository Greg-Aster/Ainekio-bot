# Seated support and angle-reference remap

The 35 / 20 / 28 / 38 / 55 mm candidate now includes recalculated Sit, Wave
and Upright recordings. Blender's Wireless controls use the firmware's joint
coordinate zero. The modeling pose, meshes and detached articulation preview
were preserved. No robot firmware, saved calibration or runtime limiter changed.

The October 6 continuation recalculates the other **20 named motions** and
packages a complete, consistently bound **23-clip offline candidate** in
`motion-library-candidate.zip`. The active firmware model remains unchanged.
In Blender, select **Motion Library - 35-20-28** for the complete library;
the original **Seated Support - 35-20-28** preview is also retained.

**Upright is experimental and will use the best achievable approximation.**
On October 6 the owner clarified that the original motion may be physically
unachievable. Its reduced reach is accepted for continued remapping and does
not block the rest of the motion library. Preserve its intended rise and
expression as closely as the new geometry permits; the original reach remains
a comparison, rather than a required outcome for this experimental motion.

Its old extended-arm direction requires the opposite output assembly branch
on this linkage. The retained-branch fit also reaches an input dead center.
These findings remain recorded for physical tuning. The experimental designation
does not establish physical feasibility or change the robot's calibration.

## What changed

* Sit moves each rear landing forward 5.58396 mm during its existing footstep.
  The original seated supporting sole orientation, chassis trajectory, contact schedule
  and timing remain intact. The previous body lowering is not applied twice.
* Wave reuses the new Sit support, retains three waves, and reverses Sit to stand.
  Its torso trajectory and recorded foot XY/sole-height targets are preserved.
* Upright reuses the exact new Sit prefix, retains the two front-foot steps,
  planted front anchors through 12 seconds, full -90 degree rise, and 20–22
  second hold. Both rear boot orientations and anchored XY remain aligned with
  the retained choreography. The grounded transfer is refitted to the linkage;
  body pitch changes by at most 5.686 degrees and translation by 12.360 mm.
* Upright's computed forelimb reach is **76.585 mm**, versus **90.339 mm** in the
  baseline. This is the chosen knee-and-ankle pose fit on the retained branch,
  not a claim that 76.585 mm is the mechanism's maximum reach in every direction.
  `upright-reach-witness.json` records both crank solutions for straightening in
  the old direction: both require output assembly branch -1, while the current
  firmware and Blender model use +1.

## Blender

Saved in `Slave/hardware/v2-12servo/ainekio-variable-gait-Recovery.blend`.
Select **Seated Support - 35-20-28** to inspect the three timeline chapters.
The Wireless modeling scene remains separate; the new preview shares unchanged
meshes and contains baked motion, so it does not depend on temporary source files.

Blender previously measured theta from -4.036908829 rad; firmware measures from
2.484925851 rad. After accounting for a complete revolution, the difference is
13.673601824 degrees. Existing Blender controls and the detached manual-preview
action were converted by that constant without moving their physical poses.
Mesh authoring angles remain separate from motor zeros. The replay also freezes
the evaluated mounting transforms and bakes the linkage transforms, avoiding
legacy frame-driven visibility/layout and chained-driver evaluation effects.

Recovery: `Slave/hardware/v2-12servo/ainekio-Angle-Alignment-Recovery.blend`.

## Evidence and limitations

`verification.json` checks all 5,163 recorded samples with independent forward
kinematics. Declared contacts are within 0.000053 mm of the modeled floor;
minimum body clearance is 0.5435 mm. Upright's provisional support margin after
Sit remains positive, minimum 1.5627 mm. Sit's existing stepping sequence still
has negative static support margins; its contact schedule was preserved, not
redesigned or claimed dynamically balanced.

`blender-preview-check.json` compares all four legs at five nonsequential poses;
maximum world-position disagreement is 0.000024 mm. `blender-alignment.json`
records the preserved modeling pose and motor-zero conversion.

The existing native C sampler passed all twelve joints at 10,373 timestamps.
Maximum position error from the independent source sampler was 0.004889 degrees.
All three selected clips passed the existing provenance checks and compiled to
firmware motion data. The original Upright test passes its support, contact,
continuity-of-hold and full-rise assertions, then fails its historical **>90 mm
forelimb reach assertion**. That assertion has not been weakened.

`travel-and-leverage.json` reports the input dead center and joint extrema.
The authored Upright track peaks at 1,230.84 degrees/second; its execution rate
would remain governed by the existing user-selected common joint-speed limit.
No additional speed ceiling was introduced. Collision corrections remain
deferred as requested. Electrical travel, mounting and loaded performance have
not been qualified for this candidate.

A clean regeneration passed the same checks; joint angles reproduced within
8.9e-16 radians. See `reproduced-verification.json`.

## Candidate handoff

`seated-support-candidate.zip` contains the previous continuous-gait candidate
plus these three updated recordings, manifests, contracts and catalog bindings.
`handoff.json` records hashes for that earlier seated-only overlay. Use the newer
`motion-library-candidate.zip` and `library-handoff.json` for the complete library.
All 23 recordings in the new archive have been recalculated and bound to the
compact geometry. It is an offline integration candidate, not a qualified flash
image. Upright's reduced reach is accepted as an experimental approximation;
physical calibration and deferred collision work remain open.

To reproduce into a separate expanded candidate model, with NumPy and SciPy:

```sh
python3 reproduce.py --baseline /path/to/baseline-model --model /path/to/candidate-model
python3 verify.py --baseline /path/to/baseline-model --model /path/to/candidate-model
```

`remap.py`, `transfer-fit.py` and `air-fit.py` contain the supporting-sole and
pose calculations; `build-upright.py` assembles the retained choreography.
`package.py` refreshes source fields and provenance. The live reference conversion
is implemented in `Slave/software/models/v2-12servo/tools/align_blender_angle_references.py`.
For a new Blender preview, run `preview.py`, then `bake_preview_transforms.py`,
with `MODEL_ROOT` set to that candidate directory.

## Complete motion-library continuation — October 6

Thirteen additional clips preserve the exact original body trajectory, foot XY
and full-sole heights: Celebrate, Curious, Cute, Dance, Freaky, Lay Down, Sad,
Shake, Shrug, Stretch, Surprised, Swim and Worm. Crouch uses the native IK on
its original planner targets, retaining its **-35 mm** terminal body translation
and matching native Stand at entry. Its existing 0.151 mm sole-profile allowance
is retained; the change in full-mesh sole height versus the old geometry's
solver residual is at most 0.024 mm.

The remaining six refits retain the original timing, contact schedule and torso
rotations, with these explicit geometric differences:

| Motion | Geometric adjustment |
| --- | --- |
| Rest | Landings move forward 5.018 mm during the existing footsteps; final boot orientations and chassis lowering are preserved. |
| Bow | Body translates by up to 5 mm while all foot paths and the extended front supporting boot orientation are preserved. |
| Nod | Body translates by up to 5 mm while all foot paths and the front supporting boot orientation are preserved. |
| Pushup | Body translates by up to 4.767 mm; all foot paths, five repetitions and torso rotations are preserved. Minimum modeled chassis clearance is 0.078 mm. |
| Play Dead | Front sliding destinations move back 7.158 mm; rear feet, body collapse and final front boot orientations are preserved. |
| Point | Full extension retains the original carrier angle and boot orientation. The pointing boot is displaced by 5 mm due to the shorter carrier; its original extension/retraction timing is retained. |

Pushup's requested root displacement follows the shortened front support. Its
downward component is smoothly blended according to the recorded chassis
clearance: `dz_new = dz_requested * clearance / (clearance + abs(dz_requested))`.
This is an offline path refit, not a runtime clamp or an added speed ceiling.
The entry and recovery use their existing phase timing. No amplitude multiplier
was applied to the original foot paths or torso rotations.

The existing 20-clip source paths regenerate identically from `library-remap.py`:
all **25,868** samples reproduce with zero joint-angle or body-translation
difference. `library-check.py` independently checks FK, planned targets,
supporting sole orientations, timing and contacts. Some baseline recordings
already penetrate the modeled floor by up to 0.241 mm; their targets are retained
within the repository's existing 0.25 mm interpolation allowance. These results
do not establish physical contact, torque or collision clearance.

All 23 clips compile. The native sampler passed **62,517** timestamps, maximum
position error **0.004937 degrees**. Independent full-sole comparison at **61,919**
timestamps found at most **0.00917 mm** vertex displacement from compression.
All source, linear-midpoint and native-cubic-midpoint geometry checks pass.
The native linkage, transition, motion, gait-clock, clip and compiler checks
pass; the original Upright **>90 mm** reach assertion still fails and was not
weakened. The invalid-pose test fixture was changed from carrier 60 to 90 degrees:
60 degrees now closes the new linkage, while 90 degrees requires a 71.02 mm
rod/pickup span against 66 mm available. Runtime limits were not changed.

The new Blender preview contains **31,031 samples** across all 23 clips, baked
at 120 Hz with quarter-frame keys on a 30 fps timeline. Forty-six nonsequential
pose checks across all clips agree with firmware FK within **0.000027 mm**.
The same checks also pass after reopening the saved file in a separate Blender
process with startup scripts disabled (`library-saved-blender-check.json`).
The existing 2,484 scene objects, meshes and modeling transforms were preserved.
The preview freezes evaluated mounting transforms from the source scene rather
than reading unevaluated identity matrices from an inactive scene.

Upright remains an experimental, best-effort candidate. Its nearest knee/ankle fit retains the
previously reported input dead center and 76.585 mm arm reach. Including the
original crank-pin position in an alternate endpoint fit avoided that dead
center, but reduced reach to 73.868 mm and increased ankle-position error from
15.026 to 22.003 mm; that alternative was not applied. This comparison is not a
proof of a global optimum over every possible gesture modification.

`library-travel.json` also identifies a mounting/calibration issue: the front
cranks span **243.868 degrees** between Upright and Bow. The unchanged provisional
11.111 microseconds/degree conversion gives only 225 degrees inside 400–2900
microseconds. A center shift alone cannot reconcile those spans under that
conversion. Actual servo angular travel remains unmeasured; no calibration or
motion was silently compressed to fit it.

Evidence: `library-results.json`, `library-verification.json`,
`library-reproduction.json`, `library-native-check.txt`,
`library-interpolation.json`, `library-compact-check.json`,
`library-blender-check.json`, and `library-handoff.json`.

To reproduce the continuation into an expanded candidate, first build that
candidate's native model, then run:

```sh
python3 library-remap.py --baseline /path/to/baseline-model \
  --model /path/to/candidate-model --work /tmp/ainekio-library-reproduction \
  --solve-cli /path/to/candidate-build/v2_walk_solve
python3 library-check.py --baseline /path/to/baseline-model \
  --model /path/to/candidate-model \
  --results /tmp/ainekio-library-reproduction/library-results.json \
  --out /tmp/ainekio-library-reproduction/verification.json
```

For an isolated full-library Blender preview, run `library-preview.py` with
`MODEL_ROOT` set to the candidate model. It requires the retained seated preview
as its mesh template. Chapter boundaries are presentation cuts, not robot
transition demonstrations.
