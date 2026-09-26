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

`config.json` owns the new Run trajectory. Forward automatic Speed progressively
opens the planted sweep from 80 mm just above 100% to **104 mm at 200%**
(92 mm at 150%). The maximum is 30% longer than the initial Run prototype.
Forward Run uses a 10 mm rearward bias at full stride and a chassis translation
of -9 mm plus 3 mm bob and 4° pitch oscillation around a 3° nose-up bias. Backward
Run and turns retain the 80 mm sweep and 20 mm bias, with a -8 mm body reference.
All directions use up to 18 mm lift. Relative to the preceding Run, the lower
body improves transmission angles; reducing lift from 22 mm preserves reachable
swing targets during rapid Walk/Run reversals. Stride length and cadence remain.

Forward Run puts the physical front pair inside and rear pair outside. At full
stride each pair shifts its touchdown lane 8 mm, giving 16 mm nominal lane
separation. The offset scales with stride and the existing Run transition.
Targets are selected at liftoff; planted feet stay fixed and airborne feet keep
their landing targets. Returning to Walk restores its lanes through subsequent
swings. Shoulder angles compensate for body motion instead of being locked.

At full forward Run, 42% stance produces about 247.62 mm of modeled advance per
cycle. Automatic rate is `2+(Speed-100)/150` against a 1.2-second base cycle:
about 0.6 s just above 100%, 0.514 s at 150%, 0.45 s at 200%. Advanced forward
Run stride 100% uses the same 104 mm sweep. These are planned values, not measured
loaded tracking. Saved calibration, horn centers and reference-only servo limits
are unchanged; the direct controller adds no solver iterations or pulse caps.

A four-cycle quintic transition changes contact timing, paired phases and body
motion. Liftoff phases advance to synchronize the pairs instead of delaying a
planted foot past its reachable stance. Existing swing landing targets stay
fixed. A foot's stance XY remains fixed; the command sequence and common clock
continue. Finish settles all feet. Output-gap faults and emergency detach retain
their existing behavior.

The gateway/dashboard negotiate `run_gait_v1` in addition to directional walking
and a declared `run` command. Unsupported bodies reject Run before dispatch.
The automatic wire gait remains `walk` when Speed crosses 100. Explicit
`gait:run` supports independent stride/rate tuning (its optional Speed maps to
`max(2/3,Speed/75)` cadence). Bare V2 Run means ongoing Walk-family Speed 150;
the V1 Run asset is unchanged.

## Demonstration and evidence

`source.json` records the real native command path at 120 Hz: Walk 100% for six
seconds, Run 150%, Run 200% at 14 s, Walk 75% at 20 s, Finish at 28 s. The clip
ends after the feet settle; that duration is not a runtime limit. It is appended
as **Walk > Run > Walk** in the existing Blender motion library. After
regeneration, `refresh_run()` in `tools/append_blender_locomotion.py` replaces
only this final chapter in the live scene; save a verified rolling recovery first.

`validation.json` records the current regenerated native trajectory against the
full soles, including transmission angles and linear joint midpoints. The old
`integration-validation.json` remains historical pre-revision evidence; current
build and regression results are in [CONTROLLER_VALIDATION.md](../../CONTROLLER_VALIDATION.md)
and the locomotion validation report. Existing Blender chapters require a separate
refresh before they depict this code revision. No hardware movement or flash was
performed for this leverage update.

The preceding `clearance-validation.json` is historical evidence for the earlier
Run, not a collision qualification of these revised joint paths. The earlier
screen covered all six lower-leg pairs at source keys and linear midpoints;
whole-robot/body/hardware clearance was not established. Recheck the current
geometry in Blender using `tools/validate_run_clearance.py --midpoints --report
/tmp/run-clearance.json` through Blender's `--python` entry point.

The current demonstration still crosses the provisional mechanical envelope;
see [the range audit](../../mechanics/original-motion-range-audit.md). This is a
flag for geometric review, not proof of actual part collision. Its unchanged
1300 us mounting reference maps to approximately 434–2489 us under the provisional
234-degree conversion. Peak sampled joint demand is about 2,901 degrees/s;
loaded servo tracking and airborne stability remain unqualified.

Regenerate this demonstration with NumPy/SciPy from the model directory:

```sh
python tools/generate_locomotion.py --run-only --cli /path/to/v2_walk_command
```
