# Centered motion revision, 2026-10-02

The current source uses the screw-aware coupled linkage region and separate
mounting references: shoulder1650 µs, carrier856 µs, crank723 µs at the retained
CAD mounting marks. The conversion remains provisional; existing device NVS
calibration is preserved. There is no new runtime collision limiter.

Full steady Walk sweep is97.7 mm and forward Run sweep104 mm. Walk↔Run uses a
continuous eight-cycle morph. Landing prediction includes the changing future
contact duration, and rephasing swing paths follow the body while retaining
committed touchdown targets and planted anchors. Normal stride changes also
respect committed contacts. No automatic all-feet pause is inserted.

Current validation covers28 model/core tests and9 firmware/IMU host tests, all
passing. It includes4,155,048 sampled leg-pose checks for threshold/stride/rate
changes and435,945 interpolation breakpoint checks on long transitions. The23
finite motions pass124,124 authored joint poses and conservative interpolation
proof against the internal linkage region. All16 native locomotion recordings
pass159,104 leg poses, along with FK, sole and closure checks.

The final Run recording contains4024 samples. A separate actual-mesh BVH check
found no intersections in148 selected robot poses /592 leg poses, including
critical interpolation midpoints, all four captured leg assemblies and the
modeled4 mm×1.5 mm shaft screw heads. This is sampled internal-linkage evidence,
not complete-body, cable, loaded-servo or physical running qualification.

Upright now retains four-foot support while leveling and shifting rearward,
then withdraws the front pair after the modeled COM reaches the rear support.
Minimum provisional support margin after its Sit prefix is1.563 mm. Other
expressive motions retain existing support/floor limitations; mass distribution
and dynamic balance are unmeasured.

Source/build validation does not flash firmware, write calibration or command
the physical robot. Blender preview parity is a separate check. The dated
sections below are historical and describe earlier source/deployments.

# Compact controller validation

The preceding controller replacement was built and application-flashed as `0.7.0-p4-compact-motion`.
The measurements below distinguish compiled resources, desktop geometry and
hardware observations under the operating conditions stated in each section.

## Saved named-motion speed, 2026-09-25

Body Control provides one shared **Motion speed (×)** for Stand, Sit and finite
named gestures, defaulting to 2×. The input accepts arbitrary positive numeric
multipliers without an application-imposed minimum, maximum or fixed increment.
Editing affects the next named motion; Save on robot retains the value across
restarts, and Read from robot confirms the stored value. Saving stops outputs
through the existing owner; starting a subsequent motion resumes operation.

A single-precision multiplier directly scales the existing entry and clip clocks.
The unrequested 0.25–3× checks, integer thousandths conversion and unused twelve-
joint derivative-rescaling loop were removed. There is one rate representation
from command decoding through playback and the separate four-byte `motion_rate`
NVS record. Missing/unreadable settings use the 2× default. Only numeric validity
is checked for the multiplier; no new motion/output restrictions were introduced.
No new queue, motion assets, runtime module, allocation or servo-loop storage
write was added. Calibration, motion paths, V1, startup Home and gait controls
retain their existing behavior.

Matched ESP-IDF 5.5.4 builds with unchanged SDK configuration:

| Resource | Before feature | Final | Change |
| --- | ---: | ---: | ---: |
| Application binary | 2,369,408 B | 2,370,848 B | +1,440 B |
| Flash code | 1,322,926 B | 1,324,126 B | +1,200 B |
| Flash read-only data | 931,000 B | 931,176 B | +176 B |
| Static RAM data + BSS | 39,260 B | 39,324 B | +64 B |
| Total occupied internal RAM, including code | 138,494 B | 138,558 B | +64 B |

The final image is 400 bytes smaller than the initial capped implementation;
static RAM is unchanged from it. The existing depth-one body request queue adds
8 bytes of payload versus the pre-feature firmware. No additional queue exists.

All 30 native/desktop tests pass with Release assertions enabled and no skips.
Production-controller tests cover every one of the 23 clips at 0.25×, 1×, 2×,
3×, 4×, 6×, 8× and 12×: equal choreography-time pulse outputs, scaled entry,
completion and unaffected gait timing. Config tests cover a saved value above
3×, reload, failed writes, invalid records and unchanged joint calibration.
Gateway/dashboard tests pass (27), variable-walk tests pass (42), and JavaScript
race tests pass. Isolated Chrome tests verify uncapped 6.125× entry, command,
save and readback after an actual reload, plus mobile layout and calibration UX.

Application SHA-256: `50a9092e3cde37a7c2644820f6e5082e2b5de29be79cac8f89b556fca0e9eaed`.
ELF SHA-256: `47a4d6aa94a5be7aedd90637427b9a0fd590570b3542505b4ba699963dbe3288`.

The application was flashed to the verified active `ota_0` slot at `0x20000`.
Flash digest verification passed. The first 128 KiB were byte-for-byte unchanged,
preserving bootloader, partition table, NVS, PHY and OTA selection metadata;
protected-region SHA-256: `e9b9e7fd47cc172bdc46f3a87efbc7df82c089e31a5fb49d88b7a8d947726810`.
The gateway was restarted with its existing credentials and runtime data.
The robot's pre-update speed (3×) was read and saved in the new
float representation by the deployment tool, without a firmware migration path.
All twelve saved joint mappings and inversion settings matched after flashing.
A further reboot retained the 3× setting with `saved:true` and
all twelve joint mappings unchanged. Both boots reported the matching ELF prefix.

Hardware deployment checks cover startup Home and settings operations, not
loaded high-speed gestures. Servo tracking and worst-case P4 frame timing at
higher multipliers have not been measured. Raw NVS, calibration snapshots,
credentials and boot logs are excluded from the repository.

## Gait leverage revision, 2026-09-25

The approved Walk body reference is -8 mm, 6 mm below its preceding trajectory.
The 92 mm stride, 30 mm rearward bias, 14 mm lift, sway and cadence are retained.
Named Stand and all 23 compiled gestures retain their existing poses and timing.
Calibration, electrical mapping, assembly references and V1 are unchanged.

Forward Run keeps its 104 mm maximum sweep, paired contacts and separated lanes;
body reference changes -6 to -9 mm, nose-up bias 6 to 3 degrees, and maximum lift
22 to 18 mm. Backward Run/turn body reference changes -2 to -8 mm. Those coordinated
changes preserve reach during rapid Walk/Run changes without extra solver passes.
Crab changes -18 to -22 mm and establishes its first anchors over two cycles
(three for backward, as before);
steady travel, stance width and cadence are unchanged. Crawl's -35 mm working
height, stride and lift remain; it enters from the revised walking-ready pose.

Thirty Release native/desktop tests pass with assertions enabled and no skips.
The same production body controller covers saved calibration, Home, gait entry,
Finish and return to Walk/Stand. Expanded full-CAD checks exercise all four gait
families and every direction, their own previous outputs, speed changes and Finish
at 20/40 ms. Native envelope tests also cover 10/30 ms, finite commands, rapid
threshold reversals and advanced stride/cadence extremes, including key midpoints.
Both four-bar branch signs are checked. Regression floors are 45 degrees at the
output during planned stance, 35 during swing, 20 at the crank and 3 mm remaining
extension. These are offline regression margins, not measured torque capability.

The original compact sole is unchanged. Walk/Crawl/Run retain their original
0.151 mm support allowance; the refined Crab sole has an explicitly tested extra
0.08 mm height allowance in its revised poses, replacing the prior 0.07 mm value.
Horizontal foot error and below-target rejection remain independently strict.
The compiled gesture and servo data are byte-for-byte identical to the baseline.

Matched ESP-IDF 5.5.4 builds with identical SDK configuration:

| Resource | Before | After | Change |
| --- | ---: | ---: | ---: |
| Application binary | 2,369,264 B | 2,369,408 B | +144 B |
| Flash code | 1,322,798 B | 1,322,926 B | +128 B |
| Flash read-only data | 930,984 B | 931,000 B | +16 B |
| Static RAM data + BSS | 39,260 B | 39,260 B | 0 B |
| Total occupied internal RAM, including code | 138,494 B | 138,494 B | 0 B |

The expanded full-sole command-path check covers 14,391 robot poses; maximum
horizontal foot error is 0.000070 mm. Across that sequence and its joint midpoints,
minimum output angle is 46.61 degrees in planned stance and 37.57 in swing, with
at least 3.13 mm remaining extension. The wider native envelope tests perform
9,611,184 leg checks (including repeated endpoints/midpoints), without branch
reversals. Recorded locomotion midpoint checks retain positive body clearance
and no floor penetration beyond 0.000087 mm numerical error. These are sampled
geometric checks, not a continuous-time collision or load proof.

Runtime changes are gait constants, a separate retained Stand height and the
Crab startup-ramp selection. No new solver, runtime motion table, allocation,
state field, buffer or output owner was added. Existing generated recordings and
reports were replaced in place; the new regression helper is host-only. The
old Walk-height value remains solely as the reviewed Stand/reference height.
All compiled gesture and servo tables are identical to the baseline.

Application SHA-256:
`ec8543b6e2ae8281ea4a97e68d8c348e08e10432248d0bfd6aaef41e6fe1f438`.
The full measurements and source identities are in
[`motions/locomotion/validation.json`](motions/locomotion/validation.json).

The checks above were offline. Loaded torque, slip, balance, actual speed and
whole-robot collision clearance remain unqualified. Current P4 frame timing and
dynamic RAM are not measured; earlier timing results below do not qualify this
revision. The direct geometry solver retains its four-pass bound and buffers.


### Application deployment verified 2026-09-25

The gait leverage revision above is now installed on the connected ESP32-P4
revision 1.3. The exact 2,369,408-byte application identified above was written
to the existing active `ota_0` slot at `0x20000`; flash digest verification passed.
Only the application was written. A before/after readback of `0x00000` through
`0x1ffff` was byte-for-byte identical, covering the bootloader, partition table,
saved NVS calibration, PHY data and OTA selection metadata. Other application
and LittleFS partitions were not written.

The reboot reported the matching ELF SHA-256 prefix `2aa15e298...`; the complete
build ELF SHA-256 is
`2aa15e2987eafa4912016a78f4316d4ba86e804740b804f303ee2c60a5511a70`.
The console confirmed calibration `valid=1 saved=1 dirty=0`; its Home values
were retained. The controller authenticated and output status reported ready,
armed and without a fault. This deployment allowed the normal startup Home sequence but
sent no gait commands. Boot and read-only status checks do not establish loaded
walking performance or new motion/frame timing measurements.

Startup also logged I2S disable-before-enable messages and unavailable removable
storage (`ESP_ERR_TIMEOUT`). An initial gateway connection timeout recovered before
authentication. These peripheral/transport observations were not changed or
qualified by this application deployment.

Preserved-region SHA-256 before and after:
`376036bff27f8cf83a1c58e01323976bcd9719fb80d271b3d74d65cc79e5acd8`.
Structured deployment evidence is recorded in the locomotion validation report;
raw device configuration and serial logs are excluded from the repository.

## Deployment verified 2026-09-24

The reviewed motions, continuous six-direction Crab and fixed-angle turn removal
are now application-flashed to the P4. The firmware version label remains
`0.7.0-p4-compact-motion`; this build is identified by the hashes below.

- Corrected both hello/status command buffers to derive their capacity from the
  actual base-command array. The added Crab declarations otherwise exceeded the
  former allocation by six pointers. A native address/undefined-behavior sanitizer
  check generated and encoded all 39 declarations without an overrun.
- Fresh Release build: 29 native/desktop tests passed, including Crab geometry;
  72 gateway/protocol tests passed with the native command executable and no
  skips. Dashboard motion-race tests passed after updating their select-option
  fixture and adding Crab Start/Finish/feature-negotiation coverage.
- All 23 compiled clips passed 61,919 full-sole comparison samples: maximum
  vertex difference 0.012861 mm and clearance difference 0.007843 mm.
- Application: 2,369,264 bytes; SHA-256
  `50ce294fd03d26fcc2fac66958ade6ea2d0f77bd8ef17c9fbfac927230ba0ae2`.
  The write at active OTA slot `0x20000` passed flash verification. No bootloader,
  partition table, NVS, OTA metadata or stored assets were written. Readbacks of
  `0x8000` through `0x11fff` before/after were byte-for-byte identical.
- Boot confirmed ELF SHA-256
  `94a53eaa8d18952094dc61d558adb3da9229f0219a3617bd1b642c4d832cde5d`,
  controller authentication, and the new catalog. Calibration reported valid,
  saved and clean, with carrier Home pulses 1270 and 1230 us preserved. Outputs
  were explicitly disabled after verification.

This verifies build, flash, boot and connection. It does not qualify loaded
movement or measure the new gait's P4 frame timing. One initial gateway connection
timeout recovered before authentication; the earlier transport limitation remains.
The offline sections below preserve the earlier comparison checkpoints.

## Fixed-angle turn retirement (offline)

Current V2 firmware retains 23 gestures/postures plus its existing algorithmic
gaits. Left/Right use gait turning with Speed, stride/cadence and Finish. Bare
V2 environment Left/Right and Move Left/Right now select ongoing gait turns;
explicit cycle counts remain supported. The dashboard derives its V2 buttons
from that firmware declaration. V1's six fixed turns and its bare 45° Left/Right
behavior are unchanged. Retired explicit angle commands are not silently
translated into indefinite turning.

Matched ESP-IDF 5.5.4 builds, with the same SDK configuration and dependencies:

| Resource | Before | After | Change |
| --- | ---: | ---: | ---: |
| Application binary | 2,856,544 B | 2,369,296 B | −487,248 B (17.06%) |
| Flash code | 1,322,926 B | 1,322,830 B | −96 B |
| Flash read-only data | 1,418,128 B | 930,984 B | −487,144 B |
| Static RAM data + BSS | 39,260 B | 39,260 B | 0 B |
| Total occupied internal RAM, including code | 138,494 B | 138,494 B | 0 B |

Removed from the runtime/build:

- All eight `turn_left/right_15/45/90/180` tracks: 4,948 compact knots representing
  22,088 dense reference samples, their tangents, extrema, descriptors and names.
- `load_turns()` in `tools/compile_clips.py`, the turn-source glob and catalog
  dependencies in CMake. Gesture model-order validation remains enforced.
- The turn-only phase, heading metadata/console fields, active-start metadata
  and generic per-track active-phase field. The single gesture sampler retains
  its semantic completion and terminal-hold behavior.
- The obsolete `v2_turn_source` CTest target and runtime turn branches in the
  reference/geometry comparison tools; V2-only static 15° dashboard buttons.

The remaining 4,885 knots across 23 gestures have byte-for-byte identical
generated positions, tangents, knot times and extrema. Their compression reports
are identical to the preceding build. Gait equations, full motion recordings,
calibration/mapping files and V1 sources are unchanged. Desktop turn references,
existing Blender chapters and shared full-sole provenance assets are preserved;
they are not linked into the application. The new binary contains none of the
eight retired command names. No runtime allocation or new buffer was added.

Validation:

- 29 native/desktop CTest checks pass with Release assertions enabled, including
  a production-body regression rejecting each retired clip while preserving an
  active gait, commanded pose and output ownership. The locomotion generator
  fixture includes the model file now checked by the gesture loader.
- 101 gateway/protocol/dashboard tests pass with simulated robots, including
  bare V2 Left/Right → native gait → speed update → Finish, rejection of absent
  fixed clips, and preserved V1 translation and command completion.
- An isolated headless Chrome check of the actual dashboard markup/catalog
  renderer shows no fixed turns for the new V2 declaration, all six for V1,
  and no stale fixed buttons when switching back to V2.

At this offline checkpoint, the connected board and running gateway were not
changed. Deployment is recorded above. P4 timing and dynamic RAM were not
remeasured; previous bench figures below do not qualify this application.

Application SHA-256: `00235de07057f14c2bca32b00e7f60ca5d63a5be52206d5b6abe01224287d15d`.
SDK configuration SHA-256: `6350c1e69b0e0c7b52a5c680191249f4f14f7932889930ee83c1d31035afe1b1`.

## Reviewed motions and ongoing Crab revision (offline)

Worm is the reviewed 20-second deep wave, Shrug is the 14-second seated arm
gesture, Play Dead (`dead`) holds with farther-reaching front arms, and Lay Down
(`lay_down`) preserves the previous reviewed Dead pose. Rest is unchanged.
Crab uses the existing continuous planner in six directions with Speed, advanced
stride/cadence and Finish. Saved calibration files, mapping logic, Stop, output
ownership and the V1 robot are unchanged.

- 30 native/desktop CTest checks pass with assertions enabled. The same production
  body controller covers Crawl/Crab → Finish → Walk/Stand with altered saved
  calibration and checks that calibration is unchanged.
- 100 gateway/protocol/dashboard checks pass, including actual gateway wire →
  native Crab, speed/manual updates, Finish, feature negotiation, old V2 finite
  Crab compatibility and V1 behavior. These tests use simulated robots.
- Compact clip comparison: 106,087 samples, maximum full-sole vertex difference
  0.012861 mm and clearance difference 0.007843 mm. The new recordings retain the
  Blender keys. Source/midpoint floor tolerance remains 0.25 mm; Play Dead reaches
  −0.220704 mm transiently between reviewed 30 Hz keys and is grounded at its hold.
- Crab checks use its own previous outputs, six directions, stride/rate extremes,
  speed changes and Finish. Full measured Blender hulls verify linkage closure,
  planted XY, body clearance and three-foot contact scheduling. The current sole
  refinements add less than 0.07 mm to the original compact profile allowance;
  this is explicitly bounded in `tests/test_crab_geometry.py`.

Matched ESP-IDF 5.5.4 application builds, same SDK configuration and dependencies:

| Resource | Before | After | Change |
| --- | ---: | ---: | ---: |
| Application binary | 2,870,000 B | 2,856,544 B | −13,456 B |
| Flash code | 1,319,342 B | 1,322,926 B | +3,584 B |
| Flash read-only data | 1,435,168 B | 1,418,128 B | −17,040 B |
| Static RAM data + BSS | 39,252 B | 39,260 B | +8 B |
| Total occupied internal RAM, including code | 138,486 B | 138,494 B | +8 B |

Crab adds one double for world lateral translation. Motion updates add no heap
allocation, storage I/O, media work, output owner or iterative geometry solver.
The four reviewed clips use 175/881/74/59 compact knots for Worm/Shrug/Play Dead/
Lay Down respectively. Detailed recordings and hulls remain host-only assets.

Removed: the entire superseded V2 `motions/gestures/crab/` finite asset package;
old Worm/Shrug/Dead `config.json`, `source-review.json`, and `blender-validation.json`;
their legacy retarget records and old body-flattening dispatch entries; obsolete
Dead-recovery test assumptions and stale aggregate Crab reports. Old Worm/Shrug/
Dead source/contract/schema assets are replaced in place. V1 Crab and V1 assets
remain intact. No alternate runtime motion implementation was added.

At this offline checkpoint, the revision had not been flashed. New-command worst-case
P4 calculation/frame times and dynamic heap/stack headroom are **not measured**;
the proposed 2 ms calculation / 5 ms completed-frame targets still require a
bench run. Earlier bench figures below apply to the preceding application.
Full robot collision, loaded tracking, balance and friction remain unqualified.

## Offline evidence

- 29 native/desktop checks pass from a fresh Release build with `-UNDEBUG`;
  assertions execute. The generator regression requires NumPy/SciPy and was run,
  not skipped, for this result.
- Regeneration checks produce Crouch, Run and eight directional Walk/Crawl
  recordings in a temporary workspace, then validate the new Crouch compiler
  handoff. They reject incorrect XY targets, below-target soles and excessive
  height offsets. Recorded reports separate XY accuracy from signed sole-height
  error and bind the compact sole profile used for the clearance allowance.
  The retained motion library and generated firmware data are unchanged by this
  desktop-tool correction; it does not require another device flash.
- Continuous tests reuse this controller's own previous output. Walk, Crawl,
  explicit Run, automatic Walk/Run transitions, directions, finite/ongoing
  commands, speed/stride/cadence updates and Finish run at 10/20/30/40 ms.
- 9,217 additional command-path samples checked against full original CAD soles:
  foot XY error <0.0001 mm; conservative sole-height difference 0.0181–0.1515 mm.
- Compact Walk/Crawl profiles use 101/90 vertices. Directed convex-hull distance
  checks every original vertex across all four legs and bounds every orientation:
  0.146325/0.147192 mm. Runtime allowance is 0.151 mm.
- 54,463 dense finite-motion frames become 10,010 cubic knots. Continuous fitting
  error <=0.005 degrees before float rounding; extrema, holds, endpoints and
  durations remain. 108,895 samples against the retained interpolation reference
  show <=0.012861 mm sole-vertex displacement and <=0.007843 mm clearance change.
  Derivatives are approximate metadata; physical PWM output consumes positions.
- Native-float bounded profile integration retains phase/contact timing. Against
  the preceding double calculation, the recorded Run differs by <=0.000061 mm
  at a foot target and <=0.00091 degrees at a joint; the accumulated world
  position and clock remain double precision.
- Saved calibration layout/values, servo profile, channel conventions, command
  interface and original gesture/turn source files are unchanged. V1 is unchanged.

## Removed runtime components

- Iterative multijoint IK, its 48-iteration/12-trial line search, Jacobian solve
  machinery and numerical search-angle bounds.
- Full per-leg Walk/Crawl sole arrays and recursive support trees from generated
  `walk_data.c`; only compact shared contact profiles and linkage constants remain.
- Dense 120 Hz clip arrays, per-sample tangent reconstruction and startup scans
  of all clip frames; one segment sampler and precomputed extrema replace them.
- Pulse-cell polygon clipping/projection (`ainekio_v2_quantized_reference` and
  helpers) and automatic motion-entry reconstruction from rounded pulse frames.
- The provisional shoulder/joint bounds and 187-node carrier/crank envelope,
  its binary search, polygon-based transition, and 256-double temporary path
  array. Calibration reference constants remain unchanged.
- The 24-step diagnostic geometric continuation loop.
- Obsolete support-tree/Jacobian tests and the desktop C retarget binding to the
  removed solver. Desktop retargeting uses its existing full-geometry Python model.

Deleted files are `tools/retarget_solver.c`, `tests/test_support.c` and
`tests/test_jacobian.c`. The solver, clip sampler, transition and pose ownership
changes replace their existing modules; no alternate runtime implementation is
retained. `joint_limits.c` now only exposes the existing calibration reference
metadata. Closure checks live beside the direct solver in `walk_kinematics.c`.

The same bounded 32-interval profile integration now evaluates locally normalized
polynomials on the FPU; repeated double integration and redundant constant-profile
work are removed.

Research CAD JSON/NPZ and Python references remain workstation assets. They are
not linked into the P4. There is no second runtime solver or dense fallback.

## Resource measurements

Comparable ESP-IDF 5.5.4 pre-v3 P4 builds use the same SDK configuration.

| Resource | Before | After |
| --- | ---: | ---: |
| Application image, bytes | 4,737,936 | 2,870,000 |
| Linker total, bytes | 4,736,892 | 2,868,944 |
| Gesture/turn data in flash, bytes | 2,616,212 | 986,440 |
| Gait geometry in flash, bytes | 224,655 | 2,887 |
| Solver code in flash, bytes | 11,996 | 4,894 |
| Limit/profile access code in flash, bytes | 5,178 | 92 |
| Transition code in flash, bytes | 3,616 | 3,748 |

The application image is 1,867,936 bytes smaller (39.43%). The transition
replacement grows by 132 bytes while removing its old envelope dependency.
Static data+BSS: 38,908 -> 39,252 bytes (+344 bytes for authoritative pose/mapping
and observed timing counters). Output/console task reservations remain 12 KiB
each. No allocation, storage write or media processing
was added to the servo update path.

The initial bench image exposed a stale ignored `sdkconfig`: Hosted TX/RX
queues were 20 despite the existing production defaults of 8. Before `app_main`,
the main task needed 12,800 bytes but the largest available block was 6,656.
Restoring both queues to 8 fixed boot without changing stacks, driver code or
calibration. Both reported size builds use the corrected identical configuration.
The temporary allocator diagnostic was removed.

Connected P4 baseline `0.6.9-p4-gait-timing`, 360 MHz, outputs disabled:
explicit Run at 200% max calculation 14,637 us; automatic Walk/Run at 200%
16,582 us. These console tests exclude PWM I/O; no comparable old end-to-end
frame maximum was recorded. Audio hardware and the wake model were initialized,
but wake capture was disabled. The OV5647 camera was absent and display remains
deferred; these measurements do not qualify concurrent media workloads.

Application SHA-256:
`318968b15de71695a2e2d6d09932e8f3461cfa07db8d3481a937cb89d5eef944`.
Only the active application at 0x20000 was flashed. Bootloader, partition table,
OTA metadata, calibration NVS and LittleFS were not written. Readbacks of
0x8000–0x11fff before and after have identical SHA-256
`003228c97981925461ce0d4d4560fec309ce7bb02c1ff219b078d8ee0d0afe02`.
The saved 1500-us Home mappings and the two measured pulse offsets remain;
the profile's 1300-us reference does not overwrite them.
The final read-only query confirmed all twelve saved joint mappings unchanged,
with `saved=true` and `dirty=false`.

The production Body Control path completed Crawl -> Finish -> Walk and
Crawl -> Finish -> Stand without the former envelope rejection. It also completed
ongoing Walk/Run/Crawl speed updates, automatic Walk/Run changes, advanced backward
stride/cadence changes, controlled Finish, and finite Walk/Run/Crawl in all four
directions. The same boot remained responsive through the tests.

Timing covers calculation of all twelve targets and the complete PCA9685 frame
write; only two unloaded servos were physically connected. Maxima include motion
entry, steady movement, changes of speed and controlled Finish. Request admission,
preflight and output arming are measured separately from recurring frames. The
unchanged PCA recovery sequence includes register writes/readbacks and its 500-us
oscillator delay; it is not a regular servo frame.

Final production measurements on this boot (33,365 frames, including Home and
holding):

| Measurement | Observed maximum / minimum | Target / interpretation |
| --- | ---: | --- |
| Motion calculation and mapping | 1,315 us maximum | <=2,000 us; zero over-target frames |
| Calculation through PCA frame write | 2,897 us maximum | <=5,000 us; zero over-target frames |
| Request processing, including preflight/arming | 6,596 us maximum | Separate from the recurring frame; not a <=5-ms result |
| Internal heap | 254,875 bytes free; 229,523 minimum free | Runtime observation, not static RAM size |
| Body task stack | 6,468 bytes minimum free of 12,288 | Reservation unchanged |
| Console task stack | 10,092 bytes minimum free of 12,288 | Reservation unchanged |

All 23 gestures completed consecutively through Body Control, followed by Stand
and Neutral, including the Upright-to-Stand exit. Outputs were detached afterward
and USB confirmed `armed=0`, `outstanding=0`. No reset or output timing fault was
observed. These are observed maxima, not an exhaustive execution-time proof or
qualification under future concurrent camera/audio/display loads.

The gateway had intermittent stale/disconnected intervals and fresh-clock or
stale-command admission rejections, including another reconnect after playback.
The remaining motion cases were completed
after reconnecting and issuing fresh command sequences; deadline checks were not
relaxed. USB remained responsive and the P4 did not reset. This is a remaining
transport qualification limitation, not evidence of uninterrupted system-level
operation. Do not describe the bench as a flawless full-workload endurance test.

## Behavior correction and limits

Explicit Run Finish after speed updates could request an unreachable landing in
the old implementation (100 -> 200 -> 75 -> 200 -> Finish at 8.5 seconds).
Finish now honors committed airborne landings before decelerating, as Run
transition Finish already did. Stride, reach and normal command timing stay intact.
Production body tests also cover Crawl -> Finish -> Walk/Stand in all four
directions with irregular frame intervals, retaining the commanded endpoint
and the saved calibration. Every recorded gesture endpoint, including Upright,
is tested for direct-model entry and exit; no old-envelope exclusion remains.
Circle feasibility and both linkage branches are checked; rejected geometry never
produces a partial frame or silently clamps a target.

Existing extreme gait settings can request about 100 degrees of joint change in
40 ms. This behavior was already present; no servo-rate cap or motion reduction
was introduced. Kinematic agreement does not qualify loaded tracking, collision,
traction, balance or power behavior. Future camera/display workloads are not
qualified by an audio/wake-only test.

## Reproduce

Build/run native tests via the model README. Geometry validation needs NumPy and
SciPy: `tools/build_sole_profile.py`, `tools/validate_walk.py <v2_walk_command>`,
and `tools/validate_compact_clips.py --binary <v2_clip_sample>`.
The segment compiler writes `clip/compression.json` in the build directory.
Console `controller` reports actual body calculation/frame/request maxima,
over-target counts, internal heap and body stack headroom. `gait` diagnostics
calculate positions without PWM; they are not end-to-end frame measurements.


## Entry endpoint rounding and pulse-center diagnosis (2026-09-26)

A production-body reproduction of Crab turn-left → Finish → Stand exposed
mixed-precision easing rounding above the transition domain:
`u=0.999633491039` produced `progress=1.0000000138189644`. The valid entry was
rejected as `ESP_ERR_INVALID_ARG`. The existing expression now evaluates the
nearer half of the same quintic in double and reflects the upper half. It does
not change the geometric path, loosen linkage checks or add a servo limit.
The native production `motion_frame` regression checks the failing input and
exact completion. The affected body, joint-mapping and transition tests pass.

The separate Point/Bow/Dead errors remain calibration/assembly conflicts.
With the saved front-left carrier Home=1230 us, model=+1.17 degrees and
Invert=On, Point's carrier target maps to approximately -261.123 us. Bow also
requests -224.500 us from the front-left crank. Playback speed does not alter
these required pulse extrema. A native fixture with the actual saved mapping
reproduced the three startup rejections at each of seven playback rates;
the other twenty named motions completed at each rate.

For observed endpoints 300 and 2900 us, **the pulse midpoint is 1600 us**.
1300 us is the half-range (`(2900-300)/2`), and is an asymmetric pulse position.
Inversion does not change the midpoint. Existing engravings correspond to the
previously selected 1300 us datum and model offsets; the UI now distinguishes
that physical reference from the center of servo travel. No saved mapping or
CAD marks were changed. A new centered mounting pose requires coupled-linkage
validation and matching physical horn placement before calibration is saved.

The final firmware contains only the entry arithmetic correction, with no new
calibration metadata, persistent fields, queues, buffers or allocations. Motion
tracks, gait parameters, existing calibration and V1 are unchanged.

| Resource | Before | After | Change |
| --- | ---: | ---: | ---: |
| Application binary | 2,370,848 B | 2,371,104 B | +256 B |
| Linked flash code | 1,324,126 B | 1,324,382 B | +256 B |
| Linked flash rodata | 931,176 B | 931,176 B | 0 B |
| Static data + BSS | 39,324 B | 39,324 B | 0 B |
| Total used DIRAM | 138,558 B | 138,558 B | 0 B |

P4 calculation/frame timing was not remeasured during this correction. Native
checks do not establish loaded motion or physical mounting. Application SHA-256:
`70b301e8ddccfa854d23a1826231dd00f2c49858a17ca4214465e38cfbe02da6`.
ELF SHA-256:
`5a0fb22a5f41d647ceab8e83b59e2f21014e2ecc0ca8292f282a93128cf6f9c8`.

Application-only deployment to the existing active OTA slot at 0x20000 passed
full-image flash digest verification. The first 128 KiB, including NVS and OTA
metadata, matched byte-for-byte before/after. The serial boot reported the new
ELF prefix `5a0fb22a5` and `home: ESP_OK`. The P4 reconnected to the physical
gateway; all twelve saved Home pulses, model angles, scales, channels and
inversion flags matched the pre-update snapshot. No motion or gait trials were
sent to the assembled robot. The corrected UI text is served by the live gateway.

## Current geometry, 1650 µs reference and servo timing (2026-09-29)

This source/build update supersedes the earlier statements that motion has no
servo-rate limit. It was built and checked offline; it has not been flashed or
tested with powered servos. Existing saved calibration is retained. The owner
places the existing carrier/crank matchmarks at 1650 µs; their model offsets
remain shoulder 0°, carrier +1.17°, crank −40.41°. The historical 234° conversion
and pulse endpoints remain reported references, not motion limits.

The visible Wireless assembly gives shoulder-axis spacing of 173.433792 mm
longitudinally and 63.500012 mm laterally, replacing 152.7 × 48.2 mm. The rear
rig was moved 21.633808 mm to match its assembled meshes, with child transforms
compensated so visible parts did not move. The linkage lengths are unchanged.
The owner identified `temp_mesh.ply` as a temporary reference; it is preserved
in the authoring scene and excluded from the robot's contact hull and playback.

The selected [MG90S advertised rating](https://www.amazon.com/dp/B0BWJ41FZB)
is 0.11 s/60° at 4.8 V, or **545.455°/s**. The supply
voltage and loaded shaft response have not been measured. The owner's flag
threshold is 125%, **681.818°/s**; flagged motion is retimed to the rating.
Continuous gaits preserve requested timing until the threshold is crossed,
then use a shared clock with bounded candidate evaluation to keep each emitted
joint step within the rated budget for the rest of that run. Stride, gait blending, foot
paths, body movement and planted anchors remain coordinated. Cadence recovers
at 0.5 clock fraction per second. The 40 ms wall-time fault still applies;
unused motion time is not replayed.

Finite clips use an analytical bound on every compiled cubic's derivative.
At 1×, all 23 authored gesture timelines are unchanged. At the firmware's 2×
default, Point's 1059.583°/s demand is flagged and the complete clip runs at
approximately 1.029564×; the other 22 clips retain 2×. Higher requested rates
use the same threshold. Entry transitions apply the policy separately to
their bounded quintic path. Saved speed settings are not overwritten.

All 47 motion sources were regenerated for the measured assembly. Old
foot excursions retain their scale while stance anchors move into the new
footprint. The four reviewed recordings retain their 30 Hz times, body
rotations, phases, contacts and cues; support/contact corrections adapt their
joints to the new geometry. No gesture amplitude or travel clamp was added.
The reviewed JSON files retain their original diagnostic samples as recording
provenance; their regenerated source/validation reports own current clearances.
Upright retains its 22-second phases, full −90° finish and 92.93 mm final arm
reach. Its intermediate support pitch changes from −27.5° to −22.954°, the
rearward support shift gains 1.5 mm, and the carrier leads the crank through the
existing 14–16 second waypoint to clear an unreachable linkage region.
Rear boot poses remain anchored within 0.000043 mm, with modeled body clearance
at least 0.543535 mm. Details are in the [Upright record](motions/gestures/upright/README.md).

The stride/rate demonstration originally demanded 1414.859°/s on this geometry.
Retiming only its timestamps changes the duration from 14.007649 to 14.981486 s
and its sampled peak to 545.455°/s. Continuous Walk at Speed 100 reaches about
67.7 mm/s of modeled body translation; Speed 200 continues changing the gait
and stride and reaches about 167.4 mm/s. These are kinematic predictions, not
measured ground speed.

Validation completed:

- All **31 native tests passed**, including production-body entry/playback,
  direct geometry, source provenance, compact clips and saved calibration.
  The gait timing test checked 38,146 frames at fixed and irregular intervals;
  15,693 were retimed. Before flagging, 283 joint samples used the permitted
  margin; the maximum was 681.719079°/s. After flagging, the maximum was
  545.391288°/s.
- Full source and interpolation-midpoint checks passed for the 23 gestures
  and eight legacy fixed-angle turn references. The reviewed recordings retain
  their existing 0.25 mm interpolation allowance; the worst sampled sole
  penetration is 0.240119 mm in Dead. Other motions use the existing 0.03 mm
  allowance. The complete-body hull excludes the temporary reference mesh.
- The saved Blender recovery was reopened. **1,724,706 joint/body key values**
  and **1,584 evaluated poses** matched the canonical sources and independent
  geometry. Maximum evaluated foot-position error was 0.002111 mm.
  `Motions - Firmware Remap` contains 47 updated firmware chapters. The original
  `Motions - Current Geometry` draft scene retains all 275 objects and 53 animated
  objects with exact key arrays, interpolation and chapter metadata. All 468
  Wireless objects retain the transforms and geometry captured after rear-rig
  reconciliation. The external experimental gait sidebar builder is outside
  this saved-playback check. [Saved playback and parity evidence](motions/blender-validation.json).
- ESP-IDF 5.5.4 produced the P4 application successfully: **2,412,928 bytes**,
  71% of the application partition free. Application SHA-256:
  `ad0bb87d0c5807c609a86df520db8624d608fcfe6f87ca3d3e54010bc24b3606`.
  ELF SHA-256:
  `7935ecc243ba7e84fbc0e0946565af1d2d2eae4df6000847b1537c018c0a7fb2`.

The [range audit](mechanics/original-motion-range-audit.md) reports electrical
demands and historical mechanical-envelope conflicts without clipping motions.
This update does not qualify full-body collision clearance, torque, balance,
servo tracking, acceleration, or P4 task timing under load. No hardware commands,
calibration writes, IMU integration or firmware deployment were performed.
