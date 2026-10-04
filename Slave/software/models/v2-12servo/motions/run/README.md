# Automatic Run

The normal Walk family uses **Speed 0–100 for Walk, above 100 through 200 for
Run**. Zero requests controlled Finish. Decreasing Speed to 100 or below returns
to Walk without restarting the command. Crawl remains independently selectable
at 0–100. Advanced stride remains 1–100% and cadence 0.25–3×; select explicit
Run for advanced bounding controls.

Run alternates physical front-left/front-right together, then rear-left/rear-right
together. Each pair has 42% stance and 58% swing, half a cycle apart: front
support → flight → rear support → flight. The model uses a rigid chassis with
pitch and vertical bob. It does not model a cheetah's flexible spine or claim
biological galloping dynamics. The paired timing is informed by
[Park, Wensing and Kim's MIT Cheetah bounding research](https://journals.sagepub.com/doi/10.1177/0278364917694244).

`config.json` owns the Run trajectory. Forward automatic Speed progressively
opens the planted sweep from 80 mm just above 100% to **96 mm at 200%**
(88 mm at 150%). The full-stride foot path is biased 8 mm forward; chassis
translation is -8 mm with 3 mm bob and 5.5° pitch oscillation. The pitch is phased
a quarter cycle ahead of the former sine profile to coordinate with paired
contacts. Backward Run and turns use an 80 mm maximum sweep, the same forward
bias, a -4 mm body reference and 4° pitch. All directions use up to 14 mm lift.

Horizontal swing returns use smooth velocity ramps in the first and last 5%
of flight and constant velocity between them. This returns the foot promptly
without the old quintic path's excessive rearward excursion. The vertical lift
profile is unchanged. A swing selects its return profile at liftoff and retains
it until touchdown. The approved 96 mm Walk remains unchanged.

Forward Run puts the physical front pair inside and rear pair outside. At full
stride each pair shifts its touchdown lane 8 mm, giving 16 mm nominal lane
separation. The offset scales with stride and the existing Run transition.
Targets are selected at liftoff; planted feet stay fixed and airborne feet keep
their landing targets. Returning to Walk restores its lanes through subsequent
swings. Shoulder angles compensate for body motion instead of being locked.

At full forward Run, 42% stance produces about 228.57 mm of modeled advance per
cycle. Automatic rate is `2+(Speed-100)/150` against a 1.2-second base cycle:
about 0.6 s just above 100%, 0.514 s at 150%, 0.45 s at 200%. Advanced forward
Run stride 100% uses the same 96 mm sweep. These are planned values, not measured
loaded tracking. The current per-joint horn references and modeled envelope remain in
`servo_profile.json`; restoring this trajectory does not undo that calibration.
The direct controller adds no solver iterations or pulse caps.

A six-cycle quintic transition changes contact timing, paired phases and body
motion. Liftoff phases advance to synchronize the pairs instead of delaying a
planted foot past its reachable stance. Existing swing landing targets stay
fixed. A foot's stance XY remains fixed; the command sequence and common clock
continue. Stride changes use three cycles, or six while changing gait. Finish
uses three cycles and reduces lift for newly planned swings as travel decelerates.
Direct automatic-Run startup uses six cycles. Finish settles all feet. Output-gap faults and emergency detach retain
their existing behavior.

The gateway/dashboard negotiate `run_gait_v1` in addition to directional walking
and a declared `run` command. Unsupported bodies reject Run before dispatch.
The automatic wire gait remains `walk` when Speed crosses 100. Explicit
`gait:run` supports independent stride/rate tuning (its optional Speed maps to
`max(2/3,Speed/75)` cadence). Bare V2 Run means ongoing Walk-family Speed 150;
the V1 Run asset is unchanged.

## Current offline verification

The native `run_calibration` regression maps production gait frames through the
firmware pulse mapper with the installed mounting calibration and 1000°/s joint
speed setting. It checks the requested 400–2900 µs range through Run entry,
steady operation, speed changes, returns to Walk, startup updates, and Finish at
32 phases per direction and command family. `v2_run` also checks existing
linkage, shared-clock, stride/cadence and rapid-reversal behavior. These are
calculated-motion checks, not proof of loaded tracking or physical clearance.
No pulse clamp or new runtime stop is introduced.

## Demonstration and evidence

`source.json` records the real native command path at 120 Hz: Walk 100% for six
seconds, Run 150%, Run 200% at 14 s, Walk 75% at 20 s, Finish at 28 s. The clip
ends after the feet settle; that duration is not a runtime limit. It is appended
as **Walk > Run > Walk** in the existing Blender motion library. After
regeneration, `refresh_run()` in `tools/append_blender_locomotion.py` replaces
only this final chapter in the live scene; save a verified rolling recovery first.

`source.json` is the exact pre-task recording, restored for comparison with the
original Walk/Run motion. `validation.json` and `blender-validation.json` retain
historical measurements of that recording and label their evidence scope.
They do not establish clearance with the current 4 mm × 1.5 mm shaft screw heads
or qualify the present calibration. Screw-clearance correction remains pending.
The original recording already reports a provisional modeled-envelope conflict.
The restored source keeps its original timing, body motion, lane offset and foot
paths; no new motion calculation, hardware movement or firmware flash was
performed for this restoration. Current measured calibration is retained.

Regenerate this demonstration with NumPy/SciPy from the model directory:

```sh
python tools/generate_locomotion.py --run-only --cli /path/to/v2_walk_command
```
