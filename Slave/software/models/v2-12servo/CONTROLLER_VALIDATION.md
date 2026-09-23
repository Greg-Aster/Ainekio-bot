# Compact controller validation

The replacement is built and application-flashed as `0.7.0-p4-compact-motion`.
The measurements below distinguish compiled resources, desktop geometry and
observations from the connected P4 with two unloaded servos and no linkages.

## Offline evidence

- 28 native tests pass in Release mode with `-UNDEBUG`; assertions execute.
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
