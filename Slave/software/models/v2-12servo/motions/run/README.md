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
of -6 mm plus 3 mm bob and 4° pitch oscillation around a 6° nose-up bias. The lower Run stance remains through an
explicit Run Finish; returning to Walk restores its original stance. Backward
Run and Run turns retain the original 80 mm sweep, 20 mm bias and -2 mm stance.
All Run directions retain up to 22 mm lift.

Forward Run puts the physical front pair inside and rear pair outside. At full
stride each pair shifts its touchdown lane 8 mm, giving 16 mm nominal lane
separation. The offset scales with stride and the existing Run transition.
Targets are selected at liftoff; planted feet stay fixed and airborne feet keep
their landing targets. Returning to Walk restores its lanes through subsequent
swings. Shoulder angles compensate for body motion instead of being locked;
the current CAD convention is positive inward and negative outward. A 6°
nose-up bias retains linkage reach with these lanes. Sweep, cadence and paired
contact timing are unchanged. Offset-only candidates failed transition/Finish
cases; this combined posture passed all 172 Run regression cases.

At full forward Run, 42% stance produces about 247.62 mm of modeled advance per
cycle. Automatic rate is `2+(Speed-100)/150` against a 1.2-second base cycle:
about 0.6 s just above 100%, 0.514 s at 150%, 0.45 s at 200%. Advanced forward
Run stride 100% uses the same 104 mm sweep. Original Walk 92/30 and Crawl 18/4
trajectories and all 39 earlier motion sources remain byte-for-byte unchanged.

Run alone uses the wider linkage search windows supported by the current horn
indexing: carrier -88.83° to +145.17°, crank -130.41° to +103.59° in CAD-relative
coordinates. These are research solver windows derived from the selected
1300 µs reference and provisional 234° conversion, not new firmware pulse caps
or proof of mechanical clearance. Shoulder search remains ±35°. The selected
horn centers and reference-only servo-limit behavior are unchanged. A 110 mm
forward sweep failed some Finish cases; 104 mm passed the regression suite.

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

`validation.json` records independent linkage/sole calculations: 3,552 samples,
maximum target error below 0.00001 mm, minimum chassis clearance about 32.32 mm,
and 233 flight samples. `integration-validation.json` records build/command
checks and exact parity against all eight original Walk/Crawl profiles.
The original 39 motion sources remain intact. `clearance-validation.json` checks
7,103 poses including every native knot and its linear-joint midpoint against
the current Part027 and Part020/022 meshes: all six pairs of lower-leg assemblies
remain separate, with at least 2.13 mm conservative sampled separation. This
specifically resolves the inter-leg crossing; other modeled internal-leg and
body clearance flags remain. It is not a continuous-time or whole-robot proof.

Recheck against an open/saved current Blender scene with
`tools/validate_run_clearance.py --midpoints --report /tmp/run-clearance.json`
using Blender's `--python` entry point. Geometry is read from the actual scene;
no cached duplicate robot is needed.

With the selected 1300 µs reference and unchanged mounting centers, the demo
uses approximately **375–2459 µs** under the provisional 234° conversion. It
still crosses the modeled mechanical clearance envelope; see
[the range audit](../../mechanics/original-motion-range-audit.md). Those flags
are not proof of actual part collision. Full-speed motion demands a sampled
peak of about **2,980°/s** at a leg joint. Loaded servo tracking has not been
measured, and this kinematic generator has no force/contact/attitude feedback
that would establish airborne stability. Physical running is unqualified;
this work does not flash firmware, change NVS calibration, or move the robot.

Regenerate only this new demonstration from the model directory:

```sh
python tools/generate_locomotion.py --run-only --cli /path/to/v2_walk_command
python tools/audit_mounting_ranges.py
```

Use a Python environment with NumPy/SciPy for the recording generator. The CMake
native suite includes Run threshold, all directions, repeated transitions,
Finish, paired contacts/flight, reference provenance and sampled playback parity.
