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

Normal Speed coordinates stride and cadence. Advanced controls remain independent.
For Walk Speed 0<s<=100, normalized stride=s% and cadence=1+s/100.
Both increase throughout the slider. Speed zero requests Finish. The base period
is 1.8 seconds; advanced cadence supports 0.25–3×.

| Speed | Stride | Requested cadence | Requested cycle |
| --- | --- | --- | --- |
| 25% | 25% | 1.25× | 1.44 s |
| 50% | 50% | 1.5× | 1.2 s |
| 75% | 75% | 1.75× | 1.03 s |
| 100% | 100% | 2× | 0.9 s |

Full Walk uses a **96 mm planted foot sweep**, centered **8 mm forward** of
its reference stance: touchdown +56 mm and stance end -40 mm. This is 2.15 times
the previous 44.62 mm sweep. Automatic, independent and default Walk commands
use the same full stroke; 50% gives a 48 mm sweep. Configuration lives in
`motions/locomotion/config.json`. The original stateless geometry sampler remains
available for comparison with the archived reference; it is not the runtime gait.

The body reference stays -8 mm. Full-Walk lift remains 8.85 mm, sway 1.2125 mm,
bob 0.7275 mm, roll 1.455 degrees and pitch 0.97 degrees. The wider fore/aft path
uses the crank and carrier together without changing saved Home references.
With the saved mirrored calibration (carrier Home 856/2444 µs, crank Home
723/2577 µs, 11.111111 µs/degree), steady forward Walk commands approximately
409–2891 µs across all joints. Entry, speed changes and Finish are checked
against 400–2900 µs in host regression tests. These are calculated commands;
servo recalibration changes the pulse envelope, and loaded tracking is unmeasured.

The saved user-selected joint-speed limit retimes the whole gait when a frame
would exceed that limit. Body motion, swings, planted anchors and transitions
share the same clock; stride is retained. Cadence recovers at 0.5 clock fraction
per second. Walk amplitude/rate changes use two gait cycles of interpolation;
backward entry retains three. This establishes each foot's new landing while
preserving planted contacts. Cadence requests still rise from 1x to 2x across
0–100% Speed; advanced rate remains 0.25–3x.

Crawl/Crab retain stride=min(100,2*s)% and cadence=max(1,s/50). Crawl uses a
-22 mm body reference, 18 mm sweep, 4 mm rear bias and up to 4 mm lift. Full Walk
turns retain the previous 8.73 degrees per cycle; Crawl turns use 10 degrees.
Run retains its separate amplitude profile above 100%.

Crawl's body reference was raised from -35 to -22 mm to fit the mounted servo
calibration while retaining its full sweep, lift, turning angle and speed mapping.
The native `crawl_calibration` regression checks the production pulse mapper
against 400–2900 µs in all four directions, through entry, speed changes and
Finish, including advanced rate extremes and 10/20/40 ms output intervals.
This is calculated motion with the saved mounting profile and 1000°/s joint
limit; physical tracking remains unmeasured. No pulse clamp is added.

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
lift-off. A reversed clock or output gap over 40 ms faults instead of replaying work.

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

Run is a front-pair/rear-pair bound: 42% stance per pair, half a cycle apart,
with two brief flight intervals. Body pitch replaces the walking side sway.
Forward Run opens its planted sweep from 80 mm just above 100% Speed to 96 mm
at 200%, biased 8 mm forward at full stride, with up to 14 mm lift. At full
stride the shorter stance fraction advances 228.57 mm per cycle, versus Walk's
131.43 mm; this is modeled translation, not measured speed. Backward Run and
turns use an 80 mm maximum sweep with the same forward bias. Run's 1.2 s base
period uses automatic rate `2+(Speed-100)/150`, requesting about 0.6 s just above
100%, 0.514 s at 150%, and 0.45 s at 200%. The joint-speed budget can lengthen
these periods without shrinking the planned stride.

Forward Run uses a -8 mm body reference, 3 mm bob and 5.5° pitch oscillation
phased a quarter cycle ahead of the former sine profile to coordinate with the
paired stance. Backward Run and turns use a -4 mm body reference and 4° pitch.
At full forward Run, front feet land 8 mm inward and rear feet 8 mm outward.
The horizontal swing return uses smooth velocity ramps over its first and last
5%, with constant velocity between them; this avoids carrying the foot beyond
the reachable fore/aft path during the long flight. Vertical lift remains smooth.
Servo references and the shared joint-speed control are unchanged; no pulse
clamp is added.

The transition takes six gait cycles with smooth body/contact changes. Feet
already in stance keep their world anchors. Cyclic offsets advance the next
step to form or separate pairs; active swings keep their landing targets.
Run stride changes interpolate over three cycles, or the full six-cycle blend
while changing gait. Finish also uses three cycles and reduces lift for newly
planned swings as travel decelerates. Direct automatic-Run startup uses six cycles.
The common clock, command sequence, controlled Finish and emergency stop remain shared.

Advanced `gait:"run"` accepts stride 1–100 and rate 0.25–3 independently;
its optional explicit-gait Speed uses rate `max(2/3,Speed/75)` (0 still finishes).
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

The existing phase planner and direct linkage controller own Crab. A three-second
entry places feet sequentially at a 190 mm stance width and body translation
−22 mm. A startup ramp of two cycles (three backward) establishes the wide stance anchors without overextending the initially planted inside leg. Three feet support each swing. Full stride travels 48 mm per cycle
forward/backward, 32 mm sideways, or 32.73 degrees while turning, matching the
steady travel of the reviewed Blender drafts. Lift is up to 12 mm. The base
period is 2.4 s; Speed 25/50/100 gives 50%/100%/100% stride and 1x/1x/2x cadence.
Advanced stride 1–100 and cadence 0.25–3x remain available. Crab Speed is 0–100;
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
push → vertical chassis over the flat rear lower legs. It holds the terminal
pose after 22 seconds; `stand` still means four feet. Physical balance, torque
and a safe recovery transition remain unqualified. [Upright](motions/gestures/upright/README.md).

## Runtime representation

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
