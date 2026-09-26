# Compact controller validation

The preceding controller replacement was built and application-flashed as `0.7.0-p4-compact-motion`.
The measurements below distinguish compiled resources, desktop geometry and
observations from the connected P4 with two unloaded servos and no linkages.

## Saved named-motion speed, 2026-09-25

Body Control now has one shared **Motion speed (×)** setting for Stand, Sit and
all finite named gestures. It defaults to 2×, supports 0.25–3× in 0.05× UI steps,
and offers explicit Save on robot / Read from robot. Editing previews the value
on the next named-motion command; saving retains it across P4 restarts. The
setting is captured at motion start and scales both entry and the clip timeline,
including velocity/acceleration, without changing poses or choreography. The
protocol and device setting retain 0.001× resolution.

The existing config owner stores a separate two-byte `motion_rate` NVS blob.
Saving stops outputs through the existing output/body owners before committing;
starting a subsequent motion resumes operation. No storage write, allocation or
new queue was added to the servo update path. The frame calculation adds bounded
integer timeline scaling and single-precision derivative scaling. Startup Home,
Neutral/Stop, the separate working V1 body and gait controls retain their timing.
The existing motion implementation and compact assets are retained; no alternate
player or new motion tables were added.

Matched ESP-IDF 5.5.4 builds with unchanged SDK configuration:

| Resource | Before | After | Change |
| --- | ---: | ---: | ---: |
| Application binary | 2,369,408 B | 2,371,248 B | +1,840 B |
| Flash code | 1,322,926 B | 1,324,526 B | +1,600 B |
| Flash read-only data | 931,000 B | 931,176 B | +176 B |
| Static RAM data + BSS | 39,260 B | 39,324 B | +64 B |
| Total occupied internal RAM, including code | 138,494 B | 138,558 B | +64 B |

ELF section checks show unchanged TCM and RTC allocations. DWARF type sizes show
unchanged 592-byte command, 672-byte controller request, 1,360-byte motion and
1,760-byte body-state structures. The existing depth-one body request queue's
payload grows 104 to 112 bytes (+8 heap bytes; no additional queue).

Validation: all 30 native/desktop checks passed across the native and geometry
runs, with Release assertions explicitly enabled (`-UNDEBUG`) and no remaining
skips. Production body-controller tests exercised all 23 clips at 0.25×, 1×, 2×
and 3×, compared output pulses at the same choreography times, and verified entry
scaling, completion, captured settings and unaffected gait timing. Config tests
covered default, save/reload, invalid values, failed commits, and unchanged joint
calibration. Gateway/dashboard Python tests passed (27), variable-walk tests
passed (42), and both the JavaScript race suite and isolated Chrome acceptance
passed. Browser checks cover selected speed in motion commands, confirmed save,
readback after an actual page reload, robot-selection races and mobile layout.
Two stale gateway test expectations were aligned with the preceding leverage
revision's Walk (-8 mm) and Crab (-22 mm) heights; gait code was not changed here.

The connected P4 received only the 2,371,248-byte application at its verified
active `ota_0` offset `0x20000`. Application flash digest verification passed;
`0x00000` through `0x1ffff` were identical before/after flashing, preserving
bootloader, partition table, NVS, PHY and OTA selection metadata. This protected
region's SHA-256 was `c369b24fe7d452cf1f04d0665d708783dadc509cde0d87ad767aa2e63c5e7afc`.
Other application slots and LittleFS were not written. The gateway was restarted
with its existing credentials and runtime data and negotiated `motion_speed_v1`.

Application SHA-256:
`a887ceda20dbd8111022110b995d8bc784e4cf55e696f23fd12de4d3c85ca952`.
ELF SHA-256:
`2be99f9ca7cb884e75cf2f6cdf61b5ea66f437f9444d89ac102bc2f19283a296`.
Both deployment and subsequent persistence-check boots reported the matching
ELF prefix. The shared 2× value was explicitly saved on the robot. Another control request
then saved a setting (epoch 1, sequence 10); after the persistence reboot the P4
reported **3× with `saved:true`**. That newer setting was preserved. The compiled
default remains 2×. All twelve saved joint mappings,
including the owner's current Home pulse values and inversion settings, matched
the pre-deployment readback after flashing and again after the persistence reboot.
No joint calibration record was rewritten by the speed save.

These hardware checks ran startup Home and read/save operations, not loaded
gestures or gait trials. Native timing-scaling checks do not establish servo
tracking, torque capability or worst-case P4 calculation/frame timing at higher
motion speeds. Dynamic heap snapshots vary with mode and connected peripherals;
no matched dynamic-RAM or motion-timing benchmark is claimed for this revision.
Raw NVS images, credentials, calibration snapshots and boot logs are excluded
from the repository.

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
