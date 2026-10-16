# Twelve-servo motion model

V2 uses a shared measured linkage, direct closure checks, finite gestures
and continuous Walk/Run/Crawl/Crab. The eight-servo V1 assets and default decoder retain
their existing behavior. Assembly references and calibration are documented in
[SERVO_ASSEMBLY.md](SERVO_ASSEMBLY.md).

## Servo profile and geometry

`servo_profile.json` owns the reported 300–3000 µs pulse span, provisional
11.111111 µs/degree mapping and screw-aware internal linkage region. The existing
mounting marks are preserved at shoulder 0°, carrier +1.17° and crank −40.41°.
Their new non-inverted mounting references are respectively **1650, 856 and
723 µs**. Carrier and crank use different references because their useful windows
have different centers. Their individual angular midpoints cannot be assembled
together: that combination does not close the four-bar.

The region includes 4 mm × 1.5 mm shaft screw heads and captured linkage geometry
on all four legs. It is an offline authoring reference; no new runtime collision
limiter is introduced. Startup and transitions retain their existing four-bar
closure and speed policies. Physical shaft travel, installed directions and loaded
tracking remain unqualified. Body Control owns the saved per-joint mapping;
firmware defaults preserve existing NVS calibration. Remounting and calibration
are deliberate operations, rather than automatic replacements.

`geometry.json` owns the 40/24/38/24 mm four-bar, 55 mm distal link, recorded CAD
frames and current complete sole hulls. Model coordinates remain signed CAD
centidegrees. Geometric zero, solved Stand, calibration Home, Sit and Rest are
separate poses. Electrical conversion belongs to the device's measured per-joint
mapping; changing calibration never stretches or clamps a motion to fit.

The 2026-09-29 visible Wireless assembly measures 173.434 mm between front and
rear shoulder axes and 63.500 mm between left and right axes (previously
152.700 × 48.200 mm). Rear animation pivots were reconciled to the assembled
parts without moving their visible meshes. Legacy motion excursions use their
original coordinate scale; changed foot placements are translated into the new
footprint instead of stretching whole gestures.

Model IDs 0–2/3–5 are physical rear-left/rear-right (CAD FL/FR), and 6–8/9–11
are front-left/front-right (CAD RL/RR). Each triple is shoulder, carrier, crank.
`model.json` preserves recorded channel assignments; assembly must verify them.

## Walking controls

As of P4 0.8.56, every semantic gait command uses fast coordinated strokes:
Walk, Run, Crawl, Crab, turns, steering and transitions. Each small path segment
is timed by its largest joint-angle change at the nominal 545.45 deg/s reference.
Other joints follow the same clock to preserve linkage coordination. This is a
commanded rate, not measured shaft speed, motor duty or torque.

Speed selects stride distance. Walk/Crawl/Crab use stride=s% for 1–100;
zero requests Finish. Walk above 100 blends into bounding Run, reaching its full
stroke at 200. Direct stride selects 1–100% of the chosen gait's envelope.
Shorter strokes take less time. The legacy `rate` field (0.25–3) remains accepted
for wire compatibility but no longer changes semantic gait timing. Body Control
therefore offers direct stride without a cadence field. The low-level
`gait_begin` API retains reference-time sampling for offline geometry authoring.

Full Walk uses a **61.945 mm planted sweep** (30.973 mm at 50%), authored
around the owner's reindexed crank endpoints: left **1600–2800 µs**, Home
2800 µs; mirrored right **500–1700 µs**, Home 500 µs. The nominal 1200 µs span
is 108 degrees at the retained scale. The carrier calibration is unchanged.
This profile uses the original 35/20/28/38/55 mm linkage, fixed shafts and bare
Part027 floor contact. Its reference foot offsets are about -54.01 to +7.93 mm,
instead of the rejected 88 mm profile's -26.3 to +61.7 mm. Those offsets exclude
body support sway; they are not distances from a measured center of mass.

Body height varies with separate forward and backward coefficients. Foot lift
spans 6–10 mm across Speed 1–100. The contact fraction remains 78%; quarter-cycle
footfall offsets retain three or four planned contacts. Support sway retains
5 mm lateral and 4 mm fore/aft amplitude, with no mean forward body shift.
The fast angular-distance clock emits swing apices and full-stroke crank
reversal landmarks as output frames, then continues on the next normal tick.
It adds no dwell or pulse clamp. Previously internal integration could pass
through a mathematical endpoint without sending it to the servo.

Curved Walk still shares stroke between translation and yaw. Run remains a
front/rear bound, and named gesture paths are unchanged. Hardware mounting
changes affect their electrical mapping too; unchanged path source is not a
physical qualification of those motions after reindexing.

**Mounting reference:** the new crank Home model angle is provisionally
**-117.68 degrees**, reconstructed from the owner's photo of the rear-left
carrier and crank at 2800 µs. This is not a measured shaft angle. The other
cranks are assumed mounted in corresponding mirrored physical poses. Reusing
the old -40.41-degree Home association after moving the horn would misregister
the geometry. Firmware compilation does not overwrite the device's saved
Home, model angle, inversion or scale. The reindexed profile and matching
calibration must be deployed together; carrier settings remain unchanged.

Offline checks retain the existing 400–2900 µs review window and linkage
criteria. Additional tests assert the owner-defined crank endpoints in emitted
25/50/100 Hz frames; they are tests, not runtime stops or restrictions.
Physical tracking, traction, load capacity and photo-reference accuracy remain
unverified. See the [gait research journal](../../../../docs/v2-12servo/GAIT_RESEARCH_JOURNAL.md).

The saved joint-speed setting still applies to posture/clip timing and balance
corrections; semantic gaits use the fast-stroke reference regardless of this
setting. `clock_scale` reports reference time divided by elapsed wall time;
`speed_flagged` remains false. Requested/commanded cadence telemetry follows the
angular-distance schedule. Walk changes stride across two cycles to coordinate
previously planted feet with the longer stroke. It retains its
Run-style constant-velocity foot return with short endpoint ramps. Crab stride
changes use its existing two-cycle anchor-establishment profile so previously
planted wide feet remain compatible with the changing travel distance. Joint
movement keeps the fast clock during that transition.

The historical forward=100, turn=100, Speed 50 → 89 → 145 failure is now an
explicit native regression at 50 and 100 Hz, including Finish. This checks the
planner and mapped pulses; loaded physical execution still requires a trial.

Crawl/Crab use stride=s% across the whole slider. Crawl uses a
−5 mm body reference, centered 32 mm sweep and 5–8 mm lift, with 78% stance.
Both use the installed bare Part027 contact shape, a broad swing arch, prompt
horizontal foot return and direction-specific body weight transfer. Full Walk
turns retain 8.73 degrees per cycle; Crawl turns retain 10 degrees.

The native `crawl_calibration` regression covers Crawl's four and Crab's six
directions with the production pulse mapper, entry, speed changes and Finish,
advanced rate extremes and 10/20/40 ms output intervals. Its 400–2900 µs review
window is an offline regression check, not a runtime pulse clamp or measured
collision boundary. Physical tracking remains unmeasured.

`walk_controls_v2` negotiates directions `fwd`, `back`, `turn_l`, `turn_r`,
`gait: "walk"|"crawl"` and `steps: 0` for ongoing operation. Finite steps 1–10
remain supported. Existing `walk_controls_v1` clients retain forward finite Walk.
The gateway requires the appropriate model, feature and declared command.

```json
{"t":"intent","name":"walk","dir":"back","gait":"walk","steps":0,"speed":25,"seq":41}
{"t":"intent","name":"walk","dir":"back","gait":"walk","steps":0,"stride":100,"rate":2,"update":41,"seq":42}
{"t":"intent","name":"walk","dir":"back","gait":"walk","steps":0,"speed":0,"update":41,"seq":43}
```

Updates name the original command and preserve direction, gait, phase and cycle
count. Their ACK completes the settings request; the original command owns motion
completion. Updates coalesce while a transition is active. Finish reduces stride
and completes active swings with all feet down. Emergency detach remains separate.
A planted foot's world XY stays fixed until lift-off. Swing endpoints are fixed at
lift-off. A reversed clock is invalid. Scheduling gaps do not stop the gait:
the planner integrates to the current time and emits one current frame, without
replaying missed PWM writes.

The dashboard supplies Speed, advanced stride/cadence, direction and ongoing mode.
Environment actions accept continuous walk/backward/left/right and crawl with an
explicit direction. Bare V2 left/right now select ongoing gait turns; Speed,
stride/cadence and Finish use the existing walking controls. Explicit `units`
select finite gait cycles, not a promised heading angle. V1 bare left/right
retain their original 45° clips.

## Automatic Run above 100%

With `run_gait_v1` and the declared `run` command, the normal Walk Speed range
extends to 200%. **0 finishes, 1–100 walks, above 100 transitions to Run.**
Returning to 100 or below transitions back to Walk within the same command.
Crawl stays 0–100. The current leverage revision and its offline checks are recorded in [CONTROLLER_VALIDATION.md](CONTROLLER_VALIDATION.md).

Run retains the front-pair/rear-pair bound: 42% stance per pair, half a cycle
apart, with flight intervals. It now uses the installed bare-Part027 linkage's
+5 mm body reference, a centered 37–44 mm forward planted sweep,
5–12 mm lift and unchanged foot lanes. Scripted body bob and pitch are zero.
This removes the previous low, forward-reaching Run posture; physical loaded
bounding remains unqualified.

Automatic Speed above 100 progressively opens the sweep from 37 mm to 44 mm
at 200%. Run's 1.2-second period parameterizes its reference path; angular
travel sets the actual cadence. At full Run the 50 Hz offline sample measures
about 3.57 cycles/s.
Backward Run and turns also use the upright body target and centered 44 mm
maximum sweep. No gait-speed reduction or servo calibration change is added.

The existing six-cycle Walk/Run interpolation solves touchdown and liftoff on
the changing leg schedule, retaining planted anchors and committed landings.
Stride changes interpolate over three cycles, or the active six-cycle blend.
Finish retains its coordinated landing behavior. See the Run configuration and
gait research journal for current verification; archived animations remain
historical references.

Direct `gait:"run"` accepts stride 1–100; the legacy rate field does not slow
strokes. Explicit Run Speed 1–100 opens its initial 37 mm stroke proportionally;
100–200 opens it to 44 mm. Zero still finishes.
The usual dashboard choice is Walk / automatic Run. Only capable V2 bodies
receive the extended slider; V1 retains its original `run` asset.

[Run configuration, research and validation](motions/run/README.md) includes the
native Walk 100 > Run 150 > Run 200 > Walk 75 > Finish demonstration. Bounding is
currently a kinematic reference: no measured ground-force/contact or attitude
feedback proves airborne stability or servo tracking. No servo reference or
original motion has been changed to accommodate it.

## Wide-stance Crab

`crab_gait_v1` adds `gait:"crab"` and sideways directions `side_l`/`side_r`.
Forward, backward and turning reuse `fwd`, `back`, `turn_l`, `turn_r`.
Semantic commands are `crab` (left), `crab_right`, `crab_forward`,
`crab_backward`, `crab_turn_left`, `crab_turn_right`. V1 retains its finite Crab.

The existing phase planner and direct linkage controller own Crab. Entry uses
its three-second reference path, retimed by angular travel, to place feet sequentially at a 160 mm stance width and body translation
−12 mm. A startup ramp of two cycles (three backward) establishes the wide
stance anchors. The quarter-cycle wave schedule has 80% stance and three or
four scheduled contacts. Full stride travels 50 mm per cycle forward/backward,
40 mm sideways, or the retained 32.73 degrees while turning. Lift is 8–14 mm.
The 2.4 s base period parameterizes the reference path. Speed 25/50/100
selects 25%/50%/100% stride; angular travel sets cycle duration.
The centered-COM load estimate still gives negative support margin during
full turns, so kinematic validation must not be read as loaded stability proof.
Direct stride 1–100 remains available. Crab Speed is 0–100;
it never blends into Run. Finish settles the feet and holds the wide stance.
Finish before selecting a different direction or gait; Stand uses normal entry.
`motions/locomotion/crab.json` owns the parameters. No per-direction runtime
recordings or additional solver are compiled. Generate development recordings
with `tools/generate_locomotion.py --cli <v2_walk_command> --crab-only`.

## Finite motions and entry

The runtime catalog contains 23 gestures/postures. The eight fixed-angle turns
(left/right 15°, 45°, 90°, 180°) have been removed from V2 firmware; Body Control
uses the declared catalog and gait turning instead. The remaining motions include
Lay Down, Crouch and experimental Upright. [The gesture README](motions/gestures/README.md) records command durations.
Nod has two cycles. Wave reproduces Sit before extending and waving. Bow reaches
both hands forward about 73.42 mm. Point reaches about 95.02 mm. Sit lays the rear lower legs along the floor; Rest lays all lower legs horizontal and grounds the current structural chassis supports.

`retarget_clips.py` preserves legacy-derived task-space choreography. Reviewed Worm,
Shrug, Play Dead and Lay Down use `remap_reviewed_clips.py` for translated support
anchors and necessary floor corrections, retaining their recorded timing,
rotations and phases. `import_reviewed_clips.py` then preserves the adapted keys. Sources and dependent hashes are
regenerated together. The compiler checks provenance and preserves the original cubic tracks. Mechanical and reference-span conflicts are listed in `mechanics/original-motion-range-audit.json`; they are not corrected by changing the motion.

P4 entry uses a known commanded reference and a coordinated path through the
carrier/crank closure region. Conservative continuous path bounds are checked against PWM timer capacity before replacing a motion; entry pulse change is bounded to 1000 µs/s at 1×. Increased entry rates also use the 125% flag threshold and retime to rated shaft speed when exceeded.
A new motion request with outputs off or only partly commanded first engages
the saved Home pulses 200 ms apart, then enters the requested motion. Invalid
model references are reported before enabling outputs. This is commanded state,
not shaft feedback. Entry checks do
not establish floor clearance or support stability for arbitrary physical poses.

`joint_mapping` stores the current body_calibration_v2 mapping without Min/Max fields. Review and Save is required before normal motion. Hardware qualification is
still false: shaft travel, direction, horn placement, tracking, dynamics and
loaded operation require physical measurement. The compact controller has been
application-flashed and tested with two unloaded servos before the expressive-motion/Crab revision. That revision is built and tested offline, not flashed; the evidence is
in [Controller validation](CONTROLLER_VALIDATION.md). Earlier deployment evidence
in `docs/v2-12servo/FIRMWARE_DESIGN.md` belongs to previous applications.

`upright` is a separate declared V2 emote: Sit → front feet backward → supported
push → a 60° rear-leg rise over the flat rear lower legs. It holds the terminal
pose after 22 seconds; `stand` still means four feet. Physical balance, torque
and a safe recovery transition remain unqualified. [Upright](motions/gestures/upright/README.md).

## Runtime representation

Stationary Stand feedback uses sustained IMU roll/pitch leveling: measured
attitude error drives the change in the accepted body-angle offset, with gyro
rate damping. At zero error the achieved offset is retained. A persistent
nose-up error therefore continues extending the modeled rear supports instead
of settling at the former 40%-of-error offset. This mode runs only during
stationary balance hold; rise, posture entry and walking retain their existing
trajectory-relative feedback. Stop retains its commanded-pose hold semantics.

Body Control exposes a saved Self-leveling On/Off setting on P4 firmware with
`balance_control_v1`. Off smoothly removes feedback while preserving the current
motion and enabled outputs; On resumes correction during an existing Stand hold
or supported gait. This setting does not issue Stand or override Stop/gestures.
Firmware with `balance_tuning_v1` also exposes saved strength/damping multipliers
(default 1×) and roll/pitch target offsets (default 0°). Positive UI pitch raises
the nose; positive roll raises the left side. Both stationary and moving feedback
use the same multipliers on their respective existing gains. Saves preserve
accepted correction and motion state; zero gains do not erase a held offset.

The existing linkage-fit and joint-speed criteria reduce the next standing
increment rather than erase an achieved offset. Only accepted increments enter
the controller state; an unreachable demand does not build up for later release.
Unavailable IMU data keeps the existing fade back toward the nominal pose.
These are commanded positions, not measured servo angles, contact or torque.

The P4 contains one motion implementation. Direct single-precision linkage
geometry replaces the numerical search; a maximum of four endpoint evaluations
per leg resolves the rocking sole. Unreachable circles and changes of linkage
branch are rejected. The 92-vertex Walk/Crawl support profiles are certified
against every original hull vertex with an all-orientation distance bound below
0.15 mm. A 0.151 mm conservative allowance preserves floor clearance. Full CAD
meshes and research fitting remain desktop inputs and are not linked into firmware.

Finite gestures retain their original workstation recordings. Historical fixed-angle
turn recordings remain desktop references only and are excluded from the build. The
compiler fits cubic segments with a continuous 0.005-degree error bound, keeps
extrema/holds/endpoints and timing, and emits compact positions, tangents and
extrema. No alternate dense runtime playback remains. The output owner retains
the actual commanded joint pose; only manually requested PWM is interpreted back
through the saved mapping, without polygon projection or invented shaft feedback.

Run Finish waits for already committed airborne landings before decelerating.
This corrects an existing explicit-Run failure after speed changes without
reducing gait reach. [Controller validation and resource costs](CONTROLLER_VALIDATION.md)
records source checks, P4 measurements and limitations. Native test assertions
remain enabled in Release builds.

## Owners and regeneration

- `motion.c` and `walk_kinematics.c`: bounded native gait clock, circle-intersection controller and compact sole support.
- `transition.c`: entry paths through the direct linkage's closure region.
- `joint_limits.c` and `servo_profile.json`: calibration reference metadata; historical collision-envelope data remains desktop-only.
- `clip.c` and `tools/compile_clips.py`: verified compact interpolation segments and one cubic sampler.
- `motions/walk/reference.py`: independent Python geometry and stride/rate reference.
- `motions/gestures/*/posture.json`: measured Sit/Rest/Wave/Point/Bow pose constraints.
- `tools/generate_assembly_reference.py`: reproducible guide, twelve-joint CSV and mounting range audit.
- `tools/audit_mounting_ranges.py`: sampled original motion ranges, pulse windows and remaining conflicts.
- `tools/plot_mounting_reference.py`: reference SVG using NumPy/Matplotlib.
- `tools/refresh_blender_motions.py`: refresh existing chapters in place.
- `tools/validate_blender_scene.py`: reopen proof (`-- --report /tmp/report.json`).

Run these commands from the repository root:

For the native test suite alone, use an isolated host environment and pass its
interpreter explicitly to CMake. This avoids selecting another Python on PATH
that cannot run the geometry tests. These tests and dependencies run on the
desktop; none are linked into the P4 firmware. The tests preserve the restored
motion library. Modeled mechanical-envelope conflicts are reported separately
from source parity and geometric correctness; they do not remap or block motions.

```sh
python3 -m venv build/native-tests-venv
build/native-tests-venv/bin/python -m pip install -r Slave/software/models/v2-12servo/requirements-test.txt
cmake -S Slave/firmware/esp32p4-wifi6/tests -B build/native-tests \
  -DCMAKE_BUILD_TYPE=Release \
  -DPython3_EXECUTABLE="$PWD/build/native-tests-venv/bin/python"
cmake --build build/native-tests -j4
/usr/bin/ctest --test-dir build/native-tests --output-on-failure
```

The commands below regenerate source assets and are a separate workflow from
running tests against the existing motion library:

```sh
python3 Slave/software/models/v2-12servo/tools/build_sole_profile.py
python3 Slave/software/models/v2-12servo/tools/generate_walk.py
python3 Slave/software/models/v2-12servo/tools/retarget_clips.py --source-repo .
cmake -S Slave/firmware/esp32p4-wifi6/tests -B /tmp/ainekio-v2-tests
cmake --build /tmp/ainekio-v2-tests -j4
python3 Slave/software/models/v2-12servo/tools/generate_locomotion.py --cli /tmp/ainekio-v2-tests/v2_model/v2_walk_command
cmake --build /tmp/ainekio-v2-tests -j4
/usr/bin/ctest --test-dir /tmp/ainekio-v2-tests --output-on-failure
python3 Slave/software/models/v2-12servo/tools/validate_motions.py
python3 Slave/software/models/v2-12servo/tools/validate_locomotion.py
python3 Slave/software/models/v2-12servo/tools/validate_walk.py /tmp/ainekio-v2-tests/v2_model/v2_walk_command
python3 Slave/software/models/v2-12servo/tools/validate_compact_clips.py --binary /tmp/ainekio-v2-tests/v2_model/v2_clip_sample
```

Changes to Crouch configuration require a bootstrap gait-only build before clip
compilation if old Crouch assets no longer satisfy provenance or source provenance.
Generated sources invalidate old Blender evidence. Refresh and reopen the exact
active `ainekio-variable-gait-Recovery.blend` before claiming current preview proof.
The motion scene has 39 chapters, including the stride/rate ramp and eight native
locomotion demonstrations. Its presentation cuts are not actuator transitions.
The cached face and editable fitting sources are retained separately.

Native tests cover source parity, interpolation, calibration mapping, transition
bounds, output lifecycle, updates, Stop, and 48 locomotion profiles at four update
intervals. Validation reports distinguish geometry, source/build and saved Blender
checks from unmeasured physical behavior. Firmware console `gait` queries calculate
poses without PWM, for example `gait walk 3 5000 25` and `gait bow 2500`.

Current verification counts, application hash and bench limitations are in
[Controller validation](CONTROLLER_VALIDATION.md). The locomotion generator
regression runs with NumPy/SciPy in the CMake-selected Python interpreter;
CTest explicitly skips that desktop geometry check when those packages are absent.
