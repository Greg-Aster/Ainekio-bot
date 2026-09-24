# Twelve-servo motion model

V2 uses a shared measured linkage, direct closure checks, finite gestures
and continuous Walk/Run/Crawl/Crab. The eight-servo V1 assets and default decoder retain
their existing behavior. Assembly references and calibration are documented in
[SERVO_ASSEMBLY.md](SERVO_ASSEMBLY.md).

## Servo profile and geometry

`servo_profile.json` owns the observed 300–2900 µs pulse span, 1300 µs selected reference,
provisional 234° conversion and mounting offsets. Its historical angle-envelope
data remains a desktop research reference and is not compiled into the firmware.
234° is not measured shaft travel. The recommended model offsets at 1300 µs are
shoulder 0°, Part 006 carrier +1.17°, and Part 005 crank −40.41°. These non-inverted
references balance the original library's combined leg-joint ranges; the motion
and gait trajectories are unchanged. Existing saved mappings require deliberate
re-indexing and calibration rather than automatic replacement. Startup and transitions use the same actual four-bar closure as locomotion.
Carrier/crank entry follows normalized coordinates inside the exact closure
annulus, with bounded interval arithmetic for path extrema and rates. Shoulder/body and full-robot collision sweeps remain
unqualified. The reproducible mesh sweep is in `tools/build_mechanical_envelope.py`.

`geometry.json` owns the 40/24/38/24 mm four-bar, 55 mm distal link, recorded CAD
frames and current complete sole hulls. Model coordinates remain signed CAD
centidegrees. Geometric zero, solved Stand, calibration Home, Sit and Rest are
separate poses. Electrical conversion belongs to the device's measured per-joint
mapping; changing calibration never stretches or clamps a motion to fit.

Model IDs 0–2/3–5 are physical rear-left/rear-right (CAD FL/FR), and 6–8/9–11
are front-left/front-right (CAD RL/RR). Each triple is shoulder, carrier, crank.
`model.json` preserves recorded channel assignments; assembly must verify them.

## Walking controls

Normal Speed coordinates stride and cadence. Advanced controls remain independent.
For Walk/Crawl Speed 0<s<=100, stride=min(100,2*s)% and cadence=max(1,s/50). Speed zero requests
Finish. The base period is 1.8 seconds; advanced cadence supports 0.25–3×.

| Speed | Stride | Cadence | Steady cycle |
| --- | --- | --- | --- |
| 25% | 50% | 1× | 1.8 s |
| 50% | 100% | 1× | 1.8 s |
| 75% | 100% | 1.5× | 1.2 s |
| 100% | 100% | 2× | 0.9 s |

Walk's full planted sweep is 92 mm, with 30 mm rearward bias and up to 14 mm lift.
Sweep and bias scale with stride. Nominal advance is `92*stride/100/0.70` mm per
cycle; this is geometric translation, not measured ground distance. The original choreography is preserved; modeled collision conflicts are reported separately. Sway, bob, roll and
pitch remain continuous and scale with stride. Cadence changes the common clock.

Crouch/Crawl use body translation -35 mm, leaving about 12 mm of complete-body
floor clearance. Crawl's full sweep is 18 mm, 4 mm rear bias and
4 mm maximum lift. Lower legs remain inclined; Rest is the separate grounded
chassis pose. Turns advance 18° per full-stride Walk cycle or 10° per Crawl cycle.
`motions/locomotion/config.json` owns these low-height and turning settings.

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
Crawl stays 0–100. Existing Walk/Crawl formulas, geometry and recordings are unchanged.

Run is a front-pair/rear-pair bound: 42% stance per pair, half a cycle apart,
with two brief flight intervals. Body pitch replaces the walking side sway.
Forward Run opens its planted sweep from 80 mm just above 100% Speed to 104 mm
at 200%, with 10 mm rear bias at full stride and up to 22 mm lift. At full stride
the shorter stance fraction advances 247.62 mm per cycle, versus Walk's
131.43 mm; this is modeled translation, not measured speed. Backward Run and
turns retain an 80 mm sweep with 20 mm bias. Run's 1.2 s base period uses
automatic rate `2+(Speed-100)/150`, giving about 0.6 s just above 100%, 0.514 s
at 150%, and 0.45 s at 200%. Forward Run uses direct linkage geometry and the existing
horn indexing without changing servo references or imposing new pulse caps.
At full forward Run, front feet land 8 mm inward and rear feet 8 mm outward;
a 6° nose-up bias preserves reach. Lanes blend through swing while stance feet
remain planted. This separates the crossing lower legs without retiming pairs.

The transition takes four gait cycles with smooth body/contact changes. Feet
already in stance keep their world anchors. Cyclic offsets advance the next
step to form or separate pairs; active swings keep their landing targets.
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
−18 mm. Three feet support each swing. Full stride travels 48 mm per cycle
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
both hands forward about 73.42 mm. Point reaches about 95.02 mm. Sit lays the rear lower legs along the floor; Rest lays all lower legs horizontal and grounds the chassis base plate.

`retarget_clips.py` preserves legacy-derived task-space choreography. Reviewed Worm, Shrug, Play Dead and Lay Down recordings regenerate through `import_reviewed_clips.py` without changing their joint paths. Sources and dependent hashes are
regenerated together. The compiler checks provenance and preserves the original cubic tracks. Mechanical and reference-span conflicts are listed in `mechanics/original-motion-range-audit.json`; they are not corrected by changing the motion.

P4 entry uses a known commanded reference and a coordinated path through the
carrier/crank closure region. Conservative continuous path bounds are checked against PWM timer capacity before replacing a motion; entry pulse change is bounded to 1000 µs/s.
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
branch are rejected. The 101/90-vertex Walk/Crawl support profiles are certified
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

From the repository root, with NumPy/SciPy available for geometry tools:

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
