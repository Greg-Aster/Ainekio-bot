# Gait research journal

## Scope and authorization

Started 2026-10-12. The owner approved the locomotion correction and modernization
plan, including feedback, dynamics simulation and learned-control experiments,
using existing hardware. Buying additional materials is outside this approval.
The owner also requested this ongoing journal.

The installed V2 robot uses the linkage shown in Blender: 35 mm carrier,
20 mm input crank, 28 mm output pickup, 38 mm connecting rod and 55 mm distal
leg. V1 remains a separate eight-servo model.

Record source/build, simulation, deployed firmware and physical evidence
separately. An animation or passing geometry test does not establish traction,
balance, loaded servo tracking or successful locomotion. Measurements that have
not been made remain unknown.

## Original problem tracker — updated 2026-10-12 after owner clarification

The objective is useful weight-bearing locomotion and feedback-based improvement,
including learned control. Sensor bring-up is supporting work, not completion of
that objective. The owner can record external phone video for movement evaluation.

| Original concern | Current evidence and status | What will establish improvement |
| --- | --- | --- |
| Feet miss the ground or fail to support a useful walk | Open. Production geometry remains 40/24/24/38/55 mm; installed linkage is 35/20/28/38/55 mm. Compact candidate exists but is not merged. | Correct installed model and motor references, then observed stance contact and displacement under load. |
| Squat/shuffle and poor leverage | Open. Compact full-stride paths miss some recorded leverage margins; a new body-height study is recorded below. | Measured body clearance, distance per cycle and loaded actuator behavior; kinematic margins alone are insufficient. |
| Legs wiggle without physically turning | Open. Local combined translation/yaw generation exists; physical achieved yaw and slip have not been measured. | Repeatable turn-angle and slip measurements from external video, cross-checked with short-interval IMU rotation. |
| Must stop before turning | Dashboard blending was implemented and software-tested; physical curved walking is unverified. | One continuous walk through forward/turn updates with achieved motion recorded. |
| Servos too weak versus wrong gait | Unresolved. Geometry and commanded leverage issues are established; loaded tracking, supply behavior and torque are not measured. | Compare reachable trajectories, commanded timing, observed shaft/leg response and supply measurements. |
| Learn a better walking system from feedback | Not implemented or trained. Corrected IMU observations are available; synchronized motion trials and a dynamics learning environment remain work. | A trained candidate outperforms the baseline on separately evaluated physical trials, not only animation or lower IMU wobble. |

A conventional tilt controller is a baseline/comparison, not learned locomotion.
We do not need to perfect a hand-authored gait before learning. We do need the
installed mechanism, motor coordinate mapping and measured trial outcomes to be
represented honestly. Learning should improve movement, contact and support as
well as attitude; stationary or minimally moving behavior must not be described
as success merely because it produces small gyro readings.

## Approved work sequence

1. Reconcile the installed geometry, motor angle references and saved calibration;
   merge the existing compact-linkage candidate into current source and regenerate
   its evidence.
2. Improve contact and body coordination and integrate continuous forward/turn
   steering through the existing command owners.
3. Characterize existing actuators and power under representative loads; connect
   the existing IMU estimator to acquisition and body feedback.
4. Build a dynamics simulation using measured geometry and actuator behaviour;
   compare and optimize conventional gait candidates.
5. Train a small policy modulating the trajectory generator; compare against the
   corrected and optimized conventional baselines. Evaluate recurrent control if
   delayed actuation and incomplete observations justify it.
6. Benchmark deployment on P4/Q6A, then extend demonstrated improvements to other
   gaits and motion transitions.

P4 retains local physical execution. Q6A supplies objectives/perception and
supports evaluation; desktop GPU resources support training. Blender supplies
geometry and authored references. Policy location remains subject to measured
execution and transport timing.

## 2026-10-12 — Research and implementation baseline

### Confirmed findings

- **Geometry mismatch:** the current source model and generated P4 build constants
  use 40/24/24/38/55 mm, while the owner confirms the installed 35/20/28/38/55 mm
  mechanism. The installed firmware image identity has not yet been read in this
  session.
- **Existing migration work:** `docs/gait-research/seated-support-20261005/`
  contains a complete 23-gesture offline compact-linkage candidate and continuous
  gait changes. Its baseline is commit `13fc3e46009f9b0cbb0b5c1c63af8cc659e415c6`.
  Integration must preserve subsequent source and owner edits.
- **Blender evidence:** live inspection of
  `Slave/hardware/v2-12servo/ainekio-variable-gait-Recovery.blend` found the Wireless
  modeling scene, compact-linkage library and separate firmware-remap previews.
  Inspected scenes have no rigid-body dynamics. Walk/Run timing revisions are
  explicitly visual drafts, not integrated firmware. The file was already dirty;
  research calls did not change the scene or save it.
- **Contact schedule:** Walk/Crawl use 0.7 stance fraction with quarter-cycle leg
  offsets. Steady scheduling includes two-foot support for about 20% of a cycle.
  This is a timing calculation, not proof of instability in every such interval.
- **Feedback:** the portable IMU estimator exists but is not called by a live P4
  acquisition task. Body pose records the last commanded target, not measured
  joint position. Current gait control has no measured balance feedback.
- **Steering:** the firmware already blends signed forward and turn controls.
  The dashboard direction handler instead finishes active motion before changing
  direction and its gamepad selects a single dominant axis.
- **Missing physical model inputs:** source mass and supply voltage are null;
  centre of mass is provisional and loaded servo response is unmeasured.
- **Historical evidence is stale:** saved locomotion recordings have source hashes
  differing from current motion code, geometry, config and sole profile. A saved
  Walk report lists 29.06 degrees stance transmission angle and 1.88 mm
  straightening clearance, versus current regression margins of 45 degrees and
  3 mm. These are historical records, not current-runtime test results.

### Research basis

- [Policies Modulating Trajectory Generators (2018)](https://proceedings.mlr.press/v87/iscen18a.html):
  learned modulation of a periodic generator; a relevant compact-controller
  baseline, not a pretrained Ainekio policy.
- [Reinforcement Learning on Cost-Constrained Quadrupedal Hardware (2026 preprint)](https://arxiv.org/html/2607.26434v2):
  recurrent policy and learned actuator model for delayed inexpensive position
  servos. Its actuator parameters, delay experiments and physical results do not
  qualify this robot.
- [Rapid Motor Adaptation (2021)](https://ashish-kmr.github.io/rma-legged-robots/):
  history-based adaptation architecture; different hardware and observations.
- [MuJoCo Playground](https://github.com/google-deepmind/mujoco_playground):
  candidate GPU training framework. Ainekio closed-linkage dynamics and actuator
  fidelity require implementation and validation.

### Work in progress

- Backed up affected pre-existing dirty source files under
  `/tmp/ainekio-locomotion-modernization-20261012/baseline/`, with a SHA-256
  manifest beside that directory. This is a local working backup, not a durable
  repository artifact.
- Extracted the approved offline candidate under the same temporary workspace
  for selective comparison. No candidate files have yet replaced production
  source.
- No firmware flash, calibration write or physical-motion command has been sent.

### Evaluation measures

Record actual distance per cycle, achieved yaw, foot slip, body height/tilt,
actuator tracking error and power demand. Include firmware/model identity,
calibration, command settings, surface and carried load with each physical trial.
Simulation metrics and physical measurements must be distinguished.

## 2026-10-12 — First implementation and repeatable command audit

### Changes made to current source

- The dashboard now negotiates `walk_steering_v1` and supplies separate signed
  forward and turn controls. Direction presets, simultaneous direction keys,
  multiple held pointer buttons and both gamepad axes update the original walk
  sequence. Slider changes coalesce while a request is outstanding. Existing
  legacy directions and Crab sideways controls remain available. Gait selection
  still follows the existing Finish/restart contract.
- A released held start cannot be revived by a delayed response. Existing
  disconnect, robot-selection, Finish and emergency-stop behaviour is preserved.
- Steering interpolation in the motion owner now uses the existing Walk
  transition span (two gait cycles) instead of one cycle. Already airborne feet
  have committed landing targets; reversing the body path too quickly pulled
  it away from those anchors. This trades a longer blend for improved transition
  geometry, retaining requested forward/turn magnitude and gait phase. It adds
  no automatic stop, gait-range reduction or sensor dependency.
- Added `tools/audit_gait.py` under the V2 model. It replays sixteen native
  commands covering Walk/Crawl/Run, both turn directions, curves, reversal and
  Walk/Run transitions. Reports include source/binary hashes, solver failures,
  leverage, modeled support schedules, pulse estimates and Finish outcomes.
  An optional alternate geometry replay measures the consequences of applying
  one linkage's joint commands to another. Regression floors remain unchanged;
  the audit explicitly reports measurements below them.

These are source changes. No firmware flash, saved calibration write, service
restart or physical movement was performed in this work.

### Geometry comparison and steering experiment

Offline reports are retained in
[`docs/gait-research/locomotion-modernization-20261012/`](../gait-research/locomotion-modernization-20261012/).

| Experiment | Result | Interpretation |
| --- | --- | --- |
| Current Walk commands evaluated on the compact linkage | Foot XY error up to 18.511 mm; declared stance soles at +3.825 to +19.186 mm relative to the modeled floor | A significant linkage mismatch exists even with ideal servo tracking. Assumes common motor zeros and the commanded chassis pose; actual body settling and calibration were not measured. |
| Current left-turn commands evaluated on the compact linkage | Foot XY error up to 11.689 mm; stance soles +8.133 to +10.058 mm | The turn's ground-contact targets do not transfer correctly between the mechanisms. This is not a measurement of physical turning. |
| Current geometry, original one-cycle curved reversal | Stance output angle 36.597 degrees; straightening clearance 1.940 mm | Completes numerically but misses existing 45 degree / 3 mm regression floors. |
| Current geometry, two-cycle curved reversal | Stance output angle 49.262 degrees; straightening clearance 4.275 mm | Completes with the original sequence and meets the recorded leverage floors for this case. |
| Compact candidate, original one-cycle curved reversal | IK fails at 13.360 s, phase 7.447514 | The archived geometry migration alone does not fix the complete control path. |
| Compact candidate, two-cycle curved reversal | Completes; stance output angle 44.519 degrees | Removes this reproduced IK failure, but remains below the 45 degree regression floor. Further tuning is required. |

The reversal starts at Speed 100 with forward=100/turn=0, changes to 75/75 at
6 s and -75/-75 at 12 s, then requests Finish at 20 s. Reports contain the
exact commands. Sampling is 50 Hz. These are kinematic targets, not measured
speed, traction, balance or joint torque.

A separate temporary experiment replaced the single midpoint prediction with
finer arc integration. The compact reversal still failed at 13.340 s. It was
not adopted: finer numerical integration alone does not solve the committed
landing/rapid-reversal problem.

### Compact migration status

The complete candidate was built under
`/tmp/ainekio-locomotion-modernization-20261012/stage/`, using the archived
`motion-library-candidate.zip` and current model/build infrastructure. The newer
Lay Down/Dead **lift, place, then lower** sequence was reauthored on the compact
endpoints with the existing `step_grounded_postures.py`, then compiled using
`import_reviewed_clips.py --commands lay_down dead`. Their grounded-step tests
pass, as do the gesture sampler/provenance checks. Current production gesture
files and the owner's original edits were not replaced.

The compact model has **not** replaced production geometry. Outstanding findings:

- Existing locomotion, full-CAD and Run tests fail leverage regressions. This
  requires trajectory/posture work; regression floors have not been weakened.
- Upright passes its support/grounding checks but fails the historical >90 mm
  reach assertion. The prior owner-accepted compact approximation is 76.585 mm;
  that test needs a geometry-specific contract when the migration is integrated.
- Two generator fixtures assume the old mechanism: a specific straightening
  pose and a 0.02 mm height perturbation. Their expected outcomes change with
  compact geometry; replace them with geometry-derived witnesses when merging.
- The candidate retains the old mounting profile. Nominal unmirrored Walk
  pulses reach about 167 microseconds under those references, outside the
  profile's declared 300–3000 microsecond span. This is a calculated mapping
  conflict, not a request to send that pulse or evidence of installed NVS
  calibration. Reconcile actual saved calibration, motor zeros and available
  travel before judging servo strength or integrating the full motion library.
- Walk/Crawl still use 0.7 stance fraction. The compact command audit confirms
  two-foot support intervals; neither geometry migration nor steering timing
  implements balance feedback or a revised support schedule.

### Validation record

- Dashboard production-handler race tests passed, including combined steering,
  queued updates, two-key driving, gamepad curves, release before the start
  response, legacy directions and robot switching.
- Dashboard HTTP integration: **32/32 passed** using temporary local test servers.
- Current native model/core suite after the steering fix: **28/29 passed**.
  The same single failure existed before this change: Run demonstration
  regeneration reports stance output angle **40.886 < 45 degrees**. This
  pre-existing failure remains open; it is not hidden or relabeled as passing.
- The expanded native locomotion test passed 84 existing envelopes plus the
  full-stroke reversal/Finish regression, retaining zero planted XY target
  drift. All sixteen current-model audit scenarios complete without solver
  failures or recorded leverage-floor violations at both 25 Hz and 50 Hz after
  the change. This finite scenario set does not qualify every possible input.
- Staged compact suite before the steering timing experiment: **24/29 passed**
  after supplying its copied protocol and asset fixtures. The five failing test targets are locomotion, gait geometry,
  Run, Upright and locomotion regeneration as described above. This is candidate
  evidence, not a firmware or physical qualification.
- Baseline hashes confirm pre-existing dirty files outside the two intentionally
  edited dashboard static files remain unchanged. The original Lay Down/Dead
  edits and untracked authoring tool/test remain in place.

Reproduce the current-model audit from the repository root (Python needs NumPy
and SciPy; select that interpreter in CMake):

```sh
cmake -S Slave/software/models/v2-12servo -B /tmp/ainekio-gait-audit -DPython3_EXECUTABLE=/path/to/python
cmake --build /tmp/ainekio-gait-audit --parallel 4
ctest --test-dir /tmp/ainekio-gait-audit --output-on-failure
/path/to/python Slave/software/models/v2-12servo/tools/audit_gait.py /tmp/ainekio-gait-audit/v2_walk_command --out /tmp/gait-audit.json
node Emulator/tests/test_dashboard_motion_races.js
PYTHONPATH=Master:Slave/software /path/to/python -m unittest discover -s Emulator/tests -p test_gateway_dashboard.py -q
```

The local SciPy-capable interpreter used here was
`/home/greggles/ComfyUI/venv/bin/python`. `/usr/bin/ctest` was used because the
user-local `ctest` launcher could not import its CMake Python package. HTTP tests
needed permission to bind local sockets outside the restricted sandbox.

### Owner update: the mounted IMU is not connected

The owner confirmed that the LSM6DS3 sensor board is mounted in the frame but
unplugged and non-operational, and is willing to connect it for feedback.
This supersedes the earlier uncertainty about whether it was already wired.
The board's printed connector labels and orientation remain unverified.

Current P4 source creates I2C0 on SDA GPIO7 / SCL GPIO8 inside
`components/ainekio_p4_media/media.c`; PCA9685 separately owns I2C1 GPIO2/3.
IMU acquisition must share the existing bus owner without depending on successful
audio/camera startup. The portable estimator already exists and is unused by a
live acquisition task. Do not infer actual sensor axes from Blender's estimated
sensor-board mesh.

The proposed connection uses the existing 7/8 bus. Power-pin correspondence must
be checked against the actual sensor board's labels. ST specifies 1.71–3.6 V
for the LSM6DS3 chip; that does not identify the connector arrangement or onboard
regulator of the mounted board.
[ST LSM6DS3 datasheet, revision 10](https://pccomponents.com/datasheets/ST_MI-LSM6DS3TR.pdf).

Next work is to reconcile mounting/calibration for the compact mechanism, tune
its trajectories against these recorded failures and support schedules, then
acquire timestamped IMU data and establish body-axis calibration. Dynamics and
policy training still need measured mass, loaded actuator timing and electrical
behaviour. A learned policy has not been trained or activated.

## 2026-10-12 — Sensor-board photos and proposed connection

The owner supplied front/back photographs of the purple board marked LSM6DS3.
They show separate VIN and 3V3 connections, GND, SCL, SDA, CS, SA0, INT1, INT2,
SCX and SDX. The remaining auxiliary label appears to be OCS/DCS; it is not
needed for the proposed interface. The printed axis graphic is visible, but
these detached views do not establish the board's orientation in the robot.
This supersedes the earlier uncertainty about the primary connector labels.
Photos establish board markings, not the chip's electronic identity or operation.
The original photographs remain outside the repository.

Use the existing P4 I2C0 bus and 3.3 V supply, with power disconnected while
making connections:

| Sensor-board label | Proposed connection |
| --- | --- |
| 3V3 | P4 3V3 |
| GND | P4 GND |
| SDA | P4 GPIO7 / SDA |
| SCL | P4 GPIO8 / SCL |
| CS | 3V3, selecting I2C |
| SA0 | GND, selecting 7-bit address 0x6A |
| SCX and SDX | GND, unused external-sensor interface inputs in Mode 1 |
| VIN | Unconnected when powering the 3V3 rail |
| INT1, INT2, auxiliary OCS/DCS | Unconnected for initial polling acquisition |

P4 GPIO7/8 are confirmed in current `ainekio_p4_media/media.c`. CS high,
SA0 low, and unused SCX/SDX tied to a supply rail follow the
[ST LSM6DS3 datasheet](https://pccomponents.com/datasheets/ST_MI-LSM6DS3TR.pdf),
pin table and I2C sections. The direct 3V3 supply/VIN-unused connection is also
documented by the [ESP-IDF LSM6DS3 module implementation](https://github.com/nopnop2002/esp-idf-lsm6ds3#wireing).
The regulator part marking and the exact board schematic are not established
by these photographs; no 5 V compatibility claim is made.

Next bring-up evidence: address response, WHO_AM_I readback, stationary raw
acceleration/gyro samples, and controlled tilts to establish sensor-to-body
axes. For the base LSM6DS3, register 0x0F should identify it as 0x69; a different
readback must be identified rather than assumed to use the same register map.
The source acquisition task is still not implemented, so connecting the board
alone will not enable balance feedback. No sensor writes, physical wiring,
firmware flash or motion commands were performed during this photo review.

## 2026-10-12 — Clarifying conflicts in the earlier P4 pinout diagram

The owner noticed that `ESP32P4_Pinout.png` labels GPIO7/8 as reserved and R5
3V3 as PCA9685 VCC. That September 15 diagram describes the servo bring-up
allocation; its wording does not explain sharing the existing I2C bus or power
rail. The IMU proposal keeps GPIO7/8 in their existing I2C role. It does not
reassign them or remove the codec/camera connections.

With the component side facing the viewer and USB-C at the top, use the
diagram's row identifiers (these are not GPIO numbers):

| Sensor | Diagram position | Existing role / sharing |
| --- | --- | --- |
| SDA | L17 — GPIO7 / SDA | Shared I2C0 data with codec/camera |
| SCL | L16 — GPIO8 / SCL | Shared I2C0 clock with codec/camera |
| 3V3 | R5 — 3V3 | Same 3.3 V rail as PCA9685 logic; retain that connection |
| GND | L18 — GND | Common ground; another labeled GND is also usable |

CS connects to the sensor's 3.3 V junction; SA0, SCX and SDX connect to its
ground junction. These straps do not consume additional P4 GPIO pins. An
occupied R5 needs a shared wiring junction, not removal of PCA9685 power.
GPIO2/3/4 stay assigned to PCA9685 SDA/SCL/OE.

The documented bus addresses are codec 0x18, OV5647 0x36, and proposed IMU
0x6A with SA0 grounded, so there is no indicated address collision. Current
`RESOURCE_BUDGET.md` already specifies this IMU bus sharing. Actual sensor
identity, bus electrical behaviour and concurrent operation still need bring-up
measurements. Firmware must add the sensor under the existing I2C0 owner;
connecting it does not yet supply live attitude feedback.

## 2026-10-12 — Combined assembly reference requested and delivered

The owner requested an updated image whenever resolving these pin conflicts,
including the 1.9-inch LCD, servo board and gyro together. Created
[Assembly_Reference.png](Assembly_Reference.png) and the corresponding
[connection table](ASSEMBLY_REFERENCE.md), and linked them from the V2 index,
servo wiring guide and LCD guide. Older diagrams remain available with their
historical scope explained.

Checked LCD SPI assignments against display.c and the local sdkconfig:
SCLK20, MOSI21, CS22, DC23, RESET26. PCA9685 retains SDA2/SCL3/OE4;
the proposed IMU retains shared SDA7/SCL8. The image explicitly branches
R5 3V3 to PCA VCC, LCD VCC/BLK and IMU 3V3/CS, keeps servo 5 V on PCA V+,
and shows local IMU ground straps. All module grounds are common.

Generated the image with the built-in image tool, reviewed its connection
tables, and revised misleading module illustrations into schematic icons.
The PCA9685 is correctly labeled as 16 channels with 0–11 used.
Initial and revision prompts are saved alongside the image. This is a
documentation update: no flashing, servo commands or sensor acquisition were
performed. IMU electrical identity, axis mapping and concurrent operation
remain unverified; the acquisition firmware is still pending.

## 2026-10-12 — First physical LSM6DS3 response and raw acquisition

Owner confirmed the gyro board wired, P4 connected and servos disconnected.
The host found the CH343 serial adapter at `/dev/ttyACM0`. Initial access was
blocked by Linux device permissions; the owner granted a device-specific ACL.
The running application was `0.8.16-p4-iso3200`, P4 silicon 1.3, ESP-IDF 5.5.4.
Boot confirmed ES8311 audio, OV5647 camera and the current temporary SSD1306
OLED. The new 1.9-inch LCD assembly guide remains a reference for that selected
LCD; it does not mean the currently installed display was changed to ST7789.

Added `imu probe` and `imu sample` console diagnostics in
`main/imu_diagnostics.c`. They borrow existing I2C0, identify addresses 0x6A/0x6B,
and can capture two seconds at nominal 104 Hz, ±2 g and ±250 degrees/s.
The sampler restores its three changed control registers and has no motion,
estimator or saved-calibration output. It records sensor-frame SI units and
read-midpoint timestamps; console polling is not a qualified feedback clock.

Validation: diagnostic native tests, body execution and existing IMU estimator
tests passed (3/3 selected CTest targets). The full native build encountered an
existing `test_calibration_store.c` include failure for `ainekio/face.h`; it is
not claimed as passing. ESP-IDF application build passed. Application-only flash
of `0.8.17-p4-imu-probe` at 0x20000 passed esptool hash verification, preserving
NVS, partition table, C6 image and the selected OLED configuration. Existing
working-tree gait/body/transport edits were retained in the application build;
this is not a qualification of their physical motion with disconnected servos.

Physical results: **0x6A acknowledged; WHO_AM_I = 0x69**, consistent with the
base LSM6DS3 register map. No response at 0x6B, as expected with SA0 grounded.
`imu sample` returned **207 samples with ESP_OK** in its two-second window.
Audio and camera initialization also succeeded with the gyro attached. These
results establish initial sensor communication and six-axis reads, not loaded
bus timing, calibrated attitude or closed-loop gait performance.

The first capture showed acceleration near gravity and nonzero gyro means.
Whether it was stationary was not established, so no bias was saved. Requested
a confirmed stationary capture next. Raw serial logs remain outside the repo
under `/tmp/ainekio-imu-bringup-serial.log`; only findings are recorded here.

The owner asked whether the stationary check required calibration and noted
that leveling the robot is difficult. Clarified that this capture does not save
calibration: gyro bias needs the body motionless at any supported angle. The
earlier request to level it was unnecessary for this measurement. Establishing
body axes and accelerometer calibration are separate steps.

### Owner-confirmed stationary check

With the robot supported at an arbitrary angle and explicitly reported still,
two completed captures returned 207 samples each (414 total), both ESP_OK.
The first of three requested console commands arrived before the boot console
was ready and was not executed; it is excluded from the measurement. No sensor
failure is inferred from that host-command timing issue.

| Measurement | Capture 1 | Capture 2 |
| --- | --- | --- |
| Mean acceleration, sensor XYZ (m/s²) | -0.6660, +0.2909, +9.9961 | -0.6687, +0.2905, +9.9983 |
| Mean acceleration magnitude (m/s²) | 10.0228 | 10.0252 |
| Mean gyro, sensor XYZ (degrees/s) | +2.7643, -4.2191, -3.4595 | +2.6198, -4.1391, -3.4733 |
| Gyro standard deviation, XYZ (degrees/s) | 0.2295, 0.1636, 0.1128 | 0.2450, 0.1270, 0.0817 |
| Twelve-byte I2C read duration (µs) | 416–517 | 416–544 |

Combined short-window stationary gyro offset: approximately
**(+2.6920, -4.1791, -3.4664) degrees/s**, or
(+0.046985, -0.072940, -0.060500) rad/s in sensor axes. These are measured bias
candidates, not saved calibration or a thermal-stability qualification.
Uncompensated gyro integration would accumulate substantial drift. The
acceleration magnitude is around 2.2% above standard gravity; this single
orientation cannot separate accelerometer bias and scale, and must not be
used to fit a complete accelerometer calibration.

The board responds and supplies plausible six-axis data. Next feedback work
requires continuous timestamped acquisition, bias handling and verified
sensor-to-body axes. None of these measurements prove foot contact, servo
torque, or an improved physical gait. Servos stayed disconnected and no motion
commands or saved calibration writes were issued. Sensor control registers
were restored after each finite capture. Stationary raw log remains outside
the repository at `/tmp/ainekio-imu-stationary-serial.log`.

Flashed application SHA256:
`99935e4ac24a54ee73e5a71c6a3dd6986facab63e56fd4fe181f5c8e14e27704`.

## 2026-10-12 — Continuous acquisition and sensor-frame estimation

Owner approved continuing and confirmed they can perform front-up and left-up
hand tilts with disconnected servos. Implemented a single continuous LSM6DS3
owner in `components/ainekio_p4_media/imu.c`. Media startup prepares its device
on existing I2C0 before registering codec/camera devices; app startup starts
acquisition after media initialization, independently of audio/camera readiness.
No second bus is created. ESP-IDF 5.5.4 serializes I2C transaction operations.

Acquisition uses 208 Hz, ±16 g, ±2000 degrees/s, block-data-update and register
auto-increment, matching the portable estimator defaults. A task polls both
data-ready flags every 2 ms, timestamps each read midpoint, and calls the
existing estimator once per acquired sample. Synchronized status copies expose
raw data, sensor-frame quaternion, age, errors and maximum read/sample intervals.
Errors retain the previous sample timestamp, so the existing freshness contract
remains meaningful. There is no new motion stop, capability restriction or
feedback connection. Bias and mounting remain uncalibrated.

`imu` / `imu probe` now report startup identity and live counters without I2C.
`imu sample` and `imu watch` print two / ten seconds of snapshots at up to 50 Hz,
without changing acquisition registers. This removes serial-output timing from
the acquisition owner. Polling still does not provide hardware data-ready/FIFO
timestamps or guarantee no missed updates under contention.

Validation: continuous-driver diagnostics, portable estimator, body execution
and camera tests passed (4/4 selected targets); ESP-IDF build passed. The prior
full-native calibration include failure remains outside this change. Application
`0.8.18-p4-imu-live` flashed at 0x20000 with hash verification, preserving settings,
partition layout, C6 and OLED selection. SHA256:
`8ecf81218aed4c131cc4151d34fcb4ecc4f04d97937687286001d82812b31e12`.

First live status: configured/running, identity 0x69, 1,435 acquired and accepted
samples, zero I2C errors, zero rejected samples and zero estimator gap restarts.
At that observation, age was 4,151 µs, maximum read time 745 µs and maximum
sample interval 9,285 µs. These are measurements from this bring-up workload,
not deadlines guaranteed under combined media/network load. Raw logs remain
outside the repo at `/tmp/ainekio-imu-continuous/`.

### Physical mounting-axis check

With servos still disconnected, the owner raised the front and then the robot's
left side by hand, holding each for a short capture. The baseline need not be
perfectly level. Measurements used raw acceleration, not the uncorrected
gyro-integrated heading.

| Position | Console snapshots | Mean sensor acceleration XYZ (m/s²) |
| --- | --- | --- |
| Resting baseline | 477 over ten seconds | -0.2312, +0.4830, +9.8495 |
| Front raised | 95 over two seconds | -2.8093, +0.2980, +9.3935 |
| Left side raised | 95 over two seconds | -0.5247, -2.3824, +9.4928 |

Front-up primarily changes sensor X negatively; left-up primarily changes
sensor Y negatively. The resting up direction is predominantly sensor +Z.
These measurements support the nominal mapping **body forward = sensor -X,
body left = sensor -Y, body up = sensor +Z**: approximately a 180° rotation
around the vertical axis. The corresponding nominal sensor-to-body matrix is
`diag(-1, -1, +1)`, a proper right-handed rotation. The hand-held captures do
not fit precise mounting misalignment or a complete accelerometer calibration.

At the end of the left-up capture, acquisition reported **58,190 samples**,
all accepted by the estimator, **zero I2C errors**, zero rejected samples and
zero estimator gap restarts. Maximum observed read transaction was 5,957 µs
and maximum sample interval 15,510 µs; the final sample age was 2,676 µs.
The maxima show occasional longer intervals despite nominal 208 Hz operation;
zero I2C errors does not imply lossless sampling. Camera/audio initialized,
but the robot had no Wi-Fi association in this run, so active streaming and
combined network/media load were not qualified.

No mounting matrix, gyro bias or accelerometer calibration was saved or applied
to the firmware during this check. Continuous estimator output remains clearly
labeled sensor-frame and uncalibrated, and no gait consumer is connected.
The baseline at the new ±16 g range measured gyro means about
(+2.659, -4.189, -3.413) degrees/s, consistent with the previous stationary
bias finding. Calibration must use these as measurements, not universal
defaults for every sensor or temperature.

## 2026-10-12 — Persistent mounting and stationary gyro correction

Owner approved continuing, then confirmed the robot stationary with servos
disconnected for a fresh bias measurement and again for the corrected check.
Neither measurement required a level chassis. The fresh ten-second raw capture
contained 476 console snapshots. Sensor XYZ gyro means were
`(+2.62823, -4.17485, -3.36368)` degrees/s, or
`(+0.045871328, -0.072864937, -0.058707263)` rad/s. Standard deviations were
`(0.26629, 0.27542, 0.09815)` degrees/s. This is a stationary offset estimate at
the current operating condition, not temperature compensation.

Added P4 calibration storage in `ainekio_p4_media/imu_calibration.c`, using NVS
namespace `p4_imu`, key `cal_v1`. The record contains nine row-major rotation
floats followed by three sensor-axis gyro-bias floats (48 bytes). It uses the
portable estimator's existing configuration validation. Acquisition loads the
record at boot and subtracts gyro bias before rotating vectors into body axes.
Saving does not reinitialize or mutate the live estimator; it applies next boot.
No record uses the existing identity/zero-bias diagnostic configuration.
No joint, home, network or other media settings are changed by this record.

Console additions: `imu calibration` reads storage and active state;
`imu calibration set r00 r01 r02 r10 r11 r12 r20 r21 r22 bx by bz` saves the
rotation and sensor-axis bias in rad/s; `imu body` exports two seconds of
corrected estimator vectors. `imu sample` and `imu watch` remain raw sensor
snapshots. Status distinguishes `body_nominal` / `bias=applied` from the previous
uncalibrated sensor frame, and explicitly reports no accelerometer calibration.

Software evidence: four selected native tests passed (hardware IMU diagnostics,
portable estimator, body execution, camera profiles/snapshots). Added checks cover
storage round-trip, save without live mutation, boot application, rotation/bias
order, invalid calibration, NVS failures, truncated storage and console parsing.
The pre-existing full-native `test_calibration_store.c` / `ainekio/face.h` include
failure remains outside this result. ESP-IDF 5.5.4 build passed; application size
was 2,859,216 bytes in the existing 8 MiB partition.

Application `0.8.19-p4-imu-cal` was flashed at 0x20000 and its data hash verified.
Application SHA256:
`3e5d22d6f4174ade4f382eda15b2ee3aea78eec5eb9f30b169227ee72279fb80`.
This working-tree image retains the existing OLED selection and other local
firmware changes; disconnected servos mean this is not physical motion proof.
Partition layout and the C6 image were not flashed.

Physical persistence evidence: before saving, the console reported
`stored=0 active_applied=0`. Saving the measured bias and `diag(-1,-1,+1)` returned
`ESP_OK`; immediate readback showed `stored=1 active_applied=0`. After the existing
`system restart` command, the board reported the new application version,
`stored=1 active_applied=1`, and the same matrix and bias. The live estimator
reported `frame=body_nominal bias=applied`. This verifies persistence over software
restart; a separate unplug/replug power-cycle test was not performed.

Three subsequent stationary body captures produced 95 snapshots each (285 total,
six seconds of capture). Results in body XYZ:

| Measurement | X | Y | Z |
| --- | --- | --- | --- |
| Corrected gyro mean (degrees/s) | -0.00156 | -0.00138 | +0.02259 |
| Corrected gyro standard deviation (degrees/s) | 0.23142 | 0.18460 | 0.09328 |
| Mean acceleration including gravity (m/s²) | +0.56026 | -0.30098 | +9.83007 |

Final capture status showed 7,994 acquired/accepted samples since boot, zero I2C
errors, zero rejected samples and zero estimator gap restarts. Maximum observed
read duration was 4,060 µs and sample interval 10,048 µs; final sample age was
2,715 µs. These maxima describe this workload, not guaranteed timing bounds.
Raw logs remain outside the repository in `/tmp/ainekio-imu-calibration/`; the
fresh bias input is `/tmp/ainekio-imu-continuous/bias_baseline.log`.

The nominal mounting and stationary gyro offset are now applied and physically
checked. Precise mounting misalignment, accelerometer bias/scale, thermal drift,
combined active network/media timing and gait feedback remain unqualified.
Heading is still arbitrary and drifts without an external reference. There is
still no IMU-driven motion correction, foot-contact measurement or servo-torque
qualification. This step supplies corrected observations for the approved gait
work; it does not yet establish an improved physical walk.

## 2026-10-12 — Return to locomotion outcomes and learning

Owner requested walking balance/feedback, then clarified that the original
contact, leverage, standing/walking and turning failures must remain the focus,
including learning better gait/motion behavior from feedback. Work had progressed
to IMU calibration ahead of the unfinished geometry migration. No new balance
controller or learned policy was installed in this continuation. Existing P4
application remains `0.8.19-p4-imu-cal`.

Owner explicitly approved this proposed future feedback behavior: if IMU data
is missing, stale or recovering, smoothly remove only the balance correction
while continuing the commanded gait; if a correction cannot fit linkage reach or
the existing joint-speed limit, reduce that correction and report the reduction.
This authorization is specific to that behavior and does not authorize new
motion stops, obstacle restrictions or a smaller commanded gait range.

### Reproducible compact-linkage posture experiment

Added `Slave/software/models/v2-12servo/tools/study_gait_posture.py`. It copies a
complete candidate model and its core dependency into a temporary workspace,
changes only the candidate Walk body-Z target, updates that temporary Walk
manifest, builds the native command sampler and evaluates the existing audit
metrics. Source models and installed firmware/settings remain untouched. The
full 96 mm stance sweep, foot lift, steering range and original regression floors
remain unchanged in this experiment. Standing entry retains the candidate's
original reference; this is not a complete reauthoring of stand/walk transitions.

Executed eight heights (-12, -10, -8, -6, -4, -2, 0, +2 mm in the model's body
translation coordinate) at 50 Hz for forward Walk, reverse curved Walk and
continuous steering updates. Each trial asks for Finish at 20 seconds and allows
up to 40 seconds for completion. These are offline commanded trajectories, not
physical contact or distance measurements. Body translation Z is not the chassis
height above the floor.

| Candidate Walk body Z | Forward stance output angle min | Reverse-curve stance output angle min | Reverse-curve straightening clearance min |
| --- | --- | --- | --- |
| -12 mm | 54.47° | 51.49° | 5.00 mm |
| -10 mm | 50.37° | 45.98° | 3.83 mm |
| -8 mm, existing compact candidate | 44.91° | 40.34° | 2.65 mm |
| -6 mm | 38.30° | 33.86° | 1.48 mm |
| -4 mm | 32.50° | 25.19° | 0.43 mm |

At -10 and -12 mm all three trials completed and met all existing leverage
regression floors. Their planted XY target drift was zero. Raising the target to
-2 mm caused a reverse-curve solver failure; at 0 and +2 mm all three cases
failed during gait development. No test floor was weakened. This shows why
"stand taller" is not a sufficient mechanical fix for the current stroke; it
does not establish an optimal height or prove that the lower candidate walks.

The electrical-reference conflict remains: at -10 mm, the historical shared
unmirrored profile computes a minimum of about 162 µs for forward Walk and
130 µs for reverse curved Walk, below its declared 300 µs lower reference span.
Those are offline calculations using the shared source profile, not readings of
the installed per-joint NVS mapping. They were not sent to the robot. Changing
height alone does not reconcile motor zeros, horn indexing or available travel.

Results and input/binary hashes:
[`compact-posture-study.json`](../gait-research/locomotion-modernization-20261012/compact-posture-study.json).
Reproduced with:

```sh
/home/greggles/ComfyUI/venv/bin/python Slave/software/models/v2-12servo/tools/study_gait_posture.py \
  --root /tmp/ainekio-locomotion-modernization-20261012/stage/Slave/software/models/v2-12servo \
  --out docs/gait-research/locomotion-modernization-20261012/compact-posture-study.json
```

The earlier compact migration section describes how the staged source was
assembled from the archived candidate while preserving newer owner work.

### Feedback and learning experiment contract

The owner confirmed an external phone recording is available; no new hardware
purchase is needed for that observation source. Use a fixed view with known
floor dimensions and enough visibility of the feet to measure short-trial
displacement, heading change, body clearance and visible slips. Synchronization
and video measurement tooling are not implemented yet; do not call phone video
automatic real-time feedback. Keep trial videos and raw logs outside the repo.

Training observations can use measured body attitude/angular rates, semantic
forward/turn requests, phase, commanded trajectories and action history. Label
planned support flags and commanded joint positions as planned/commanded, not
measured contact or shaft tracking. IMU-only observations do not supply an
absolute travelled distance, foot force or individual servo load measurement.

The approved learning direction is a small policy adjusting trajectory parameters
such as body height/tilt, landing offsets, lift, phase timing and cadence through
the existing local motion owner. It need not generate twelve raw servo commands
or replace semantic command ownership. First compare against the corrected
geometric and conventional-feedback baselines. Evaluate command tracking using
actual distance and yaw, contact/slip, body motion and completion; report any
tradeoffs rather than optimizing only stillness. Run training on the workstation;
benchmark the resulting policy on P4/Q6A before claiming a deployment rate.

This is consistent with [Policies Modulating Trajectory Generators](https://proceedings.mlr.press/v87/iscen18a.html),
which demonstrated learning quadruped locomotion by modulating a trajectory
generator, including a compact policy using IMU observations. That result
supports an experiment architecture; it is not an Ainekio policy or a guarantee
that Ainekio can learn physical walking from gyro data alone. No policy training,
reward optimization or physical walking trial has occurred in this continuation.

## 2026-10-12 — Live joint readback and compact standing/walking reconciliation

Owner plugged the robot in and authorized proceeding with the saved-calibration
comparison. Read the already connected P4 through the existing authenticated
Body Control gateway, using only calibration `get`. A fresh correlated response
(sequence 5 in that connection) reported saved=true, dirty=false and all twelve
channels assigned. No new gateway, network change, serial reset, firmware flash,
calibration write, Home or motion command was issued. Other ongoing firmware
recording/OTA work in the shared checkout was preserved.

At readback the output was disarmed, output_ready=false, fault=1 (the existing
emergency-disable latch), and all last commanded pulses were zero. This was not
an I2C fault: the status showed zero transfer failures and last_esp_error=0.
The investigation did not clear the latch. Saved motion rate was 3; saved joint
command-speed limit was 1,000 degrees/s. Neither setting measures loaded shaft
speed. Both were left unchanged.

### Actual saved mapping

All channels match joint IDs. The saved angle scale is 11.1111106873 µs/degree
for all joints; shaft_travel_measured=false remains explicit. Carrier model angle
at Home is +1.17°, crank -40.41°, shoulder 0°. The four shoulder Home pulses are
1600, 1670, 1670, 1760 µs in physical RL, RR, FL, FR order.

| Physical leg | Shoulder ID / inverted | Carrier ID / Home µs / inverted | Crank ID / Home µs / inverted |
| --- | --- | --- | --- |
| Rear left | 0 / no | 1 / 2444 / yes | 2 / 2577 / yes |
| Rear right | 3 / yes | 4 / 856 / no | 5 / 723 / no |
| Front left | 6 / yes | 7 / 2444 / yes | 8 / 2577 / yes |
| Front right | 9 / no | 10 / 856 / no | 11 / 723 / no |

The reported pulse_min_us=3 and pulse_max_us=19986 are **PCA timer
representability**, not servo travel. The offline comparison below uses the
source profile's declared 300–3000 µs review window; that is still not a measured
travel/torque envelope for the installed mechanism.

Added `tools/audit_calibrated_gait.py` beside the existing gait audit. It applies
the readback's per-joint mapping after the native source-to-model leg reorder and
float centidegree boundary. Reports retain per-joint extrema and timestamped
witnesses, initial standing targets, source/binary hashes and reference-window
excursions. It never connects to the robot or changes a runtime limit.

Verified its rounded pulses against **production `joint_calibration.c`** compiled
with the read-back records: 37,081 native frames, 444,972 individual joint pulses,
32 cases across old and compact geometry, **zero mismatches**. This checks mapping
math and joint order, not physical shaft angles. See
[`mapper-verification.json`](../gait-research/locomotion-modernization-20261012/mapper-verification.json).

### Results at the owner's saved 1,000°/s command limit

All sixteen cases completed for each of these models at 50 Hz. The source
regression floors and full requested stride/steering ranges were retained.

| Model | Cases missing leverage margins | Cases outside source pulse window |
| --- | --- | --- |
| Current 40/24/24 model | 0/16 | 0/16 |
| Compact 35/20/28 model, Walk Z -8 mm | 3/16 | 7/16 |
| Compact 35/20/28 model, Walk Z -10 mm | 0/16 | 7/16 |

The -10 mm experiment was built in a temporary copy and changes only Walk's
operating body-Z target; its original standing entry and other motions remain.
These finite samples do not qualify all commands, interpolation, collisions or
loaded dynamics. Results at 1,000°/s differ from the earlier source-default-speed
study because common gait-clock retiming changes the sampled phase history.

Compact default forward Walk requires these crank pulse spans under the actual
saved mapping: rear left 1617–3132, rear right 166–1679, front left 1657–3129,
front right 171–1641 µs. The -10 mm candidate still reaches 163–3135 µs in forward
Walk. The posture change resolves the sampled leverage issue, but not the
electrical-reference conflict. These pulse values were **calculated offline and
not sent**. Readback proves which mapping is saved; it does not prove that the
physical horn alignment agrees with the model. Simply changing Home values to
make the numbers fit would also change shaft positions unless the mechanical
indexing/angle reference is reconciled.

### Standing witness directly related to the reported squat/contact problem

At the same commanded body translation (0,0,-8 mm), replaying the **old model's
standing joint angles** on the installed compact geometry places all four full
soles approximately **9.27 mm above the modeled floor**. Solving standing with
the compact model instead gives about **0.15 mm**, consistent with its compact
sole approximation allowance. This is a kinematic mismatch of about 9.12 mm;
it is not a physical height measurement. A free supported body may settle lower
than the commanded model predicts, but these calculations do not simulate that
settling or prove its exact amount. Both geometry files use the same carrier and
crank angle-zero constants, so this comparison does not insert an arbitrary
servo-zero shift.

Under the saved mapping, compact standing changes carrier targets by about
26 µs and crank targets by about 218 µs relative to old-model standing. All
compact standing targets are within the source window (766–2534 µs). Shoulders
retain their individual saved centers. This makes standing a concrete candidate
for physical pose comparison after establishing the installed horn reference;
it does not qualify full walking or imply permission to send the outlying pulses.

Reports:

- [`current-device-mapping-audit.json`](../gait-research/locomotion-modernization-20261012/current-device-mapping-audit.json)
- [`compact-device-mapping-audit.json`](../gait-research/locomotion-modernization-20261012/compact-device-mapping-audit.json)
- [`compact-minus10-device-mapping-audit.json`](../gait-research/locomotion-modernization-20261012/compact-minus10-device-mapping-audit.json)
- [`standing-replay.json`](../gait-research/locomotion-modernization-20261012/standing-replay.json)

Raw gateway/readback data remains outside the repository under
`/tmp/ainekio-joint-reconciliation/`. Reports contain only the relevant numerical
mapping and derived research evidence. The owner was asked whether the compact
carrier/crank horns were installed at the same printed matchmarks as the old
assembly; that physical reference has not yet been established in this check.
No balance controller, learned policy or geometry migration was deployed.

## 2026-10-12 — Owner confirms the installed matchmark reference

Owner reports that the carrier and crank remain installed at the same printed
matchmarks, using carrier/crank pulses 856/723 µs on one side and 2444/2577 µs
on the other. These exactly match the fresh saved P4 readback above. This
resolves the pending question about whether the owner changed the mounting
reference when installing the compact linkage. It is owner-reported assembly
evidence, not an independent shaft-angle or loaded-motion measurement.

`SERVO_ASSEMBLY.md`, the model README and `servo_profile.json` associate the
existing carrier/crank marks with +1.17° / -40.41° at the non-inverted references
856 / 723 µs. Current and staged compact geometry retain identical carrier,
crank and distal angle-zero constants, including all four per-leg crank zeros.
The compact motion retargeting also explicitly excludes servo calibration and
assembly reindexing. There is no evidence in this comparison that Home values
were accidentally changed; preserve the saved mapping during reconciliation.

Found a documentation inconsistency: both geometry files still contain a
`servo_calibration` sentence describing 1650 µs at the carrier/crank matchmarks,
and `provenance.servo_max_travel` repeats that reference. Those historical text
fields conflict with the assembly guide, current saved mapping and owner's
confirmation. They must not be treated as instructions to reset Home. This
entry records the discrepancy without rewriting hash-linked geometry assets
or historical candidate provenance during the investigation.

The compact full-Walk pulse excursions remain a path/mapping compatibility
problem under the confirmed references, not evidence by themselves that the
servos lack torque. Confirming one mounting pose also does not measure the
provisional pulse-to-angle scale. The next physical comparison should establish
whether the installed leg follows the modeled Home/standing poses and assess
foot placement before attributing poor walking to insufficient servo power.
Requested the current servo power/connection and support state before movement.
No calibration, firmware, output latch, or physical pose was changed here.

## 2026-10-13 — Powered robot, awaiting supported pose comparison

Owner reports the robot is active, all servos connected, and all feet on a flat
surface. Requested secure body support with the feet clear for the initial
unloaded pose comparison; support has not yet been confirmed.

Read the connected P4 through the existing gateway using calibration `get`.
All twelve saved mappings match the preceding readback, including carrier Home
856/2444 µs and crank Home 723/2577 µs. Saved=true, dirty=false;
shaft_travel_measured=false. The status reports state=active but
output_ready=false, output_armed=false and output_fault=1 (existing emergency
disable latch). All reported channel pulses are zero. I²C transfer failures are
zero, last_esp_error=0; motion queue depth is zero. These are controller reports,
not measurements of servo supply voltage or actual shaft position.

No movement, output enable, latch clear, calibration write or flash was issued.
Physical pose matching, loaded standing and walking remain untested in this
continuation. Raw status and calibration responses remain outside the repo.

## 2026-10-13 — Supported saved-Home command completed

Owner confirmed the robot is supported with feet clear after reporting all
servos connected. Issued the existing Body Control Home operation. The first
request was rejected with HTTP 409; the gateway audit recorded `mode`, consistent
with the firmware requiring calibration mode for Home. No automatic retry was
made. A subsequent read showed outputs disarmed and channel pulses zero.

Inspected the owning mode and Home implementations, then requested the existing
`calibrate` mode (sequence 6), confirmed that mode in gateway status, and issued
saved Home (sequence 7). The correlated device response reported success,
ready=true, saved=true and dirty=false. All twelve commanded channel pulses
equal their saved Home values: 1600, 2444, 2577, 1670, 856, 723, 1670, 2444,
2577, 1760, 856, 723 µs in model ID order. Follow-up status reported
output_ready=true, output_armed=true, output_fault=0, zero I²C transfer failures
and queue depth zero. The existing mode/Home procedure recovered the previous
output latch; no new recovery mechanism was introduced.

Left the supported robot commanding Home in calibration mode for observation.
Asked the owner whether carrier/crank matchmarks align on all four legs and
whether there is binding or persistent loud buzzing. Physical tracking remains
unconfirmed until that observation; pulse readback is not shaft feedback.
No saved calibration change, firmware flash, standing or walking command was
issued. Raw responses remain under `/tmp/ainekio-joint-reconciliation/`.

## 2026-10-13 — Home alignment confirmed; unloaded Stand observed

Owner reports all carrier/crank matchmarks align at saved Home and there is no
buzzing. This establishes the observed mounting reference on all four legs;
it does not measure the pulse-to-angle scale away from that pose or loaded torque.

While the robot remained supported, returned the existing Body Control mode to
normal, verified that mode, and issued one semantic Stand intent. The gateway
reported a correlated `done` for sequence 7 in that connection, with no pending
command. Outputs remained ready/armed, fault=0, and I²C transfer failures=0.
Fresh calibration `get` reported saved=true and dirty=false. Reported Stand
pulses, in model ID order, were 1600, 2437, 2123, 1670, 863, 1177, 1670, 2437,
2123, 1760, 863, 1177 µs. These are commanded pulses, not encoder measurements.

Owner then reports all four legs moved smoothly with no buzzing. This is a
successful observed unloaded Stand transition, not yet proof of loaded standing
or walking. Left the robot holding Stand in normal mode. Asked the owner to
lower it onto the flat surface with support available and report sole contact,
rocking, sagging or strong buzzing. No further motion was commanded.

### Clarification of the earlier standing replay

The earlier `standing-replay.json` comparison at body Z=-8 mm and initial
pulses 1600/2508/2141/... describes the stationary **Walk starting pose**, not
the separate named Stand command exercised here. `body.c` implements Stand
through `ainekio_v2_walk_pose` at zero stride; `motion.c` uses
`V2_STAND_BODY_Z`, generated as -2 mm in the inspected current native build.
Walk initialization uses `V2_BODY_Z`=-8 mm. Thus the current source requests a
6 mm lowering between named Stand and Walk entry. This is a model-coordinate
change, not a measured physical height change. The previous approximately
9.12 mm old-versus-compact sole discrepancy at Z=-8 remains an offline
Walk-entry geometry result; do not present it as measured named-Stand contact.

No geometry migration, learned controller, feedback correction or calibration
change was deployed in this check. Raw responses remain outside the repository.

## 2026-10-13 — Owner identifies floor drag and specifies feedback-led recovery

Owner reports the robot is standing in its normal leg position. Home is slightly
crouched. During returns to Home/Stand, especially on carpet, shoulders and legs
move toward their targets while feet drag and bind against the surface. The
unloaded transition success therefore does not qualify the transition under
contact. The observation identifies a motion-path/contact problem; it does not
establish a servo torque deficit.

Owner further clarifies the intended behavior: estimate the robot's condition
using the installed IMU and use tailored programmed motions to bring it upright
or correct its movement, rather than using a return to calibration Home as
recovery. This clarification resolves the purpose of the pending Home question:
assembly alignment and operational posture recovery are different tasks.

### Confirmed current implementation

- Explicit calibration Home in `main/body.c` engages assigned channels one at a
  time, at 200 ms intervals, at saved pulses. It has no foot-placement plan.
- Ordinary pose entry uses `ainekio_v2_transition` with a quintic time ramp.
  `transition.c` preserves four-bar closure while interpolating shoulder/crank
  and solving the carrier in linkage coordinates. It does not constrain planted
  sole contact or schedule foot lifts. It is not literally a constant-speed
  linear trajectory, but easing joint motion does not resolve floor drag.
- The existing completed Lay Down/Dead recovery branch retraces its authored
  lift/place/lower sequence in reverse, then aligns to the requested target.
  This is a limited source implementation tied to known completed clips, not a
  general IMU-based recovery from an arbitrary physical posture.
- `ainekio_p4_imu_status()` already exposes body-frame orientation, angular rate,
  acceleration, timestamp/freshness and estimator state. `body.c` does not
  consume it. Current Home/Stand execution cannot adapt to the measured tilt.

### Updated implementation requirements

Use body orientation and angular velocity from the accelerometer/gyro estimator
together with the last commanded joint pose and motion phase. Keep commanded
joint position explicitly distinct from measured joint position: the present
servos provide no shaft feedback here. Ground-contact state from a planned
support schedule remains an estimate, not a foot sensor reading.

Operational Stand/recovery should coordinate body motion with planted supports;
when a foot must change its floor location, lift it, place it and settle it
rather than dragging it through an interpolated joint path. Use authored
recovery sequences for known postures and body-feedback corrections during
execution. End at the standing posture, not the assembly Home reference.
Support-transfer timing, lift height and posture selection must be checked
against the installed compact linkage, existing saved pulse mapping and
physical observations before claiming this works on carpet.

Retain the previously approved walking-feedback behavior: unavailable IMU data
removes only the correction smoothly while commanded gait continues; infeasible
corrections are reduced and reported. This clarification does not define a new
automatic fall threshold, permission to interrupt walking, or an arbitrary-pose
self-righting routine. Those behaviors require concrete definitions rather
than invented triggers. Learning remains a later means to tune the measured
motion outcomes and feedback parameters; it does not replace this contact-aware
execution requirement.

No new physical movement, calibration write or firmware deployment occurred
while investigating this observation. The robot's last issued command is Stand.


## 2026-10-13 — Contact-aware Stand and IMU feedback implemented; combined build

Owner confirms the concurrent firmware session concerns the camera and explicitly
allows these gait changes in the shared checkout. Camera work and project version
were preserved; this session uses its own `/tmp/ainekio-feedback-p4-build` directory.

The production body owner now consumes calibrated, fresh IMU snapshots. Stand and
Walk entry use measured starting roll/pitch with the last commanded joint frame.
A new linkage/contact planner shifts the modeled body pivot toward three supports,
lifts one foot 8 mm, places it, lowers it, and repeats before settling into the
requested posture. It holds modeled planted material-point XY coordinates during
body motion. Authored duration is eight seconds, scaled by the selected motion rate
and existing joint-speed setting. Calibration Home and saved pulse references are
unchanged. Ground contact and body center of mass remain model estimates.

A filtered proportional/derivative attitude correction uses roll/pitch error and
angular velocity. It operates through linkage IK and foot targets in the local
output owner. Standing hold and walking consume it; completed known Lay Down/Dead
recovery now hands over to standing feedback. Missing/stale/recovering observations
fade only the correction. Infeasible corrections are reduced and reported, using
the owner's previously approved behavior. No new fall trigger, automatic stop,
learned policy, contact sensor requirement or raw-servo AI interface was introduced.
Command completion still means the planned trajectory finished, not measured
upright convergence. Telemetry separately exposes measured tilt and corrections.

### Validation and defect found during this continuation

- Production body feedback, contact planner and balance tests pass (three CTest
  entries). The body test uses the saved installed mapping, checks Stand pulses
  against the source's declared 300–3000 us window, and covers standing hold,
  stale-data fade, continuing Walk, disarm and known grounded-posture recovery.
- Added the 80 degrees/s limit with requested rate 3 alongside 1000 degrees/s/rate 1.
  This exposed an entry retiming defect: proportional step shrink approached the
  speed ceiling from above and exhausted retries at authored time 1.624165 s.
  Replaced it with a bracketed time search and included the corrected output frame
  in its speed calculation. Both settings now pass without changing their limits.
- Five geometric Home-to-Stand cases (level and +/-0.05 rad on each tilt axis)
  retain planted XY anchors to under 0.000049 mm in the native model, lift no more
  than one foot at once, and finish at the exact requested joint frame. The modeled
  pivot remains 5.72–6.92 mm inside the three-foot support triangle at worst for
  each case. These are numeric model checks, not measured stability on carpet.
- ESP-IDF 5.5.4 P4 application build succeeds: 2,843,712 bytes, 66% of the 8 MiB
  application slot free. SHA256:
  `3f0e2602cf4521040be03aac8808d830548871fb5c681eab229ec64aa78130fc`.
  Version string remains the camera session's `0.8.25-p4-rolling-logs`.
  The artifact includes current camera/logging source. No claim of runtime timing
  or physical balance follows from this build.

### Original locomotion issues remain open

The shared model now contains the installed compact 35/20/28/38/55 linkage and
retargeted clips. The experimental Walk target retains the full 96 mm sweep with
body Z -12 mm and forward placement bias 18 mm. Saved Home mapping is unchanged.
The calibrated offline audit completes forward Walk (309–2986 us), backward Walk
(318–2983 us), both on-the-spot turns and all four Crawl cases. It still fails IK
for full curved forward/reverse Walk; sampled pulses reach 275/287 us. Forward Run
reaches 240–3060 us and Walk/Run transition 78–3223 us. These are targets under the
saved mapping, not measured servo travel. The legacy clip calibration check also
fails Sit joint 8 at 2995 us against its 400–2900 us assertion, and the full body
suite fails its retained-gesture listening pulse-window check. Assertions and
requested stride/turn ranges have not been weakened to hide these results.

Consequently the current candidate is for a supported Stand/feedback experiment,
not a qualified unrestricted walking release. Walking distance, turning accuracy,
foot slip, loaded tracking, torque, physical support margin and learning-based gait
optimization remain unproven. The owner can record external video for those tests.

Before installation the owner confirmed the robot supported, servo power off, and
no other session flashing. Read-only OTA status found the connected P4 running
`0.8.22-p4-body-maintenance`, ota_0, no pending verification. Raw device responses
and build logs stay under `/tmp/ainekio-joint-reconciliation` and `/tmp`.


### Installation attempt: candidate did not remain running

The authenticated existing OTA owner accepted the 2,843,712-byte upload as staged
and acknowledged activation/restart. Subsequent reconnection reports ota_0 running
`0.8.22-p4-body-maintenance`, no pending verification. This is consistent with an
OTA rollback; the new feedback firmware is **not confirmed running**. No Stand or
Walk command was sent during this attempt. Servo power remained off by owner
confirmation. A startup log is required to distinguish panic, watchdog, power/reset
or another boot failure; no cause is asserted yet.

The owner connected USB, but host-side `lsusb` and serial-device inventory still
show no Espressif device or ttyACM/ttyUSB port. Asked for the previously working
data cable in the top POWER/FLASH/LOGS USB-C connector. Do not repeat activation
without a way to capture the failure. The original application remains connected.

Compiler stack-usage output for the candidate reports output_task 2448 bytes,
start_motion 5904 bytes, balance_apply 864 bytes and posture_sample 768 bytes.
These per-function static frames are not total call-chain or runtime high-water
measurements, and do not establish the reason for rollback.


### Owner correction: Wi-Fi is the update and diagnostic workflow

Owner clarifies the robot now uses Wi-Fi updates and no longer uses USB cables.
The preceding USB request is withdrawn as a required next step. The candidate
upload/activation above already used the existing authenticated Wi-Fi OTA path;
the transport worked. Read-only Wi-Fi checks again confirm the original 0.8.22
application connected in ota_0 with no pending verification and outputs disarmed.
The dashboard log proxy reaches the robot but its `/api/logs` route returns HTTP
404 in that installed version. Thus this application cannot supply the proposed
boot-log download through that endpoint; availability in current source is not
availability on the running robot.

The concurrent camera work has prepared an isolated `0.8.27-p4-wifi-diagnostics`
source/build and a post-attempt status capture that also reports the old 0.8.22
image. This is evidence of shared update/startup work already being investigated,
not proof of a particular failure cause. This gait session did not overwrite that
candidate, repeat its deployment, or send any movement command during these
checks. Keep the Wi-Fi diagnostic work with its existing owner; continue gait
validation separately. Physical feedback operation remains unverified until an
updated application remains running.


## 2026-10-13 — Wi-Fi logging requested; deployment stays with camera session

Owner explicitly requests adding Wi-Fi logs, with the objective of OTA updates
without USB flashing. USB was subsequently attached to assist diagnosis only;
this does not change the OTA objective. Host inventory still did not enumerate a
serial adapter during this check. No USB reset, flash or serial command occurred.

Current source contains authenticated `/api/logs`, its selected-robot dashboard
proxy, and the bounded current/previous-boot recorder. The production recorder's
host test (`python3 Emulator/tests/test_p4_logs.py`) passed, covering wraparound,
warm-reset retention, power-on clearing and nonblocking panic capture. This test
is not evidence that the running application exposes the endpoint. The last live
read in this session still found 0.8.22 and HTTP 404 for logs.

The camera session continued revising and deploying isolated diagnostic images
while this session inspected the source. Its 0.8.31 capture reports a booted
candidate with `pending_verify=true` and `ESP_ERR_INVALID_STATE` from the existing
startup acceptance path. The precise failed readiness condition is not exposed
in that status. Do not label this as a proven gait failure or disable readiness
checks to make acceptance pass.

After a coordination question, owner explicitly selected **Leave deployment with
the camera session**. That session owns firmware uploads, activation and restarts.
This gait session must preserve its logging/OTA edits and avoid competing uploads.
Gait source/model validation and this journal remain here; the supported physical
Stand/feedback test awaits a running combined image and verified wireless logs.
No additional firmware upload, restart, motion or calibration write was performed
by this session during these Wi-Fi logging checks.


## 2026-10-13 — Combined camera/gait image now confirmed running

Owner reports the camera session complete and asks whether firmware was flashed.
Live authenticated Wi-Fi reads confirm version `0.8.34-p4-rolling-logs`, running
and boot slot ota_1, state accepted, pending_verify=false, error ESP_OK. The Wi-Fi
log endpoint returns HTTP 200 (3843 bytes in this read). Body telemetry includes
the balance fields; balance is inactive and outputs are disarmed at this check.
The completed camera-session deployment record states its image includes the
current gait/body build snapshot; later separate IMU telemetry edits are excluded.

The camera session installed this combined image. This session did not issue a
new flash, restart or motion command during verification. The earlier statement
that only 0.8.22 was running is superseded. Loaded Stand/balance and gait performance
still require physical validation; successful OTA acceptance is not that proof.


## 2026-10-13 — Review of broader native gait failures

Owner asks whether the network session's report of motion/calibration failures
and missing NumPy is a valid concern. Inspected that exact run at
`/tmp/ainekio-wifi-native37/Testing/Temporary/LastTest.log`: 35 passed, 13 failed,
three skipped. Targeted body feedback, contact planner and balance tests pass in
that same run. Their success does not qualify the broader gait library.

Failures include mapped pulse-window assertions (Walk 2902 us, Run 2907 us,
Crawl 2902 us, Sit 2995 us, against test window 400–2900 us), commanded gait tick
failures, leverage-margin assertions, source-sampling process failures, and a
geometry-limit fixture assumed unreachable. Several failures can share one cause;
they are not automatically thirteen independent bugs. Some fixtures/requirements
may need reconciliation with the compact geometry, but no assertion should be
weakened merely to pass. The existing source profile's 300–3000 us window is not
measured physical servo travel and does not by itself resolve these failures.

The missing NumPy was in that run's `/home/greggles/.local/bin/python3.10` test
interpreter. Reran `tests/test_upright.py` using the already available NumPy-equipped
`/home/greggles/ComfyUI/venv/bin/python`, without installing packages or changing
code. It gets through the earlier geometric/support checks but then fails line 77:
`min(rows[-1]['arm_reach_mm'][2:]) > 90`. Thus the dependency error hid an additional
reach/expectation mismatch; fixing Python dependencies alone is insufficient.

The network session correctly left motion failures outside its change scope.
This gait session owns their investigation. OTA acceptance and working Wi-Fi logs
remain valid results, but unrestricted walking/turning and gesture qualification
remain incomplete. No physical command or firmware update occurred in this review.

## 2026-10-13 — Native gait failures reproduced and Walk baseline repaired

Owner requested resolution of the gait/calibration failures reported by the
Wi-Fi session. Work is offline; no hardware motion, upload or activation was
performed. Deployment ownership remains with the camera/network session.

The full Debug native build with the existing NumPy/SciPy interpreter reproduced
15 failures among 51 tests (the missing dependency had previously hidden two
Python failures). Full-speed Walk failed at 3390 ms / phase 1.9607397 with the
default joint-speed setting. Debugging localized this to the inverse-crank
assembly-branch selection, not a missing IMU sample or a demonstrated servo
stall. The requested foot trajectory crossed the retained linkage branch.

A level-body, zero-lift workspace screen at 1 mm resolution found a largest
sampled contiguous span of 89 mm satisfying both 400–2900 us and the existing
45-degree stance output / 20-degree input leverage floors. This is a restricted
kinematic screen, not a general hardware reach limit or torque measurement.
The existing 96 mm planted sweep also had pulse and leverage failures in the
full trajectory. Neither the solver's branch checks nor the pulse/leverage
assertions were relaxed.

The owner explicitly approved the prepared **78 mm Walk baseline**. Applied:
body Z -10 mm (2 mm higher), planted sweep 78 mm, placement bias -16 mm.
Saved Home angles, pulse centers, direction flags and device calibration remain
unchanged. An offline 50 Hz / 80 degree/s screen completed straight forward,
backward, left/right turns, forward/reverse curves and steering updates. These
Walk cases mapped to 408–2867 us; weakest measured stance/swing output leverage
in this screen was 49.929 / 44.295 degrees. These are commanded model targets,
not measured foot contact, displacement or loaded performance.

Crawl retains its 18 mm sweep and 4 mm lift. Moving its body from Z -22 to -20 mm
and its placement bias from +4 to -2 mm corrects the pulse excursions without
reducing the commanded stroke. The independent 50 Hz screen mapped its four
basic directions to 411–2843 us.

Validation repairs:
- The impossible-pose fixture now uses carrier 120 degrees / crank zero. Its
  71.586 mm knee-to-crank span exceeds the compact linkage's 66 mm rod + pickup;
  the old 60-degree fixture was physically closable with the new geometry.
- Near-extension validator fixtures now derive a pose 0.15 mm short of the
  actual compact linkage extension, instead of using old-linkage angles.
- Recording validation independently checks the compact contact surface against
  target height. The full-CAD sole allowance previously hid a 0.02 mm wrong
  target; the existing regression now catches it.
- The diagnostic phase sampler uses the current Walk trajectory parameters.
  Archived Blender poses still supply independent IK parity, while a separate
  formula-based comparison checks the current planner across four strides.
- Native calibration fixtures now match the saved shoulder inversion flags.
- Moved the native test assertion compiler option before the first target so
  optimized builds also execute that target's assertions.

Nine focused suites pass: joint_calibration, crawl_calibration, v2_locomotion,
v2_motion, v2_gait_timing, v2_walk_source, body_feedback_execution,
v2_posture_contacts and v2_balance_feedback. This includes 10–40 ms timing,
stride/rate changes, planted-contact continuity, Finish cases and IMU feedback
regressions. Additional validation and repairs remain in progress.

Remaining defects are visible: full Run/Walk-to-Run trajectories and several
stored gestures still exceed pulse/leverage checks. Upright's stored front
crank extrema map to approximately -664 / 3964 us under the saved calibration;
its old >90 mm reach test is also inconsistent with the current stored compact
pose. Those are not resolved by changing the expected reach number. The
recorded gesture paths need reconciliation with the actual available travel.

The owner subsequently approved reauthoring Run to a 78 mm maximum sweep and
revising the affected stored gestures within the existing 400–2900 us window,
including deep Crouch and the two-leg Upright trick. Four-leg Stand is separate.

Run now opens from 64 to 78 mm. Its forward placement bias is -20 mm, body Z
-12 mm and pitch amplitude 6 degrees; the other Run directions use bias -12 mm,
body Z -6 mm and pitch amplitude 2 degrees. The 14 mm maximum lift is retained.
The planner now solves touchdown and next liftoff on the changing phase/duty
schedule during Walk/Run blending, and uses the resulting actual stance interval
to place the next foot. Previously it extrapolated the present offset/duty as
though they would remain fixed. Comparing both implementations with the same
revised parameters reproduced an old-planner failure at phase 24.791 while the
corrected planner completed the broad Run suite. A new regression checks that
newly committed touchdown lies on the future leg phase schedule.

The Run suite checked 3,918,144 leg poses: minimum stance output/input leverage
45.491466 / 56.058903 degrees, swing 41.234958 / 43.701918 degrees, extension
clearance 4.126876 mm. Separate entry/steady/speed-change/Walk-return/Finish
calibration checks passed at 420–2880 us. These remain native commanded geometry,
not evidence that the robot runs or supports dynamic loads.

The optimized RelWithDebInfo native build now succeeds. Its full suite is
**48/51 passing**. Remaining failures: clip_calibration, body_execution's retained
gesture pulse check, and the archived Upright reach expectation. Gesture
reauthoring is being validated in an isolated candidate copy before replacing
shared source assets. No firmware update or physical movement has occurred.

The isolated gesture work now fits Sit, Crouch, Wave, Point, Nod, Pushup,
Freaky, Worm, Shake and Shrug to the saved pulse window. The first bounded
Worm/Shake fits introduced abrupt joins when returning to already-valid source
poses. Independent midpoint FK exposed a 1.16 mm Worm floor penetration;
refitting near the original body path removed that failure. Updated Worm,
Shake, Shrug and Crouch source/monotone-cubic/linear midpoint checks pass the
existing thresholds. These assets are still staged, not adopted or deployed.

Sit's fitted rear soles initially lost much of their broad seated footprint.
Adding the original rear sole orientation to the offline fit preserves that
support geometry while accommodating the front crank travel. Wave must inherit
this exact revised Sit entry, support pose and reverse exit.

Upright needs more than a smaller arm angle. Full-vertical candidates fitting
the pulse window still produced discontinuous paths, negative modeled support
margin or body-hull interference. A flat rear-sole sweep reached a body-clearance
boundary near 77.7 degrees of rearward pitch; this is evidence about that path,
not a proof that all 90-degree maneuvers are impossible. Applying the owner's
approved Upright range revision, the current replacement under development is
a 60-degree rear-leg rise. Its isolated rise segment retains modeled support
and body clearance; the seated entry and foot placements still need complete
path validation. Ordinary four-leg Stand and the continuous walking controller
are separate from this experimental gesture.

The P4 source build with the locomotion repairs completed successfully in the
existing external feedback build directory. Nothing was flashed and no robot
motion was commanded during these repairs. A final build must follow adoption
of the fully validated gesture assets.

## 2026-10-13 — Approved motion revisions adopted; native suite passes

Adopted the approved 78 mm Walk/Run baseline and revised Sit, Crouch, Wave,
Point, Nod, Pushup, Freaky, Worm, Shake, Shrug and Upright assets. Existing
400–2900 us pulse bounds and saved calibration remain unchanged. All 23 compiled
gestures and tested Home/gesture-terminal entry paths fit that pulse window.
The eleven revised paths pass the existing source and midpoint interpolation
geometry checks. These are commanded-geometry results, not loaded-servo proof.

Upright now reaches 60 degrees while retaining the exact revised Sit prefix and
rear planted-foot positions. Independent checks find a 2.87 mm minimum modeled
support margin after Sit, 1.245 mm minimum body clearance and a 1.111-degree
maximum source joint step. Ordinary four-leg Stand remains separate. These
results do not establish physical balance or prove all 90-degree paths impossible.

The complete optimized native suite passes **51/51 tests** with assertions
enabled. NumPy-dependent checks used the existing Python environment containing
NumPy and SciPy. Final executor fixture repairs preserve the original assertions:
scalar entry tests exercise Neutral/Sit rather than contact-planned Stand; the
invalid-reference case uses an actually unclosable compact-linkage pose with a
representable target pulse; completion tests allow the existing eight-second
Stand path plus staged Home; the scheduler workload test starts after actual
entry completion. None of these changes adds a robot timeout or changes motion
timing. Test completion failures now identify their call site and motion state.

An additional comparison of 61,919 compiled gesture samples against their source
interpolation found maximum sole-vertex error 0.009167 mm and maximum clearance
change 0.007173 mm, within the existing 0.1 mm thresholds.

The owner emphasized algorithmic walking and a sound concurrent foundation,
without arbitrary deadlines, blocks or patches. Walking uses calculated foot
trajectories, inverse kinematics, steering/Walk-Run interpolation and IMU posture
correction; it is not yet a learned gait. Stored-gesture work is separate and
must not become a prerequisite for physical walking validation.

The deadline audit found existing runtime behavior beyond desktop test timeouts:
100 ms body-request expiry; a synchronous admission-response timeout that can
disable outputs; 40 ms servo-update progress stops; and a 100 ms task watchdog.
No arbitrary whole-walk completion timeout was found in the body executor.
Clip duration and posture elapsed time select trajectory samples/completion,
not a fault deadline. Scope clarification is pending before changing admission
semantics or removing watchdog behavior. These runtime mechanisms were not
added by the native-test repairs above.

Tracing the caller confirms the admission issue spans `controller.c`'s control
worker, `body.c`'s synchronous `submit`, and the output task's single-result
mailbox. An asynchronous repair must preserve request/result identity and
command receipts, rather than replacing the waits with an infinite wait or
deleting expiry while leaving timed-out requests queued. The shared core also
has a one-second command-queue age and transport command expiry, separate from
motion completion. This audit does not change those protocol semantics.

The final-source P4 build succeeded. Before preparing deployment, comparison
with the camera session's 0.8.37 build found two missing external-build settings:
the existing separate WebSocket transmit lock and its 2000 ms timeout. The gait
build configuration now retains those settings; the rebuild succeeded at
3,032,880 bytes (64% of the 8 MiB application partition remains free). Config
entries match the camera session's external sdkconfig. The candidate retains
the shared 0.8.37 version string, so its image hash must distinguish it from the
earlier camera image. Application SHA-256:
`47e472388298b34476898090875c0905ffb62300a811e1dbd792bd533f7911fd`.
No upload,
activation, restart, calibration write or physical movement occurred in this
repair pass. Supported Stand and recorded walking remain the next hardware
evidence needed; native success does not qualify ground contact, traction or load.

## 2026-10-13 — Owner-directed removal of hardware-stall shutdowns

Owner explicitly requested: “remove hardware stall shutdowns. we do not restrict
or block the robots functions.” Applied to the P4 output path in candidate
`0.8.38-p4-gait-progress`:

- Removed elapsed-time shutdowns in the PCA driver, body frame executor and
  gait sampler, including the old 40 ms progress cutoff and rejection of a
  successful I2C call solely because it took over 5 ms.
- Removed the body task's 100 ms watchdog registration/reconfiguration and
  disabled the P4 application task and interrupt watchdogs in build settings.
- Removed the automatic output disable on a body admission-response timeout.
  Admission expiry and its synchronous request/result contract remain a
  separate unresolved architecture issue; this is not a claim that every
  timeout or blocking call has been removed throughout the system.
- The PCA bus interface now distinguishes timeout from actual transfer error.
  A timeout releases the individual bus call and increments failure telemetry
  without changing OE, output generation or the last completed-frame record.
  The normal frame schedule makes the next write; failed writes never emit a
  successful motion-completion receipt. The existing 5 ms bus wait remains to
  let a stalled bus call return; it is not an output-shutdown deadline.
- Explicit Stop/disarm, generation ownership, actual non-timeout I/O errors,
  invalid geometry/pulse handling and existing network-session handling retain
  their separate semantics. No new guard, movement restriction or replacement
  stall cutoff was introduced.

Native regressions exercise scheduling gaps through one second in the body/gait,
gaps through 60 seconds in the PCA driver, slow successful writes, timeout
resumption without re-arming, Stop during a timeout and final-frame completion
only after successful writing. Output timing and errors remain observable.
These tests model software behavior; no physical stall or powered-motion test
has been performed. Servos can remain energized during a controller or bus
stall under the requested policy.

Validation completed: **51/51** firmware/model native tests pass, plus the
separate PCA9685 driver suite. The added admission-response timeout regression
also passes and verifies that existing energized outputs are not disabled.
The generated P4 configuration confirms task and interrupt watchdogs disabled.
P4 candidate `0.8.38-p4-gait-progress` builds successfully: 3,024,816 bytes,
64% application-partition space free. Application SHA-256:
`3953c67e5b4fb427e96f7d53ff22dbd7c4bfacd7c15cf08037b8ee372ac3adda`.
No flash, restart, NVS/calibration change or robot movement was issued.

## 2026-10-13 — 0.8.38 installed and accepted over Wi-Fi

Owner confirmed the robot was plugged in and ready to flash. Read-only status
found `ainekio-p4-e6ebe5` at 192.168.0.44 running 0.8.37, ota_1, with fresh
calibrated IMU data. Uploaded the tested 3,024,816-byte application image with
SHA-256 `3953c67e5b4fb427e96f7d53ff22dbd7c4bfacd7c15cf08037b8ee372ac3adda`
through the existing authenticated gateway/robot Wi-Fi OTA route. Upload returned
staged, activation required, body Doze. Requested activation with restart.

At 22:40 UTC the robot reconnected at epoch 3. Live firmware status reports
`0.8.38-p4-gait-progress`, running and boot slot ota_0, state accepted,
pending_verify=false and error ESP_OK. IMU data is available/fresh with saved
calibration applied and no recovery flags. Outputs report disarmed with fault
code 1 (the generic emergency/disable code); no I2C failures are recorded. The
cause of that disable was not established by this status read. No re-arm or
walking command was sent. This verifies Wi-Fi installation and boot acceptance,
not physical gait performance. No USB flashing, partition erase or calibration
write was performed.


## 2026-10-13 — Physical walking failure, V1 comparison and owner-directed cadence

Owner reports that 0.8.38 performs a long preparation before walking, rear legs
sag and the chassis touches carpet. Increasing Speed to Run produced
`Command 59 rejected: busy — Motion stopped after execution failed`. These
physical observations supersede any suggestion that earlier native passes
established useful loaded walking.

Read-only gateway audit identifies command 59 as forward=100, turn=100,
Speed=50, followed by accepted updates to 89 and 145 approximately 29 and
40 seconds after start. The original motion failed approximately four seconds
after the latter update. No I2C failure was recorded for that event. The firmware
unconditionally selects the contact-planned entry for new Walk commands;
its four-leg placement and settle schedule totals eight seconds before gait
execution. That explains an entry delay, not the physical rear-leg sag.

Subtracting the eight-second entry gives a native command replay with updates
at 21 and 32 seconds. At 50 Hz and the saved 1000 deg/s joint setting, the previous
gait clock fails at 36.28 seconds. Straight walking with equivalent speed changes
completes. Before failure, the coordinated gait retiming can reduce cadence to
about 74% of the request. This retiming responds to computed joint displacement,
not a foot contact sensor or measured motor load.

Owner explicitly requested continuous gait speed governed by Body Control.
Removed the global joint-budget retry/clock-scaling loop from `motion.c`.
Walking now integrates the full elapsed time for the body, contacts and swings;
posture/gesture timing and the previously approved balance-correction budget
remain separate. No calibration, gait geometry, stride, lift or joint range was
changed. Existing trajectory interpolation and directional reversals remain.
This does not command motor torque or prove physical tracking.

V1 comparison from current repository source: ESP32-S3 semantic motions use
`run_smoothed_frame`, enabled in both sdkconfig.defaults and the local sdkconfig.
Cubic ease-in/ease-out runs over min(frame duration, 300 ms), followed by any
remaining scheduled hold. It preserves the scheduled frame duration, with the
existing 20 ms minimum and tick quantization. No equivalent of P4's adaptive
joint-demand whole-gait slowdown was found in that playback path. The installed
firmware on the eight-servo robot was not inspected or changed.

Cadence verification: **51/51** firmware/model native tests pass. Updated timing
regressions compare identical Run requests under 100 and 20000 deg/s settings:
phase, contact state and commanded joint positions match frame by frame through
irregular scheduling. Automatic and explicit Run maintain the requested steady
cadence through the tested Speed range instead of asserting automatic slowdown.

The real curved Walk/Run replay still fails at 36.10 seconds with clock_scale=1.
A private diagnostic scan at the failing frame finds source leg 1's requested
sole height 7.746 mm, while the highest sampled reachable sole height with the
same foot reference XY and assembly branch is about 7.065 mm. Newton corrections
oscillate; increasing iteration count did not fix the earlier replay. This is
sampled geometry evidence of an infeasible trajectory target, not proof of
insufficient servo torque. The turning trajectory producer requires further
repair. Its failing replay is separate from the 51 passing existing regressions.
No robot movement, flash, restart or calibration write was issued in this pass.

## 2026-10-13 — Geometry-derived stroke study and removal of Walk preamble

Owner reports excessive forward foot placement, crouching and roughly 90° of
carrier/crank travel despite over 230° servo travel. Owner explicitly directs
analysis of the actual leg geometry and redesign if needed, and separately
orders removal of all automatic Home/Stand choreography before Walk.

Read the unchanged live Wireless Blender scene and compared its 35/20/28/38/55
mm mechanism with the repository model. All four foot transforms match within
0.000026 mm translation; the current visible sole support differs from the
compiled profile by at most 0.152 mm including allowance. Hidden alternative
boots were excluded. No Blender geometry, control, frame or action was modified.

Added `tools/study_linkage_workspace.py` and the
[workspace study](../gait-research/locomotion-modernization-20261012/workspace-20261013/README.md).
It samples carrier/crank combinations independently of the current authored gait,
then derives monotonic planted strokes on constant-height contours. The original
Walk is a 78 mm authored foot path centered 16 mm forward at body Z −10 mm; it
was not selected by maximizing this linkage's usable workspace. Native 99% Walk
commands about 105–109° carrier and 109–112° crank travel, not measured tracking.

Level-body results under the pre-existing offline geometry criteria: about
87.6 mm stroke at 40 mm model body clearance, 82.8 mm at 45 mm, 76.1 mm at 50 mm,
and 55.1 mm at 60 mm. Raw closure-only reach is reported separately and extends
closer to near-straight linkage configurations. No new runtime restriction or
angle window was introduced. These are modeled body-hull clearances, not
measured robot height. Mass, supply voltage and loaded servo capability remain
unknown; unused shaft rotation does not directly measure available foot force.
The analytic vertical-load moment arms were checked against independent FK and
finite differences on 546 valid samples, with errors below 0.000017 mm.

Replaying candidates through the complete gait exposed extra foot excursion
from the whole-swing quintic return. At the candidate 78 mm stroke / 45 mm model
clearance, a mostly constant-speed swing return reduces peak commanded joint
speed from about 1,182 to 578 deg/s at the same gait cadence. It also reduces the
reference pulse excursion from about 351 to 390 us. This candidate still extends
past the previous 400 us review endpoint; its height/placement has NOT been
adopted. No pulse window or calibration was widened to make it pass.

Applied the return-shape correction to the existing Walk baseline, reusing Run's
short endpoint ramps and constant middle velocity. The current 78 mm placement
and height remain unchanged pending full workspace-based trajectory validation.
An added native regression checks that the steady Walk return stays within 1%
of stroke beyond its planted endpoints; observed front-left overshoot at 100%
and 100 Hz is about 0.36 mm. This is an offline regression, not a runtime clamp.
The separate curved Walk-to-Run failure remains unresolved.

Removed body-owned preparation from Walk: no contact-planned Stand, reverse
lying-pose recovery, generic pose entry or staged Home before gait execution.
A disarmed/unknown-reference Walk writes its initial gait pose directly; Home
and Stand remain separate commands. Regression checks first-frame phase progress
at 20 ms, direct gait output instead of staged Home and preserved explicit Stand
recovery. Crawl/Crab still retain their own gait-specific stance setup; this
change removes the unrelated body-owner preamble.

Candidate `0.8.39-p4-direct-walk` includes this removal, the already approved
removal of whole-gait cadence reduction and the Walk return-shape correction.
All **51/51** native tests pass; the new endpoint-overshoot regression also passes.
P4 build succeeds, 3,024,384 bytes, SHA-256
`04de235be8fd128183b6ce9eab16f85575be9287b048c013c32f4f3ae6f32bed`.
Owner confirmed the robot is supported with servo power off. Wi-Fi upload
reported staged/activation required and activation reported selected for next
boot. Boot acceptance is checked separately below. No walking command was sent.

At 23:23 UTC, live readback confirms `0.8.39-p4-direct-walk`, running and boot
slot ota_1, accepted, pending_verify=false, error ESP_OK, connection epoch 6.
IMU is fresh with saved calibration applied; output_fault=0 and I2C failures=0.
PWM reports armed after normal startup; the owner had confirmed servo power off.
No assistant-issued walking, Stand or calibration command accompanied the update.
This verifies deployment and startup, not loaded walking or elimination of sag.

### 2026-10-13 — complete-path fit for a taller ordinary Walk

Owner requested immediate work on walking after deployment of direct gait
startup. Adopted the geometry-derived 78 mm full sweep at body Z -4.75 mm,
with its center 12 mm forward of the reference stance. Compared with the old
-10 mm / 16 mm setting this raises modeled nominal hull clearance from 39.25
to 44.5 mm and moves the entire foot stroke 4 mm rearward. These are commanded
geometry differences, not measured loaded clearance. Calibration, stride,
cadence and the removal of automatic Home/Stand before Walk are preserved.

Static 45 mm-clearance candidates were fitted through full swing and curved
paths; they exposed pulse or leverage excursions. The adopted 44.5 mm path
passes all sixteen sampled command cases at both 50 and 100 Hz, including
forward/reverse curves, steering updates and straight Walk/Run transitions.
Existing 400–2900 us review window and leverage margins were not relaxed.
Evidence: workspace-20261013/adopted-walk-calibrated.json. Native suite: 51/51
pass. Added a saved-calibration curve regression for both travel directions
at 50/100 Hz. The separately reported combined curve-to-Run failure remains
unresolved and is not represented by the passing straight transition case.

P4 candidate `0.8.40-p4-walk-height` builds, 3,024,224 bytes, SHA-256
`13a15f0095668fb1ad1c102defa5018c1b608683a521e80f49b1a6016211c150`. Installation and loaded walking are separate evidence steps.

At 23:33 UTC, Wi-Fi readback confirms `0.8.40-p4-walk-height` running and boot
slot ota_0, state accepted, pending_verify=false, ESP_OK, epoch 7. IMU data
is fresh with calibration applied; PCA I/O failures remain zero. Outputs
are disarmed with the existing EMERGENCY reason (1), not an I/O failure;
no gait command has been issued after this installation. Asked the owner
to reconnect servo power and confirm readiness for three forward Walk cycles
at 100% walking speed. Physical walking remains unverified.

### 2026-10-13 23:36 UTC — owner-requested three-cycle Walk

Owner explicitly requested walking cycles. Sent semantic forward Walk through
the existing gateway: epoch 7, sequence 10, three cycles, speed 100%, forward
100, turn 0. Gateway recorded the command at 23:36:24 UTC and controller
reported done at 23:36:31 UTC. No Home or Stand command was sent. Afterward,
output is armed, output_fault=0, PCA I/O failures=0; calibrated IMU data is
fresh and balance is active without reduction. This confirms execution receipt
and feedback activity, not forward displacement or absence of rear-leg sag.
Awaiting the owner's physical observation.

### 2026-10-13 — loaded failure and mechanical leverage comparison

Owner reports the three-cycle test sagged onto the floor without forward
movement, and clarifies that the drop happened during stepping. Physical
walking qualification FAILED despite the controller's done receipt.

Read-only native replay of current full-speed Walk, 8–12 seconds at 100 Hz,
found same-side two-foot support in 45/401 samples (25 on physical left,
20 on physical right); another 35 samples had diagonal two-foot support.
The 0.70 duty fraction with quarter-cycle offsets allows overlapping swings.
This is a concrete support-schedule weakness; it does not prove the sole
cause of the observed sag. Balance currently corrects roll/pitch, not measured
body clearance, support forces or joint tracking.

Owner asked what physical geometry changes improve leverage. Preliminary
planar statics comparison used the same sampled grounded carrier/lower-leg
poses and current sole support vertices, re-solving the crank circle with
the negative inverse branch. Unit vertical foot load gives peak torque arms
(carrier, crank), in mm: current 20/28/38 crank/pickup/rod (43.16,45.46);
18/28/38 (40.72,39.34); 16/28/38 (38.32,33.77); 20/32/38 (37.90,36.27).
Thus 16 mm crank reduces peak vertical-load crank torque demand about 26%
and carrier demand about 11% for this sampled planar comparison. Horizontal
load is a tradeoff: peak carrier arm rises 28.28 to 32.80 mm, while crank arm
falls 40.06 to 33.22 mm. No mass, friction or dynamic load was assumed known.

Separate full-cycle linkage-closure check for 20/18/16 mm crank, retaining
28 mm pickup and 38 mm rod, keeps the installed assembly branch for all
sampled poses. Crank excursion ranges across legs: 100.2–103.0 degrees
(current), 101.0–104.3 (18 mm), 102.8–105.9 (16 mm). A shorter crank therefore
does not automatically use the servo's full travel in this coupled mechanism.
These are candidate design comparisons, not installed calibration, collision,
strength or loaded hardware validation. No CAD, firmware or hardware changes
were made for this comparison, and no further motion command was sent.

Mechanics references: Northwestern Modern Robotics, section 5.2, virtual-work
relation torque = Jacobian-transpose times foot force; Carnegie Mellon
Introduction to Mechanisms, chapter 5.2.4, transmission angle.
https://modernrobotics.northwestern.edu/nu-gm-book-resource/5-2-statics-of-open-chains/
https://www.cs.cmu.edu/~rapidproto/mechanisms/chpt5.html

### 2026-10-13 — crank fixed by physical horn clearance

Owner confirms the crank cannot shorten because of the servo horn. Treat
20 mm as fixed; the earlier 16/18 mm crank proposals are physically excluded.
Compared rod length and lower-leg pickup radius while retaining the actual
carrier and lower-leg poses, 35 mm carrier, 55 mm distal length, current sole
and unchanged motor pivots. Evidence and reproducible calculation are saved
in workspace-20261013/fixed-crank-comparison.{py,json}. No CAD or firmware
change, calibration write, or hardware command was made.

Peak planted vertical-load torque arms (carrier/crank, mm): baseline pickup
28 / rod 38 = 43.16/45.46; rod 42 only = 41.64/40.25; pickup 32 only =
37.90/36.27; pickup 32 plus rod 42 = 37.05/32.33. The combined candidate
reduces these peaks by about 14%/29%, respectively. Under horizontal unit
force its carrier peak increases from 28.28 to 34.23 mm (21%), while crank
peak decreases from 40.06 to 35.65 mm (11%). These separate force-axis peak
comparisons do not establish performance under combined dynamic loads.

All sampled candidate paths close on the installed assembly branch over the
full sampled cycle. Independent central differences of the forward mechanism
agree with analytic contact derivatives within 4.49e-8 mm/rad. The comparison
is planar, with fixed contact vertex for each derivative; actual three-axis
loads, new mounting references, housing/screw collisions, link strength and
physical tracking remain unqualified. Distances are pivot center to center.
Changing the pickup extends the lower leg's rod-attachment lever, without
lengthening its knee-to-foot section.

### 2026-10-13 — shorter distal leg with greater joint sweep

Owner proposes shortening the knee-to-foot section and using more servo
rotation to preserve stride. This is a valid kinematic design direction,
but torque savings cannot be inferred from length ratio alone at a preserved
foot path. A single rotating link illustrates reach: a 55 mm radius sweeping
90 degrees has a 77.78 mm endpoint chord; 45 mm sweeping 120 degrees has
a 77.94 mm chord. This is not a four-bar prediction or a constant-height
stance trajectory. Vertical support torque about the knee depends on the
horizontal knee-to-contact offset; preserving that offset preserves its
vertical-load moment regardless of nominal lower-leg length. A full redesign
must compare vertical reach, joint speed, carrier/crank transmission and
combined support/propulsion loads. No shorter distal leg has been adopted.

### 2026-10-13 — shorter rod and lower-leg stance angle

At the native Walk initial front-left pose, holding carrier/crank angles
fixed, shortening the rod rotates the lower leg rearward on the current
assembly branch. With the existing 55 mm distal section: rod 38→36 mm
rotates it -4.09 degrees and moves its reference point -3.51 mm fore/aft,
-2.60 mm vertically; 38→34 gives -8.19 degrees, -7.19/-4.95 mm; 38→32
gives -12.33 degrees, -11.07/-7.05 mm. Positive fore/aft is forward; the
reference point moves backward and downward. The knee-to-reference line
changes from 38.65 degrees forward of vertical to 30.46 with the 34 mm rod.
This is a fixed-angle modeled pose comparison, not a 35 mm distal-leg test
or a measured hardware change. Correctly updating IK while retaining the
old foot targets would compensate joint angles and restore those targets;
rearward gait stance placement must be authored explicitly. No motion sent.

### 2026-10-13 — owner revises distal-leg target to 45 mm

Owner progressed from 35 mm (reported too short), through a 40 mm trial,
to a current 45 mm knee-to-foot target. Part 027 contacts the floor directly;
separate boot meshes must not define the new contact model. Owner is also
considering shortening the carrier and the knee-to-rod pickup arm. These
dimensions remain exploratory; the production geometry has not been changed.

Terminology correction: the independently driven carrier and crank, rod,
lower-leg pickup segment, and fixed servo-mount segment form a five-bar
closed chain (five revolute joints, two planar degrees of freedom). Calling
the complete mechanism a four-bar was imprecise. The foot is an extension
of the pickup link. MIT Introduction to Robotics chapter 3 section 3.2
describes this two-actuator five-bar structure.

There is no universal ideal length ratio. For a 45 mm distal leg, the
existing 28 mm pickup gives pickup/leg = 0.622; a 32 mm pickup gives 0.711.
At equal rod force and equal rod-to-pickup angle, shortening pickup 28 to
20 mm reduces knee torque by 28.6 percent. This local lever comparison is
not a prediction of complete robot foot force: crank transmission, carrier
load, pose, and contact-force direction must also be included. No new
carrier, pickup, or rod dimension has yet been qualified for the 45 mm leg.

### 2026-10-13 — concrete 45 mm dimensional candidate

Owner requests specific dimensions, including an opportunity to shorten
carrier or rod. Preliminary comparison of 45 combinations: carrier 30/32/35,
pickup 24/26/28, rod 30/32/34/36/38, crank fixed 20, distal leg fixed 45 mm.
At nominal hull clearance 35 mm and a 70 mm planted sweep, the best sampled
combined-load score was carrier 35, crank 20, pickup 28, rod 30, distal 45 mm.
This is the recommended next CAD comparison, not a universal optimum.
It shortens the rod 8 mm without shortening the pickup's torque arm.

Scope: planar static stance, existing servo datum and 400–2900 us review
window, fixed assembly branch, existing offline transmission-angle/closure
criteria. Contact is an analytic 7.5 mm radius rounded foot centered 45 mm
from the elbow, not the complete new CAD mesh. Angular grid 1.125 degrees,
contour interpolation; score is worst absolute vertical torque arm plus
0.3 times horizontal torque arm, not measured traction or actuator load.
Candidate sampled stance span 70.21 mm, carrier excursion 75.94 degrees,
crank excursion 130.10 degrees. Its selected interval touches the existing
crank calibration boundary; full swing and alternative foot placement must
be evaluated before a runnable gait is adopted. Complete path, collisions,
all-leg support, physical tracking and load capacity remain unverified.
Candidate maximum sampled stance span 84.94 mm is not a commanded stride.
Results: workspace-20261013/leg45-preliminary-dimension-comparison.json.
No production geometry, firmware or robot commands changed.

### 2026-10-13 — predicted force and angular travel, 45/30 versus 55/38

Repeated planar comparison at 0.375 degree angular sampling with identical
7.5 mm circular foot-contact approximation for both distal lengths. Carrier
35, crank 20 and pickup 28 stay fixed. For each geometry independently,
select the lowest combined-load score over a nominal 70 mm planted stroke
at 35 mm hull clearance. Baseline distal 55 / rod 38 score 49.0073 mm;
candidate distal 45 / rod 30 score 42.2892 mm. This is 13.7 percent lower
peak conservative torque demand, or 15.9 percent higher allowable force
scale for equal carrier/crank torque ratings under this comparison scenario.
The load envelope uses |vertical derivative| + 0.3*|horizontal derivative|;
it is not a measurement of friction, servo output torque or dynamic load.

Stance placement differs: baseline foot reference X 51.15–121.32 mm versus
candidate 33.78–103.99 mm, in the model front-left world frame. Consequently
this compares each geometry's chosen stance, not an isolated link change at
identical foot positions. Carrier angular excursion: baseline 97.96 degrees,
candidate 75.94 degrees. Crank: baseline 114.18, candidate 130.09 degrees.
Candidate uses about 33/57 percent of a nominal 230 degree servo range in
the planted phase. This does not predict full-cycle range or confirm actual
shaft travel. The candidate starts at the reviewed crank pulse boundary;
lift/return and finite-cycle transitions still need solving. The force
comparison does not establish successful walking or explain all observed sag.
Results: workspace-20261013/leg45-versus55-preliminary.json.

### 2026-10-13 — longer planted stroke for the 45 mm candidate

Owner requests greater fore/aft travel and asks whether reduced linkage
travel increases carrier load. Repeated the same preliminary 45/35/20/28/30
distal/carrier/crank/pickup/rod analysis at nominal sweeps 70, 78 and 82 mm.
At 35 mm body clearance, resulting carrier/crank excursions are respectively
75.94/130.09, 88.69/133.72, and 95.44/134.62 degrees. The sampled 82 mm
interval is 82.043 mm; combined-load score increases from 42.289 to 43.009
mm (1.70 percent). Peak vertical torque arms carrier/crank are 41.369/28.521
mm at 70, 41.369/33.467 at 78, and 41.369/37.546 at 82. The longer stroke
increases peak crank vertical-load torque by 31.6 percent relative to the
70 mm candidate, while the peak carrier value is unchanged. Different peaks
need not occur at the same pose. Shoulder load is outside this planar model.

82 mm is the next research stroke target, not an installed gait. It is
17.1 percent longer than the comparison's 70 mm and 5.1 percent longer than
the existing 78 mm firmware sweep. The selected interval still starts at
the crank calibration endpoint. Rounded-foot approximation, load assumptions,
support/contact limitations, and unresolved complete swing/transition and
collision checks from preceding entries all remain applicable. No production
configuration or firmware changed. Angular excursion alone does not determine
carrier torque; both joint derivatives and contact-force direction matter.
Results: workspace-20261013/leg45-longer-stroke-preliminary.json.

### 2026-10-13 — Blender 70 versus 82 mm complete-cycle demonstration

Owner explicitly requested editing Blender to demonstrate both strokes.
Live Wireless CAD now has 45/35/20/28/30 mm distal/carrier/crank/pickup/rod.
Exported actual evaluated Part027 vertices from all four legs. Built a new
`Gait - 70 vs 82 mm` scene with both robots side by side, preserving Wireless
and previous gait/motion scenes and their actions. Existing playback manifest
contained obsolete part names; preview uses current renamed leg meshes and
omits the old boots/foot reference. Detached rear helmet omitted only from
the comparison. Saved copy:
`Slave/hardware/v2-12servo/Ainekio-45mm-70-vs-82-Stroke-Study.blend`.

Both options use a fixed body frame, 35 mm nominal hull clearance, 2 second
cycle, 75 percent stance, quarter-cycle leg offsets and 12 mm sole lift.
Planted foot-reference motion is linear in time. Lifted return uses a quintic
fore/aft path matching planted endpoint velocity and a smooth height bump.
Ground slide in this fixed-body visualization is body-relative motion, not
physical traction simulation. No support/COM dynamics or measured contact.
Full IK solutions sampled at 120 Hz close to <1.6e-11 mm residual. Eight
Blender phase checks of all eight displayed feet agree with ground/12 mm
lift within 0.00005 mm. Rendered views inspected. This establishes kinematic
and mesh placement consistency, not collision or hardware qualification.

Complete-cycle excursions: 70 mm carrier 90.31 / crank 144.86 degrees;
82 mm carrier 110.16 / crank 156.22 degrees. Owner asked whether 156 applies
at 100 percent Walk: it is the proposed full 82 mm stride study, not the
current installed speed-slider mapping. Run has not been retargeted.

The full return reveals two unresolved issues concealed by the stance-only
comparison: crank pulses reach 379.09 / 373.37 us versus the reviewed 400 us
endpoint; peak commanded crank velocities at the two-second cycle are about
952 / 1142 degrees/s for 70 / 82 mm. Carrier peaks about 555 / 657 degrees/s.
Minimum crank-to-rod transmission angles are 23.20 / 9.28 degrees; the
82 mm return approaches poor input transmission. Inverse branch stays
negative throughout both cycles. No pulse clipping, runtime changes or
automatic gait slowdown was introduced. Return path needs redesign before
deployment; the greater stroke is not yet a solved physical walking gait.

Reproducible source mesh export, solver, complete cycles, metrics, plots,
preview builder and image are in
`docs/gait-research/locomotion-modernization-20261012/stroke-comparison-20261013/`.

### 2026-10-13 — owner identifies forward foot placement / support omission

Owner rejects both previews as walking solutions: feet appear too far forward
and posture transfers excessive load to the legs. Audited live-preview hip
frames, actual bare-foot lowest vertices and three-foot support triangles.
The 82 mm rear foot reference spans approximately -5.9 to +76.1 mm relative
to its hip over the full planted sweep; front spans -45.9 to +36.1 mm.
The same canonical mechanism-space path therefore does not produce the same
hip-relative placement in front and rear assemblies. The differing offsets
must be incorporated into whole-body foot placement; shifting all legs by one
global bias is not a sufficient design method.

Model mass is null; COM [0,0,65] is explicitly provisional. Under its XY
projection [0,0], 226/240 (70 mm) and 202/240 (82 mm) sampled three-foot phases
are outside the point-contact support triangle. Worst signed margins are
-16.56 and -22.50 mm respectively. Linear programming over every triangle's
halfplanes finds best possible FIXED COM margins of -14.68 / -16.79 mm.
Thus no fixed body-relative COM can give positive static margin for these
specific cycles under the point-contact assumptions. Body shifts, different
placements/timing, or an explicitly modeled dynamic gait are needed. This is
not a measurement of the hardware COM or a general impossibility result for
the mechanism. Sole contact width and dynamics were not included.

Documentation: CMU Robot Planning 16-350 footstep-planner lecture describes
COM shifts and support-based foothold planning:
https://www.cs.cmu.edu/~maxim/classes/robotplanning/lectures/casemanipandarticrobots_16350_sp25.pdf
MIT Cheetah 3 convex MPC plans contact forces for body dynamics:
https://dspace.mit.edu/entities/publication/bc8c7e1e-5830-443f-a879-787947111fcf
MIT Wensing et al. 2015 describes hip-relative foot placement combined with
stance torso control:
https://www.mit.edu/~pwensing/Papers/Wensing_et_al-2015-AURO.pdf

The earlier torque ranking used an assumed per-foot force envelope, not
whole-body load distribution, and cannot establish a mechanically optimal
robot gait. The dimensional recommendation remains a local kinematic
candidate, not an ideal whole-body design. Next analysis must couple body
mass/COM assumptions, support phases, foot placements and joint torque.
Results and reproducible support check saved alongside the comparison.

### 2026-10-13 — 82 mm whole-body support and carrier/crank load comparison

Owner authorized linkage and servo-mount research, clarified that the 28 mm
dimension is the lower-leg knee-to-rod pickup spacing, and requested similar
carrier/crank loads. Retained 45 mm bare Part027 ground contact and 20 mm crank.
The live Wireless source now has 35 mm carrier / 28 mm pickup / 30 mm rod;
the comparison below is new concept geometry, not installed hardware.

Corrected an earlier interpretation: the rear shoulder shaft is longitudinal,
and its carrier pivot is about 26 mm forward of the shoulder origin. A foot
being forward of that shoulder origin does not itself establish sagittal
overload. Foot placement and torque must use the actual carrier/crank pivots,
contact positions and applied forces. Front/rear carrier pivots are near
world X +66.69 / -66.72 mm. New nominal foot-path centres use these positions,
about 9 mm rearward of the previous fixed-body comparison centres.

Replaced the fixed-body preview with a coordinated 82 mm nominal stance sweep,
80% stance, two-second cycle, quarter-cycle foot offsets and approximately
10 mm return lift. The body shifts approximately +/-5.8 mm fore/aft and
+/-14.5 mm sideways during walking. Nominal forward progression is 102.5 mm
per cycle. There is no separate Home/Stand preparation sequence in this study.
Actual body-relative sweep varies with this body shift; 82 mm denotes the
nominal planted reference sweep, not measured distance travelled.

Support calculations assume a centred torso point mass and include horizontal
torso acceleration. The effective ground-pressure point, rather than only the
static COM projection, must lie in the planned support polygon. Phase-shaped
force caps model unloading before lifting and loading after placement during
four-foot overlap. Three-contact reactions solve force/moment equilibrium;
four-contact allocation minimizes squared joint demand. These are offline
design calculations, not force control implemented on the robot. Contact forces
are not measured. The optimizer does not model complete compliant contact
dynamics or guarantee smooth real force tracking.

Calculated torque uses tau = J-transpose F at the actual lowest mesh contact
point, with the shoulder-frame reflection handled in the lateral Jacobian.
Finite-difference checks independently checked the analytic Jacobian. Joint
return paths use endpoint position/velocity interpolation plus an optimized
airborne shape; stance paths and the two-second cadence remain unchanged.
This removes the earlier folded return's excessive crank excursion without
clipping pulses or introducing a runtime slowdown.

| Quantity | Candidate A | Candidate B |
| --- | ---: | ---: |
| Carrier / pickup / rod (mm) | 40 / 28 / 30 | 45 / 32 / 34 |
| Crank / knee-to-foot (mm) | 20 / 45 | 20 / 45 |
| Actual lowest static body clearance (mm) | 43.02 | 53.02 |
| Peak carrier torque, Nm/kg total robot mass | 0.2395 | 0.2075 |
| Peak crank torque, Nm/kg total robot mass | 0.1245 | 0.1309 |
| Carrier/crank ratio of cycle peaks | 1.92 | 1.58 |
| RMS carrier / crank torque, Nm/kg | 0.1203 / 0.0649 | 0.1067 / 0.0602 |
| Peak commanded carrier / crank speed, degrees/s | 466.7 / 466.7 | 444.2 / 560.5 |
| Full-cycle carrier excursion, front / rear, degrees | 89.0 / 64.4 | 80.1 / 63.3 |
| Full-cycle crank excursion, front / rear, degrees | 117.5 / 126.1 | 107.3 / 114.1 |
| Sampled pulse range, us | 577.0–2723.0 | 585.3–2714.7 |
| Minimum effective support margin (mm) | 2.27 | 2.55 |

Candidate B reduces the larger carrier peak by 13.4% versus A and raises body
clearance by 10 mm; crank peak load rises by 5.2% and its peak return speed
rises by about 20%. Load sharing improves between these two candidates, but
is not equal. The quoted ratio compares separate peaks, not simultaneous
torques. RMS imbalance remains about 1.77 for B. Increasing both demands just
to obtain a 1:1 ratio would not be an improvement. This is a tested comparison,
not proof of a globally ideal ratio or mechanism.

The taller candidate uses a LONGER pickup and rod than the current live CAD;
shortening every link did not emerge as the best answer to support/load demand
in the tested set. A coarse alternative crank-pivot study found no additional
stance-closing tall layouts in its sampled set. It is not an exhaustive mount
optimization. Candidate B also does not retain the previous 156-degree crank
excursion: its reconstructed return uses about 107–114 degrees. Useful loaded
stroke, body clearance, torque and return speed are the comparison criteria;
servo angular travel alone is not a performance result.

Both reconstructed full cycles close at all 120 samples per cycle, clear the
ground to numerical precision and fit the unchanged 400–2900 us review window.
Independent analytic/finite-difference Jacobian maximum discrepancy was
0.001913 mm/rad for B and 0.000000688 mm/rad for A at the checked samples.
Equilibrium residuals are below 6e-8 for the retained candidates. Blender's
evaluated Part027 meshes agree with calculated sole height within 0.000021 mm
over 72 checked leg/pose combinations. These are sampled numerical checks;
they do not establish collision clearance, continuous-time robustness or
physical walking capability.

Live Blender scene: `Gait - 82 mm body support`. It shows A/B side by side,
forward body progression, supporting-contact polygons, assumed COM markers,
effective pressure-point markers and stored animated joint load properties.
Source Wireless CAD and other scenes are retained. Meshes in the new scene
are deformed preview copies preserving pivot regions, not manufacturing-ready
parts. Saved copy: `Ainekio-82mm-Body-Support-Study.blend` in the V2 hardware
folder. Reproducible scripts, actual source foot/frame export, trajectories,
verification results, preview and load plots are in
`docs/gait-research/locomotion-modernization-20261012/body-support-20261013/`.

Limitations: actual mass/COM and motor torque-speed capability are unmeasured;
leg/servo inertia, friction/slip, compliance and collisions are not qualified.
An optional owner question about measuring front/rear supported weight remains
pending. The assumed support margins are only a few millimetres, so these
calculations do not establish robustness to a different real COM. No firmware,
calibration, hardware commands or manufacturing source geometry were changed.
The last physical walking result remains failure by sagging during stepping.

Technical reference for converting contact force to joint load:
https://modernrobotics.northwestern.edu/nu-gm-book-resource/5-2-statics-of-open-chains/
The COM/contact-planning sources in the preceding entry also apply here.

### 2026-10-13 — installed 55 mm parts confirmed; upright planted-path comparison

Owner confirms no new parts have been printed: installed dimensions are
55 lower leg / 35 carrier / 38 rod / 28 pickup / 20 crank (mm). Owner reports
that legs become nearly horizontal, the body strikes the ground during steps,
and it cannot recover. This is physical failure evidence, not successful
walking. Prior 45 mm studies describe candidate CAD only.

Read the preserved `Wireless - Original 55mm Legs` scene and exported the bare
Part027 mesh (6627 vertices) in its foot-anchor coordinates. Earlier firmware
contact research used separate Part020/021/022 boot components; this new study
uses bare Part027 as shown in the owner's photograph. Source scene and hardware
are unchanged. Carrier/crank pivots and angular datums come from the existing
geometry, with the calibrated 400–2900 us mapping retained.

Computed level-body, shoulder-neutral, planted straight paths at several
heights and strokes. Foot centres were searched at 1 mm offsets from -25 to
+40 mm relative to the carrier pivot; the valid path with centre nearest that
pivot was selected at each height/stroke. Each path has 401 samples. This is a
stance comparison, not a complete gait: no airborne return, lateral body shift,
whole-body force distribution, collisions, dynamics or actuator tracking are
qualified. Heights use the model's 47.273 mm lowest static-body datum. They are
model clearances, not measured physical clearances.

| Installed parts: stroke / model clearance (mm) | Centre forward of carrier (mm) | Minimum lower-leg angle above horizontal | Peak carrier / crank torque per 10 N upward foot force (Nm) | Carrier / crank travel during stance (degrees) |
| --- | ---: | ---: | ---: | ---: |
| 78 / 43 | 22 | 24.7 | 0.413 / 0.546 | 100.6 / 104.0 |
| 60 / 53 | 15 | 36.8 | 0.351 / 0.416 | 65.4 / 85.0 |
| 40 / 53 | 5 | 42.0 | 0.351 / 0.299 | 36.8 / 65.2 |
| 40 / 58 | 7 | 46.2 | 0.314 / 0.288 | 36.4 / 63.5 |
| 40 / 63 | 10 | 51.7 | 0.282 / 0.320 | 38.0 / 64.4 |

The 40/58 path uses the existing parts, keeps the loaded leg farther from
horizontal and reduces carrier/crank peak vertical-load demand by about
24% / 47% versus the 78/43 path above. It improves load sharing without
reprinting. These are two newly calculated paths; the 78/43 row is not an
exact replay of the installed firmware. Raising the body alone is not a
monotonic torque improvement: 60 mm stroke at 58 mm clearance increases
crank demand to about 0.730 Nm per 10 N. No calibrated 78/82 mm candidate was
found at 53/58/63 mm clearances in this sampled placement range and branch.

At the same 40 mm stroke / 58 mm clearance, choosing the nearest feasible
centre separately for each geometry gives:

| Leg / carrier / rod / pickup / crank (mm) | Centre offset (mm) | Minimum lower-leg angle | Peak carrier / crank Nm per 10 N |
| --- | ---: | ---: | ---: |
| 55 / 35 / 38 / 28 / 20 installed | 7 | 46.2 | 0.314 / 0.288 |
| 55 / 35 / 36 / 28 / 20 | 2 | 48.4 | 0.334 / 0.283 |
| 55 / 35 / 34 / 28 / 20 | 0 | 49.4 | 0.353 / 0.298 |
| 55 / 35 / 38 / 32 / 20 | 10 | 45.2 | 0.272 / 0.232 |
| 45 / 40 / 30 / 28 / 20 earlier A | 0 | 49.2 | 0.425 / 0.393 |
| 45 / 45 / 34 / 32 / 20 earlier B | 0 | 41.9 | 0.390 / 0.252 |

This comparison does not isolate link length alone because the nearest feasible
path centre changes. It does show that shortening the rod does not automatically
reduce carrier demand, and the shorter-leg proposals do not dominate the
existing hardware at this common stroke/height. The 32 mm pickup option needs
a different lower-leg part and is not the first no-print candidate.

Torque uses the actual foot-contact Jacobian under a specified 10 N vertical
force. It excludes horizontal traction and inertial/impact forces. These units
are NOT the previous whole-robot-mass-normalized Nm/kg values. Independently
checked the analytic Jacobian by central differences at six path poses:
maximum discrepancy 2.37e-8 mm/radian. All rows listed above close on the
selected assembly branch and fit the current pulse mapping for stance.

Read-only replay of the existing native `v2_walk_command` binary at 100% Walk,
8–12 seconds, yields commanded loaded lower-leg angles of about 20.2–68.8
 degrees with the installed linkage. This is offline binary output, not live
shaft tracking. The photograph's flatter collapsed pose cannot establish the
commanded angle or cause by itself. Commanded shallow stance and physical
loss of support must be distinguished; load, speed, power delivery and support
transfer remain possible contributors.

Artifacts: `docs/gait-research/locomotion-modernization-20261012/installed55-20261013/`
contains the original bare mesh export, calculation scripts, comparison JSON,
independent verification and an illustrated 78/43 versus 40/58 stance plot.
No firmware, calibration, Blender geometry or hardware commands were changed.
Next proposed calculation is the complete return/support cycle for the existing
55 mm geometry at the promising upright operating point; stance feasibility
alone does not establish a working cadence.

### 2026-10-13 — owner opens geometry design; printed inventory and measured mass

Owner requests designing from useful proportions before restricting the answer
to previously selected sizes. All link lengths and servo pivot placement may be
considered. Owner identifies the servos as MG90, supply as 5 V, and assembled
robot mass as 566 g. These are owner-reported physical inputs. Exact MG90 maker,
variant and loaded torque-speed curve remain unmeasured. Weight is approximately
5.55 N; equal three-foot static support would be 1.85 N per foot. Earlier tables
using 10 N per foot were normalization comparisons, not actual measured loads.

Clarified that the prior 82 mm body-support scene increased carrier length;
its crank remained 20 mm. A longer crank is not automatically more foot force.
For identical installed-geometry 40 mm / 58 mm planted paths, changing only
crank length gives these peak carrier/crank demands per 10 N vertical force:
20 mm: 0.314 / 0.288 Nm; 24 mm: 0.384 / 0.397 Nm;
28 mm: 0.530 / 0.547 Nm; 32 mm: 0.770 / 0.778 Nm.
Crank travel falls approximately 63.5, 57.6, 53.7 and 50.8 degrees respectively.
The 24 mm substitution increases crank torque demand by about 38% at this
operating point. All four sampled stance paths close and fit existing indexing.
This is a controlled single-dimension comparison, not a universal statement
about every mechanism using a longer crank.

Measured STL inventory directly; no Blender import or source geometry edit was
needed. Method: identify a broad planar face, section the mesh parallel to that
face at multiple depths, fit closed circular bore contours, compare bore axes.
Horn screw holes were distinguished from the shaft and distal joint axes.
Initial PCA-plane trials were discarded because tilted sections biased fits;
the retained inventory uses actual planar-face normals. Files named by owner:

- `STL/Red/legs&bottom/... FL Part_027 - 24mm pickup ...stl`:
  24.00 mm pickup, knee-to-outer-toe extent 62.5003 mm; subtracting the existing
  7.5 mm toe radius gives a 55.0003 mm knee-to-toe-centre length.
- `STL/Red/009_Crank_R_L/... FR Part_009 - 24mm ...stl`:
  24.00 mm shaft-to-joint spacing.
- `STL/Red/LR_Carrier_legs/... RR Part_023 - 4.9mm outside-horn ...stl`:
  40.00 mm shaft-to-knee spacing. 4.9 mm in its name is not carrier length.
- `short-carrier-lr` examples measure 35.00 mm; `shorterl-legs-crank` examples
  measure 20.00 mm crank and 28.00 mm pickup.
- Rod meshes under `linkage_026_r_l_41mm` and `black-link`, despite their 41 mm
  filenames, measure 38.00 mm between bore axes. Filenames alone are not evidence
  of current dimensions. Inventory does not confirm quantities of physical prints.

The owner-supplied 55 / 40 / 38 / 24 / 24 combination (leg / carrier / rod /
pickup / crank) closes the same 40 mm / 58 mm / +7 mm-centred stance path but
requires about 0.595 / 0.565 Nm per 10 N, versus installed 0.314 / 0.288.
It is not a demonstrated low-load substitution at that operating point.

Broader analytical study sampled 65,536 candidate mechanisms, split equally
between existing and variable crank-pivot positions. Fixed task: centred 82 mm
planted stroke, 80% stance, 10 mm Cartesian return lift, two-second cycle.
Initial ranges: carrier 25–80, lower leg 35–80, crank 20–40, pickup 20–50,
rod 25–85, model body clearance 40–100 mm. Variable crank pivots span X -30..10
and Z -10..30 mm relative to carrier; existing is about -12.5 / +11.5 mm.
This is a bounded exploratory search, not all possible sizes or topologies.

Compared closure/assembly branch, 225-degree available shaft excursion with
potential new physical indexing, loaded lower-leg angle, peak vertical-load
moment arms, an illustrative Fx=+/-0.3 Fz traction envelope, and full-cycle joint
speeds. A 45-degree loaded-leg-angle criterion identifies the upright subset;
these criteria and speed bins are research comparisons, not firmware limits.
669 existing-pivot and 725 relocated-pivot samples met that subset definition.
The planar screening foot is a circular 7.5 mm toe. New shapes were subsequently
checked using reshaped copies of the actual bare Part027 mesh, preserving joint
regions. New-geometry mass changes, collisions, compliance and moving-link inertia
are excluded, so this search cannot establish a global or physically ideal ratio.

One local low-torque planar result rounded to leg81/carrier22/rod25/pickup51/
crank36 mm at 74 mm clearance. Its isolated 82 mm cycle closes, holds the leg
above 56 degrees, and gives approximately 0.260 / 0.260 Nm per 10 N. However,
reusing the whole-body support shifts makes it lose geometric closure. It is
REJECTED as a complete walking recommendation, despite the attractive isolated
load calculation. Do not print or deploy it as an established optimum.

A nearby reference family retained for further mechanical review is:

| Dimension | Installed | Supplied STL combination | Research reference |
| --- | ---: | ---: | ---: |
| Lower leg, knee-to-toe centre | 55 | 55 | 72 |
| Carrier | 35 | 40 | 26 |
| Connecting rod | 38 | 38, measured separately | 26 |
| Lower-leg pickup | 28 | 24 | 43 |
| Crank | 20 | 24 | 28 |

Research-reference ratios normalized by lower-leg length are approximately
1 : 0.361 : 0.361 : 0.597 : 0.389 in that order. These describe a candidate
family, not a universal ideal. Useful changes are combined: shorter carrier,
larger pickup relative to the foot, shorter rod and a moderately longer crank.

The 72 mm candidate was checked with the previous 82 mm whole-body support
trajectory, actual shoulder frames and a reshaped bare-foot mesh. At model
clearance 64 mm, both stance and a reauthored airborne return close at all 120
samples per cycle; sampled ground clearance error is numerical roundoff.
Minimum loaded lower-leg elevation is 48.22 degrees. Body support remains an
assumed centred point mass with model COM height about 81.73 mm; minimum
effective support margin is 2.69 mm, and force-equilibrium residual is 4.7e-12.
No claim is made that the real COM has that position.

Using 566 g as the fixed comparison mass, calculated supporting-load peaks are:
shoulder 0.1057 Nm, carrier 0.0773 Nm, crank 0.0606 Nm. The shoulder is now the
largest modeled servo demand; balancing only carrier/crank would miss it.
These exclude link inertia and impacts, and the redesigned robot may weigh
something different. Peak demands are not simultaneous equal load shares.

After return-path refinement, maximum full-cycle excursions over all legs are
18.6 degrees shoulder, 94.3 carrier and 154.7 crank. At a two-second cycle,
peak commanded speeds remain 33.9 / 600.6 / 645.6 degrees/s. The crank's fastest
sample is near the end of a planned stance with only about 0.0028 Nm modeled
load; airborne crank peak is about 619 degrees/s. This is still an unresolved
speed/inertia feasibility issue, not proof that an MG90 can track the trajectory.
It would be wrong to compare stall torque and maximum speed as simultaneously
available output. No automatic cadence reduction was implemented.

Current physical crank indexing does not fit the new geometry: planar checking
already requires negative pulse values if old offsets are reused. The geometric
angular excursion fits within 225 degrees, but a new physical horn/mount index
and subsequent calibration would be required. Existing calibration and matchmarks
remain unchanged. Mechanical housing/link clearance and print design are still
unqualified. This is a reference for CAD review, not manufacturing-ready geometry.

Independent finite-difference contact Jacobians for the reshaped 81 and 72 mm
planar cases agree within 3.5e-8 mm/radian at checked poses. Scripts, mesh-derived
inventory, controlled crank comparison, sampled candidates, full-cycle reference,
verification and plot are saved in
`docs/gait-research/locomotion-modernization-20261012/geometry-ratios-20261013/`.
No robot motion, firmware, calibration or Blender source-part edits were made.

Research context: MIT's leg-design work treats mechanical strength, mass/inertia
and task kinematics together rather than specifying a universal link ratio:
https://dspace.mit.edu/entities/publication/c1c547a0-da5e-46e0-ba78-014fb3a3ee98
Stanford Doggo is an example of a robot-specific actuation/mechanism co-design,
not dimensions that transfer directly to MG90 position servos:
https://arxiv.org/abs/1905.04254
TowerPro's separate MG90S page lists 1.8 kgf-cm stall torque and 0.10 s/60 degrees
at 4.8 V; this is context only, not identification or qualification of the owner's
MG90 units at 5 V:
https://towerpro.com.tw/product/mg90s-3/

### 2026-10-13 — Animated 72 mm reference for owner evaluation

Owner requested a Blender scene of the proposed geometry, then explicitly asked
for animated walking. Created two independent scenes in the open Blender session:
`Geometry - 72 mm walking reference` and
`Geometry - Leg dimensions and motion`. Saved their dependencies in
`Slave/hardware/v2-12servo/Ainekio-72mm-Animated-Geometry-Reference.blend`.
The original CAD scenes and source file were not overwritten.

The full robot uses the previously calculated 72 mm foot / 26 mm carrier /
26 mm rod / 43 mm pickup / 28 mm crank cycle: nominal 82 mm planted sweep,
80% stance, 2-second cycle, and 64 mm modeled body clearance. The detail scene
animates one linkage in its body frame and compares the installed and candidate
Part 027 at equal scale, with knee, pickup and toe-centre dimensions. This makes
the packaging cost explicit: 55+28=83 mm installed versus 72+43=115 mm candidate,
approximately 39% longer. This remains a research reference, not an established
ideal, printable CAD, or a qualified gait for the installed robot.

Preview Part 027 meshes were deformed from the preserved 55 mm mesh in its
exported mechanism coordinates. An initial preview incorrectly used unevaluated
cross-scene transforms; corrected that before delivery by using the same exported
vertices as the solver. Verification of 96 sampled foot poses found maximum
mesh-versus-solver sole height difference 0.000024 mm (floating-point precision).
This establishes that the animation follows the calculated geometry, not physical
walking performance. Detached helmet preview pieces were hidden only in the new
study. The standalone file contains the two studies; the original file stays open.

Saved generator, rendered previews and verification JSON under
`docs/gait-research/locomotion-modernization-20261012/geometry-ratios-20261013/`.
No firmware, calibration, hardware movement or manufacturing files were changed.
Physical crank re-indexing, servo speed, collisions and actual support remain
unqualified as already recorded for this candidate.

### 2026-10-13 — Owner rejects oversized reference; compact 45–55 mm study

Owner judged the 72+43 mm lower leg impractical and asked for a smaller geometry,
specifically 45–55 mm knee-to-foot, and noticed the 28 mm crank exceeded the
26 mm carrier in the large reference. This is not a required mechanism ratio.
The next search bounds lower-leg pickup-to-toe span to the installed 83 mm and
compares 45, 50 and 55 mm feet. The dimensional, posture and speed filters are
research comparison criteria only; no runtime limits or firmware changes.

`compact_search.py` sampled 147,456 planar paths across 60/70/82 mm sweeps,
fixed/relocatable crank pivots, and the three foot lengths. Promising planar
results often failed when the actual foot mesh and existing whole-body lateral
shift were included. `compact_body_search.py` checked 960 rounded/local variants;
its surviving 55 mm family uses carrier26 / rod23 / pickup27 / crank21 mm.
The crank is therefore SHORTER than the carrier in this compact family.

The crank centre in this family is at (4,0) mm relative to the carrier centre in
the mechanism's sagittal coordinates, versus the current (-12.5,+11.5) mm.
It requires changing servo placement: +16.5 mm along local X and -11.5 mm along
local Z. The projected shaft separation is only 4 mm. This is a substantial
mount/axial-packaging question; servo housings, horns and link layers have NOT
been collision-qualified. It is not a drop-in replacement or printing advice.

Using this same 26/23/27/21 mechanism, checked complete sampled Cartesian cycles
with scaled longitudinal body shift and the unchanged lateral shift:

| Knee-to-toe | Pickup-to-toe span | Nominal sweep | Modeled clearance | Minimum loaded sagittal leg angle | Peak carrier / crank torque |
| --- | --- | --- | --- | --- | --- |
| 45 mm | 72 mm | 50 mm | 41 mm | 41.4 deg | 0.0488 / 0.0502 Nm |
| 50 mm | 77 mm | 55 mm | 46 mm | 44.4 deg | 0.0506 / 0.0531 Nm |
| 55 mm | 82 mm | 60 mm | 51 mm | 46.8 deg | 0.0520 / 0.0557 Nm |

All three listed cases close through the sampled stance AND swing. Approximate
carrier/crank excursions are 85/82, 86/78, and 88/77 degrees, respectively.
At 2 seconds per cycle their peak carrier/crank speeds are 447/446, 469/446,
and 491/444 degrees/s. These are commanded speeds, not verified MG90 performance.
Shoulder support torque remains approximately 0.106 Nm in this reused body plan;
balancing carrier/crank load has not eliminated shoulder demand. Whole-body
support margins are only about2–2.5 mm under the assumed centred COM.

Torque figures use a fixed 566 g point-body model, computed contact reactions and
Jacobian statics; exclude limb inertia, impact, compliance and actual motor
tracking. The three strokes and clearances differ, so this table is not a
controlled leg-length-only comparison. 45/50 nominal cases numerically fit the
old angular-index pulse test, but changing physical shaft placement still
requires physical assembly/calibration review. The55 case does not fit old
indexing. No existing calibration changed.

Additional height checks: 50 mm foot at47 mm clearance still closes, minimum
loaded angle45.5 degrees, but demands560 deg/s crank speed; at48 mm clearance
this path loses closure. The45 mm foot at42 mm clearance closes, but43 mm fails.
See `compact-same-linkage-body-check.json`, `compact-height-refinement.json`,
and the other `compact-*` results in the geometry-ratios research directory.
These are viable kinematic candidates to inspect for packaging, not a proven
perfect ratio or physical walking demonstration. The large reference scene is
retained as a rejected size study; no new compact assembly has been drawn yet.

### 2026-10-13 — Compact55 animated Blender reference delivered

At the owner's explicit request, created `Geometry - Compact 55 mm walk` and
`Geometry - Compact linkage detail` in the open Blender session. Saved a separate
normal Blender project at
`Slave/hardware/v2-12servo/Ainekio-Compact55-Walking-Reference.blend`.
Original CAD and the rejected oversized reference remain untouched.

This reference uses the calculated55/26/23/27/21 mm foot/carrier/rod/pickup/crank
candidate:60 mm nominal planted sweep,51 mm modeled clearance,80% stance and
2-second cycle,120 samples at60 fps. Full robot view combines actual chassis
scale with schematic linkage beams and the reshaped bare Part027 profile.
The detail scene animates the linkage and labels installed versus proposed
lengths and the crank shaft relocation(+16.5 mm X,-11.5 mm Z), with4 mm final
projected shaft spacing. Motor housings, mounts and axial linkage layering are
explicitly unresolved; no manufacturing geometry or physical fit is implied.

Verified all480 sampled foot poses against the numerical solver. Maximum sole
height difference0.0000225 mm; maximum link-length difference0.0000065 mm.
This checks animation correspondence, not real-world gait performance.
Generator,120-sample cycle, renders and verification JSON are saved alongside
`compact55-animation-cycle.json` in the geometry-ratios research directory.
The standalone project was converted from a dependency-only library to a normal
Blender project with the walking scene active. No firmware/calibration changes,
robot commands or source-file overwrite.

### 2026-10-13 — Optimize ratios for balanced actuator demand and upright walking

Owner specified 45–55 mm knee-to-foot length, crank and carrier each at least
20 mm, other dimensions open. Priority: balanced crank/carrier loading, upright
support, useful motion across Walk 1–100, and long stroke without overloading
MG90 servos. The previous compact Blender reference's 27 mm pickup was a feasible
example, not an established optimum. It is superseded as an optimization claim.
No new physical geometry has been installed.

The source speed mapping matters: `motion.c` maps Walk speed to stride percent
and motion rate `1 + speed/100`; `geometry.json` has a 1.8-second base cycle.
Thus current 100% Walk timing is 0.9 seconds/cycle. Earlier 2-second Blender
references were not demonstrations of the deployed 100% speed. This study uses
that cycle timing with a NEW RESEARCH trajectory: 80% stance, 10 mm maximum
lift, coordinated wave phases and calculated lateral/fore-aft body shifts.
Deployed geometry still specifies 70% ground contact. No motion code changed.

Method: Sobol population exploration and differential evolution, then local
Nelder–Mead refinement. Search varied carrier, foot, crank, pickup, rod, body
height and both projected crank-shaft offsets. Broad numerical bounds were
carrier20–160, foot45–55, crank20–100, pickup8–120, rod8–180 mm;
height35–170 mm, shaft X−100…100/Z−100…80 mm. Additional comparison envelopes
carrier<=45 and <=60 mm distinguish packaging tradeoffs; these upper bounds
are not owner-selected requirements or runtime restrictions. The objective
minimizes maximum simultaneous normalized torque/speed demand, with a soft
penalty for peak-load imbalance above10%, a45-degree minimum loaded lower-leg
angle target and a small linkage-size tie-breaker. This is an explicitly chosen
engineering objective, not a universal definition of ideal geometry.

Load calculation uses actual exported bare-foot geometry, all four mechanism
transforms, contact Jacobians, nonnegative point-body support reactions, and
estimated gravity/inertia of uniform plastic links. Link masses scale from
existing STL volumes with ASSUMED solid-plastic density1.24 g/cm3, preserving
the measured566 g baseline. Some source STLs are not watertight, so their volume
is only an estimate. Assumed centred COM remains15.75 mm above the old body
bottom datum; moving servo mounts would change actual COM and packaging.

Reference objective is |torque|/0.1765197 Nm + |speed|/600 deg/s. The endpoints
come from TowerPro MG90S published4.8 V stall torque and nominal speed, NOT a
measured torque-speed curve for the owner's5 V MG90 servos. Their sum is a
comparison proxy, not a verified thermal/continuous-load limit. Jacobian statics
uses tau=J-transpose F; link inertia is estimated using two Gaussian mass points
per uniform link. Motor/gear inertia, friction, backlash, impacts, actual
contact tracking, new brackets/housing clearance and continuous heating remain
unmodeled. Sources:
https://modernrobotics.northwestern.edu/nu-gm-book-resource/5-2-statics-of-open-chains/
https://towerpro.com.tw/product/mg90s-3/

Best locally refined results for the two selected stroke targets:

| Quantity | Compact comparison | Longer assembly comparison |
|---|---:|---:|
| Knee-to-foot |54.946 mm|55.000 mm|
| Carrier |45.000 mm|113.102 mm|
| Crank |21.583 mm|20.157 mm|
| Rod |21.482 mm|63.292 mm|
| Pickup |20.022 mm|15.186 mm|
| Crank pivot relative to carrier pivot, local X/Z |−10.512 / −23.983 mm|−9.520 / −58.911 mm|
| Nominal clearance relative to OLD body-bottom datum |67.747 mm|137.313 mm|
| Planted sweep target |60 mm|82 mm|
| Peak carrier/crank torque,1920 phase samples |0.09227 /0.10256 Nm|0.10268 /0.11546 Nm|
| Peak carrier/crank speed,1920 phase samples |533 /550 deg/s|319 /426 deg/s|
| Carrier/crank excursion |44.38 /33.92 degrees|31.26 /22.85 degrees approximately|
| Estimated revised robot mass |564.5 g|588.6 g|

Both dense local refinements converged; the broad global searches did not prove
an absolute global optimum. The compact solution is on its45 mm carrier
comparison boundary. The longer solution is a113 mm carrier despite its55 mm
lower leg; it is not compact and cannot be represented as a drop-in option.
60/82 mm are evaluated sweep targets, not proven maximum possible strides.
Balancing peak actuator demands does not make their torque equal at every
instant or remove shoulder load.

Verification found a substantive sampling problem:120 points/cycle understated
brief crank-speed peaks. The first compact candidate rose from534 to687 deg/s
when checked at960 samples. Reoptimized at480 samples; the resulting compact
candidate checks at537,546,550 deg/s crank peak for480/960/1920 samples,
respectively. Carrier peak is533 deg/s. Retain these residual sampling differences
instead of treating a single coarse pass as exact. Files `actual-body-dense-*`
and `check_dense_resolution.py` supersede coarse optimization speed claims.
Independent finite differences of18 linkage point Jacobians agree within
2.9e-8 mm/radian for the compact starting candidate.

The rounded compact dimensions55/45/21.6/21.5/20 mm foot/carrier/crank/rod/pickup,
with local shaft offset(−10.5,−24.0) mm and nominal height67.8 mm, also close at
960 samples: peak loads0.09227/0.10279 Nm, speeds533/545 deg/s, loaded leg angle
>=45.03 degrees. Existing projected shaft offset was(−12.5,+11.5) mm, so this
requires a crank-shaft shift of approximately(+2.0,−35.5) mm in mechanism local
X/Z. Mount feasibility and axial layering have not been established.

A one-at-a-time ±0.5 mm sensitivity check around the dense compact optimum
retains mathematical closure in all16 variations, but several exceed600 deg/s
crank demand. This is not a tolerance-qualified print recommendation. The earlier
long-carrier optimum was particularly fragile: several±0.5 mm changes broke
closure. Robust manufacturing optimization and actual mounted-servo identification
are unresolved. Existing calibration, firmware and Blender references were
preserved; these calculations are not a physical walking demonstration.

Reproducible scripts and JSON evidence are under
`docs/gait-research/locomotion-modernization-20261012/geometry-ratios-20261013/`:
`optimize_dynamic_linkage.py`, `optimize_actual_body.py`, `refine_dense_linkage.py`,
`audit_dense_final.py`, `check_dense_resolution.py`, `check_linkage_jacobian.py`,
`actual-body-dense-optimized-*.json`, and `actual-body-dense-compact60-sensitivity.json`.

The optimized dimensions use modest angular excursions; these are not the prior
156-degree reference. Under this study's0.9-second/80%-stance timing, the return
window is0.18 seconds. A156-degree return alone requires867 deg/s AVERAGE, before
acceleration, versus the600 deg/s nominal reference. Large servo travel, long
stroke, high cadence and low load cannot all be assumed independently. Changing
the gait duty/cadence could move this tradeoff; it has not been silently changed
in firmware. The research compares actuator demand, not percentage of servo
travel used as a proxy for useful power.

Final speed-range audit completed for both dense-refined candidates: all100
integer speed settings close at480 samples/cycle. Each setting recomputes its
120-sample body support plan and actual-contact force distribution, then uses
periodic cubic interpolation of body motion and linear interpolation of contact
reactions for480-sample dynamics. All body-plan optimizations succeeded; maximum
force-equilibrium residuals were2.9e-7(compact) and3.8e-7(longer) in the mixed
coordinate/force-fraction equations. Minimum sampled support margins under the
assumed COM were2.23 and2.06 mm. The compact minimum loaded leg angle is44.996
degrees (soft45-degree objective, not an exact hard constraint). These narrow
modeled margins are not measured balance robustness.

Peak shoulder point-body demand over the audited settings is0.1024 Nm(compact)
and0.1087 Nm(longer); shoulder dynamics remain outside the two-actuator objective.
All-speed audit results are `actual-body-dense-speed-audit-compact60.json` and
`actual-body-dense-speed-audit-unrestricted82.json`. The1920-sample full-speed
check remains the better evidence for brief peak joint speed than the480-sample
audit. No hardware or firmware action was performed.

Clarification requested by owner: the refined compact carrier/crank PEAK loads
are0.0923/0.1026 Nm, so carrier peak is about10% below crank peak. These peaks
need not occur simultaneously; they are not a claim of50:50 sharing at each
instant. At low commanded speeds, crank demand remains appreciably higher than
carrier demand. Full-speed approximate equality partly reflects carrier inertia;
this has not demonstrated equal static support loading or measured motor current.

The final dense long-carrier candidate also remains tolerance-sensitive:
1920-sample one-at-a-time variations of−0.5 mm carrier/foot/crank,
+0.5 mm pickup/rod/height, or−0.5 mm shaft Z break sampled closure.
See `actual-body-dense-unrestricted82-sensitivity.json`. Its lower nominal
comparison score therefore does not establish a robust build choice.

### 2026-10-13 — Fixed20 mm crank and shorter carrier ratio

Owner rejected the45/55 carrier-to-foot ratio as too long, then explicitly fixed
the crank at its nominal printed20 mm and retained45–55 mm knee-to-foot length.
Owner does not want to choose arbitrary carrier ceilings: calculate other
lengths. Earlier minimum20 mm carrier remains recorded;35/40 mm upper bounds in
this comparison are exploratory cases, not owner-authorized dimensional limits.
All dimensions are joint-centre distances. The20 mm crank is the nominal model
value, not a new caliper measurement of the installed part.

Changed the research objective to include quasi-static support RMS torque and
the RMS instantaneous difference between carrier/crank torque magnitudes,
instead of balancing only maximum torque peaks that may occur at different
phases. Used full-cycle torque/speed proxy plus
2*(maximum support RMS +2*RMS torque-magnitude difference)/0.1765197 Nm.
This weighting is a declared engineering comparison, not a unique universal
physical definition of ideal. Source model and physical limitations from the
previous entry still apply. Added support metrics to research functions only;
no firmware, calibration, printed parts or Blender scene changed.

Screened40/50/60 mm strokes with the20 mm crank fixed; compared carrier search
envelopes up to25/35/40 mm, then expanded rod/pickup/shaft-position bounds to
identify results dominated by artificial search boundaries. The first40 mm
stroke result hit pickup50 mm and shaft X−40 mm bounds. Expanded search reached
an interior carrier28.173 mm, pickup77.677 mm, rod36.036 mm, foot54.99999 mm,
crank20 mm, nominal old-body clearance47.646 mm and crank-to-carrier shaft
local offset(−44.083,+26.301) mm. Carrier/foot ratio0.5122, carrier/crank1.4087.
For this40 mm stroke comparison both differential evolution and local refinement
converged numerically. This is not proof of global optimality across every
stroke, assembly branch or mechanism topology.

Actual bare-foot/full-body checks at1%,50%,100%, with1920 dynamics samples per
cycle, all close. RMS torque during stance is:

| Speed | Carrier RMS Nm | Crank RMS Nm | Carrier/crank peak Nm |
|---|---:|---:|---:|
|1%|0.02175|0.02137|0.03379 /0.03085|
|50%|0.02154|0.02178|0.04243 /0.03754|
|100%|0.02122|0.02272|0.04822 /0.05080|

This is substantially better average stance-effort sharing than the previous
45 mm carrier candidate. It still does not mean equal torque at each instant:
at100% the RMS instantaneous magnitude difference is0.01152 Nm. Full-speed peak
shaft speeds are587/594 deg/s; the generic reference proxy is0.993, almost its
reference boundary, so do not describe this as comfortably unstressed hardware.
Minimum support margin at these sampled speeds is2.41 mm under assumed COM.

IMPORTANT packaging consequence: the78 mm pickup is the lever behind the knee,
not the connecting rod. With55 mm knee-to-foot, the full straight lower-link
joint span becomes about133 mm before end material, versus83 mm on the installed
55+28 part. Relocated shafts and this long tail require new collision/mount
assessment. A shorter carrier alone has not established a compact assembly.

A less extreme comparison is30.338 carrier/55 foot/20 crank/50 pickup/27.676 rod,
local shaft offset(−40.000,+9.227) mm and nominal clearance47.690 mm,40 mm stroke.
It also closes at1/50/100% with1920 samples. Stance RMS carrier/crank:
0.02017/0.02495,0.02041/0.02504,0.02102/0.02503 Nm respectively.
Peak loads at100% are0.04849/0.05011 Nm; peak speeds556/583 deg/s.
Its total lower-link joint span is105 mm, so it too is larger behind the knee
than the installed part. It is a size-versus-load-sharing comparison, not an
unqualified ideal ratio.

The50 mm stroke candidate from the35 mm carrier envelope loses closure in the
actual full-body100% check. The60 mm stroke case closes but demands758/964 deg/s
at100%. A40 mm carrier/10 mm pickup planar candidate also fails full-body closure
at50% and100%, despite its attractive planar score. These checks prevent treating
isolated-leg optimization as a qualified walking geometry.

Artifacts: `optimize_fixed20.py`, `optimize_fixed20_expanded.py`,
`optimize_fixed20_shortpickup.py`, `audit_fixed20.py`, `fixed20-*.json`,
`body-audit-fixed20-*-n1920.json` in the geometry-ratios research directory.
All-speed verification remains separate from the three representative settings
reported above. No manufacturing recommendation or global ideal claim follows
from these finite search results.

Owner reiterated: leg45–55 mm, crank20 mm. Carrier, rod, pickup and shaft
positions are variables; do not turn the earlier35/40 mm comparison envelopes
into owner requirements. A broader carrier20–160 mm exploratory run at40 mm
stroke found a different planar local candidate with63.903 mm carrier,55 mm foot,
10 mm pickup and57.116 mm rod, showing why the28 mm candidate cannot be called
an unrestricted global optimum. The broad differential-evolution run did not
converge; local refinement did. This larger-carrier case also conflicts with the
owner's stated preference for a shorter carrier relative to the leg. A single
crank constant sets scale but does not remove the size/load/stride tradeoff.
The broader63.9 mm carrier candidate fails actual full-body closure at50% and
100% in the1920-sample audit. Its better isolated-leg score is not a usable
whole-body result. The current checked shorter-carrier comparisons remain
28.17/55 with77.68 pickup and30.34/55 with50 pickup. Neither has established an
ideal compact manufactured linkage; do not recommend printing from nominal
optimization dimensions alone.

### 2026-10-13 — Compact whole-body result retaining the installed lower leg

Owner rejected the133 mm lower-link proposal and demanded concrete workable
ratios with a crank no shorter than20 mm. Correction: an initial commentary
briefly interpreted45–55 mm as the complete link; that was corrected before
calculation. Existing project convention remains45–55 mm knee-to-foot reference,
with pickup measured separately. The compact comparison now keeps foot+pickup
no longer than the installed55+28=83 mm joint span, avoiding the oversized tail.
The exported original bare-foot outline spans95.500 mm along its long axis,
including approximately5 mm beyond the pickup and7.5 mm beyond the foot reference.
Thus joint span must not be mislabeled exact printed end-to-end length.

Planar scores repeatedly favoured10 mm pickups that failed the actual four-leg
check. Moved local refinement to the actual foot/body model at1%,50%,100%
concurrently, starting from two closing upright geometries. Objective combines
maximum normalized actuator demand, maximum stance RMS effort plus twice the
instantaneous torque-magnitude difference, and a soft preference for carrier/foot
no larger than the installed35/55 ratio. The latter is an engineering compactness
preference, not a hard dimensional limit or a universal optimum criterion.

Two local refinements converged. The lower score uses carrier38.645,foot54.466,
crank20,pickup28.425,rod55.977 mm; nominal clearance69.466 mm and local crank
shaft relative to carrier(+15.475,+21.190) mm. The second gives carrier39.757,
foot55,pickup24.299,rod59.799. Both have closely matched stance RMS effort across
the three optimization speeds. Neither establishes a global mathematical optimum.

Rounded design selected for complete numerical validation:

| Component | Installed nominal | Rounded compact target | Ratio to20 mm crank |
|---|---:|---:|---:|
| Crank shaft-to-pin |20 mm|20 mm|1.00|
| Carrier shaft-to-knee |35 mm|39 mm|1.95|
| Connecting rod pin-to-pin |38 mm|56 mm|2.80|
| Lower-leg pickup knee-to-rod |28 mm|28 mm|1.40|
| Lower-leg knee-to-foot reference |55 mm|55 mm|2.75|

This retains the original lower-leg dimensions and crank, with a39 mm carrier
and56 mm rod. Carrier/foot ratio0.709, compared with0.818 for the rejected45/55
candidate and0.636 on the installed35/55 parts. Shaft placement is ESSENTIAL:
crank shaft(+15.5,+21.2) mm relative to carrier in mechanism local X/Z, versus
installed(−12.5,+11.5); displacement(+28.0,+9.7) mm. Shaft separation26.26 mm.
These local axes mirror across opposite-side legs. New mounts and horn indexing
must be resolved physically; this is not a rod-only substitution or a firmware
update for the current assembly. No saved calibration or hardware changed.

Gait evaluated:40 mm planted sweep at100%,10 mm peak lift,80% stance,0.9-second
full-speed cycle; stride scales with speed and cycle uses1.8/(1+speed/100).
Nominal body-bottom clearance69.5 mm refers to the OLD body datum, not verified
clearance of future mounts. Walking uses the researched wave/body-shift path,
not deployed firmware's70% contact trajectory.

All100 integer speed settings1–100 close in the actual-foot four-leg audit,
with body support/reactions recomputed per setting at120 samples and dynamics
checked at480 samples. The carrier/crank loaded-stance RMS difference is at most
2.12% of the larger RMS value across all100 settings; equality is not instantaneous.
Minimum loaded lower-leg angle57.986 degrees above horizontal. Minimum modeled
support margin2.07 mm under the assumed centred COM, not physical disturbance
robustness. Maximum comparison torque-speed proxy0.813. This proxy uses nominal
MG90S endpoints, not an identified continuous-load curve for the installed MG90s.

Independent denser1920-sample checks at1%,50%,100%:

| Speed | Carrier / crank peak Nm | Carrier / crank loaded RMS Nm |
|---|---:|---:|
|1%|0.05065 /0.04930|0.03340 /0.03404|
|50%|0.05388 /0.05609|0.03350 /0.03364|
|100%|0.05767 /0.05926|0.03365 /0.03351|

Full-speed carrier/crank peak speed484/470 deg/s, angular excursions35.06/36.10
degrees. Shoulder point-body demand remains about0.103 Nm; carrier/crank sharing
does not eliminate shoulder torque. A single-parameter±0.5 mm sensitivity check
for all eight model dimensions retains closure in16/16 cases on the fixed
full-speed body trajectory; worst tested speed494 deg/s and proxy0.830. This
is not simultaneous tolerance-stack validation, collision analysis, measured
servo tracking, structural proof or a physical walking demonstration.

Artifacts in the geometry-ratios directory:
`refine_compact_body.py`, `compact83-rounded39.json`,
`body-audit-compact83-rounded39-n480.json`(100 settings),
`body-audit-compact83-rounded39-n1920.json`(dense1/50/100),
`check_compact39.py`, `compact39-sensitivity.json`,
`draw_compact39.py`, `compact39-dimensioned-reference.png`.
The image is a dimensioned mechanism-plane schematic with the existing lower-leg
outline, not printable manufacturing CAD. Existing Blender scenes, firmware,
calibration and physical robot state are unchanged.


### 2026-10-13 — Compact39 Blender reference and installed-parts walking revision

Owner requested a Blender representation of the proposed linkage, then explicitly
requested recalculating walking for the currently installed parts, applying it to
firmware, and preparing an image for flashing. Owner reconfirmed that bare Part027
itself touches the floor; separate boots/toes are not installed.

**Blender deliverable.** Added `Geometry - Compact39 proposed linkage` to live
Blender without saving over the dirty original CAD file. Saved an independent
`Slave/hardware/v2-12servo/Ainekio-Compact39-Linkage-Reference.blend` containing
only the new reference scene and dependencies. It shows the 20/39/56/55/28 mm
crank/carrier/rod/foot/pickup design and proposed crank shaft (+15.5,+21.2) mm,
with the old shaft marked for comparison. Frames 1–120 show the calculated
0.9-second cycle, initially displayed at mid-stance frame49. The original foot's
projected convex envelope is represented as a prism, not manufacturing CAD.
This is a single mechanism-plane reference: body and shoulder motion are omitted.
Inspected the camera view; all five link dimensions were checked on all120 frames
(maximum Blender transform rounding error0.000025 mm). Generator and sampled
motion: `geometry-ratios-20261013/build_compact39_blender.py` and
`compact39-blender-motion.json`. Original robot scenes and CAD file preserved.

**Installed mechanism, unchanged.** Carrier35 / crank20 / pickup28 / rod38 /
knee-to-foot55 mm, with existing crank-shaft offset(-12.5,+11.5) mm. Saved electrical
Home values and existing source servo profile were not changed. No part from the
proposed39 mm carrier /56 mm rod design is used by this firmware revision.

**Concrete findings.** The previous source used78 mm planted sweep,70% contact,
bodyZ−4.75 mm, and a12 mm forward stride bias. Its schedule included two-foot
support. Its walking contact profile included boot/toe geometry absent on the
physical robot. The revised contact source is
`Slave/software/models/v2-12servo/motions/locomotion/walk-contact.json`, derived
from the previously exported original55 mm bare Part027 and linked by hashes.
The compact hull has99 vertices, with0.149268 mm maximum full-hull distance error;
the existing0.151 mm contact approximation allowance is unchanged. The existing
virtual foot-reference coordinates are retained; their vector length is not the
physical knee-to-foot length. Initial planar screening used a55 mm collinear
reference. Final results below come from native firmware targets with the actual
retained virtual reference and independent bare-foot forward geometry.

**Walking implementation.** Reauthored Walk in the existing planner:

| Quantity | Previous | Installed-parts candidate |
|---|---:|---:|
| Full planted sweep |78 mm|32 mm|
| Stance fraction |70%|80%|
| Body translation Z |−4.75 mm|+8.75 mm|
| Nominal model hull clearance |44.5 mm|58.0 mm|
| Stride-dependent foot bias |12 mm forward|0 mm|
| Walking contact shape |boot/toe assembly|bare Part027|

Body support translation is in body axes, rotated with commanded heading:
X = (8−2.5p)+4 sin(4πphase) mm; Y =9 sin(2πphase) mm, p=stride/100.
The first contact overlap establishes the body translation; it then remains
active for short steps as well as full strides, fading through the existing Run
blend. Walk uses no decorative bob/roll/pitch; the existing IMU correction path is
retained. Speed/cadence still follows Body Control,1.8/(1+speed/100) seconds/cycle.
At100%,32/.8/.9 =44.44 mm/s theoretical travel, not measured ground speed.
Planted world anchors remain fixed; no gait clock slowdown, automatic Home/Stand
pre-sequence, new runtime stop, sensor requirement or fault fallback was added.
Crawl/Crab retain their separate contact profiles and timing. First-frame contact
selection now matches the requested Crawl/Crab mode instead of defaulting to Walk.

Bare contact also changes Run's pose solution. Native transition checks exposed
insufficient linkage transmission angle at the previous78 mm Run sweep. Reauthored
Run's full forward sweep to74 mm and reverse/turn sweep to72 mm, retaining64 mm
initial Run amplitude, existing bounds and full Body Control cadence. These are
trajectory dimensions, not an automatic rejection or speed limiting mechanism.
Physical bounding remains unqualified.

**Final native evidence.** `geometry-ratios-20261013/installed-native-audit.json`
contains every integer forward speed1–100, including startup and Finish at100 Hz.
All100 complete. Minimum scheduled steady contacts3; minimum loaded lower-leg
angle47.4758° above the world floor; saved-mapping pulse span473.35–2826.67 us.
Independent full bare-hull contact error stays within the existing compact-profile
allowance (approximately0.092–0.152 mm). At100%, steady shoulder/carrier/crank peak
commanded speeds are41.69/429.55/403.65°/s. Assumed external support load peaks are
0.09559 Nm carrier /0.06736 Nm crank at100%; these exclude link/gear inertia and
servo losses and are not a measured torque rating. No claim of equal crank/carrier
loads for the installed hardware is made.

Support calculation assumes566 g total mass and centered body COM at originalZ65
mm. Minimum modeled support margin is0.627 mm across the speed sweep,3.356 mm at
100%. The low-speed margin is small; COM location, disturbances, foot slip and
actual servo tracking remain physically unmeasured. Three scheduled contacts and
an IMU tilt estimate do not establish that three feet bear the predicted load.

**Regression changes and validation.** Retained pulse, closure, contact-height,
leverage and anchor-continuity checks. Replaced obsolete tests demanding the old
78 mm stroke/near-endpoint pulse use with proportional32 mm reach and at least
three scheduled contacts. Historical boot-based reference recordings remain
unchanged: parity now checks their spatial targets through independent bare-foot
FK rather than requiring the obsolete boot-specific joint angles. Crouch's
archived entry is compared with its own Crawl contact model. The native suite
passed51/51; expanded calibration checks also pass forward/reverse curves with
both yaw signs at50% and100% turn, at50 and100 Hz. Existing IMU feedback, posture,
body ownership, gait timing, irregular tick, Walk/Run round-trip, generator and
calibration tests pass. Targeted diff whitespace checks pass.

Firmware version prepared: `0.8.41-p4-upright-walk`. First build invocation resolved
its relative output directory to repository-root `build` and ran out of disk.
Cleaned only that invocation's Ninja-generated outputs, retaining the existing
root gateway data, then rebuilt in the established P4 project build directory.
Final image result and hash are recorded below when verified. No robot command,
calibration write, OTA upload, activation or flash has been performed in this work.

Final P4 build succeeded with ESP-IDF5.5.4. Application image: `Slave/firmware/esp32p4-wifi6/build/ainekio_p4_body.bin`, 3020752 bytes, fits the8 MiB application slot. Version `0.8.41-p4-upright-walk`. SHA-256: `d8921f6df6f5a3333f89135e39a41b7cc6a529044b1f7eae2413faa90c57acfb`. Build record: `geometry-ratios-20261013/installed-gait-build.json`. Ready for Wi-Fi installation; not uploaded or activated.


## 2026-10-14 — Installed upright-walk firmware over Wi-Fi

Owner requested the Wi-Fi update and confirmed the robot was supported with servo power off. Reverified the prepared 3,020,752-byte application SHA-256 `d8921f6df6f5a3333f89135e39a41b7cc6a529044b1f7eae2413faa90c57acfb`. The existing authenticated maintenance upload staged the image, then explicit activation restarted the controller. No USB flashing, partition changes, calibration writes, or C6 update were performed.

Live verification: previous version `0.8.40-p4-walk-height` on `ota_0`; running and selected boot partition now `ota_1`, version `0.8.41-p4-upright-walk`, OTA state `accepted`, `pending_verify=false`, `ESP_OK`. Startup logs reported required/ready devices `0x1f/0x1f`, and the existing gateway reconnected. Saved joint calibration fields were identical before/after (excluding message sequence, live readiness and instantaneous output pulses). IMU readings were available/fresh with calibration applied.

At verification, outputs were unarmed, fault code 1 (`AINEKIO_PCA_FAULT_EMERGENCY`), with zero output I/O failures. This is the reported output-disable state; no claim is made that the physical power switch caused it. We did not rearm outputs or send a walking command. Physical loaded walking remains unqualified. Raw diagnostic captures remain outside the repository in `/tmp`; the build manifest records deployment evidence.


## 2026-10-14 — Separate startup rise from calibration Home

**Owner observation and requested change.** Boot immediately moved toward saved calibration Home, extending the legs before shoulder alignment and preventing standing on the floor. Owner requested crouch first, shoulder Home second, then leg extension into Stand; full Home must remain calibration-only.

**Confirmed source cause.** `app_main.c` called `ainekio_p4_home_command()` on ordinary resets. `body.c` engaged assigned channels individually at 200 ms intervals. Stand and other named motions from detached outputs also established full calibration Home before their entry. Saved matchmarks are calibration references, not a floor-aware startup trajectory.

**Implementation: 0.8.42-p4-startup-rise.** Boot now submits an asynchronous body-owner rise. All eight carrier/crank channels first receive an IK-derived crouch 25 mm below the existing nominal Stand; shoulders remain off for the 0.6 s folding interval. Next, shoulders receive their saved Home pulses while the legs retain the crouch for 0.6 s. Then a 1.2 s geometric rise raises the body over four fixed modeled sole contacts, using existing IMU balance corrections during the rise and subsequent standing hold. Stand from detached/unknown outputs uses this sequence. Already-commanded Stand retains its existing contact-aware transition. Walk has no added startup choreography. Other detached named motions use their own entry targets instead of calibration Home. Explicit calibration Home remains available and saved joint records are not modified. Existing reset/admission policies are unchanged; no new stop, restriction or fallback was added.

**Evidence and limitations.** Native production-body tests check the initial shoulder-off frame, all eight leg targets, shoulder engagement while the legs stay folded, channel-map permutation, 400–2900 us installed mapping, modeled sole position/height within 0.002 mm throughout rise, completion receipts, explicit calibration Home, cancellation during each phase, and IMU correction. Nominal modeled rise peak is 50.89 degrees/s. Both body test targets pass. The full run passed the other 49 tests; its two new body tests initially used an incorrect inclusive boundary at the instant IMU correction starts, corrected to check the shoulder-only interval strictly before that boundary. Both were rerun successfully after the final body change. P4 build passes and fits the application slot. Entry planners share union storage; compiler stack-use reports 6000 bytes for start_motion and 2496 for output_task, without increasing the task stack.

The 0.6 s folding and shoulder intervals are commanded movement intervals, not sensed arrival: MG90 servos provide no position feedback through this interface. Initial physical joint positions and foot contact remain unknown. The IMU estimates body orientation, not knee/shoulder position or contact force. Native results do not establish physical startup success. The owner confirmed support and servo power off for Wi-Fi installation; upload/acceptance results follow.

**Wi-Fi deployment verified.** Uploaded and staged 3,022,768 bytes, SHA-256 `10de45ff27db73434b7daba62ff0075fe0b2fa7d3c5c84ef844e8178afe67ece`, then explicitly activated. Latest live status reports `0.8.42-p4-startup-rise`, running/boot `ota_0`, `pending_verify=false`, `ESP_OK`, and phase `idle`. The observed log is a power-on boot (reset reason 1, previous log empty), not the requested software-restart log; its cause was not established. It contains `startup crouch, shoulders, stand` and gateway authentication. Reconnected status reports outputs armed, fault 0, IMU balance active, and fresh calibrated IMU readings. Saved calibration fields compare equal before/after. This confirms deployed controller behavior; no agent-issued Walk or physical loaded-motion qualification occurred. Owner asked about simultaneity: the eight leg motors are commanded together in fold, four shoulders together in the next stage, then all four legs rise together. Only explicit calibration Home remains channel-by-channel.


## 2026-10-14 — Front/rear stagger for startup electrical demand

Owner requested near-simultaneous rather than simultaneous starts, and explicitly selected **front two legs, then rear two legs**. Implemented a 100 ms pair offset as the initial setting. Model joints 6–11 are physical front (CAD RL/RR); joints 0–5 are physical rear (CAD FL/FR). Timing follows joint roles and the saved channel map, never raw PCA channel order.

Firmware candidate `0.8.43-p4-staggered-rise`: front/rear carrier-and-crank folding begins at 0/100 ms; front/rear shoulder Home engagement begins at 600/700 ms; front/rear body lift begins at 1200/1300 ms and each lift lasts 1.2 s. Total choreography is 2.5 s. Each leg's crank/carrier pair remains coordinated. Initial fold no longer enables all eight leg channels together. The rise uses a common body height/pitch solution with planted contact targets, not separately spliced leg poses. Native modeled maximum pitch is 1.284 degrees, returning to level, with nominal peak joint rate 50.66 degrees/s. Existing balance feedback may adjust supporting legs during the rise; staggering the desired front/rear lift does not mean the rear joints are motionless during body attitude compensation.

Both production body tests pass, including the physical front/rear order with deliberately permuted electrical channels, delayed rear activation, fixed-contact FK error below 0.002 mm, final Stand, pulse mapping, completion after the rear rise, explicit calibration Home, cancellation, and IMU feedback. Command starts are separated; current reduction is not measured or guaranteed because movement and holding current overlap. No walking cadence, calibration, runtime stop, fallback or restriction was added. Build/deployment evidence follows.

P4 build completed successfully: 3023680 bytes, SHA-256 `7696217077037f6c3aed33a6e8060f3c9d65daa43437a0e05c67fd6fcf44fd83`. Build record: `geometry-ratios-20261013/staggered-rise-build.json`. Awaiting current support/servo-power confirmation before installation.

Owner confirmed support and servo power off. First Wi-Fi upload client terminated with exit 143 before a saved response. Read-only device status reported `failed`, `ESP_ERR_TIMEOUT`, 1,970,464 of 3,023,680 bytes received; running and boot remained `ota_0`, version `0.8.42-p4-startup-rise`. No activation occurred on that attempt. Retrying the same verified image; the reason for the client termination is unknown.

**Installed over Wi-Fi.** Second upload successfully staged the full 3,023,680 bytes, then explicit activation/restart succeeded. Latest live firmware status: `0.8.43-p4-staggered-rise`, running/boot `ota_1`, `pending_verify=false`, `ESP_OK`, phase `idle`. Gateway connected, output armed with fault 0, balance active, and IMU fresh/calibrated. Saved calibration fields compare equal before/after. Physical electrical-current improvement and loaded startup success remain unmeasured; no Walk command was sent.


## 2026-10-14 — Owner-operated leg geometry calculator

Owner requested an interactive calculator after repeated ratio recommendations produced impractical designs, and explicitly identified omitted servo shaft locations as a problem. Added `tools/leg-geometry-calculator/index.html`, a local browser tool with no server, network requests or robot-control connection.

The initial design uses the owner's 55/35/38/28/20 mm leg/carrier/rod/pickup/crank lengths. `robot-data.js` records geometry.json provenance/hash, physical leg names, carrier/crank shaft coordinates transformed into the chassis frame, shoulder axes, the chassis side outline and assumed COM. Installed shafts are fixed by default; changing link lengths does not relocate the motors. Users can explicitly unlock/edit shaft offsets and each selected carrier's body position, with original mounts drawn as ghost references. Recorded crank offset is approximately -12.5001 mm X / +11.5000 mm Z from carrier; front/rear carrier X positions are +66.6878/-66.7216 mm at Z 69.7118 mm. These are repository geometry, not newly measured hardware.

Controls cover link lengths, foot bend angle, branch choice, joint pose, requested body clearance, stride/centre/lift/cadence, available servo excursion, robot mass and support-force assumptions. Animated geometry, body view, travel/torque plots, snapshots for design comparison, a sampled maximum-stride search, and JSON/CSV/SVG export are implemented. The tool reports reach failures without silently reducing the requested path. No design is labelled universally ideal.

Model scope is explicit: two driven axes with shoulder held at neutral, ideal point foot rather than the Part027 mesh, and analytical external-force torque via the closed-chain Jacobian. It does not simulate housing collisions, rocking soles, motor torque/speed limits, link inertia, real load distribution or whole-body balance. Eight numerical tests pass, including independent forward/inverse closure, Jacobian finite differences and virtual work, actual exported shaft reconstruction, mount sensitivity, load/speed scaling and sampled-stride search. Desktop and 390px mobile browser checks passed: controls, preserved mounts, relocation display, animation, comparison snapshots, JSON round-trip, CSV with 240 samples, SVG export and unreachable-path reporting; no JavaScript exceptions. The mechanics model and files remain separate from firmware.


## 2026-10-14 — Strength, load sharing and useful range comparison

**Owner evidence and objective.** Owner now reports the installed robot walks, but with little foot lift/stride and continued difficulty standing. This is physical evidence of limited walking, not successful full-library movement. Owner prioritizes strength, balanced actuator loading, practical collision-free horn indexing and diverse postures over a universal “ideal ratio.” No firmware, calibration, CAD or robot commands were changed in this comparison.

**Calculation method.** Used the existing calculator's analytical closed-chain IK/Jacobian with a collinear point foot, shoulder neutral, knee/crank branches -1/-1. Installed crank shaft remains at (-12.5000722, +11.5000265) mm relative to the carrier shaft unless a relocation is explicitly listed. External-force torque is -J-transpose times the ground force; see [Modern Robotics, statics](https://modernrobotics.northwestern.edu/nu-gm-book-resource/5-2-statics-of-open-chains/). Mass 566 g; equal support on three feet gives 1.850188 N per foot. Screening loads include horizontal force -25%, 0 and +25% of that vertical force, as a stated comparison assumption, not a measured friction or acceleration limit.

Two finite searches were compared. Fixed mounts: leg 45/50/55 mm; carrier 20–40 mm by 2; pickup 16–36 mm by 2; rod 20–56 mm by 2; crank 20 mm: 6,897 candidates. Relocated mounts: leg 45/50/55; carrier 26/30/34/38; pickup 24/28/32; rod 24–48 by 4; crank X -20..20 by 5, Z 0..25 by 5: 13,608 candidates. These are bounded coarse searches, not proof of a global optimum. Ranked by the largest per-servo external-load torque over support points X +/-25 mm at shaft-to-ground heights 60/65/70/75 mm, plus a centred rise from 40 to 75 mm. Closure, consistent assembly branch and sampled 50 mm stroke / 12 mm lift cycles at 65 and 75 mm height were checked. A 230-degree excursion was only a screening assumption, not measured physical travel or a firmware change. Speed and torque were reported separately; motor dynamics were not used to qualify candidates.

**Dense follow-up.** Compared three candidates at 887 support/rise points: 1 mm horizontal/vertical spacing across X +/-25, height 60..75, plus centred rise 40..75 by 0.5 mm. All closed on one assembly branch. Candidate dimensions below are lower leg / carrier / rod / pickup / crank, all centre-to-centre, mm:

| Geometry | Crank offset X,Z from carrier | Worst carrier/crank torque across sampled load envelope, Nm |
| --- | --- | --- |
| Installed 55 / 35 / 38 / 28 / 20 | -12.5001, +11.5000 | 0.09668 / 0.07029 |
| Fixed-mount comparison 55 / 32 / 26 / 36 / 20 | unchanged | 0.06254 / 0.05794 |
| Relocated comparison 50 / 30 / 40 / 32 / 20 | +10, +20 | 0.05663 / 0.05122 |

The relocated comparison moves the crank shaft approximately 22.5 mm forward and 8.5 mm upward; it is not a link-only substitution. The fixed-mount comparison's enlarged pickup also needs physical clearance assessment. These candidates were chosen for comparing load and movement, not approved for printing.

**Same upright walking benchmark for all three:** foot X +/-25 mm about its carrier, shaft 75 mm above ground (approximately 54.54 mm chassis-bottom clearance using the source mount), 12 mm lift, 80% stance, 1.8 s cycle, vertical equal-support force only. This is a proposed comparison path, not the deployed gait. Each was checked at 1,920 phases, with independent FK closure error below 1.1e-13 mm and no assembly-branch changes.

| Result | Installed | Fixed-mount comparison | Relocated comparison |
| --- | --- | --- | --- |
| Peak support torque carrier/crank, Nm | 0.05515 / 0.05014 | 0.04621 / 0.04345 | 0.03073 / 0.02872 |
| RMS support torque carrier/crank, Nm | 0.05292 / 0.02844 | 0.04116 / 0.02442 | 0.02227 / 0.01956 |
| Cycle excursion carrier/crank, degrees | 49.41 / 113.16 | 52.69 / 87.58 | 64.43 / 67.16 |
| Peak speed carrier/crank, degrees/s | 385.66 / 600.37 | 412.85 / 515.10 | 462.61 / 480.79 |
| Minimum planted lower-leg angle above horizontal, degrees | 49.34 | 53.15 | 64.16 |
| Carrier + lower-leg maximum geometric reach, mm | 90 | 87 | 80 |

For this upright benchmark the relocated candidate reduces carrier peak torque about 44%, crank about 43%, and makes support RMS torque and angular excursions substantially closer. Across the wider sampled force envelope the largest actuator torque falls about 41%. This is reduced required torque, not an increase in servo-rated torque or measured stall margin. At the lower 65 mm shaft height its crank peak speed rises to about 651 degrees/s at the same cadence; the favourable upright result does not qualify every posture/speed. Its 80 mm total reach leaves little extension margin at 75 mm height with 50 mm stroke. Minimum output transmission angle across the dense support envelope is about 18.4 degrees. It is not a maximum-workspace solution.

**Shortening alone.** At a separate identical 40 mm stroke, 12 mm lift, 65 mm shaft-height benchmark, changing only leg 55 to 45 mm reduces carrier peak support torque from 0.06832 to 0.05469 Nm (20%). At centred 45 mm shaft height the reduction is only 0.08584 to 0.07861 Nm (8%). This supports shortening as a useful change but does not establish that it fixes rising from a deep crouch.

**Interpretation and remaining evidence.** Equal motor speed does not imply equal torque or power. Compare torque and velocity together, and their peaks at the same instant. Horn reindexing translates the electrical travel window relative to the linkage; the best index must cover the union of actual poses and collision-free motion. Maximizing angular travel alone can approach a toggle and increase speed demands. The above point-foot screen omits the Part027 sole outline, link/horn/housing collisions, shoulder motion, link mass/inertia, impact, friction, electrical sag, actual servo torque-speed curves and measured contact distribution. It does not qualify standing success, maximum comfortable stride, the entire motion library or manufacturing fit. Eight existing mechanics tests pass. The next design assessment needs actual meshes and shaft placements, not another unconstrained ratio claim.


## 2026-10-14 — Fixed housing constraint supersedes shaft relocation

Owner clarified that the crank shaft cannot move because the housing is fixed. The relocated 50/30/40/32/20 candidate is therefore excluded from recommendations for this robot; its reported 44%/43% walking-torque reductions do not apply to a compatible replacement. Subsequent comparisons must preserve the existing shaft locations, including crank offset (-12.5001, +11.5000) mm relative to carrier. No housing relocation is assumed.

The previously calculated fixed-shaft candidate remains 55 mm lower leg, 32 mm carrier, 26 mm rod, 36 mm pickup and 20 mm crank. On the stated 50 mm stroke / 12 mm lift / 75 mm shaft-height benchmark it reduces peak carrier/crank support torque about 16%/13%, with excursions 52.69/87.58 degrees. It retains the 55 mm lower leg and shortens the carrier; it is a numerical comparison candidate, not an established optimum or a physically checked replacement. In particular, the enlarged 36 mm pickup must fit the fixed housing throughout motion. No firmware, calculator, CAD or calibration changes were made for this clarification.


## 2026-10-14 — Published five-bar quadruped linkage ratios

Owner requested comparisons against other quadrupeds. Research used project-maintainer source code and research papers, rather than estimating lengths from videos. All ratios below list the two driven arms followed by the two passive loop links; the fixed frame between the driven axes is the fifth link and is listed separately. Any foot extension is also separate. These are reference designs, not replacement dimensions or proof that symmetry alone solves Ainekio's gait.

| Robot | Driven arms, mm | Passive loop links, mm | Four-link ratio normalized to first driven arm | Evidence |
| --- | --- | --- | --- | --- |
| Stanford Doggo | 90 / 90 | 162 / 162 | 1 : 1 : 1.8 : 1.8 | Maintainer controller GetGamma uses L1=0.09 m, L2=0.162 m; published symmetrical coaxial mechanism |
| Minitaur, CMU 2018 study | 100 / 100 | 200 / 200 | 1 : 1 : 2 : 2 | Ren and Johnson Table I explicitly labels lengths measured; text identifies symmetric five-bar |
| Waveshare WAVEGO, original main firmware | 40 / 40 | 40 / 39.8153 | 1 : 1 : 1 : 0.9954 | Manufacturer ServoCtrl.h Linkage_A/B/C and linkage diagram |
| Installed Ainekio | crank 20 / carrier 35 | rod 38 / pickup 28 | 1 : 1.75 : 1.9 : 1.4 | Current geometry.json parameters and owner dimensions |

**Shaft layout and foot topology matter.** Doggo's linkage outputs are coaxial (zero planar separation), even though its belt-driven motors are offset; project documentation explicitly describes nested drive shafts. Its foot is at the meeting of the two distal links. The 2016 Minitaur design paper also models the symmetric mechanism as two RR chains closing at the toe and discusses coaxial actuation. These layouts cannot be reproduced by copying lengths into Ainekio's fixed separated shafts. WAVEGO instead explicitly uses 12.2 mm planar servo spacing and a bent foot extension. Ainekio's source offset is (-12.5001,+11.5000) mm, magnitude approximately 16.9854 mm, and remains fixed by owner instruction.

WAVEGO defines C=39.8153 mm (knee to rod junction), D=31.7750 mm (continuation beyond that junction), and E=30.8076 mm (right-angle foot segment). Its IK computes the knee-to-foot vector length as sqrt((C+D)^2+E^2), approximately 77.9377 mm. Thus D alone is not comparable to Ainekio's 55 mm knee-to-foot dimension. The calculated knee-to-foot/pickup ratio is about 1.9575, numerically close to Ainekio's 55/28=1.9643, but the foot is attached on a different side/direction relative to the pickup. Ainekio's current planar calculator models the pickup and foot on opposite sides of the knee. These similarly sized ratios therefore do not imply equivalent leverage, foot path or physical fit.

**Interpretation.** All three reference designs use equal driven-arm lengths; Doggo and Minitaur also match their distal links, and WAVEGO's four moving loop links are nearly equal. This supports evaluating more symmetric arrangements as comparisons for load sharing, while preserving Ainekio's actual shaft placement and evaluating the foot extension. It does not establish a universally optimal ratio, equal torque under all loads, or that the current asymmetry is the sole cause of poor motion. Doggo and Minitaur use different actuator/transmission systems from MG90 servos. No new printed geometry, firmware, horn indexing or robot commands were applied.

Primary sources inspected:

- [Stanford Doggo controller, GetGamma](https://github.com/Nate711/Doggo/blob/838562cd2474e398507204237319bdc6cec725fe/src/position_control.cpp): 90/162 mm controller dimensions. The published project pins this controller commit.
- [Stanford Doggo project, legs and coaxial drive](https://github.com/Nate711/StanfordDoggoProject), and [2019 robot paper](https://arxiv.org/pdf/1905.04254): mechanical topology and practical 80–250 mm leg extension.
- [Ren and Johnson, Toward Robust Stair Climbing of the Quadruped using Proprioceptive Sensing](https://allenzren.github.io/PDF/riss_2018.pdf), Table I and Section II-A: measured 100/200 mm Minitaur links and symmetric mechanism.
- [Kenneally, De and Koditschek, Design Principles for a Family of Direct-Drive Legged Robots, 2016](https://repository.upenn.edu/server/api/core/bitstreams/8592ddaa-98e8-4163-844f-e6ea737b9422/content), Section II-B and footnote 4: mechanism comparison and toe closure. The web reader returned 403; direct download succeeded and text was inspected locally.
- [Waveshare WAVEGO ServoCtrl.h](https://github.com/waveshare/WAVEGO/blob/main/Arduino/WAVEGO/ServoCtrl.h), dimensions near lines 25–52 and IK near lines 124–137, 357–399: manufacturer geometry and foot-vector calculation.

RoboAmbler was also located as an eight-servo five-bar example; its fetched walking sketch contains angle tables but no link dimensions, so no dimensions were inferred or included. No claim was made from that example about an optimal ratio.


## 2026-10-14 — Choosing a published reference under fixed shaft constraints

Owner asked which published ratio to emulate. WAVEGO is the closest architectural reference among the three: separated fixed drive axes, nearly equal four moving loop links, and an extended foot. This is a reference choice, not evidence that an exact four-link ratio transplant works. Doggo/Minitaur's coaxial toe-closing arrangement is a larger departure from the fixed Ainekio housing.

The fixed fifth link prevents exact geometric similarity: WAVEGO has 12.2/40 = 0.305 shaft-spacing/driven-arm ratio; Ainekio has approximately 16.9854/20 = 0.8493. A true half-scale WAVEGO would need 6.1 mm planar shaft separation, incompatible with the current approximately 17 mm offset. Its foot attachment direction/shape also differs. Retaining Ainekio's fixed shafts while using four 20 mm links is therefore not a scaled WAVEGO.

A direct numerical check with the existing calculator used carrier/crank/rod/pickup all 20 mm, current shaft offset, opposite-side collinear Ainekio point foot, leg 45/50/55 mm, 40 mm stroke, 12 mm lift, 80% stance, 1.8 s period and 480 samples per cycle. At 75 mm shaft-to-ground height all three legs had unreachable targets. At 65 mm height the 45 mm leg had unreachable targets, while the 50/55 mm cases closed at individual samples but changed closure branch 2/4 times respectively; they did not form a continuous cycle on one assembly branch. At 55 mm height the 50/55 mm cases closed without branch changes, but this is a different body height and still lacks collision/contact qualification. This check is of a simple ratio transplant, not a simulation of the actual WAVEGO geometry or proof that all equal-link layouts fail. No robot, firmware or CAD changes were made. Recommendation: WAVEGO as the reference architecture, with explicit adaptation to fixed shafts and foot topology before any print dimensions are selected.

## 2026-10-14 — WAVEGO-style foot topology with horn-constrained minimum arms

**Owner clarification:** both shaft positions remain fixed; crank may be longer; 50 mm effective lower leg is the target, with compromise allowed. The approximately 20 mm crank/carrier minima come from servo-horn clearance, not a demand for exactly 20 mm arms. No new hardware or firmware restrictions were authorized or added.

Implemented a reproducible offline study using the calculator's existing IK/Jacobian. WAVEGO's foot lies beyond the pickup, unlike the installed opposite-side pickup/foot. Its source dimensions imply a 23.2838-degree bend between knee-to-pickup and knee-to-foot directions. Both mirrored bends and both assembly choices were searched around the unchanged (-12.5001,+11.5000) mm shaft offset. The equal-driven-arm family covered 61,864 cases: leg 45/50/55, arms 20–40 by 2, rod 20–56 by 2, pickup 20–44 by 2 mm, with the pickup before the bend. 16,650 passed the sampled geometric checks. This is a bounded family, not global optimization of every independent dimension, trajectory or collision geometry.

**Reference chosen for CAD evaluation:** effective leg 50, carrier 30, crank 30, rod 52, pickup 40 mm. Foot shape continues 5.9279 mm beyond the pickup, then turns 90 degrees for a 19.7643 mm segment. Straight knee-to-contact distance remains 50 mm. This requires a differently shaped lower leg, not simply a shorter Part 027. A 26/26 mm arm alternative has lower static demand but higher joint speed and loses the 60 mm stroke at 70 mm shaft height; the 30/30 reference trades some holding leverage for range and lower return speed.

Same-path dense comparison: 50 mm sweep centred beneath the carrier, 12 mm lift, 70 mm shaft height, 1.8 s cycle, 80% stance, 566 g and three equal-load supporting feet. At 1,920 phases, installed/reference both close on one assembly branch. Peak carrier/crank support torque changes from 0.06216/0.05341 to 0.04204/0.04274 Nm; RMS from 0.05943/0.03272 to 0.03077/0.02764 Nm. Full-cycle travel changes from 50.52/91.60 to 57.70/58.10 degrees; peak speed from 399.73/541.16 to 446.94/419.32 degrees/s. Most-loaded peak torque drops 31.2%, but carrier peak speed rises 11.8%. This is improved calculated torque sharing, not more crank excursion or proven equal electrical power. The minimum planted knee-to-foot angle rises from 43.97 to 53.80 degrees above horizontal.

A dense 622-position support/rise envelope with horizontal forces +/-25% of vertical load gives peak 0.06135/0.06133 Nm versus installed 0.09668/0.07029 Nm. This remains external-load statics, not measured continuous MG90 torque, dynamics, actual inter-foot load distribution or a working startup sequence.

**Contact finding:** the 70 mm stroke at 70 mm shaft height closes but brings another part of the foot within 1.69 mm of the floor before accounting for material thickness. An 82 mm stroke at 65 mm height closes but leaves only 0.77 mm at the foot bend; at 70 mm height it does not close throughout the cycle. These are not recommended usable strides. Actual housing/horn/joint/ground clearance and contact shape require CAD evaluation before printing or firmware changes.

Artifacts: [review, comparisons and reproduction commands](../gait-research/locomotion-modernization-20261012/geometry-ratios-20261013/wavego-fixed-shafts-review.md), [three-pose dimensioned reference](../gait-research/locomotion-modernization-20261012/geometry-ratios-20261013/wavego-fixed-shafts-50mm.svg), calculator-import JSON and dense results beside it. Script: `tools/leg-geometry-calculator/wavego-study.js`. Calculator foot-angle control now spans +/-180 degrees to represent the same-side foot. Nine numerical tests pass, including independent FK and finite-difference Jacobian checks for this topology. Dense reports also validate FK/Jacobians. A local headless-browser import check passed with the fixed mounts, selected geometry and zero JavaScript exceptions; the reference SVG was visually inspected. No firmware, physical motion, calibration or Blender scene was changed.


## 2026-10-14 — Shorter pickup: compensate with a shorter crank

Owner identified the 40 mm knee-to-pickup dimension as problematic and asked whether shortening it while lengthening the crank could preserve load capacity. Calculations retained the fixed shafts, 50 mm effective lower leg, 30 mm carrier, WAVEGO-style foot bend and knee/crank branches +1/-1. A bounded comparison varied pickup 28/30/32/34/36 mm, crank 20–42 mm by 2 and rod 24–64 mm by 2: 1,260 cases, of which 741 met the existing study's sampled path/rise/branch/excursion criteria. This comparison did not alter firmware, CAD, the selected calculator import or the previous reference.

**Finding:** shortening the pickup can preserve approximately the same actuator torque and motion when accompanied by a shorter crank. A longer crank instead raised crank torque in the directly compared configurations. Near unchanged transmission angles, crank torque per knee moment scales with crank/pickup, multiplied by the sine ratio of crank-to-rod and pickup-to-rod angles. Thus 30/40 and 24/32 preserve the simple ratio at 0.75. The actual fixed-shaft model, rather than that ratio alone, supplies the numbers below. General external-force-to-joint-torque basis: [Modern Robotics, velocity kinematics and statics](https://modernrobotics.northwestern.edu/nu-gm-book-resource/velocity-kinematics-and-statics/).

Same benchmark: 50 mm centred stride, 12 mm lift, 70 mm carrier-shaft height, 1.8 s cycle, 80% stance, 566 g and three equal-load supports. Each row passed all 1,920 samples with no assembly-branch changes. Pairs are carrier/crank.

| Pickup / crank / rod, mm | Peak support torque, Nm | RMS support torque, Nm | Excursion, deg | Peak speed, deg/s | Peak axial rod force, N |
| --- | --- | --- | --- | --- | --- |
| 40 / 30 / 52 reference | 0.04204 / 0.04274 | 0.03077 / 0.02764 | 57.70 / 58.10 | 446.94 / 419.32 | 1.4417 |
| 32 / 36 / 52 longer crank | 0.04175 / 0.06079 | 0.03715 / 0.03974 | 57.70 / 44.00 | 446.94 / 288.95 | 1.7103 |
| 32 / 24 / 52 proportional reduction | 0.04198 / 0.04271 | 0.03121 / 0.02759 | 57.70 / 58.25 | 446.94 / 428.39 | 1.7819 |
| 28 / 22 / 52 compact alternative | 0.04182 / 0.04433 | 0.03206 / 0.02866 | 57.70 / 56.29 | 446.94 / 415.71 | 2.0162 |
| 28 / 20 / 50 minimum-crank alternative | 0.04223 / 0.04055 | 0.03087 / 0.02618 | 57.70 / 61.40 | 446.94 / 449.19 | 2.0395 |

The minimum-crank alternative uses the installed crank's nominal 20 mm length, with a new 50 mm leg, 30 mm carrier, 50 mm rod and 28 mm pickup in the WAVEGO-style direction. It is not the installed leg assembly or a drop-in conversion. Its peak rod/pickup force rises about 41.5% despite similar motor torque. The 32/24 option raises peak rod force about 23.6%. Rod force was independently computed from moment balance about the knee: absolute cross(T-D,F) divided by cross(E-D,unit(P-E)). Printed-joint strength, stiffness, wear and friction are not evaluated by the torque result.

Dense checks also covered 50 mm stride at heights 65 and 75 mm, and 60/70 mm stride at height 70 mm for all five rows: complete cycles and no assembly-branch changes. Independent forward reconstruction errors were below 9e-14 mm; central-difference Jacobian errors below 3.4e-8 mm/radian. Reproduction uses existing `wavego-study.js` exports `screen(g)` and `analyze(g,height,stroke)`, with the row dimensions and original foot angle 203.28375875845825 degrees (+1/-1 branches). Carrier, leg and foot-bend geometry remain unchanged, so the prior floor-clearance finding persists: at 70 mm shaft height, another point of the foot is 6.70/4.50/1.69 mm above the floor at 50/60/70 mm strides before material thickness. This is numerical evidence, not physical qualification or a new motion restriction.


## 2026-10-14 — Active Wireless parts versus last-confirmed assembled robot

Owner asked about torque and motion ranges of the current scene parts versus the active robot. Read-only Blender inspection reconfirmed scene Wireless, frame 43, in `ainekio-variable-gait-Recovery2.blend`. Live parameters are leg/carrier/rod/pickup/crank **45/35/30/28/20 mm**; the prior turn measured the four joint distances from all four live rig assemblies, with leg 45 mm nominal from part metadata. The robot comparison remains the owner's last-confirmed assembled **55/35/38/28/20 mm**, not a new physical measurement. Shaft offset is unchanged at approximately (-12.5001,+11.5000) mm. These are the original opposite-side pickup/foot arrangements, not the WAVEGO candidate.

Used the existing calculator with footAngle=0, kneeBranch=-1, crankBranch=-1, ideal point-foot lengths and neutral shoulder. Benchmark: 50 mm sweep centred beneath the carrier shaft, 12 mm lift, 1.8 s cycle, 80% stance; 566 g supported equally on three feet, upward force 1.850188 N per foot. H denotes carrier-shaft height above the floor, not chassis clearance. All rows below completed 1,920 samples on one assembly branch. Entries are carrier/crank pairs; torques are external-load demands, not motor ratings.

| H, mm | Installed peak torque, Nm | Scene peak torque, Nm | Installed excursion, degrees | Scene excursion, degrees |
| --- | --- | --- | --- | --- |
| 60 | 0.07401 / 0.05988 | 0.06871 / 0.05768 | 55.81 / 90.77 | 55.45 / 88.16 |
| 65 | 0.06832 / 0.05680 | 0.06606 / 0.06589 | 52.69 / 89.31 | 53.64 / 83.24 |
| 70 | 0.06216 / 0.05341 | 0.11754 / 0.11571 | 50.52 / 91.60 | 53.66 / 79.65 |

At H65 the scene reduces carrier peak demand 3.3% but raises crank demand 16.0%. At H70 it raises carrier demand 89.1% and crank demand 116.7%. Minimum acute rod-to-pickup transmission angle on the H70 planted path is 15.82 degrees versus 57.24 degrees installed. The shorter rod brings the closed chain toward collinearity as the body rises, increasing force/torque demands despite the shorter distal leg. H65 peak speeds are installed 423.62/577.53 versus scene 411.34/587.19 degrees/s; this is not a substantial speed reduction either.

**Isolating leg shortening:** a 45 mm leg with the original 38 mm rod gives H65 peak torque 0.05469/0.04873 Nm, roughly 20.0%/14.2% below installed. Reducing that rod to 30 mm loses these benefits at H65. The 45/38 combination does not close throughout the H70/50 mm benchmark, so it is not a general solution for the taller posture.

**Range:** carrier-plus-leg radial reach upper bound falls from 90 to 80 mm, before the rod/crank constraint. At H65, an 80 mm stride closes for the installed point-foot model but not the scene model; 70 mm closes for both. At H70, 60 mm closes for both, but the scene's minimum transmission angle falls to 5.01 degrees. At H75 the installed 50 mm stride closes on one assembly branch; the scene's samples individually solve but switch closure branch four times, so they do not form a valid continuous cycle on one assembly branch. These geometric checks do not establish collision-free, calibrated or load-capable usable strides.

The dense helper's finite-difference check failed on the H75 scene case near the singularity; the case was investigated with raw `mechanics.analyze` and branch changes were explicitly reported, rather than altering the solver or calling it valid. Complete H60–70 benchmark rows have independent FK reconstruction error below 1.4e-13 mm and Jacobian central-difference error below 7.4e-8 mm/radian. Computation can be reproduced with `wavego-study.analyze({...robotData.dimensions,leg:45,rod:30,footAngle:0,kneeBranch:-1,crankBranch:-1},H,50)` for valid rows and `mechanics.analyze` for the invalid-path diagnostics.

Conclusion: the scene is not a demonstrated strength/range upgrade over the assembled robot. Its benefit is modest at lower body height; it loses range and becomes substantially more demanding at taller height. Calculations omit real Part027 contact hull, collision geometry, dynamics, friction, joint compliance and actual support-force distribution. The method uses [Jacobian-transpose statics](https://modernrobotics.northwestern.edu/nu-gm-book-resource/velocity-kinematics-and-statics/). No Blender, firmware, calibration or robot-state changes were made.


## 2026-10-14 — Correcting the comparison to the actual question: standing up

Owner explicitly corrected the focus: getting the robot to stand, not reach or stride. The preceding near-doubling of torque was a peak over a walking stroke with X +/-25 mm, and must not be described as the torque of a centred static Stand or a straight body rise. Current source `posture.c` lines 12–36 constructs a planted-contact rise from 25 mm below its target. No live firmware pose or support-force distribution was measured here.

A standing-specific comparison now uses a **proposed** 25 mm vertical rise, carrier-shaft height 40 to 65 mm, foot directly beneath its carrier throughout, 566 g shared equally across four planted feet (1.387641 N each), neutral shoulders and no horizontal force. Sampled every 0.1 mm (251 poses), same assembly branch throughout. These are nominal point-foot static holding torques along the rise, excluding acceleration, linkage friction, collisions, actual soles, supply behaviour and uneven foot loads. All three geometries below close throughout this proposed rise.

| Geometry, leg/carrier/rod/pickup/crank mm | Peak carrier/crank torque during rise, Nm | Torque at final centred Stand, Nm |
| --- | --- | --- |
| Installed 55/35/38/28/20, original topology | 0.06623 / 0.03935 | 0.05112 / 0.02582 |
| Active scene 45/35/30/28/20, original topology | 0.06064 / 0.03228 | 0.04942 / 0.02649 |
| Short leg, original rod 45/35/38/28/20 | 0.06287 / 0.03453 | 0.04085 / 0.01916 |
| WAVEGO-style candidate 50/30/50/28/20 | 0.02549 / 0.02369 | 0.02502 / 0.02186 |

The scene reduces peak rise demand only 8.4% carrier / 18.0% crank. Shortening only the leg reduces the hardest carrier demand about 5.1%, although final holding demand improves considerably. WAVEGO-style rearrangement reduces peak rise demand 61.5% carrier / 39.8% crank in this comparison, giving a stronger modeled answer to getting up. It requires the new same-side pickup/foot geometry; it is not a length-only edit or proof the hardware will rise. Its definition remains footAngle=203.28375875845825 degrees, kneeBranch=+1, crankBranch=-1; original topology uses 0,-1,-1. Both shafts stay fixed. A second centred rise from 45 to 70 mm also closed for all four cases. No physical command, firmware change, CAD edit or calibration change was made.


## 2026-10-14 — Detecting an individual stalled leg

Owner asked about actual servo position and current draw as stall feedback. The standard three-wire MG90 connection provides power, ground and commanded PWM, with no exposed position/current telemetry. Inspected PCA9685 driver interface reports transport/output state, not measured joint angle or motor current; no current-sensor integration was found in the inspected board/assembly/driver paths. [NXP PCA9685 datasheet](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf) confirms a PWM output controller, not a motor-current or position sensor.

Actual angle can be obtained through an external encoder or, if the particular servo PCB permits it, a high-impedance tap of its internal feedback potentiometer with a fourth wire and suitable ADC interface. Exact MG90 PCB and voltage range must be inspected before a wiring prescription. [Pololu feedback-servos documentation](https://www.pololu.com/category/23/rc-servos) describes the fourth-wire potentiometer approach and blocked-output detection; [Pololu support](https://forum.pololu.com/t/how-to-know-servo-motor-is-not-moving/3500) discusses both potentiometer tapping and averaged current sensing.

One shared servo-rail current sensor measures total load and cannot identify a specific leg during simultaneous motion. A sensor on each leg's supply branch identifies the loaded leg; per-servo measurement distinguishes carrier/crank/shoulder. High current alone does not distinguish a blocked servo from acceleration or legitimate loaded holding. The strongest stall evidence combines target-versus-measured angle error, lack of progress, current draw and rail voltage; voltage identifies supply droop as a separate possible cause. IMU body tilt cannot uniquely identify an individual stalled joint. Feedback could inform standing corrections or diagnostics; detection does not inherently require automatic shutdown. No sensor, new runtime detection, fallback or shutdown was installed or implemented.


## 2026-10-14 — Existing IMU correction and its standing limitation

Owner asked whether gyro data can let the robot correct itself. Current source inspection confirms `balance.c` computes roll/pitch error and angular-rate damping, then solves corrected joint targets. `body.c` calls this during the planted rise, walking and continued standing hold. Sensor use requires applied calibration and available/fresh attitude outside estimator startup/recovery. This is verified source wiring, not confirmation of the currently deployed image, active feedback state or successful loaded correction.

The LSM6DS3 contains both accelerometer and gyro; combining gravity-referenced tilt and angular rates supports roll/pitch correction ([ST LSM6DS3 documentation](https://github.com/stm32duino/LSM6DS3)). Body attitude alone does not identify an individual stalled servo or reliably measure static floor clearance: a level chassis can be either standing or sagged on the floor. In current `body.c`, startup rise completion follows the commanded front/rear progression; it is not measured proof that the body rose. No new sensor requirement, completion restriction, stop, runtime behavior or physical motion was added. The useful immediate verification is deployed IMU freshness/calibration, balance-active state, correction direction and actual response under support; adaptive recovery beyond attitude compensation remains a separate behavior.

## 2026-10-14 — Live tilt test: balance inactive after a gesture

Owner reported no leg response while manually raising the front. Read-only gateway status checks around 21:52 UTC found the connected P4 reporting fresh, available, calibrated IMU data, with estimator startup/recovery false. Quaternion conversion gave approximately -16.3 degrees pitch and -2 degrees roll. Outputs reported ready and armed with fault 0, but balance was inactive and both corrections were zero. These are live controller reports, not measured servo positions.

The last tracked body command was `emote` asset `shrug`, sequence 33, from the coordinator. Current `body.c` clears balance hold when a new ordinary motion starts; a gesture does not restore standing hold on completion. Ordinary Stop also clears balance hold. This source behavior is consistent with the observed inactive state and explains why fresh tilt data alone did not cause a correction. It does not establish whether the servos can execute a loaded correction when balance is active.

Requested that the owner select Stand once through Body Control and report completion, leaving it in Stand for a fresh status check before another tilt. That physical verification remains pending. No motion command, firmware update, calibration change or runtime behavior change was sent by the agent. The direct board HTTP connection was unavailable; live evidence came through the existing authenticated local gateway session.

After the owner reported Stand complete, live status at 21:54:18 UTC confirmed manual Stand sequence 36 completed, no pending command, balance active and not reduced. Measured pitch was about -2.16 degrees; reported pitch correction was +0.015606 rad (0.894 degrees). Outputs remained armed with fault 0 and IMU fresh/calibrated. This confirms activation and computed correction in the deployed controller. Requested a supported front-lift observation next; physical leg response remains unverified.

At the owner's front-raised confirmation, status at 21:55:01 UTC showed approximately -11.25 degrees pitch and +0.078528 rad (4.50 degrees) correction, active/not reduced, with Stand still the last body motion. The owner's subsequent message "logs still" was interpreted as "legs still" and this interpretation was stated. This observation does not demonstrate successful physical compensation despite changing computed correction. A read-only calibration GET (sequence 37) captured published commanded pulses at approximately -10.54 degrees pitch for comparison after lowering; no calibration was changed. This GET also replaces the gateway's last-command tracking entry, so subsequent calibration entries there must not be mistaken for an operator calibration edit. Requested a lowered-position comparison to distinguish changing output commands from internal correction telemetry alone.

After the owner confirmed lowered, read-only GET sequence 39 at 21:58:10 UTC found pitch -0.037835 rad (about -2.17 degrees), correction +0.0154738 rad (0.887 degrees), balance active/not reduced and outputs armed/fault 0. Compared with tilted GET 37, rear-left carrier/crank pulses changed 2302/2304 to 2387/2355 us; rear-right changed 993/997 to 898/948 us. At the saved provisional 11.1111 us/degree, these are commanded carrier changes of 7.65/8.55 degrees and crank changes of 4.59/4.41 degrees. They are not measured shaft movements. Current `body.c` publishes these pulse values after its output driver returns success; an independent electrical waveform measurement has not been made. Thus changing correction reaches published output commands, while the owner's reported lack of physical motion remains unresolved. Asked whether Stand physically moved the legs and whether the separate servo supply is currently on. No firmware, mapping, gain or calibration change was made.

Owner confirmed Stand physically moved the legs and the servo supply is on. This rules out simply disconnected servo power for this test, but does not establish voltage under load or sufficient joint torque. Requested the same gentle tilt with the chassis securely supported and feet clear, observing the rear horns directly. That comparison is pending; do not label the loaded observation a confirmed stall or increase gains based on it alone.

Owner clarified the desired response: continued limb extension to compensate, using available travel rather than a small fixed response. Reinspection of `balance.c` confirms the current filtered PD target is 0.4 times attitude error minus 0.05 times angular rate, applied relative to the nominal pose. For stationary 11-degree pitch error it settles near 4.4 degrees of requested body correction; persistent error does not accumulate further correction. This is a controller-design limitation relative to the requested sustained leveling behavior, separate from the unresolved physical tracking observation. Proposed behavior is continued coordinated carrier/crank adjustment toward measured level, using the linkage's available extension when needed. Individual servo endpoints are not equivalent to maximum leg extension. No controller change was implemented.

## 2026-10-14 — Owner-authorized standing feedback repair

Owner explicitly requested a plan and implementation to fix the unsatisfactory extension response. Work is scoped to sustained stationary leveling, its linkage solution and tests; physical deployment and outcome are recorded separately below. Plan: reproduce persistent-error failure, verify front-up/rear-extension geometry, implement continuing correction, run native and firmware builds, then perform a supported hardware tilt test. A changing telemetry number alone is not the acceptance criterion.

**Reproduction:** added an ideal-actuator closed-loop test with a constant 0.08 rad (4.58-degree) disturbance. Existing feedback retained 0.057143 rad (3.27 degrees) error after four seconds and failed the new residual-error assertion. Existing body feedback tests passed, demonstrating their previous gap: they checked correction sign, changed pulses and lifecycle, not disturbance rejection.

**Implementation:** `ainekio_v2_balance_hold_apply` integrates `2 * attitude_error - 0.2 * angular_rate` over the actual frame interval into the accepted offset. Stationary `body.c` balance hold selects this function; moving gait/rise/entry retains the prior filtered PD controller. Zero attitude error retains the achieved offset. The already-authorized linkage/speed correction reduction applies to the proposed increment, retaining prior extension instead of scaling the entire offset toward nominal. Only the accepted increment is stored, so sustained unreachable demand does not accumulate a hidden backlog. Existing unavailable-IMU fade and Stop semantics remain. No joint mapping, horn index, Home value or new automatic stop was introduced.

**Linkage result consistency:** prolonged extension exposed an existing numerical edge case: float-angle encoding could return a frame whose linkage could not be reconstructed on the following sample. Corrected `walk_kinematics.c` to apply the existing closure criterion to the encoded result atomically and keep its joint radians consistent with that frame. This implements the previously approved reduction when a correction cannot fit the linkage; it adds no angle cap or different physical range. Native extension tests now retain a reconstructible pose at the boundary and reverse immediately when error reverses.

**Evidence:** ideal-actuator residual after four seconds is approximately 0.000094 rad (0.0054 degrees), tested in both signs of roll and pitch. Fixed nose-up input continues to a modeled 25.37-degree compensating body offset and approximately 17.57/17.58 mm of rear contact-point extension relative to the chassis. That boundary is a mathematical reachable result, not collision/torque qualification. Production body tests use the saved mirrored calibration: a held nose-up input extends the modeled rear supports over 10 mm after one second and changes each rear carrier output over 100 us. Tests also cover holding achieved correction at level, reversal without accumulated delay, stale-sensor fade, and Stop holding its final pose. All 51 native tests passed in `build/native-balance-repair` (68.18 seconds), including existing walking, Run, calibration, gesture and body execution checks. Firmware candidate is `0.8.44-p4-standing-level`; build/deployment verification follows.

**Network correction:** the previous direct connection used 192.168.0.44, which is the gateway host's local address, not the robot's current peer address. The active robot connection is from 192.168.0.89. Authenticated read-only maintenance through the gateway succeeded: running version 0.8.43-p4-staggered-rise, ota_1, idle, no pending verification or OTA error. No upload or activation has occurred at this point. The reported absence of physical movement under load is still unresolved until the new controller is tested on hardware.

**Build ready:** final ESP-IDF 5.5.4 application build succeeded for the configured pre-V3 P4, retaining the existing partition layout. Binary is 3,024,304 bytes; SHA-256 `b96f5c8c7a114a2b55e8fb959828249f2528041741ac7098dcf2a9f0c1fc7431`. A fixed upload copy is `/tmp/ainekio-0.8.44-p4-standing-level.bin`. After the full native suite, final feedback tests also passed with the stationary use of the existing joint-speed setting exercised at 3 degrees/second. Requested supported/servo-power-off readiness before Wi-Fi installation because activation restarts the controller. No physical correction success is claimed.

**Installed over Wi-Fi:** owner confirmed ready with support and servo power off. Uploaded the exact 3,024,304-byte image through the existing authenticated gateway maintenance endpoint; response was staged, body Doze. Explicit restart activation selected the new slot. Subsequent live maintenance status confirmed `0.8.44-p4-standing-level`, running/boot ota_0, pending_verify=false, ESP_OK. IMU was available/fresh/calibrated; before returning to Doze, output faults and transfer failures were zero. Recorded maximum motion calculation/frame times were 5,173/7,295 us versus the existing 20 ms output cadence. This is live boot/telemetry evidence, not loaded mechanical qualification.

Because the powered P4 accumulated correction while servo power was off, returned it to existing Doze before requesting servo-power restoration and a fresh Stand. Confirmed state dozing, output_armed=false and all twelve published pulses zero. The balance fields still retained their preceding values in status, so those cached fields must not be read as proof that disabled outputs are moving. Requested a chassis-supported, feet-clear powered test next; no powered motion success is recorded yet.

**Mirrored servo mapping:** in response to the owner's direction/inversion question, read back the saved configuration after reboot. Left carrier/crank joints 1/2 and 7/8 remain inverted with Home 2444/2577 us. Right carrier/crank 4/5 and 10/11 remain non-inverted with Home 856/723 us. Shoulder joints 3/6 are inverted; 0/9 are not. All channels, home_cd and 11.1111106873 us/degree values were preserved, saved=true and dirty=false. The new production-body test uses this mirrored map. This confirms configured electrical directions, not that physical indexing/direction has been independently verified on each joint.


## 2026-10-14 — Configurable self-leveling in Body Control

**Owner request:** add the self-leveling feature as a configurable Body Control option. Implemented an independent On/Off selection, default On, saved in P4 NVS separately from all joint and IMU calibration. Off invokes the existing correction fade; it neither stops a gait nor disables outputs. On resumes correction in the existing Stand hold or supported moving gait without starting another motion. Stop and gestures retain their existing behavior.

**Owner path:** dashboard Self-leveling select → authenticated `/api/balance` → selected gateway connection → negotiated `balance_control_v1` command → P4 configuration owner. Matching ACK plus `balance_status` confirms the value and persistence. UI reads from the robot before presenting a selection and separates enabled from active. A delayed response from a previously selected robot cannot overwrite the current robot's setting. Saving does not claim the walking command's ownership. The P4 updates the atomic selection only after NVS commit succeeds. Corrected stale Doze balance publication by publishing the reset body state after clearing feedback; output-disabled telemetry cannot claim active leveling.

**Validation:** native production-body tests cover Off fading to nominal with outputs enabled, On resuming the same Stand hold, and walking phase continuing while Off. NVS tests cover default On, saves while armed, reboot persistence, failed commit preserving the old setting, and unchanged calibration. Firmware `0.8.45-p4-leveling-control` builds with ESP-IDF 5.5.4. The 51-test native suite initially passed 50 tests; the new outbound reply fixture lacked its gateway receiver annotation. Correcting that fixture made the remaining control-fixture test pass. Dashboard JavaScript race tests pass including the new setting and continued Walk ownership. All valid/invalid schema fixture checks pass. Broader Python coverage checks expose pre-existing missing motion-speed/robot-settings fixtures and missing robot-settings schema definitions; these unrelated contracts were not changed. An initial network test run used websockets 15 from the camera environment, incompatible with the test suite's pinned websockets 10.4; rerunning under the installed 10.4 interpreter.

**Deployment boundary:** current robot still reports 0.8.44-p4-standing-level with outputs unarmed. Requested supported/servo-power-off confirmation before activating this new image because reboot executes startup rise. No new loaded-motion success is claimed.

**Ready for installation:** all 62 gateway/dashboard tests passed using the repository's required websockets 10.4 environment. The three broad Python protocol coverage failures were confirmed against the pre-change HEAD: missing motion-speed and robot-settings valid/invalid fixtures, plus missing robot-settings schema definitions. The new balance messages have valid/invalid schema and runtime coverage; targeted schema checks pass. `git diff --check` is clean. Fixed Wi-Fi artifact: `/tmp/ainekio-0.8.45-p4-leveling-control.bin`, 3,025,168 bytes, SHA-256 `7d551e12c22f8236edd2d917bc6ac69b874866e066051a6a534021f696a94200`. Activation and gateway reload await the requested physical readiness confirmation; the robot remains on 0.8.44.

**Installed over Wi-Fi:** owner requested installation. Uploaded the fixed 3,025,168-byte artifact and explicitly activated restart through the authenticated selected-robot gateway. Live maintenance confirms `0.8.45-p4-leveling-control`, running/boot `ota_1`, `pending_verify:false`, `ESP_OK`. Reloaded the gateway for `/api/balance`; the first restart used the launcher's relative argument after its working-directory change and failed. Restored it through the absolute existing launcher path with the original Python interpreter, saved runtime data and repo environment. Dashboard and robot reconnected on the existing addresses. Correlated live self-leveling readback: `enabled:false`, `saved:true`, `active:false`; outputs unarmed. Preserved that reported selection rather than changing it during verification. Owner confirms the switch is visible. No loaded physical leveling result is claimed.

**Next owner question:** calibration and response intensity are separate. Current Body Control exposes On/Off only. Existing firmware diagnostics can read/save sensor-to-body alignment and gyro bias; balance response gains are still compiled constants. Adjustable response gain, damping and a separate desired-level reference would require a further explicitly requested change. No additional controls or calibration changes were made.


## 2026-10-14 — Adjustable self-leveling response and target attitude

**Owner request:** make the leveling response adjustable. Added saved strength and damping multipliers plus desired roll/pitch offsets in Body Control. Defaults preserve the existing gains (1×, 1×) and reference (0°, 0°); positive roll raises the left side and positive pitch raises the nose. UI labels explain these directions. Use default response edits the form without changing On/Off or saving automatically. Controls do not alter servo calibration or available motor torque.

**Implementation:** negotiated `balance_tuning_v1` extends the existing correlated balance command. All four tuning fields are saved together; old enabled-only saves retain current tuning. A single versioned NVS record commits enabled plus tuning, published to runtime after success. Upgrade preserves the legacy On/Off record and starts with original response defaults. Reader locking excludes the NVS write. Both walking and stationary hold consume these settings on subsequent frames, retaining current motion and accepted correction. Existing linkage-fit/speed behavior remains. No new automatic stop, motion range cap, or sensor requirement was introduced.

**Validation:** 50 of 51 full native checks passed initially. The new production-body zero-gain assertion mistakenly expected an already-established standing offset to be zero. Pulse inspection showed all twelve targets unchanged and the prior offset retained, which is the intended hold behavior. Correcting the assertion to compare against the prior offset made the remaining body-feedback test pass. Model tests verify doubled response/damping effects and both target-angle signs in moving/standing modes; NVS tests cover legacy Off migration, atomic commit failure, reboot retention, enabled-only preservation, and unchanged joint calibration. UI tests verify readback, edit retention, and explicit defaults without changing On/Off. Five targeted protocol/schema/gateway tests pass. ESP-IDF build succeeds as `0.8.46-p4-leveling-tuning`; fixed image is 3,026,592 bytes with SHA-256 `e583a8f9b5547d0f0a11dcd72fe8375f5defa3c2ad77617cee3b3c93cd5fcd71`. Not yet deployed at this entry.

**Installed and verified over Wi-Fi:** owner confirmed the robot was supported with servo power off. Uploaded the fixed image through the existing authenticated gateway, then explicitly activated it. Live maintenance reports `0.8.46-p4-leveling-tuning`, running/boot `ota_0`, `pending_verify:false`, and `ESP_OK`. Reloaded the gateway through its existing absolute launcher path with its original environment. The upgrade retained self-leveling Off and the original response defaults: strength 1, damping 1, roll 0°, pitch 0°. An initial read was interrupted by a reconnect; retained logs reported reset reason 1 (power-on), without establishing its cause. Subsequent live readback succeeded with fresh telemetry and the robot in Doze, outputs disabled.

**Live Body Control verification:** the production browser controls read the four defaults, then saved those same values unchanged through the selected robot's gateway path (sequence 19). Confirmed readback changed the tuning status from original defaults to settings saved on robot, while On/Off remained Off. Desktop and 390-pixel mobile layouts showed no horizontal overflow or JavaScript exceptions. Saved tuning is operational; no loaded physical response or mechanical leveling success is claimed. The robot was left in Doze with outputs disabled and the gait research journal updated.


## 2026-10-14 — Separate Blender motion working file

Owner requested removal of stale motion scenes in a new file while retaining the original for reference. Saved `Slave/hardware/v2-12servo/Ainekio-Motion-Working.blend` from the live unsaved state. Original `ainekio-variable-gait-Recovery2.blend` was not overwritten; its before/after SHA-256 remained `262fef76557fb5f91e148cba9c638da6caeee57e0eacdded0f5076fba21b83fa`. A full pre-cleanup live snapshot, including unsaved edits, is at `/tmp/ainekio-motion-before-cleanup.blend` (temporary recovery, not the durable reference).

Removed nine obsolete scenes: Gait - 70 vs 82 mm; Gait - 82 mm body support; Gait - Stride and Rate; Geometry - 72 mm walking reference; Geometry - Compact 55 mm walk; Geometry - Compact linkage detail; Geometry - Compact39 proposed linkage; Geometry - Leg dimensions and motion; Motions - Firmware Remap. Dependency inspection found no external users of their exclusive objects/collections. Removed 3,121 exclusive objects, 20 ordinary collections and 2,067 now-unused object data/action blocks; no global orphan purge.

Retained Motion Library - 35-20-28 (23 chapters), Seated Support - 35-20-28, Wireless - Original 55mm Legs, Wired, Wireless, Monitor carrier and its Print layout. Retained scene object membership was checked before saving. A separate background Blender reopened the saved file with automatic scripts disabled and verified all seven scenes, 397 main-library objects and 23 motion chapters. The live main library already contained 397 objects when this task began; its earlier 409-object count was not restored over current edits. Main library remains selected. No motion retargeting, firmware changes or physical qualification occurred.


## 2026-10-14 — Upright Run bound for the installed linkage

**Owner report and scope:** Walk now moves the robot, but Run places the legs too far forward and the rear hits the floor. Owner requested correction and Wi-Fi installation. A diagonal trot was initially approved, then explicitly superseded by the owner's clarification that Run must retain animal-like front/rear bounding. The temporary trot changes were discarded. The final planner and geometry compiler are unchanged from the beginning of this task; the correction is in Run's authored trajectory configuration, with regression tests and documentation.

**Confirmed cause in commanded geometry:** existing forward Run used body Z -12 mm (20.75 mm below Walk's +8.75 mm), 3 mm bob, 6° pitch, a 20 mm forward-biased 74 mm planted sweep, 14 mm lift and different front/rear foot lanes. A native 200% sample showed body Z -15.00 to -9.01 mm and rear foot references reaching approximately -0.97 mm relative to the body origin. These are computed targets, not measured servos, forces or a diagnosis of the entire physical failure.

**Revised trajectory:** retained the existing front/rear paired phases, 42% stance, flight intervals, 1.2-second base cycle, Speed-to-cadence mapping and Walk/Run interpolation. Run now uses +8.75 mm body Z, zero fore/aft stride bias, zero programmed pitch/bob, unchanged nominal foot lanes, and up to 8 mm lift. Automatic forward Run opens from 32 mm near Speed 100 to 40 mm at Speed 200 (36 mm at 150). No Home/Stand preamble, speed limiter, pulse clamp, automatic shutdown or calibration change was introduced. The original linkage remains 35 mm carrier / 20 mm crank / 28 mm pickup / 38 mm rod / 55 mm lower leg, with bare Part027 contact and fixed shafts.

**Candidate rejection and correction:** a 44 mm candidate with a 5.5 mm forward body offset exceeded the existing review window at 2910 us. At 40 mm with that offset, newly added curved-Run coverage found a 383 us crank demand. Removed the candidate's body offset, centering Run on the existing foot reference. The final 40 mm path passes forward/reverse curves at Speed 100/150/200 and 50/100 Hz. This does not establish 40 mm as a global mathematical maximum; it is the fully tested upright candidate.

**Evidence:** all 51 native tests pass (25.69 seconds), including leverage, paired contact/flight, world-space planted anchors, requested cadence, startup, all cardinal Run directions, Walk/Run transitions, rapid reversals, explicit/automatic speed changes, Finish, and body feedback. Extended calibration regression reports 411–2889 us within the unchanged 400–2900 us review window. New tests require upright body targets and prevent recurrence of the former forward-reaching Run posture. At steady 200%, the final native path has body Z 8.75 mm, zero programmed pitch, 2.2222 cycles/s, rear foot reference X approximately -79.84 to -38.52 mm relative to body, and scheduled contact counts 0 or 2, confirming retained bounding. At 150%, requested cadence is 1.9444 cycles/s. Predicted speed is not measured displacement. Archived Blender/Run source recordings remain explicitly historical.

**Build ready:** ESP-IDF 5.5.4 build passed as `0.8.47-p4-upright-bound`. Fixed Wi-Fi image `/tmp/ainekio-0.8.47-p4-upright-bound.bin`, 3,025,616 bytes, SHA-256 `4c7803e7c96a8b4fcb26ca070a9db8528808f7c1ea0ece8749e37ac1a2fd61a3`. Live robot reports 0.8.46 and outputs enabled; requested support and servo-power-off readiness before installation. No hardware motion or OTA activation has been sent during this task at this entry. Loaded bounding and rear clearance remain physically unverified.


**Installed over Wi-Fi:** owner confirmed support and servo power off. Uploaded the exact 3,025,616-byte artifact through the authenticated selected-robot maintenance endpoint; response reported staged and body Doze. Explicit restart activation succeeded. Live status confirms `0.8.47-p4-upright-bound`, running/boot `ota_1`, `pending_verify:false`, `ESP_OK`. Sent Doze after startup; fresh telemetry confirms state dozing, `output_armed:false`, connected with fresh body clock. Readback retains self-leveling Off, saved strength/damping 1/1 and roll/pitch targets 0°/0°, tuning_saved=true. No powered bounding trial was conducted; the owner's loaded rear-clearance check remains next.

## 2026-10-15 — Level reference, visible corrections, and stationary gyro calibration

**Owner report:** on a level surface, self-leveling curls the front-right leg and shortens the front pair; Off resolves it. Owner repositioned the IMU level in the frame and confirmed the frame is supported. Fresh read-only telemetry with leveling Off still measured approximately -2.15 degrees roll and +2.55 degrees nose-up pitch. Earlier On telemetry showed accepted correction approximately +17 degrees roll and -15.4 degrees nose-up pitch. With a supported frame, leg movement cannot necessarily reduce measured attitude error, so the existing standing integrator can continue toward its modeled workspace boundary. These observations do not establish a reversed physical servo. Existing mirrored joint calibration is retained.

**Implemented:** Body Control Self-leveling now shows fresh quaternion-derived tilt even while feedback is Off; offset from saved targets; commanded body correction; reduced-correction status; and physical front-left/front-right/rear-left/rear-right extension and joint-angle changes. Per-leg telemetry is derived from the successfully written pose relative to its nominal motion, with chassis transform removed. It is explicitly commanded/model data, not sensed servo position or contact.

**Level reference:** with the frame physically level, “Use current pose as level reference” copies measured roll/pitch to the existing target-angle fields. “Save on robot” explicitly persists them. This retains the current On/Off choice, strength and damping. The target error reads zero at that reference; raw sensor angles remain visible. Capturing the reference does not send a command or silently change calibration. No sampled baseline has been remotely saved during this work.

**Stationary gyro bias:** a separate explicit button requests 256 new raw samples from the existing acquisition owner, which saves their mean into the existing IMU calibration record and applies bias between samples. No reboot, axis/mounting change, actuator command or automatic Off/Stop is introduced. Sample standard deviations and completion/storage error are visible. The operator must keep the robot still; this does not measure accelerometer bias/scale. The new `balance_feedback_v1` capability distinguishes this request and per-leg diagnostics from earlier firmware. Existing control gains, correction reduction, motion range, inversion and walking/running paths are unchanged.

**Validation:** all 51 native tests passed (26.87 seconds), including body feedback and hardware-IMU diagnostics. New tests cover physical leg ordering, matched rear extension, raw-sample averaging, standard deviation, live bias application without AHRS reset, preserved mounting, failed storage preserving active bias, and command decoding. Three targeted gateway tests passed, including calibration receipt correlation and preservation of the current motion owner. Dashboard motion/race, workspace navigation and body-event tests passed. Live desktop/mobile browser inspection verified fresh tilt and the reference control with the current firmware; no page overflow or JavaScript errors. The old firmware correctly shows per-leg/gyro features as awaiting update.

**Build/install preparation:** ESP-IDF 5.5.4 built `0.8.48-p4-leveling-feedback`. Fixed artifact `/tmp/ainekio-0.8.48-p4-leveling-feedback.bin`, 3,028,496 bytes, SHA-256 `9b7664c743470cd87635e1d84e5e952413c1bac7813ef1381a1f0c6cc5787d5c`. Owner confirmed supported with servo power off. Wi-Fi upload is underway; boot verification and physical direction/loaded-leveling checks are not yet complete.

**Installed and checked:** exact Wi-Fi artifact staged and activated successfully. Live maintenance confirms `0.8.48-p4-leveling-feedback`, running/boot `ota_0`, `pending_verify:false`, `ESP_OK`. Reloaded the existing gateway with its current runtime environment for the new calibration operation; a subsequent launcher restart briefly interrupted dashboard access, then the robot reconnected normally. New status fields arrived with zero commanded adjustments while leveling was Off. Post-update desktop/mobile checks showed fresh tilt, offset from saved targets, enabled level-reference control, and “Ready for a stationary gyro measurement,” with no browser errors or page overflow. Final fresh status confirms Doze, outputs disabled, leveling Off, saved strength/damping 1/1 and targets 0/0. No gyro measurement or new reference was automatically saved. The owner can now level the chassis, capture the reference, and Save; physical axis directions and loaded correction remain unverified.

**Post-calibration inactivity report:** owner saved level-reference targets approximately roll -2.0112 degrees and nose-up pitch +3.0183 degrees, with strength/damping 1/1 and self-leveling On. Initial live readback was active with less than 0.2 mm commanded leg adjustment and roughly 0.1 degree residual error. During the subsequent 45-second read-only observation, leveling was inactive throughout; IMU remained fresh near the saved reference and no distinct tilt was captured. Follow-up gateway state identified the body command as Stop, sequence 22. Production `body.c` clears `balance_hold` and correction on hold/Stop, matching the observed On-but-inactive state. This is the current Stop semantics, not evidence that saving the reference disabled feedback. No settings or movement commands were issued during this diagnosis. Requested physical tilt remains unverified; select Stand to re-enter supported leveling before that check.

## 2026-10-15 — Revised Walk and PCA9685 pulse staggering (0.8.49)

**Owner request:** improve the slow, short, unnatural Walk, increase useful distance and foot clearance, and enable PCA9685 staggering. The owner approved these changes. Existing installed linkage and shaft locations remain 35 mm carrier / 20 mm crank / 28 mm pickup / 38 mm rod / 55 mm bare Part027 leg. Saved Home references, inversions and IMU settings are unchanged. Run retains its front/rear bound.

| Walk parameter | Previous | Revised |
| --- | ---: | ---: |
| Full planted sweep | 32 mm | 37 mm |
| Low/full-gain foot lift | 4 / 8 mm | 6 / 10 mm |
| Stance fraction | 80% | 78% |
| Lateral support-shift amplitude | 9 mm | 7 mm |
| Body Z reference | +8.75 mm | +7 mm |
| Forward Walk amplitude/rate blend | 2 cycles | 1 cycle |
| Cycle at Speed 100 | 0.9 s | 0.9 s |
| Planned travel at Speed 100 | 44.44 mm/s | 52.71 mm/s |

The planned travel increase is 18.6%, not a measured speed improvement. Quarter-cycle footfall offsets remain staggered, with three or four scheduled contacts. Supporting legs continue moving as the body advances. Vertical swing now uses a broader quartic arch with zero velocity at both contacts; the same peak lift clears the floor earlier than the prior sixth-degree arch. The diagnostic pose sampler now uses the same horizontal return shape as runtime Walk. Support transfer has a 0.02-cycle phase lead and a mean forward translation of 9 to 3 mm, interpolated with squared stride gain. This preserves support through medium steps. No gait-clock slowdown, new stop, pulse clamp, guard or sensor prerequisite was added.

**Selection evidence and tradeoffs:** initial 40 mm candidates reached beyond the earlier reviewed pulse window; simply reducing sway or shortening stance without moving the support-transfer phase also produced negative modeled support margins. The final 37 mm path follows the native command and anchored-foot path, including curves and Finish. It uses a body reference 1.75 mm lower than the preceding Walk. The final straight-path study samples every integer Speed 1–100. Its lowest modeled dynamic support margin is only 0.064 mm (Speed 83): this is not robust physical stability evidence, especially with unmeasured actual center of mass and floor friction. At Speed 100, the loaded lower-leg angle reaches 43.83 degrees above horizontal versus 47.48 previously. Peak commanded steady carrier/crank speeds are about 466/412 degrees/s versus 430/404 previously. Modeled peak external carrier/crank torques are 0.0996/0.0784 Nm versus 0.0956/0.0674 Nm: the longer step does not provide free torque, and physical tracking must be tested. The model assumes centered 566 g mass at original Z 65 mm and omits link/gear inertia and actual servo response.

**Pulse staggering:** `ainekio_pca9685/pca9685.c` now sets each active channel's ON count to `floor(4096 * channel / 12)` and OFF to `(ON + pulse_width_ticks) mod 4096`. Adjacent starts differ by 341/342 counts, roughly 1.67 ms at nominal 50 Hz. One I2C frame write remains; there are no channel-by-channel sleeps. Disabled outputs and channels 12–15 remain full-off. Pulse widths, mapping and nominal refresh frequency are unchanged. These are staggered control signals; MG90 motor-current reduction is not proven by register tests and requires an electrical measurement.

**Clarification requested by owner:** the “calibration boundary” mentioned during comparison meant the previous offline 400–2900 us review window. It is unrelated to self-leveling, is not a measured mechanical stop, and is not a new runtime movement restriction. A calculated excursion outside that window does not by itself establish collision or stall.

**Validation:** all 51 native tests pass in the final tree (25.58 seconds), plus the separate PCA9685 driver suite. Walk tests now cover every integer Speed 1–100, commanded lift, increasing stroke, at least three planned contacts, no preparation sequence and the unchanged wall-time clock. Production pulse mapping checks cover all these speeds forward/backward, curves at 50/100 Hz, Walk/Run transitions, Finish, and the historical full-curve Speed 50 → 89 → 145 failure. Combined mapped pulse span is 403–2885 us. The 16-case native audit has no linkage regression-margin misses or command failures. The archived Run recording is retained; only the four Walk demonstrations were regenerated. Register tests cover unique channel phases, unchanged 400/1500/2900 us widths, counter wrap, individual detach, unused outputs and one transaction per frame. The P4 firmware build succeeds. No scope trace, current measurement or powered walking trial has yet validated this revision.

Reports: [straight comparison](../gait-research/walk-stagger-20261015/straight-comparison.json), [native commands](../gait-research/walk-stagger-20261015/native-audit.json), [curved pulse mapping](../gait-research/walk-stagger-20261015/curved-pulses.json). These contain offline target data, not captured robot logs.

**Wi-Fi artifact:** `0.8.49-p4-staggered-walk`, 3,028,544 bytes, SHA-256 `511da92abb50152915c3ce3692a9ca6e13a55c8987088c8ac112935adea71319`. Prepared at `/tmp/ainekio-0.8.49-p4-staggered-walk.bin`. Read-only pre-update status confirmed online robot `ainekio-p4-e6ebe5`, running `0.8.48-p4-leveling-feedback`, outputs enabled and leveling Off. Owner then confirmed frame supported and servo power Off; Wi-Fi upload initiated. Activation and runtime confirmation follow below.

**Installed and verified:** Wi-Fi upload returned `staged`, body Doze; activation returned `selected_for_next_boot`. After the reconnect, live firmware status confirms `0.8.49-p4-staggered-walk`, running/boot `ota_1`, `pending_verify:false`, `ESP_OK`, session epoch 9. Startup completed with outputs enabled; the owner-confirmed external servo supply remains off for this update. Self-leveling readback remains Off, as before the update. No powered Walk, Run, servo-range measurement or current test was issued. The software update is verified; physical gait improvement and electrical benefit remain to be measured.

## 2026-10-15 — Run, Crawl and Crab revision (0.8.50, prepared)

**Owner request:** update Run, Crawl and Crab following the revised Walk. The installed 35/20/28/38/55 mm linkage, fixed shafts, bare Part027 floor contact, saved Home references and inversion remain the basis. Run retains the explicitly requested front/rear bound. No additional stop, limiter, fallback, pulse clamp or sensor prerequisite was introduced. PCA9685 staggering remains enabled; ordinary Walk and self-leveling settings are unchanged.

**Contact-model correction:** runtime Crawl and Crab still selected the historical boot/toe contact profile. Both now use the same measured bare Part027 surface as the installed robot. Native geometry checks and new recordings use that same physical surface. The retained Crouch gesture is a separate historical asset: it was not regenerated. Its entry regression now pins its archived entry instead of incorrectly equating it with the new bare-foot Crawl entry. Gesture-source validation remains separate from the native locomotion recording validator.

| Parameter | Previous | Revised |
| --- | ---: | ---: |
| Run full planted stroke | 40 mm | 44 mm |
| Run minimum / maximum lift | 2 / 8 mm | 5 / 12 mm |
| Automatic Run stroke above Speed 100 | 32–40 mm | 37–44 mm |
| Run body Z reference | +8.75 mm | +5 mm |
| Crawl full planted stroke | 18 mm | 32 mm |
| Crawl minimum / maximum lift | 2 / 4 mm | 5 / 8 mm |
| Crawl body Z reference | −20 mm | −5 mm |
| Crawl stance fraction | 70% | 78% |
| Crab fore/aft planted stroke | 36 mm | 40 mm |
| Crab sideways planted stroke | 24 mm | 32 mm |
| Crab minimum / maximum lift | 6 / 12 mm | 8 / 14 mm |
| Crab stance width | 190 mm | 160 mm |
| Crab body Z reference | −22 mm | −12 mm |
| Crab stance fraction | 75% | 80% |

Run retains its 42% paired stance, flight intervals, existing cadence and 20-degree turn setting. At Speed 200, planned straight travel rises from 95.24 to 104.76 mm/cycle, or 211.64 to 232.80 mm/s at the unchanged 0.45-second cycle. Lowering the body reference 3.75 mm accommodates the longer centered stroke through the mounted linkage; this is an explicit posture tradeoff, not a torque improvement claim.

Crawl and Crab use the broad quartic vertical swing already adopted for Walk and the prompt horizontal return with short endpoint ramps. Direction-specific body-frame harmonic translations transfer weight as the single swinging leg changes, without moving planted anchors or slowing the gait clock. Crawl removes its former small bob/roll/pitch oscillations. Crab adopts source-leg phase offsets [0, 0.5, 0.75, 0.25]. It retains the existing 32.73-degree turn, base period, command interfaces and entry/Finish ownership. Its narrower stance remains wider than normal Walk (approximately 134.2 mm).

At full gain, planned Crawl travel rises from 25.71 to 41.03 mm/cycle (about 59.5%). Crab forward travel rises from 48 to 50 mm/cycle (4.2%); sideways travel rises from 32 to 40 mm/cycle (25%). Stance fraction affects the conversion from planted stroke to cycle travel, so the stroke percentage alone is not the speed improvement. These are commanded distances, not measured displacement.

**Load-model evidence and limitations:** the 48-case study uses current native targets, bare-foot forward geometry, complete body Euler rotation, and the owner-provided 566 g mass. COM is still assumed centered at original Z65 mm. Sampled Crawl support margin is at least 0.766 mm across the studied four directions and Speeds 1/25/50/100. Crab retains negative modeled margins: approximately −3.885 mm during full turns, and −0.052 mm at backward Speed 50. Larger harmonic shifts improved the assumed support but demanded pulses outside the existing review window, so the installed candidate retains a smaller turn support shift and the original turning angle. This does **not** establish robust physical stability. No runtime restriction was added to hide that limitation. Actual COM, foot friction, servo tracking, link inertia and yaw inertial moments remain unmeasured. Paired/flight Run dynamics are not evaluated by the three-foot support model.

At full forward commands, sampled carrier/crank speeds are approximately Run 401/375 degrees/s, Crawl 428/423, and Crab 429/393. Modeled forward Crawl external carrier/crank peak torques are 0.117/0.093 Nm; Crab 0.114/0.085 Nm. Those are estimates, not measured motor load or stall qualification. The calculation's four-contact least-squares force split can produce negative force fractions and is not a contact dynamics simulation.

**Validation:** all 51 native tests pass (26.04 s). The expanded production mapping test now covers all four Crawl and six Crab directions through entry, speed/rate changes and Finish, including 10/20/40 ms output intervals. Combined production mapping checks report 402–2898 us, within the unchanged offline 400–2900 us review window. Run tests preserve paired/flight semantics, commanded cadence, curved commands and Walk/Run transitions. The 26-case native audit completes without linkage-margin failures. Fourteen locomotion demonstrations were regenerated and their full-hull/interpolated geometry checked. The historical Run and Crouch recordings remain intact. The P4 build succeeds.

Reports: [native audit](../gait-research/run-crawl-crab-20261015/native-audit.json), [support/load study and exact configurations](../gait-research/run-crawl-crab-20261015/support-study.json), [validation summary](../gait-research/run-crawl-crab-20261015/validation-summary.json).

**Prepared Wi-Fi artifact:** `0.8.50-p4-gait-library`, 3,027,824 bytes, SHA-256 `8460df6e98d55ede70e8e7e35c2702801702d2f8b736491af925ef08a3671f6b`; fixed copy `/tmp/ainekio-0.8.50-p4-gait-library.bin`. Read-only Wi-Fi status confirms robot `ainekio-p4-e6ebe5` online, still running 0.8.49 on ota_1, pending_verify false, outputs enabled and self-leveling Off. No hardware motion or update was issued in this task. Fresh supported/servo-power-off confirmation is needed before activation because restart runs startup rise. Loaded gait performance remains unverified.

**0.8.50 installed and verified over Wi-Fi:** owner confirmed the robot supported and then explicitly confirmed separate servo power Off. The prepared artifact checksum matched before upload. Upload returned `staged` with body Doze; activation returned `selected_for_next_boot`. After restart and reconnection, live status reports `0.8.50-p4-gait-library`, running/boot `ota_0`, `pending_verify:false`, `ESP_OK`, session epoch 10. The controller returned Active with outputs enabled; self-leveling remains Off. External servo power was owner-confirmed Off for installation. No powered gait commands were issued. Deployment is verified; loaded Run/Crawl/Crab performance, including the recorded Crab-turn support limitation, remains unverified.


## 2026-10-15 — Expressive seated Wave (source revision)

**Owner direction:** keep Wave seated, with a quick lift and big playful waves. This revision changes Wave only. It preserves the installed 35/20/28/38/55 mm linkage, fixed servo shafts, saved Home references and inversion. No runtime gate, clamp, automatic stop, fallback, calibration change or new sensor requirement was added. The existing motion-rate and joint-speed settings still apply.

| Authored parameter at 1x playback | Previous Wave | Revised Wave |
| --- | ---: | ---: |
| Seated entry complete | 3.0 s | 1.2 s |
| Arm lift complete | 4.2 s | 1.6 s |
| Extended waving starts | 5.8 s | 2.0 s |
| Shoulder wave amplitude | ±18 degrees | ±42 degrees |
| Wave cycles | 3 | 3 |
| Foot replaced | 12.2 s | 4.8 s |
| Standing recovery complete | 15.2 s | 6.0 s |
| Clip duration | 16.0 s | 6.2 s |

The old gesture used the boot contact hull even though the owner confirmed bare Part027 floor contact. Evaluating it with the bare leg left supporting feet approximately 1.6–2.1 mm above the modeled ground. Wave now has its own bare-leg contact hull and refitted entry/support poses; the separate Sit command is unchanged. Its sequential rear-foot placements remain, retimed into the entry, and recovery reverses that entry. The seated body pitch is −25.5 degrees, with nominal 1 mm complete-body hull clearance. Physical front-left is model/CAD RL, joints 6–8. The other three joint triples and body pose remain constant throughout arm lift, waving and replacement.

**Offline results:** 745 source samples at 120 Hz; approximately 447.70 degrees/s peak source joint speed, below the unchanged 545.45 degrees/s default. Saved calibration readback maps the source to approximately 438.63–2861.37 us inside the existing 400–2900 us review window. No pulse bounds or inversions were changed. During the three waves, bare foot clearance is at least 40.23 mm; assumed support margin while the arm is airborne is at least 19.32 mm. Minimum linkage closure height is 13.42 mm. The compact C playback comparison at 1,489 Wave sample times gives maximum sole-vertex difference 0.00781 mm and clearance difference 0.00697 mm from the full source.

**Unresolved physical qualification:** the inherited sequential seating/standing foot-placement pattern has a minimum modeled support margin of −13.49 mm with the assumed COM. That transient is not quasi-statically supported by the modeled active feet; positive margin during the seated wave does not prove the entry stable. Whole-body/shoulder collision clearance, current demand, actual COM and loaded tracking of the larger/faster swing remain unmeasured. The pulse-window and linkage checks do not prove physical clearance or strength. The active Blender scenes were inspected but not modified or claimed to preview this new Wave. No powered Wave command or firmware deployment was issued.

Authoring owner: `Slave/software/models/v2-12servo/tools/author_expressive_wave.py`. It consumes canonical Sit, the current bare contact shape, geometry and a local saved calibration readback. Source, manifest, contract phases/contact events/face cue timing, posture and catalog hashes were updated together. Tests now distinguish Wave's bare-foot entry from archived boot-foot gestures and cover the 84-degree sweep, duration, reversed recovery, stationary support legs and grounded bare contacts. The calibration test fixture uses the current 1500 us first shoulder Home readback (previous fixture was 1600 us).

**Completed verification:** all 51 native tests pass (65.12 s while the independent P4 build was running); the 24 compiler/handoff tests also pass after the final provenance/hash updates. The P4 build succeeds in `/tmp/ainekio-wave-20261015/p4-build`. Its compiled Wave duration is 6,200,000 us, and its certified interpolation peak is 453.57 degrees/s (the sample-gradient estimate above is 447.70). No runtime slowdown is required at 1x under the unchanged 545.45 degrees/s default.

The shared firmware version had independently advanced to `0.8.51-p4-lateral`; this task did not alter that version or deploy over the other work. Build artifact: 3026208 bytes, SHA-256 `80f1dc2fe7151b8c901d7e929431af1902e9fa1b8c60043e7238c61e96fa7eae`. Wave source SHA-256 `e117471c079df2cd697a30b769e96138a374f9ce42e17980bb69720b1233e61e`. This is a build result, not an installation or physical qualification.

**Owner-requested Wi-Fi installation, 2026-10-15:** owner explicitly requested proceeding with the Wave firmware ("we are going to yolo this"). Pre-update live readback: `ainekio-p4-e6ebe5` online on `0.8.51-p4-lateral`, ota_1 running/boot, pending_verify false, ESP_OK, outputs disabled and self-leveling Off. External servo-supply state was not independently confirmed this turn. The existing startup-rise behavior on activation was stated before upload. Version advanced to `0.8.52-p4-wave` to distinguish the new artifact, preserving current lateral work. Incremental P4 build succeeds; artifact is 3,026,208 bytes, SHA-256 `ba32987fe8880e24bd66cc3228042b67e65a255de034c65f7f901c01fd9b46c5`. Fixed upload copy: `/tmp/ainekio-0.8.52-p4-wave.bin`. Wave source SHA remains `e117471c079df2cd697a30b769e96138a374f9ce42e17980bb69720b1233e61e`. Upload initiated through the existing authenticated gateway; activation/readback results follow.

**0.8.52 installed and verified:** upload returned `staged` with body Doze; activation returned `selected_for_next_boot`. Live Wi-Fi readback after restart confirms `0.8.52-p4-wave`, running/boot ota_0, pending_verify false, ESP_OK, session epoch 2. Controller is Active with outputs enabled; self-leveling remains Off. No Wave command was sent. OTA deployment is verified; expressive-motion tracking, body clearance and the seating-transition support limitation remain physically unqualified.


## 2026-10-15 — Expressive Point, Pushup and held Bow (0.8.53)

**Physical feedback and owner direction:** owner reports the installed 0.8.52 Wave is good, then requests the same dramatic character for Point, Pushup and Bow: Point faster, Pushup much deeper/faster, Bow faster into position with a longer hold. The accepted Wave source remains byte-identical (`e117471c079df2cd697a30b769e96138a374f9ce42e17980bb69720b1233e61e`). This is qualitative owner acceptance of Wave, not general mechanical/load qualification of all poses.

**Confirmed Pushup failure mechanism:** the former reauthored high/low body poses largely canceled the front press. Full body-hull FK gives front underside heights 53.15655 mm at the high endpoint and 53.18585 mm at the nominal low endpoint: only 0.0293 mm, slightly upward instead of a downstroke. The complete hull minimum changed 24.88427 to 23.32680 mm (about 1.56 mm), primarily at the rear. Merely accelerating that recording would retain the ineffective movement.

| Authored behavior at 1x playback | Previous | Revised |
| --- | ---: | ---: |
| Point fully extended | 4.2 s | 1.55 s |
| Point extension hold | 2 s | 1.5 s |
| Point complete clip | 11 s | 4.8 s |
| Pushup front underside high / low | 53.157 / 53.186 mm | 48.329 / 3 mm |
| Pushup presses | 5 | 5 |
| Pushup down / bottom hold / up | 1 / 0 / 1 s | 0.6 / 0.1 / 0.45 s |
| Pushup complete clip | 14.5 s | 7.35 s |
| Bow reaches low pose | 2.5 s | 1.05 s |
| Bow low hold | 3 s | 5 s |
| Bow complete clip | 8.5 s | 7.3 s |

Point retains its full extended arm (about 111.51-degree carrier and 70.43-degree crank model offsets), with a quicker support shift, lift and extension. Bow retains its forward-hand stretch and approximately 2.024 mm modeled body clearance. Both hold exactly, then retrace their fitted entry. This avoids an observed bare-contact IK branch discontinuity when independently solving Bow recovery from its old boot-based seed. Contact IK follows the preceding solution during entry. Point's arm lift blends the bare-contact pose correction out before extension; recovery retraces the same join.

Pushup is rebuilt as a body-space front press with all four foot anchors fixed. The high/low poses keep body X at −20 mm, change pitch from −15 to +5 degrees, and solve body Z for complete-hull clearances 24 and 3 mm. Front underside displacement is 45.329 mm; rear underside changes 24 to 17.030 mm. The 0.7-second preparation and recovery move between normal bare-foot standing and the press posture. The five presses each descend in 0.6 seconds, hold the low pose 0.1 seconds and rise in 0.45 seconds. These are gesture timings, not runtime waits or command-admission blocks.

All three now use their own bare Part027 contact hull copies and the installed 35/20/28/38/55 mm linkage with fixed shafts. No saved calibration, Home pulse, inversion, runtime safety behavior, restriction, fallback or motion-rate setting was changed. Fresh Wi-Fi calibration readback confirms the same Home/direction/scaling values used for authoring; only current commanded pulse readbacks differed. The old `servo_profile.json` coupled envelope still describes historical geometry and rejects existing accepted motions as well; it was not treated as evidence of collision in the current geometry or changed to mask a fit. Whole-body collision qualification remains explicitly false.

**Validation:** all 51 native tests pass (31.77 s), including new user-behavior checks for prompt Point extension, five full-depth planted Pushups, five-second stationary Bow hold, entry/completion and saved pulse mapping. Source sampling, compiled derivatives and library-wide Home/terminal entry paths pass. Compiled peak joint speeds are Point 296.17, Pushup 262.97 and Bow 370.26 degrees/s, below the unchanged 545.45-degree/s default at 1x. Sampled mapped pulse spans are Point 448.70–2479.32 us, Pushup 721.70–2578.29 us, Bow 812.46–2487.54 us. Minimum assumed support margins are respectively 24.64, 44.32 and 51.98 mm. No runtime clamp was added.

Full bare-hull compiled/source comparisons cover 1,153 Point, 1,765 Pushup and 1,753 Bow sample times, with maximum sole-vertex errors 0.00834, 0.00682 and 0.00596 mm. The library-wide comparison passes as well. These are geometry and numerical playback results: actual torque/current, servo tracking, frame flex, contact friction (especially Bow's intentional forward hand slide), physical body clearance and collision remain to be tested. Blender animations were not updated by this firmware task.

Reproducibility: `Slave/software/models/v2-12servo/tools/author_expressive_gestures.py` consumes the retained [baseline archives and validation summary](../gait-research/expressive-gestures-20261015/validation-summary.json), current geometry/contact assets and a local saved calibration readback. Baseline recordings are preserved as compressed JSON; Point/Bow retain their spatial choreography with bare-contact refitting, while Pushup gets the new body-space path. No unrelated gestures or locomotion were reauthored.

**Wi-Fi installation prepared:** P4 build succeeds as `0.8.53-p4-emotes`, 2,905,072 bytes, SHA-256 `a8f6287bafd31e5b8a134b78a0d7cf579d2d18edba500c31a98567eb057fc5b3`. Pre-update live readback confirms online 0.8.52-p4-wave, ota_0 running/boot, pending_verify false, ESP_OK, Active, outputs enabled, self-leveling Off. Update uses the existing gateway upload/Doze/activation path. Startup-rise behavior was stated before upload. No physical gesture command was sent. Installation verification follows.

**0.8.53 installed and verified over Wi-Fi:** upload returned staged/Doze; activation selected the new image. Live readback confirms 0.8.53-p4-emotes, running/boot ota_1, pending_verify false, ESP_OK, session epoch 15, Active, outputs enabled, self-leveling Off. No Point, Pushup or Bow was remotely executed. Gesture physical behavior remains for owner testing. Additional observed status: the latest storage receipt reported mounted=false and ESP_ERR_NO_MEM. This is separate from the successful OTA status; its cause/preexistence was not determined and storage work was not broadened into this motion task.

## 2026-10-15 — Rear-squatting Point, slower braced Pushup, brisk Worm (0.8.54)

**Owner correction:** Point must squat both rear legs before pointing; Pushup must squat the rear and press more slowly. “Work” was explicitly clarified as Worm, requested faster and more dramatic. This supersedes the prior request for faster Pushup strokes. Wave remains physically accepted by the owner; Wave and Bow sources remain byte-identical to 0.8.53.

**Point:** reuses the accepted Wave's complete 1.2-second seated entry, including its sequential foot placements, before lifting the physical front-left leg in 0.4 seconds and fully extending it in 0.6 seconds. Both physical rear legs (model FL/FR) retain the seated pose throughout the 1.5-second point hold. The arm keeps the prior 111.51-degree carrier / 70.43-degree crank endpoint. Recovery replaces the foot before reversing the seating entry. Total 6.1 seconds; full extension at 2.2 seconds includes the now-explicit rear squat. This replaces the previous asymmetric weight shift, which did not squat both rear legs. The standing, seating and air-arm poses use bare Part027 contacts.

**Pushup:** a 1-second rear-first squat lowers rear body-hull clearance to 8 mm. Five presses then keep that rear clearance constant while front clearance moves from 44.729 to 3 mm (41.729 mm travel), with all four foot anchors planted. Each descent takes 1.1 seconds, bottom hold 0.2 seconds, ascent 1.1 seconds. Recovery takes 1 second, followed by a 0.2-second standing hold; total 14.2 seconds. Rear joints are allowed to articulate to maintain the low rear posture; they are not locked. High-pose rear carrier offsets are approximately −36.51 degrees. This is a deeper rear squat than the previous 24 mm rear clearance, with substantially slower presses.

A literal fixed-joint Wave seat could not provide the requested deep front press with the existing front-foot anchors: the front servo mapping exceeded its saved travel as the body pitched down. Holding only 1 mm rear body clearance with those seated anchors also produced unreachable rear IK. The final Pushup instead uses standing foot anchors and a body-space rear-clearance constraint, solving every joint at every sample. It does not drag the front feet forward or silently reduce the front press depth.

**Worm:** three 1.6-second front-to-back body waves, with 0.7-second entry/recovery and 0.2-second standing hold (6.4 seconds total, previously 20 seconds). Pitch reaches ±20 degrees; fore-aft body translation is −16 ±6 mm. Whole-body minimum clearance follows a 4–16 mm heave envelope. All four bare feet remain planted. The first/last 0.3 seconds smoothly introduce/remove wave amplitude without pausing between cycles. An initial 14-degree candidate was discarded in favor of retaining the previous broad pitch range; shifting the body farther back allowed the ±20-degree motion within the existing pulse mapping.

Authoring is repeatable with `tools/author_seated_emotes.py`, retained pre-change source archives (including accepted Wave), current fixed-shaft geometry/contact hulls and local saved calibration. Existing `author_expressive_gestures.finish` now also rebuilds retimed 30 Hz review samples and semantic completion bindings for newer handoff formats such as Worm. No runtime control, calibration, inversion, motion limit, guard, fallback or locomotion behavior was added or changed. Stored review data is numerical evidence, not Blender playback or physical qualification; active Blender scenes were not updated.

Validation and installation results follow below. The inherited Wave seating transition still has a negative assumed static support margin briefly (−13.49 mm); owner acceptance of Wave is evidence of observed behavior, not proof of static stability or measured COM. Point's held pose, Pushup and Worm retain positive modeled support margins. Torque, current, servo tracking, actual loaded clearances and whole-body collision remain physical-test unknowns.

**Final validation:** all 51 native tests passed (26.69 seconds), including revised Point rear-seat assertions, slow/deep Pushup rear-clearance and planted-foot assertions, Worm's three waves and full 40-degree pitch sweep, all-gesture pulse mapping and semantic completion. A final face-cue deduplication removed duplicate Worm standing cues; focused compiler and C clip tests were rerun afterward. Compiled peak speeds are Point 407.46, Pushup 125.49 and Worm 420.01 degrees/s, within the unchanged default 545.45 degrees/s at 1x playback. Mapped pulse spans are respectively 438.63–2861.37, 437.31–2862.68 and 557.82–2742.18 us. Point hold support margin is 19.32 mm; Pushup minimum is 44.49 mm and Worm 42.56 mm, all based on the assumed COM model.

Full-hull compiled/source comparisons cover 1,465 Point, 3,409 Pushup and 1,537 Worm times; maximum vertex errors are respectively 0.00781, 0.00714 and 0.00501 mm. The complete library comparison passes. Linkage closure remains valid, with minimum closure heights 11.265, 9.212 and 8.698 mm in the comparison. These measurements do not establish loaded physical tracking. See the retained `docs/gait-research/seated-emotes-20261015/validation-summary.json` for source hashes and detailed results.

**Wi-Fi deployment:** built 0.8.54-p4-seated-emotes, 2,834,624 bytes, SHA-256 `2ff4c3bef9e0502b57bec62ec4e4c60a718b16640cc3c927417fda13e02cb3fe`. P4 and tested native generated clip data match byte-for-byte. Gateway upload returned staged/Doze; explicit activation returned selected_for_next_boot. The restart/startup rise was stated before upload. No emote test command was sent. Post-boot verification follows.

**Installed and verified:** live Wi-Fi readback confirms `0.8.54-p4-seated-emotes`, running/boot ota_0, pending_verify=false, ESP_OK, epoch 19, Active and outputs enabled. Self-leveling remains off. The pre-existing storage ESP_ERR_NO_MEM status remains present and was not changed by this motion task. No Point/Pushup/Worm command was sent; physical acceptance remains with the owner.

## 2026-10-15 — Walk target-speed versus perceived strength investigation

Owner requests fast servo strokes with stride controlling travel, suspecting small/slow servo commands cause weak walking. Native 50 Hz sampling of current firmware trajectories confirms a large stance/swing timing distinction. For straight Walk, measured over 6–10 seconds, carrier/crank median commanded speed while planted is 15.5/34.4 deg/s at Speed 25, 17.6/35.1 at Speed 50, and 35.1/75.3 at Speed 100. Corresponding swing peak speeds are 150.8/101.1, 229.1/184.1, and 465.9/411.8 deg/s. Every sampled gait clock scale is 1. These are commanded trajectories, not measured shaft speeds or motor effort.

The same 50 Hz native sampling gives moving carrier/crank median / 90th percentile / peak speeds of Wave 32.9/117.6/315.2, Point 33.7/139.0/406.2, Pushup 43.9/101.0/125.3, and Worm 67.4/163.2/414.3 deg/s (values under 1 deg/s excluded for this gesture summary). Thus successful Pushup does not require the highest joint command speed. Slow stance progression is confirmed; reduced available torque caused by it is not established. Walk and clips share pulse mapping, PCA refresh and staggering. MG90 position pulse control exposes no direct motor-duty/full-torque command. Changing stance target progression is a trajectory experiment, distinct from setting cadence alone or asserting full internal motor drive. No firmware or hardware motion was changed during this comparison.

## 2026-10-15 — Implemented fast coordinated Walk strokes (0.8.55)

**Owner authorization:** explicitly requested the experiment after repeated clarification: move servos briskly, use stride for distance, and do the implementation. This is a change to commanded movement timing, not a claim that the MG90 exposes motor-duty control or that full physical torque/speed is measurable.

**Implementation:** Automatic Walk now traverses its coordinated joint path by angular travel. Each small reference segment (nominally 1/64 cycle) is solved with the existing contact/steering/IK planner. The largest joint-angle change sets that segment's time at the existing nominal full joint-rate reference, 545.45 degrees/s. Every other joint follows the same shared segment clock, preserving linkage coordination. Shorter path segments take less time. Partial segments consume the remaining frame time; zero-distance segments consume no artificial dwell. No pause, extra rejection, runtime pulse clamp, new shutdown, calibration change, or reduced stride was introduced. The angular rate is an authoring reference rather than a new enforced ceiling; interpolation curvature and 50 Hz sampling can place observed frame rates slightly above or below it.

Automatic Walk's 1–100 control selects stride, with a 2x reference cadence used only to parameterize its geometric path. Actual cycle rate follows joint travel. Advanced stride/rate requests retain their explicit cadence as a comparison mode. Explicit Run, Crawl and Crab retain their timing; automatic Walk-to-Run uses the established Run timing while bounding/rephasing is active. Fast Walk resumes after the transition back to Walk completes. Named gestures and their accepted sources are unchanged. `clock_scale` now reports reference-time/wall-time ratio; requested cadence telemetry reflects the angular-distance schedule in fast mode. Body Control's obsolete 96 mm/automatic-slowdown explanation was replaced with the actual 37 mm stride and experimental timing behavior.

**Native 50 Hz comparison, steady 6–10 s window:**

| Stride selection | Previous planted carrier/crank median deg/s | Fast planted carrier/crank median deg/s | Previous / fast cycles per second |
| --- | --- | --- | --- |
| 25% | 15.5 / 34.4 | 93.1 / 192.6 | 0.694 / 5.041 |
| 50% | 17.6 / 35.1 | 68.6 / 113.7 | 0.833 / 3.515 |
| 100% | 35.1 / 75.3 | 60.2 / 103.5 | 1.111 / 2.030 |

The fastest joint's per-frame median demand is approximately 487, 531 and 545 deg/s at those three selections. Fast-cycle swing peaks are approximately 558/547, 555/548 and 553/548 deg/s for carrier/crank. These are requested positions over time, not measured motor speed, current, force or ground speed. Short-stride stepping is deliberately much more frequent; no planted wait was added to maintain the previous cadence. See `docs/gait-research/fast-stroke-20261015/comparison.json` for numeric results and provenance scope.

**Sampling caveat:** at 1% stride, the resulting nominal cycle rate is about 6.25 Hz. At 50 Hz output, the sample clock can repeatedly miss one pair's exact lift apex: sampled peak lift for the four legs was about 4.406/4.406/6.029/6.029 mm against a 6.04 mm continuous target. At 25–100%, all sampled lift peaks remain within about 0.06 mm of the target over the audit window. The geometric-extrema regression now samples at 1 ms to separate geometric range from output sampling; it did not weaken the trajectory's lift assertion. This aliasing is recorded rather than hidden by a new cadence cap. Physical response to this aggressive experiment remains untested.

**Validation:** all 51 native tests pass (23.59 seconds). New assertions verify brisk joint movement for both short/full strides, shorter cycle time for short strokes, and switching back to Advanced's original explicit cadence. Existing checks cover current pulse mapping, geometry, contacts, curves, Walk/Run updates, Finish and gestures. The Run archive check retains unit clock scale during Run; its Walk sections may now use the requested fast-stroke clock. No test window or calibrated travel was widened. The native comparison completes without hardware commands. Host sampling overhead increased roughly 2–3x for the short-stride cases; P4 timing under powered walking has not yet been measured.

**Build/deployment:** P4 build succeeds as `0.8.55-p4-fast-stroke`, 2,835,040 bytes, SHA-256 `bd137596d3e986a7e7bfe6c648f3e16c8a5ea942d32d777c6d547d998b19a81f`. Wi-Fi pre-update status is online 0.8.54, ota_0, pending_verify=false, ESP_OK, outputs enabled, leveling off. Installation uses the existing gateway Doze/upload/activation owner; controller restart and startup rise were stated before upload. No walking command is issued by the agent. Post-boot verification follows.

**Installed and verified over Wi-Fi:** live readback confirms `0.8.55-p4-fast-stroke`, running/boot ota_1, pending_verify=false, ESP_OK, Active, outputs enabled, leveling off. No walking command was sent. The experiment is installed for owner testing; stronger physical walking has not yet been demonstrated. The existing storage ESP_ERR_NO_MEM receipt remains separate and unchanged.

## 2026-10-15 — Owner reports improved Walk; fast strokes extended to all gaits (0.8.56)

**Physical observation and authorization:** after testing 0.8.55, the owner reports a notable improvement in walking and explicitly requests removal of slower servo timing from all gaits. This is physical owner feedback supporting the timing experiment. It does not measure shaft speed, motor torque/current or distance travelled. Earlier entries saying fast Walk had not yet been physically tried are superseded by this report.

**Implementation:** all semantic Walk, Run, Crawl and Crab commands now use angular-distance stroke timing, including plain commands, direct-stride requests, directions, steering and Walk/Run transitions. Run retains its front/rear paired bound. No automatic return to reference cadence remains on entering Run. The segment resolution follows the active gait's reference period, including its blend. The existing nominal 545.45 deg/s reference determines coordinated segment duration; smaller-moving joints follow the common clock. This is not a motor-duty setting or a promise that every joint runs at identical speed. Calibration, PWM frequency/stagger, maximum strides, linkage geometry and accepted named gestures are preserved.

Speed now controls stroke amplitude throughout the range: Walk/Crawl/Crab 1–100 maps to 1–100% stride; explicit Run 1–100 opens the initial 37 mm envelope proportionally and 100–200 opens it to 44 mm. This removes Crawl/Crab's former stride saturation at 50%, where the remaining slider only changed cadence. The `rate` field remains accepted for protocol compatibility, but all semantic requests normalize it to the same reference path rate and execute fast strokes. Body Control replaces Advanced with Direct stride and removes the cadence input. The low-level `gait_begin` reference-time API remains available to offline geometry authoring/tests; production semantic commands select fast timing explicitly. Posture/gesture playback remains separate.

**Transition defect found and fixed:** the faster clock and formerly untested short-to-long Crab stride updates exposed incompatible old planted anchors during one-cycle stride changes (one diagnostic requested 376 us against the unchanged 400–2900 us offline review window). Crab updates now use its existing two-cycle anchor-establishment interpolation, as already used for its entry, allowing the coordinated body/landing path to change across the wide stance. Joint movement stays on the fast angular-distance clock. No pulse clamp, stride reduction, delay timer, speed limiter, new rejection or shutdown was added. The full Crawl/Crab calibration regression now passes without widening its pulse window, including 10/20/40 ms intervals, all directions and Finish.

**Offline 50 Hz comparison:** median of the fastest joint's requested movement rate per output frame, steady 10–18 s window. These are position-command measurements, not physical shaft speed.

| Selection | Previous deg/s | New deg/s | Previous cycles/s | New cycles/s |
| --- | ---: | ---: | ---: | ---: |
| Walk 100 | 545.0 | 545.0 | 2.025 | 2.025 |
| Run 100 | 135.2 | 545.0 | 1.111 | 4.217 |
| Run 200 | 320.5 | 545.1 | 2.222 | 3.574 |
| Crawl 100 | 243.7 | 545.1 | 1.111 | 2.190 |
| Crab 100 | 254.6 | 543.9 | 0.833 | 1.831 |

All 17 before/after straight scenarios complete Finish with all planned feet grounded; the new trajectories stay inside the calibrated review window. The previous Walk behavior is numerically preserved at 1/25/50/100. Data: `docs/gait-research/all-fast-gaits-20261015/comparison.json`.

**Sampling limitation:** extremely short Run strokes can request about 20.33 cycles/s at 1% explicit Run, leaving only about 2.46 output samples/cycle at 50 Hz. Short-stride reversal/lift may therefore be poorly represented at the output and cannot be assumed physically trackable. No cadence cap was added. Geometric lift extrema are checked at 1 ms independently of output sampling. Planted-anchor tests distinguish the same contact interval from a complete intervening swing between two 40 ms samples. Actual loaded response and P4 computation time for the new families still require physical evaluation.

**Validation/build:** all 51 native tests pass (23.22 s). New semantic regression covers every gait/direction, Finish and identical output for legacy rate 0.25 versus 3; all 1–100 selections preserve an effective stride control. Existing tests retain calibrated pulse windows, linkage closure, bare-foot contact, Run paired/flight phases and transitions. Dashboard production-handler tests and JavaScript syntax pass. A final removal of an overwritten obsolete cadence expression passes the affected motion/Run tests again. P4 build succeeds as `0.8.56-p4-fast-gaits`, 2,834,960 bytes, SHA-256 `bff5a30747ee55e26f6a35c20836b358cc19613fb4fc01edf5b12cf7e4d631a1`. Artifact provenance is in the adjacent research directory. Wi-Fi installation/activation uses the existing gateway owner; no agent-issued walking test is part of deployment.

**Installed and verified over Wi-Fi:** live readback confirms `0.8.56-p4-fast-gaits`, running/boot ota_0, pending_verify=false, ESP_OK, Active, outputs enabled, epoch 43, leveling off. No walking command was sent. New Run/Crawl/Crab physical results remain pending owner testing. The pre-existing storage ESP_ERR_NO_MEM receipt persists independently.

## 2026-10-15 — PCA9685 staggering audit after reported supply brownouts

The owner reports an 8.4 V battery, a 5 A buck converter, occasional leg stalls and shutdowns attributed to brownout. The converter output voltage, current waveform and reset cause were not measured in this audit.

Source verification: P4 `body.c` samples both `MOTION_WALK` and library clips into the same frame-to-pulse mapping, then `output_step` calls `ainekio_pca_write_frame`. Startup rise uses the same driver's arm/write path. Driver `frame` unconditionally sets each channel ON counter to `floor(4096*channel/12)` and OFF to `(ON+width)%4096`. There is no per-gait or per-clip option disabling staggering. The board config is nominal 50 Hz, 25 MHz oscillator, prescale 121; nominal channel start times are 0, 1.664, 3.328, 4.997, 6.661, 8.325, 9.994, 11.658, 13.322, 14.991, 16.655 and 18.320 ms. Pulse widths remain unchanged. Register updates use one burst and latch on I2C STOP; signal pulse phase remains staggered afterward.

Freshly compiled driver tests pass, including 400/1500/2900 us widths on all twelve channels, 341/342-count phase spacing, OFF wrapping, and disabled unused channels. The retained 0.8.56 image matches the SHA of the artifact previously verified installed over Wi-Fi. A fresh gateway status request found no entry for this robot, so this audit does not claim current live register readback or oscilloscope proof.

This staggers servo control pulses, not the entire duration of motor current or the motion-library choreography. Several motors can still draw current together while driving or holding load. NXP describes staggered ON/OFF signals (https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf); Pololu explains the servo's internal position-error-to-motor-drive behavior (https://www.pololu.com/blog/17/servo-control-interface-in-detail). No firmware change, flash or robot motion was performed. Brownout root cause and the degree of peak-current reduction remain physically unmeasured.

## 2026-10-15 — Longer installed-linkage Walk (0.8.57)

**Owner request:** increase the short Walk stride and use more available servo travel. The preceding fast-stroke changes altered timing, not the 37 mm maximum planted sweep. Existing hardware remains 35 mm carrier / 20 mm crank / 28 mm pickup / 38 mm rod / 55 mm bare Part027, fixed shafts and saved mirrored calibration. No new parts or horn re-indexing are assumed.

**Implemented candidate:** 47 mm full planted sweep (+27.0%); body reference +5 mm instead of +7 mm; lateral support translation 5 instead of 7 mm; full-stride fore/aft support mean 0 instead of 3 mm; support phase lead 0 instead of .02 cycle. Low-stride mean remains 9 mm, fore/aft harmonic remains 4 mm, contact fraction remains .78 and lift remains 6–10 mm. Stride interpolation uses two cycles to coordinate already-planted anchors with the larger distance. The same fast angular-distance clock executes that interpolation; no cadence limiter, dwell, auto-Home, pulse clamp, new fallback or shutdown was added. PCA9685 staggering and named gestures remain unchanged.

**Search and rejected results:** isolated native builds compared 37/42/44/46/47/48/50/55 mm sweeps with body heights, support means, lateral translation and phase. Simply changing the original sweep to 50 mm requested roughly 354–2946 us in the sampled forward path, outside the unchanged 400–2900 us offline review window. Some 48 mm candidates passed straight/reverse/full-curve checks but failed the broader ongoing speed-change or curved Walk-to-Run calibration tests. A 47 mm candidate passes that broader suite, including the historical full-curve 50 → 89 → 145 sequence. These are evaluated samples and regression checks, not a proof that 47 mm is the mechanical maximum. No calibration interval or linkage regression floor was widened. Search records are retained under `docs/gait-research/longer-walk-20261015`.

**Full-stride native comparison at 100 Hz, steady 8–12 s:** joint spans below are ranges across the four legs, using the installed mirrored physical model. They are commanded travel, not measured MG90 shaft movement.

| Quantity | Installed 37 mm Walk | New 47 mm Walk |
| --- | ---: | ---: |
| Carrier stroke | 27.8–40.6 degrees | 37.2–47.7 degrees |
| Crank stroke | 49.4–56.6 degrees | 61.9–64.0 degrees |
| Shoulder stroke | 9.0–9.1 degrees | about 6.6 degrees |
| Cycles per second | 2.025 | 1.658 |
| Modeled straight body X progress | 97.0 mm/s | 99.0 mm/s |

The longer step is deliberately less frequent at the same nominal fast joint rate; it does not imply a 27% increase in ground speed. Modeled advance per cycle is 47/.78 = 60.26 mm, versus 37/.78 = 47.44 mm. Actual progress depends on contact, slip and servo tracking. Model validation does not justify using all nominal free-servo travel while loaded: shaft offsets, circle closure, sole contact and available pulse travel all affect the useful loaded path.

**Load/support tradeoff:** independent bare-foot forward geometry at full stride estimates the maximum vertical-load torque arm as carrier .03695 Nm/N and crank .03258 Nm/N versus .03599 and .02863 previously (about +2.7% / +13.8%). These are geometry-derived torque arms, not measured torque or current. Minimum loaded lower-leg inclination is about 38.8 degrees above horizontal versus 43.7. A simple assumed-centered-COM, point-contact quasi-static support calculation has negative margin in both paths, approximately −5.10 mm candidate versus −2.83 mm baseline at full stride. Its least-squares allocation contains negative contact-force fractions and therefore is not a physically supported force solution in those samples. Do not present its aggregate torque estimates as validated loads. Dynamics, extended sole contact, actual COM, floor friction, shaft tracking and rail droop remain unmeasured. Longer stride is an experiment in useful travel, not a remedy for the owner's reported 5 A supply brownouts.

**Validation:** all 51 native tests pass (21.97 s), including every integer Walk Speed 1–100, calibrated forward/backward updates, curves, Run transitions, Finish, bare-foot geometry, linkage branch/leverage and unchanged gesture tests. The production curved/Run mapping suite reports 407–2899 us. The increased 47 mm stride and 6–10 mm lift are asserted directly; no existing pulse window or leverage threshold was relaxed. The archived Blender motion scenes were not updated and are not claimed to show this timing/path. Body Control copy now states 47 mm full stride / 23.5 mm at 50%.

**Build:** `0.8.57-p4-longer-walk`, 2,835,008 bytes, SHA-256 `5821900bd492a0bba148ad2816b6af2fca755873a68cd45af3393bd53dce633c`. The owner explicitly confirmed supported frame and servo power off for Wi-Fi activation. The local gateway initially refused connection: its existing user service was failed (exit 143), with no listeners on the configured ports. The existing service was started with tool approval, preserving its saved configuration; the robot reconnected on 0.8.56 with outputs disabled. Upload/activation follows the existing gateway owner. No agent-issued walking trial is authorized by the installation check or sent.

**Deployment verified:** Wi-Fi readback confirms `0.8.57-p4-longer-walk`, running/boot ota_1, pending_verify=false, ESP_OK, epoch 2, Active, outputs enabled and leveling off. The owner confirmed servo power off before restart. No walking command was sent; physical comparison remains pending. The pre-existing storage ESP_ERR_NO_MEM receipt remains separate.

## 2026-10-15 — Recalculate full operating stroke with varying body height (in progress)

The owner rejected treating the previous 47 mm candidate as the available maximum. They reported physical rear-left crank 2900 us at rearward reach and carrier about 1400 us at forward reach, measured in different poses. They subsequently clarified that these pulses are examples of unused travel, **not mandatory endpoints**, that body clearance is not the objective, and that body height need not remain constant through the stride. The objective is useful walking with the full operating stroke at 100%, coordinated carrier/crank movement, and retained fast angular-distance timing. The owner explicitly approved sharing available stroke between translation and turning, rather than adding unrestricted full translation and full yaw together.

Read-only live calibration matches the retained mapping: rear-left model IDs 1/2 have carrier/crank homes 2444/2577 us, inverse mapping, home angles 1.17/-40.41 degrees, 11.1111106873 us/degree. Equivalent model angles map to 1900/400 us on right-side carrier/crank for the owner's 1400/2900 us examples. This verifies mapping, not equal physical collision clearance on every leg. The reported instantaneous 1496/2200 us pair was explicitly disavowed by the owner as no longer representing the physical pose; it is not evidence that the assembled linkage contradicts the model.

A preliminary fixed-Stand-height fit produced 88.039 mm while reaching both example pulses. Full-path analysis exposed a near-straight four-bar segment: about 0.0009 mm rod/pickup extension clearance, with much larger modeled vertical-force torque arms. That fit was rejected, not deployed. Forcing both examples in a lower constant posture produced a 95.240 mm candidate, but the owner clarified that exact pulse endpoints and constant height were the wrong design objectives. These are conditional model fits, not mechanical-maximum claims.

The current calculation jointly fits planted sweep, fore/aft placement and a periodic body-height trajectory. Two- and four-cycle sine/cosine terms allow rise/fall synchronized with the footfall schedule. Grounded world anchors remain stationary; inverse kinematics solves all four legs with their fixed shafts and bare Part027 sole. The existing 400–2900 us offline review window, four-bar closure/assembly branch and existing leverage regression criteria remain in place; no new runtime clamp, shutdown, pause or speed limiter has been added.

An initial forward-only fit reached 91.203 mm, with modeled peak vertical-force moment arms approximately 0.0525 Nm/N carrier and 0.0510 Nm/N crank. This is a geometric load comparison, not measured torque, current or motor tracking. Reverse and transitions need their own validation; a forward steady-cycle optimum is insufficient. A subsequent 85 mm integration candidate passes the production calibrated Walk/Run mapping scenarios at 407–2893 us, but still fails leverage checks and is not ready for installation. Joint optimization across directions and gains is continuing.

The implementation also corrects two related trajectory-owner issues: steering landing prediction integrates the varying shared translation/yaw path rather than using one midpoint over an entire future stance; a fresh automatic Run request starts from Run geometry instead of constructing a synthetic maximum-Walk entry first. Actual in-progress Walk-to-Run commands continue to blend. Existing Run steady geometry, named gestures, PCA9685 staggering and saved calibration are unchanged. No robot movement or firmware upload has been issued in this work.

### Completed candidate — 0.8.58-p4-full-stroke (built, not yet installed)

The resulting full Walk uses **88 mm planted sweep**, versus the installed 47 mm; 50% commands 44 mm. Body height is no longer constant. The joint fit uses separate forward/backward height waveforms with the installed fixed shafts and bare Part027 sole. A larger 89 mm trial with this profile passed the sampled electrical mapping checks but failed loaded linkage transmission checks. Thus 88 mm is the largest passing whole-millimeter candidate in this search, **not a proved absolute mechanical maximum**. The owner's 2900/1400 us examples were not imposed as simultaneous endpoints.

Production-rate offline sampling (50 Hz, steady 10–16 s):

| Quantity | Full forward Walk | Full backward Walk |
| --- | ---: | ---: |
| Planted sweep | 88 mm | 88 mm |
| Carrier command spans across four legs | 114.0–116.2 degrees | 111.2–119.7 degrees |
| Crank command spans across four legs | 115.0–117.0 degrees | 113.3–117.9 degrees |
| Body rise/fall, peak-to-peak | 6.90 mm | 12.55 mm |
| Modeled cycles/s | 0.806 | 0.846 |
| Modeled body-X progress | 91.8 mm/s | 95.5 mm/s |
| Peak planted vertical-force moment arms, carrier/crank | .0510/.0492 Nm/N | .0526/.0468 Nm/N |

Rear-left forward Walk commands sampled carrier 1580–2872 us and crank 1584–2884 us. These are emitted-model command samples, not measured shaft positions or proof of equal physical clearances on every mirrored leg. The longer step takes longer at the unchanged nominal fast joint rate. It does not claim faster ground speed or more motor torque. The modeled force moment arms are higher than the previous 47 mm candidate (.03695/.03258 Nm/N); the long stroke therefore costs mechanical advantage at its most demanding poses. Actual load sharing, current, traction and tracking remain unmeasured. The detailed derived comparison is in `docs/gait-research/full-stroke-walk-20261015/comparison.json`.

Transition repairs are at the trajectory owner:

- Shared steering includes the stroke endpoint in the outer foot radius; the future body path is integrated through changing steering. The inner-foot shoulder radius contributes a geometric body rise during curves. Neither action clamps servo commands.
- Fresh automatic Run starts in Run geometry. Existing Walk-to-Run changes still interpolate between the two gaits; Run remains a front/rear bound.
- Returning footfall phases use the nearest equivalent phase. The old downward-only rounding could turn a tiny interrupted Run change into nearly a whole-cycle Walk phase shift.
- Positive Walk/Run updates now retarget stride immediately from its current value, alongside footfall changes. Previously footfall rephasing could start while stride remained queued behind an earlier update. Already committed airborne landing anchors remain intact.
- The fitted transition body path has a 4 mm rearward midpoint transfer for forward travel and 1 mm for reverse. Reverse height timing follows the mean footfall-offset shift with a fitted 1.55 phase gain. These are body-trajectory parameters, not added delays, stops, stroke clamps or motor-speed limits.

A proposed height-amplitude estimate from planted anchors was evaluated and rejected because it produced solver failures; that implementation is not retained. Multiple earlier 85–88 mm parameter trials are superseded by this candidate. A new calibrated test now covers the independent geometry validator's timed 100 → 200 → 75 → 200 → Finish sequence at 25 and 50 Hz, alongside the existing extensive cases.

One test classification was corrected in both C and Python: the old linear joint-midpoint test called a midpoint loaded when either endpoint was grounded. At liftoff/touchdown that does not establish a planted midpoint. Both actual planted endpoints still receive the 45-degree loaded-output check; midpoints within continuous stance do too. Transition midpoints retain swing transmission, closure and assembly-branch checks. The numerical transmission floors, 3 mm straightening margin and 400–2900 us review window were not reduced. This is offline qualification logic, not a runtime restriction or measured contact detector.

**Final validation:** all **51/51 native tests pass** (60.19 s), including independent CAD geometry, source parity, calibrated mapping, speed changes, steering, Run transitions, Finish, balance and gesture checks. The calibrated trajectory suite reports **401–2896 us**. ESP-IDF 5.5.4 built `0.8.58-p4-full-stroke`; image size 2,842,640 bytes, SHA-256 `2fbc8f7090c8f1f4163ef0cecfe646b61f22e287d59653b7d52f417862d48d63`. The frozen upload image is `/tmp/ainekio-0.8.58-p4-full-stroke.bin`; build/validation records and the authenticated deployment helper remain outside the repository under `/tmp/ainekio-measured-stroke-20261015`.

Read-only Wi-Fi status still reports installed **0.8.57-p4-longer-walk**, ota_1, pending_verify=false, ESP_OK; connected, outputs disabled. The existing storage ESP_ERR_NO_MEM receipt is unrelated. No movement, upload, activation or calibration write was issued. A new physical support/servo-power-off confirmation is needed before activation because the intervening manual range work superseded earlier readiness confirmations, and restart runs startup rise. Physical gait qualification remains pending.

**Deployment verified (2026-10-16T00:05:34.851884+00:00):** After the owner freshly confirmed supported frame and servo power off, the existing Wi-Fi gateway staged and activated the frozen image. Post-restart firmware readback confirms **0.8.58-p4-full-stroke**, running/boot **ota_0**, **pending_verify=false**, **ESP_OK**. The robot is connected and Active, outputs enabled by the existing startup sequence, with leveling disabled. The first status request caught the reconnect interval; subsequent readback confirmed the new image. The pre-existing storage ESP_ERR_NO_MEM remains separate. No walking command or calibration write was sent. Installation is verified; actual walking performance, traction, and load handling remain physically untested for this image.

## 2026-10-15 — Reindexed crank, owner-defined 1600–2800 us Walk

The owner rejected 0.8.58 after physical walking: its legs still reached too far forward. They subsequently **removed and refitted the rear-left crank horn**, and supplied a photo with carrier and crank both commanded to 2800 us. The crank touches the carrier housing at this upper endpoint. The new requested rear-left walking interval is **1600–2800 us**, with **2800 us as Home**, not the center of travel. The carrier mounting/calibration is unchanged. The owner is reindexing the other cranks as well. Existing mirrored mapping gives right-side **500–1700 us**, Home 500 us (3300 minus the corresponding left pulse). This assumes mirrored physical horn placement; it does not measure that placement.

Read-only device calibration still reports the previous crank references 2577/723 us at -40.41 model degrees. A horn reindex invalidates that pulse-to-angle association. No calibration or robot motion was written. The owner declined additional matchmark measurements. A provisional planar reconstruction uses the photographed five joint centers, the fixed shaft positions and 35/20/28/38/55 mm linkage, and the unchanged carrier mapping at 2800 us. It estimates rear-left crank Home at **-117.68 model degrees**, approximately 57.2 degrees away from the old mapping at 2800 us. The perspective fit has about 12 pixels total residual; printed parts have depth, and landmark selection is approximate. This is **photo-derived authoring evidence, not measured shaft calibration**. At the retained 11.111111 us/degree scale, the requested 1200 us span corresponds to 108 model degrees.

The first forward profile fits 63.511 mm planted sweep with +25.087 mm rearward bias. Its unshifted stance reference offsets are approximately -56.84 to +6.67 mm, versus -26.3 to +61.7 mm for the rejected 88 mm profile. The changed placement addresses forward overreach rather than maximizing a sweep number. Variable body height and 10 mm swing lift remain. Reverse, steering and transition checks are in progress; this is not yet a deployable profile.

A command-generation defect was also reproduced: the fast path integrates through internal samples but emits only the final pose each output tick. At 50 Hz, the initial fitted rear-left curve mathematically reached 1600/2800 us but repeatedly emitted approximately 1617/2779 us. An authored-reversal sampling change now emits those path landmarks before reversing, then resumes on the next ordinary output tick. It introduces no dwell, pulse clamp, emergency stop or new joint-speed setting. In the first forward 50 Hz prototype, the production pulse mapper now emits **1600 and 2800 us** using the provisional reindexed mapping. This result remains offline; the robot was not commanded or flashed.

### Completed source/build candidate — 0.8.59-p4-reindexed-walk

The final forward/reverse profile uses **61.945054 mm sweep**, **23.041079 mm rearward bias**, and no mean forward support translation. Reference foot offsets are **-54.014 to +7.931 mm** at 100%, before cyclic body sway. The earlier 63.511 mm forward-only trial is superseded. Both directions are fitted to the same owner crank interval, rather than selecting a larger stride first. Separate forward/reverse height coefficients retain fixed shafts, carrier calibration and the original bare-foot linkage.

Authored swing apices are now emitted as well as full-stroke crank reversals. A native test at 3% Walk exposed that the old integration could skip the foot-lift maximum even at 1 ms diagnostic sampling; this was fixed in the trajectory sampling, without relaxing the test. Each event is an ordinary output target and the next tick continues immediately. There is no dwell, pulse clamp, added stop or new servo-speed setting. Some frames end at an authored event before consuming their full nominal angular-distance budget; finite output cadence is therefore explicit rather than pretending every frame has identical travel.

Production planner plus mapper tests prove that the **rear-left crank emits exactly 1600 and 2800 us** in forward and reverse full Walk at **25, 50 and 100 Hz** under the provisional mapping. Right rear emits the mirrored 500/1700 us. The front pair remain inside those intervals but do not use an identical span: the final 50 Hz forward sample has left-front 1602–2762 us and right-front 538–1698 us; reverse has left-front 1600–2693 us and right-front 607–1700 us. Do not describe every leg as having exactly 1200 us stroke. The front/rear fixed shaft/reference placement and phase-dependent body height give different joint excursions.

A Finish test found a carrier reaching 2902 us in the first candidate. The body-height fit was revised to resolve that actual transition; full crank endpoint use was retained. Reverse input transmission also received a small geometric adjustment after the independent interpolated-path check found 19.985 degrees versus its existing 20-degree review criterion. No numerical criterion was relaxed and no runtime restriction was added. The provisional crank mapping was updated only in the walking calibration test fixtures; historical default/mirror tests remain intact.

**Validation:** all **51/51 native tests pass** in **21.74 s**, including independent geometry, integer walking gains, steering, Run blends, arbitrary-phase Finish, fast timing, lift, balance and existing gestures. Straight Walk gains 1–100 including entry/Finish are also checked against the owner's upper crank housing endpoint. Gesture tests retaining the historical electrical fixture do not qualify those gestures physically after horn reindexing. Final 50 Hz modeled cycles/s are 1.088 forward and 1.044 reverse at full stride; these are not measured ground speeds. Detailed command spans and moment-arm estimates are recorded in `docs/gait-research/reindexed-walk-20261015/comparison.json`.

**Build:** ESP-IDF 5.5.4 completed `0.8.59-p4-reindexed-walk`, 2844032 bytes, SHA-256 `7b5f88d0c06a8a6d82540073456fd62b8f0d6f2244a0e5939a5ff0f906c81d32`. Frozen image: `/tmp/ainekio-0.8.59-p4-reindexed-walk.bin`. **Not deployed; no motion or calibration write sent.** The owner is still refitting the other crank horns. The old live saved mapping cannot be used for this reindexed candidate. Deployment must include the corresponding new crank mounting reference through Body Control; carriers, inversion and existing scale stay unchanged. Photo-reference accuracy, actual horn parity and physical walking remain unverified.

### Wi-Fi deployment and mounting-reference readback — 0.8.59

**Deployment verified (2026-10-16T01:01:50.380621+00:00):** The owner confirmed all crank horns refitted, frame supported and servo power off. The frozen 0.8.59 image was staged through the existing gateway and activated. Reconnected firmware reports **0.8.59-p4-reindexed-walk**, running/boot **ota_1**, **pending_verify=false**, **ESP_OK**. Saved calibration was read back after reboot and matches the applied settings. No walking or manual Home command was sent; the existing startup sequence ran with servo supply off per owner confirmation. Controller reports Active and outputs enabled after startup; that flag does not measure the external servo supply.

Fresh pre-install calibration unexpectedly showed carrier Home pulses changed from 2444/856 to 2800/500 us while home_cd remained 117. The owner explicitly clarified that only carrier Home settings changed and carrier horns were **not** physically remounted. Retained the owner's 2800/500 us carrier Home pulses and changed carrier home_cd to **-3087**, preserving the original angle-to-pulse relationship (affine offset difference under 0.000014 us from float precision). This avoids interpreting a Home-setting edit as a changed carrier mounting angle. All four crank references are now **home_cd -11768**, with left Home **2800 us** and right Home **500 us**. Shoulder settings, channels, inversion and pulse-per-degree scales were preserved. The first calibration set was rejected by the existing mode requirement without applying it; entering the existing Body Control calibration mode allowed set/save and readback.

Installation and persistence are verified. The crank mounting angle remains photo-estimated; actual shaft angles, mirrored mechanical alignment and physical walking performance remain unqualified. Native results establish the emitted rear-left 1600/2800 us endpoints under this mapping, not measured servo tracking. Runtime receipts and before/after calibration snapshots are retained outside the repository under `/tmp/ainekio-reindexed-walk-20261015`.

## 2026-10-16 — Owner walking observations and feedback-learning requirements

Following the 0.8.59 installation, the owner reports some actual forward walking at 100%, though poor quality. Reducing the control reduced stride and mostly produced twitching without useful translation. The rear sags under load, and feet tend to drag with insufficient physical lift. These are owner-reported physical observations; distance, speed, ground clearance, current and joint tracking were not instrumented in this turn. They establish that the smaller tested strides were ineffective on this setup, not a universally optimal stride or a confirmed cause of rear sag.

Source inspection confirms IMU telemetry exports attitude, acceleration and angular rate, not measured forward speed or distance (`Slave/firmware/esp32p4-wifi6/main/imu_telemetry.c`). Walk also ties lift amplitude to stride percentage (`Slave/software/models/v2-12servo/motion.c`), so changing the control changes more than planted distance. Existing commanded trajectories cannot establish actual foot lift under load.

Proposed learning direction, not implemented: use stationary external phone video with a scale reference to measure displacement, rear/body height and visible foot clearance, synchronized with IMU attitude/rate/acceleration and commanded gait phase. Optimize a small set of gait parameters from actual trial outcomes; execute trajectories and attitude feedback on P4, with trial evaluation/optimization on the workstation or Q6A. Separate stride, swing lift and cadence in the experiment. Use distance/time as progress, with tilt/impact/sag/drag costs; IMU calmness alone cannot distinguish standing still from successful translation. Rear sag may involve load geometry, actuator tracking, supply behavior or posture commands; no unique cause is established.

References: ST LSM6DS3 datasheet (3-axis accelerometer and gyro), https://community.st.com/ysqtg83639/attachments/ysqtg83639/mems-sensors-forum/21052/1/st_imu_lsm6ds3_datasheet.pdf ; VectorNav inertial-navigation explanation and integration drift, https://www.vectornav.com/resources/detail/what-is-an-ins ; gait parameter learning via Bayesian optimization, https://arxiv.org/abs/2406.07065 . Research examples do not validate this robot. No firmware changes, uploads or robot commands were made during this assessment.

### Freestyle support request and live trial preparation

Owner authorized supervised camera/IMU walking trials and confirmed floor readiness, then explicitly requested adding Freestyle support to the current firmware before trials. No walking command was sent. Read-only inspection found the robot connected, camera and IMU live, and self-leveling enabled/active. Camera preview was stored outside the repository; it shows textured carpet and a bright light source ahead. Current sensing does not establish metric distance, electrical efficiency, individual servo tracking or ground clearance.

The existing `motion_plan_v1` contract is eight servo targets (map 1). P4 controller explicitly excludes `AINEKIO_COMMAND_MOTION_PLAN`, omits its command-mask bit and feature advertisement, and the body executor accepts semantic intents only. Enabling its feature string alone would not implement Freestyle. A P4 implementation needs a model-specific plan representation, parser/gateway support, asynchronous execution through the existing calibrated/staggered output owner, and completion/interruption tests. Existing V1 byte/token/frame and duration capacities must not silently be mistaken for twelve-servo capability.

Asked the owner whether P4 Freestyle should use foot/body keyframes solved by IK, or twelve joint-angle keyframes with explicit direct-angle authorization. AGENTS.md states “Use semantic robot commands through the existing MetaHuman and body-control owners; do not let AI output raw servo angles.” No firmware changes or flash were performed while that material format decision is pending. Earlier floor readiness is for trials, not servo-power-off update readiness.

### Twelve-joint Freestyle implementation and unsuccessful activation — 0.8.60

The owner removed the raw-angle prohibition and explicitly authorized continuing.
Implemented negotiated `motion_plan_v2` / map 2 with twelve signed model-angle
targets, gateway translation and authenticated Body Control submission, and P4
execution through saved calibration and the staggered PCA output owner. Plans
use caller-authored linear timing without a Home/Stand prefix. Explicit end-pose
selection retains normal completion receipts. Arbitrary joint plans clear active
balance correction without changing the saved setting; contact-aware leveling
during Freestyle and camera-based gait optimization are not implemented.

Build 0.8.60-p4-freestyle completed: 2,847,088 bytes, SHA-256
`600b00fcb9a42aa6b89f0850ca88b9e20756928084cf16363a0c21a9ec788fc8`.
All 51 native tests, three new gateway tests, and four existing V1 Freestyle
tests passed. Three broader Python schema/fixture completeness failures were
reproduced against unchanged HEAD datasets. These checks are not hardware proof.

With fresh supported/servo-power-off confirmation, calibration was read and
retained outside the repository. Wi-Fi upload returned staged; activation
returned selected_for_next_boot. The gateway was reloaded, but the robot did
not reconnect. The owner reported the display remained at update/restarting;
after the requested power cycle, the display was blank. Gateway and the robot's
last HTTP address are unavailable for robot diagnostics. USB boot-log capture
has been requested. The running image, cause of failure, calibration persistence
after reboot, and physical Freestyle execution are **not verified**. No trial
or Freestyle motion command was sent. Do not treat 0.8.60 as successfully deployed.

### Boot failure diagnosed and previous slot recovered

The replacement USB cable enumerated the CH343 serial device; after the owner
granted device access, serial capture confirmed 0.8.60 repeatedly rebooting at
`vApplicationGetIdleTaskMemory`, failing to allocate the idle stack before
`app_main`. This is a firmware startup allocation failure, not measured servo
load or a confirmed power-supply fault. The repository's earlier maintenance
bring-up records the same pre-V3 P4 constraint: most internal heap becomes
available only after the scheduler releases startup-stack regions.

The new receive buffer had grown from 4,097 to 8,193 bytes in BSS. Corrected it
to allocate its full workspace in `controller_start`, alongside the existing
queues, after scheduler startup. The receive-length check still accepts 8,192
payload bytes. No protocol range/capacity reduction, runtime motion restriction
or new recovery fallback was added. Build 0.8.61-p4-freestyle succeeds with
2,847,120 bytes and SHA-256
`0f72acf927ca4c217221cfcd678dfa4e21257796537f5856d0651eab0fdb95ce`.
Five targeted native body/feedback/protocol/OTA tests pass.

The owner explicitly authorized USB selection of the existing previous slot.
ESP-IDF otatool changed only the 8 KiB otadata partition at 0x10000. Wi-Fi
readback confirmed 0.8.59 in ota_1, boot ota_1, pending_verify false, ESP_OK.
Neither application image, NVS, partition table nor bootloader was rewritten
over USB. The first 0.8.61 upload was interrupted by a reboot before activation;
the P4 returned to 0.8.59 and discarded the in-RAM staging selection. A second
Wi-Fi upload is underway with the serial capture held open across activation.

### Corrected Freestyle deployment verified — 0.8.61

At 2026-10-16T17:25:17Z, authenticated Wi-Fi readback confirms
**0.8.61-p4-freestyle**, running and boot **ota_0**, pending_verify false,
ESP_OK, and the negotiated **motion_plan_v2** feature. All twelve joints'
channel, Home pulse, Home model angle, inversion and scale match the pre-update
snapshot exactly. No calibration write was needed.

With servo supply still off per owner confirmation, submitted one 40 ms map-2
frame computed from the current commanded pulses and saved calibration, ending
in hold. The robot returned **done, sequence 7**. This establishes authenticated
gateway-to-P4 twelve-joint execution and completion, not powered shaft tracking
or successful walking. The staged image and updated deployment metadata are
retained outside the repository under `/tmp/ainekio-freestyle-20261016`.

Serial and Wi-Fi logs also confirm the corrected boot passes controller,
camera/audio, IMU and display initialization, admits startup rise, reaches the
console, and authenticates to the gateway. No idle-stack assertion appears in
this corrected boot. Display initialization is firmware evidence; visible screen
appearance has not yet been confirmed by the owner.

## 2026-10-16 — Recorded floor trials and cumulative sag

The owner authorized supervised floor trials and confirmed the tape visible in
camera images is marked in inches. Added `Master/gateway/gait_trials.py` to
record the existing authenticated intent/Freestyle owners, JPEG frames, full
status, device-timestamped IMU samples and command receipts. Runtime data and
session credentials remain outside the repository under
`/tmp/ainekio-gait-trials-20261016`. Recording duration does not stop motion.
Distance and electrical energy remain unmeasured. There is no saved camera
intrinsic/ground-plane calibration, so image flow/tape displacement in the
changing onboard view cannot be labeled metric travel. Preview was requested
at VGA/10 fps; actual recordings generally delivered about 5 fps.

| Trial | Leveling | Fresh IMU samples | Roll span ° | Pitch span ° | Largest IMU sample gap s |
| --- | --- | ---: | ---: | ---: | ---: |
| Stationary | On | 39 | 0.07 | 0.04 | 0.242 |
| Native Walk 100%, two requested cycles | On | 139 | 5.92 | 4.42 | 0.402 |
| Same native command | Off | 151 | 6.87 | 10.86 | 0.223 |
| Freestyle baseline, first placement | Off | 77 | 6.62 | 3.21 | 0.246 |
| Freestyle baseline repeat | Off | 84 | 7.10 | 3.53 | 0.192 |
| Freestyle 12 mm lift, first trial | Off | 30 | 0.22 | 3.00 | 2.024 |
| Freestyle 12 mm lift, repeat | Off | 71 | 5.69 | 4.76 | 0.376 |

All movement commands returned done. The last finite trial was sequence 22;
readback then showed no pending sequences. Completion proves controller
execution, not measured shaft arrival. The owner observed forward travel and
rear sag. Onboard images show scene movement and changing viewing angle, but
cannot directly inspect the feet. General gait/balance status updates can lag
an entire short motion; IMU and receipts must be interpreted separately.

The owner disabled self-leveling because calibration was suspect, then allowed
it to be reenabled if needed. It remained off for Freestyle comparisons.
Freestyle currently clears trajectory balance correction even if the saved
switch is on; this feature does not yet add leveling to raw joint plans.

`tools/export_freestyle.c` exports the native geometry without contacting a
robot. Increasing swing lift alone from 10 to 14 mm demanded carrier pulses
around 2955/345 µs with the current saved mapping. The tested candidate instead
used 12 mm lift plus an 8 mm rear-foot airborne X offset, retaining the planted
stroke. A full six-phase-cycle native command compressed into the protocol's
32 frames produced about 19° peak angular error; that plan was not executed.
The single-cycle comparison used 32 frames, about 0.94 s authored duration,
1.25° peak angular approximation error and under 0.8 mm modeled sole-height
error. One-ms interpolation samples closed in the model. These are offline
results, not measured clearance or actuator tracking.

**No gait winner was established.** The first lift trial lost IMU coverage
across movement; its low sampled peak rate is invalid evidence of smoothness.
The recorder now exposes maximum IMU sample and camera receipt gaps. Three
recorder tests pass, including duplicate/stale sample handling and absence of
an unsolicited Stop. More importantly, trials were repeated without physically
restoring the starting stance. The owner reported cumulative sag and widening
legs, making comparative scores confounded. These trials must not be used as
learning rewards or promoted as improved walking.

The owner reported Stand could not restore height under load but the legs
extended when unloaded. Further gait comparisons were stopped. A subsequent
read-only Stand check found the robot absent from the gateway registry; no
Stand completion or pulse readback was established for that attempt.

## 2026-10-16 — Fast Stand and startup stepping repair

The owner explicitly requested full-speed Stand and boot behavior, with lifted
foot repositioning rather than shoulders sweeping planted feet inward. Source
inspection found an eight-second authored Stand path, quintic easing and an
additional per-frame speed search. Startup separately used 600 ms folding,
600 ms shoulder engagement and a 1200 ms eased rise, with 100 ms rear delay.

Changes in progress for 0.8.62-p4-fast-stand:

- Stand uses angular-distance timing at the same nominal full servo rate as
  automatic Walk (profile 545.45 degrees/s), independent of the saved playback
  multiplier and slow joint-rate setting. Removed Stand's extra time-bracketing
  slowdown. The geometric path retains support shifts, an 8 mm foot lift,
  airborne placement and planting; stage coordinates are no longer elapsed
  seconds. Endpoints are emitted on the existing 50 Hz output clock.
- Startup sends folding targets directly, then uses the same stepping path.
  Shoulder output remains off until its own modeled lift stage, rather than
  commanding all shoulders to calibration Home on the floor. Front folding
  leads rear by one PWM frame (20 ms). Initial fold transit is estimated from
  the profile's provisional 243° travel and nominal rate (~446 ms), replacing
  the old 600 ms constant. It is not a sensed arrival or a torque command.
- Disabling self-leveling now also disables IMU-derived rotation of Stand's
  entry path. Previously Stand still used that orientation with the switch off.
  Enabled leveling retains its existing behavior; no calibration values change.
- Explicit calibration Home remains separate. No Walk preamble, automatic Stop,
  new sensor requirement or additional fault shutdown was introduced.

Targeted native tests pass: nominal Stand paths take 0.66–0.78 s with small
initial tilts; the retained Freestyle endpoint takes about 0.90 s with leveling
off. Startup completes in 1.04 s in the production-owner test. The test proves
each shoulder first receives PWM at its lifted-foot stage, preserves remapped
channels/calibration, and retains cancellation. Stand output is identical with
playback settings 0.05/12 and saved joint-rate settings 20/2000 when leveling is
off. These timing and geometry assertions do not prove the MG90s track them
under load.

Current-calibration offline audit: startup carrier targets span approximately
385–2905 µs, slightly beyond the earlier 400–2900 review window but within the
current declared 300–3000 profile. Startup crank targets span approximately
1211–2084 µs. No pulse clipping was added. The post-trial input already contains
a rounded 499 µs right crank endpoint. Large tilted-start contact geometry also
remains problematic: the retained trial endpoint at −0.20/−0.25 rad pitch fails
the contact solver when IMU-driven entry is enabled; positive large tilts can
request excessive carrier travel. This repair is not proof of general tilted
recovery, and these cases are not grounds to silently clamp or claim success.
The requested leveling-off tests use the unrotated entry path.

Research reference: Stanford Pupper separates support and swing foot targets,
then uses IK (https://github.com/stanfordroboticsclub/StanfordQuadruped).
Unitree's Go2 example blends standing joint targets with explicit stiffness and
damping commands (https://github.com/unitreerobotics/unitree_mujoco/blob/main/example/python/stand_go2.py).
Those designs do not establish that this position-only MG90 assembly has the
same feedback or load capacity. Firmware build and physical validation status
are recorded below when completed.

### Build and installation status

Built and frozen **0.8.62-p4-fast-stand**, 2,844,736 bytes, SHA-256
`ef0b1980a7da7e4a575a923dc5b4cab628a0ded77c2d0049d206b8bd48956c2e`.
The full 51-test native suite passed; following final Stand status/playback-field
cleanup, both production body tests and posture-contact tests passed again.
Three recorder tests and `git diff --check` pass. Artifact and logs are outside
the repository in `/tmp/ainekio-gait-trials-20261016`.

**Not deployed and not physically validated.** The final authenticated gateway
read returned an empty robot registry. Requested controller Wi-Fi reconnection,
frame support and servo power off for update activation, which runs startup.
No additional physical motion or calibration write was sent after sequence 22.

### Wi-Fi activation attempt after reconnection

Owner confirmed frame supported and servo power off. Preflight read back
0.8.61-p4-freestyle on ota_0, with self-leveling disabled; calibration and
leveling settings were saved outside the repository for comparison. Two uploads
returned staged successfully, but gateway activation returned HTTP 409 because
the robot connection was gone. Subsequent reads returned the old firmware with
idle staging state; retained logs show a controller panic and reset reason 4.
The truncated log does not establish the crash's root cause.

The same authenticated Wi-Fi maintenance endpoint remained reachable directly.
A direct upload of the frozen, hash-verified 0.8.62 image followed immediately by
activation returned `selected_for_next_boot`. No USB write, calibration write,
or additional physical trial was performed. Post-restart verification follows.

**Deployment verified:** authenticated readback reports
`0.8.62-p4-fast-stand`, running and boot partitions both `ota_1`,
`pending_verify=false`, and `ESP_OK`. All twelve joint calibration records match
the preflight values for ID, channel, Home pulse/angle, inversion and pulse scale.
Saved leveling remains disabled with its prior strength, damping and level-zero
values. The new boot log reports software reset reason 3 and no panic. Local
artifact metadata and verification evidence were updated outside the repo.
Servo power was off for installation: loaded Stand, actual foot lifting, shoulder
drag reduction and startup tracking remain physically unverified.

### Owner physical result: startup ends before loaded standing is achieved

After deployment, the owner placed the robot on the floor and powered it on.
Startup completed while the robot remained crouched with motors straining.
Repeated Stand commands raised it incrementally until it stood. This establishes
that the current completion receipt is not evidence of physical standing.
Source confirms posture progression uses elapsed time and nominal joint speed;
completion occurs at the end of the modeled path without shaft/height readback.
PWM continues holding the final target after completion, so merely delaying the
receipt does not establish a fix. Premature transitions between loaded stepping
stages are a plausible explanation requiring observation, not a measured cause.

The LSM6DS3 measures acceleration and angular rate. It can inform tilt and
settling, but a stationary level crouch and stationary level Stand can produce
the same inertial readings. IMU-only settlement must not be reported as measured
standing height. Actual height feedback needs an external geometric reference
(for example calibrated camera observations) or a distance/position measurement.
No additional firmware change or physical command was sent for this assessment.

### Servo potentiometer feedback and proposed acquisition interface

Owner modified a spare MG90 by exposing its confirmed centre potentiometer
wiper, retaining the internal connections. End-to-end pot resistance measured
about 4.8 kOhm. Tested through PCA socket 11: 500 us gave approximately 0.2–0.3 V
(mostly 0.3, slowly changing on a coarse meter), 1650 us gave steady 1.7 V, and
2800 us gave steady 3.2 V. Owner previously tested 400–2900 us travel and chose
100 us endpoint margins. Voltage at those outer endpoints remains unmeasured.
These readings are promising feedback evidence, not precise angle calibration.

Checked current ESP-IDF ADC mapping, firmware source, frozen 0.8.62 build config,
and board references. ADC2 GPIO49–52 have no assigned role in this firmware.
ADC1 GPIO16–19 are used by C6 SDIO. The current SSD1306 still uses GPIO20/21;
GPIO22/23 are unused by that driver but needed if ST7789 returns. ADC2 GPIO53/54
belong to audio/C6 reset. Thus six currently unassigned ADC inputs, four retained
with either display, are insufficient for twelve direct feedback inputs.

Selected design proposal: first feedback input on GPIO49 (ADC2 channel 0,
header guide L10). For all twelve joints, CD74HCT4067 at regulated 5 V selects
feedback channels, followed by a 5 V MCP6001 unity-gain buffer and a 1:1 divider
into GPIO49. Buffer precedes divider to avoid appreciably loading the servo pot.
Two equal 10 kOhm divider resistors nominally map 0–5 V to 0–2.5 V; ADC sampling
and filtering need bench validation. Proposed select pins S0/S1/S2/S3 are
GPIO27/28/29/30 (R14/L7/L6/L5), currently unassigned. HCT is intentional: its
5 V operation accepts 3.3 V control logic; ordinary HC at 5 V has different
guaranteed thresholds. One-servo bench interface can omit the multiplexer.
This is an interface selection, not an assembled circuit or implemented driver;
power sequencing, decoupling and exact package pinout remain wiring-design work.
No parts purchased, firmware modified, or physical command issued.

References: TI CD74HC/HCT4067 datasheet
(https://www.ti.com/lit/ds/symlink/cd74hc4067.pdf), Microchip MCP6001 datasheet
(https://ww1.microchip.com/downloads/en/DeviceDoc/MCP6001-1R-1U-2-4-1-MHz-Low-Power-Op-Amp-DS20001733L.pdf),
Espressif P4 datasheet and Waveshare board schematic linked in PCA9685_WIRING.md.

Space constraint refinement: owner prefers a single CD74HC4067 module. A 3.3 V
HC multiplexer directly into the P4 ADC is a valid simpler candidate, conditional
on every feedback input remaining between ground and the actual multiplexer
supply, including other poses and supply variations. The measured 3.2 V at
2800 us is encouraging but does not prove that condition over full travel or
across all servos. HC at 3.3 V does not need the 5 V selection-level translator.
An analog buffer is not intrinsically required; direct acquisition settling,
cross-channel error and interaction with the servo's own feedback must be tested.
The earlier 5 V buffered design was presented too strongly as a necessity.
No servo travel reduction is proposed to accommodate the measurement circuit.
Power sequencing must also avoid driving an unpowered multiplexer or ADC.
This remains a proposed bench interface, with no hardware/firmware change made.

### 2026-10-16 — Multiplexer acquisition and measured-position Stand implemented

Owner purchased the DORHEA CD74HC4067 module and is modifying the remaining
eleven MG90 servos. After clarification, owner explicitly approved:
"Yes—use the measurements to coordinate Stand", specifically completing a leg
lift before bringing that shoulder inward. The implementation retains fast
movement commands, holds stage targets until measured arrival, and accepts a
replacement motion command. No new timeout or automatic shutdown was added.

Candidate **0.8.63-p4-servo-feedback** now provides:

- Independent ADC2 channel 0 / GPIO49 acquisition, selecting the 3.3 V HC4067
  with GPIO27/28/29/30. Sixteen channels per scan, one discarded conversion then
  four retained samples per channel; raw average, spread, timestamp and optional
  ADC-calibrated voltage are available. Sensor scans do not run in the body task.
- Separate persistent `p4_feedback` calibration: configurable input per logical
  joint, three observed raw/pulse reference points, ascending or descending
  sensors, and explicit extrapolation rather than clipped readings. Existing
  Home/inversion and PCA output assignments remain authoritative and unchanged.
- Authenticated GET/POST `/api/servo-feedback`, proxied by the existing selected
  robot maintenance owner. Body Control's Servo feedback tool shows measured
  versus commanded pulse-equivalent positions, sample age/spread, saved points,
  Stand progress and waiting joints. Calibration capture never commands motion.
- Separate saved reader/Stand enables and adjustable arrival tolerance (initial
  30 us). Both features initially off while wiring/calibration is incomplete.
  Measured Stand uses the shaft-derived starting pose. Startup confirms its fold,
  then the existing shift/lift/place/lower landmarks; a shoulder stays uncommanded
  until its leg's lift arrival is confirmed. Final completion follows measured
  arrival. A reading predating the target write cannot confirm arrival. If a
  required reading is missing or a joint cannot arrive, the stage stays active
  with targets applied; it does not time out or shut down.

Validation: pinned ESP-IDF 5.5.4 build succeeded, application 2,865,056 bytes in
an 8 MiB slot. All **53 native tests**, **36 dashboard integration tests**, and
the seven dashboard JavaScript test files passed. New checks cover reversed
feedback polarity and servo inversion, independent mux/PCA mapping, stale sample
arrival, incomplete calibration, extended stage holding, shoulder sequencing,
final arrival, cancellation, authentication, saved-request forwarding, selected
robot changes and concurrent UI polling. The broader gateway run initially
found its existing camera test double lacked `_publish_event`; that fixture now
records published events, without changing camera behavior. System Python lacks
optional OpenCV; the unrelated camera measurement path reported that limitation.
Syntax and diff whitespace checks passed.

Frozen candidate is outside the repository at
`/tmp/ainekio-servo-feedback-20261016/ainekio_p4_body.bin`, SHA-256
`045cbf6d2ce6ea12dda604bedd595b44d11ead6ceb80d511c27016041d298f9e`.
**Not flashed, gateway not restarted, no physical movement sent.** The module is
not installed, so ADC settling/loading, feedback accuracy, persistence across a
real reboot and loaded Stand remain unverified. Wiring, mapping and commissioning
are recorded in [PCA9685_WIRING.md](PCA9685_WIRING.md#mg90-fourth-wire-feedback--october-16-2026).
Joint arrival estimates pose; it does not measure motor current, contact force
or absolute body height, and it cannot itself overcome inadequate load torque.

### 2026-10-17 — Replacement 1.9-inch LCD firmware restored

Owner received the replacement LCD and requested removal of the temporary OLED
and its associated code. The original `main/display.c` ST7789 driver and shared
color face renderer were still present. Current firmware now compiles that driver
directly; `display_ssd1306.c`, the temporary panel choice and the OLED default
were removed. Existing color animations, listening/speech presentation, manual
face selection, connection/setup pages, warning icons and OTA progress remain
on the original LCD path, at 320×170, 15 FPS and the installed 180-degree rotation.
The newer servo-feedback source and other existing local work were retained.
V1's separate display implementation was not changed.

Clean ESP-IDF 5.5.4 build **0.8.64-p4-lcd-restored** succeeded for pre-V3 P4
using the full OTA layout. Application size is **2,905,696 bytes**, within the
8 MiB application slot. Build inputs include only `main/display.c` for the P4
display; linked-symbol inspection confirms the ST7789 driver and no SSD1306 or
temporary OLED driver symbols. All four focused native tests pass: wide color
faces, motion-face timeline, LCD connection guidance, and OTA upload/activation.
Scoped whitespace checks pass. No new display policy or motion restriction was
added.

Frozen application: `/tmp/ainekio-lcd-restored-20261017/ainekio_p4_body.bin`.
SHA-256: `249b8b9f54320442699e60aee1de150ec45f2f72879f088ad8b634e04f361a50`.
Build logs, configuration and artifact manifest remain outside the repository.
The owner confirms the replacement is not wired yet; **not flashed or physically
tested**. No robot command or calibration write was sent. The existing
[LCD wiring image/table](LCD_FACE.md#connections) remains authoritative:
SCLK20, MOSI21, CS22, DC23, RESET26, VCC/BLK 3V3 and common ground. These do not
conflict with the proposed feedback multiplexer pins.

### October 17 installation — startup allocation fixed; LCD picture pending

The owner wired the replacement and authorized installation. USB initially
enumerated but denied serial access. The existing authenticated Body Control
OTA path staged the complete application and selected it for restart. The P4
then stopped reconnecting and the owner reported backlight without an image.
After the owner granted access to `/dev/ttyACM0`, the serial log confirmed the
initial LCD image repeatedly asserted in `vApplicationGetIdleTaskMemory` before
`app_main`; this was a startup allocation failure, not an LCD presence test.

Linked-symbol comparison against the preceding OLED candidate shows about
9,510 additional internal-RAM instruction bytes for the LCD SPI driver. The
Hosted global constructor allocated its transport before the scheduler released
the pre-V3 P4 startup-stack regions. The build now omits that constructor source
and calls the same `esp_hosted_init()` API from the existing network task before
its first remote Wi-Fi call. No managed SDK source, transport queue capacity,
task stack, movement limit, LCD rate or camera rate was changed. This removes
the early allocation at its initialization owner rather than reducing capacity.

The corrected **0.8.64-p4-lcd-restored** application is **2,905,408 bytes**,
SHA-256 `ad25134dcabc7f0c11d3ac38742788588599c1ade5f171f4245e50230b369345`.
It was written over USB to the already selected `ota_0` at `0x20000`; esptool's
write hash check and separate `verify_flash` both passed. Metadata readback from
`0x8000` through `0x11fff` matches its pre-write backup byte-for-byte, preserving
the partition table, NVS, PHY and OTA selectors. The previous application in
`ota_1`, bootloader, assets and calibration were not rewritten.

The corrected boot reaches main, initializes camera/audio and ST7789, then
starts Hosted under the network task. Serial reports display ready, 342 rendered
frames, no output fault, and about 119 KB free internal heap at the sampled
console check. C6 2.12.8 and the unchanged TX/RX queue sizes of eight are reported.
Body Control subsequently reports the robot online, camera and display ready,
and calibration saved with no pending edits. Authenticated firmware status
confirms running/boot `ota_0`, version 0.8.64, pending verification false, ESP_OK.

**The owner still sees no LCD picture**, despite a working backlight. Write-only
SPI cannot acknowledge the physical panel, so transfer success does not prove
that the LCD receives the signals or displays them. The owner suspects this
replacement and will compare another panel with power removed during the swap.
No second flash is required for that comparison. Physical picture, colors and
orientation remain unverified; the remaining cause is not yet identified. No
test movement was commanded; reboot followed the existing startup policy.

### 2026-10-17 — Multiplexer assembly image for C4–C15

Owner received the CD74HC4067 module and selected C15 through C4 for twelve
feedback wires. Added `Multiplexer_Wiring.svg` and a 2400 × 1740 PNG alongside
existing assembly images. The diagram shows seven P4 connections, an EN-to-GND
local jumper, the twelve selected inputs, and the distinction between the new
feedback wire and the existing PCA9685 servo wiring. It uses printed labels and
explicitly does not claim to reproduce the delivered module's connector layout.
Header rows were checked against the existing P4 pinout; signal assignments
match the feedback driver. The rendered PNG was visually checked for legibility.
Input-to-joint assignments are not assumed: the existing C0–C11 software defaults
must be mapped to the owner's actual C4–C15 wiring. No firmware, saved calibration,
or physical robot state changed for this documentation request.

### 2026-10-17 — First physical C4 feedback acquisition

Owner connected the multiplexer to the P4 and one modified servo to PCA9685
socket 0, with its added wiper wire on mux C4. Live authenticated Body Control
status confirms firmware 0.8.64-p4-lcd-restored, running/boot ota_0 and pending
verification false; the installed image advertises servo_feedback_v1. Reader
settings initially disabled, measured Stand disabled, with no captured curves.
Enabled acquisition only, retaining measured Stand off and the existing 30 us
arrival tolerance. No motor command, input remapping, calibration capture,
firmware upload or restart was issued.

Collected 15 C4 samples over approximately 3.3 seconds while the existing socket
0 command remained 1500 us. ADC initialization and voltage calibration report
ESP_OK. C4 raw values were 1536–1570 (1476–1508 mV); excluding the first sample,
1556–1570 (1495–1508 mV). Scan advanced from 11 to 176. Last sample's four-read
spread was 8 ADC counts; the first was 63. This establishes live analog
acquisition through the selected mux channel, not calibrated shaft position or
proof of adequate accuracy/settling under motion. Raw observations are outside
the repo at /tmp/ainekio-c4-initial-samples.json. Asked whether the test servo is
free of the linkage before any movement-based check. Existing default logical
input mappings remain unchanged; the test wire is identified directly as C4.

### 2026-10-17 — C4 spare-servo movement and repeatability check

Owner confirmed the socket-0 servo is a loose spare with the horn clear to move.
Used the existing Body Control calibration owner, entering calibration mode,
reading the saved joint-to-output mapping, and commanding only the joint mapped
to PCA9685 socket 0: 1500 → 1650 → 1350 → 1500 us. Collected twelve C4 snapshots
per position. Last-six sample medians were respectively 1525, 1702, 1340 and
1506 mV (raw 1587.5, 1772, 1395 and 1568). C4 responds in the expected direction
and distinguishes these commanded positions. Readback confirms return to 1500
us; comparison of all saved joint fields confirms no motor calibration change.
Requested return to the original normal mode. No feedback curves or input
mapping were saved; measured Stand remains disabled.

A separate sixty-sample stationary check at the retained 1500 us command gave
raw median 1570.5, 10th–90th percentile samples 1561–1583 and total range
1543–1614; voltage median 1508.5 mV, total range 1482–1550 mV. Maximum spread
inside a four-conversion average was 193 counts. The local two-position slope
is approximately 1.257 ADC counts/us, so the observed total stationary spread
would correspond to about 56 us using that provisional slope. This is not a
saved calibration or a measured angle. Noise, supply variation, acquisition
settling and actual shaft motion have not been separated; do not attribute all
variation to motor position or claim the existing 30 us arrival tolerance is
physically qualified from this test.

Evidence remains outside the repo at /tmp/ainekio-c4-motion-test-results.json
and /tmp/ainekio-c4-stationary-test-results.json. The test confirms a responsive
analog feedback path for one loose servo around its middle travel; full-range
accuracy, loaded response and the other eleven servo wires remain untested.

### 2026-10-17 — Loose servos 1–3 checked on C5–C7

Owner clarified that the legs are not attached: the servos are being checked
before installation. Confirmed wiring is PCA9685 socket 1 → C5, socket 2 → C6,
and socket 3 → C7. The P4 reconnected on 0.8.64; acquisition remained enabled
across reboot and measured Stand remained off. Tested one output at a time
through the existing Body Control calibration owner, using the saved logical
joint-to-output mapping. Each sequence was 1500 → 1650 → 1350 → 1500 us, with
12 C4–C7 snapshots at each command. Settings were not staged or saved.

Last-six-sample voltage medians:

| PCA socket / input | First 1500 us | 1650 us | 1350 us | Return 1500 us |
| --- | --- | --- | --- | --- |
| 1 / C5 | 1.5020 V | 1.6980 V | 1.3160 V | 1.5105 V |
| 2 / C6 | 1.5160 V | 1.6780 V | 1.3165 V | 1.4810 V |
| 3 / C7 | 1.5125 V | 1.6925 V | 1.3190 V | 1.5000 V |

Each commanded output caused the corresponding input to change in the expected
direction; simultaneously observed other connected inputs did not show a
comparable command-sized change. Final command readback confirms all three at
1500 us. Saved motor calibration fields compare unchanged before/after; return
to the original normal mode was requested. Feedback input mapping and curves
remain unchanged. This establishes basic loose-servo movement/feedback response
around mid-travel, not full-range or loaded performance. Sample variation remains:
maximum within-scan spreads were 180, 180 and 94 counts for C5, C6 and C7, and
socket 2's return-to-centre median differed by 35 mV from its first centre reading.
These measurements alone do not separate shaft hysteresis from acquisition noise.

Detailed observations remain outside the repo at
/tmp/ainekio-c5-c7-motion-test-results.json. No firmware update, Home sequence,
Stand command, loaded-leg test or calibration save was performed.

### 2026-10-17 — Remaining loose servos 4–11 checked on C8–C15

Owner confirmed all remaining servos are loose with horns clear, and socket 4–11
feedback wires are connected in order to C8–C15. Live 0.8.64 firmware reported
acquisition enabled, measured Stand off, ADC/voltage errors ESP_OK. Used the
existing Body Control calibration owner to test each output individually at
1500 → 1650 → 1350 → 1500 us, collecting twelve snapshots per target and
observing all twelve connected feedback inputs simultaneously.

| PCA socket / input | First 1500 us | 1650 us | 1350 us | Return 1500 us |
| --- | --- | --- | --- | --- |
| 4 / C8 | 1.4865 V | 1.6735 V | 1.3175 V | 1.4850 V |
| 5 / C9 | 1.4935 V | 1.6710 V | 1.3140 V | 1.4860 V |
| 6 / C10 | 1.4750 V | 1.6470 V | 1.2985 V | 1.4660 V |
| 7 / C11 | 1.5170 V | 1.7010 V | 1.3340 V | 1.5040 V |
| 8 / C12 | 1.4995 V | 1.6710 V | 1.3205 V | 1.4860 V |
| 9 / C13 | 1.5105 V | 1.7010 V | 1.3280 V | 1.5100 V |
| 10 / C14 | 1.4875 V | 1.6735 V | 1.3175 V | 1.4860 V |
| 11 / C15 | 1.4990 V | 1.6765 V | 1.3175 V | 1.4910 V |

All eight expected inputs responded in the commanded direction. The high/low
command separation produced 362.5–389 raw counts on the corresponding input;
the largest change in any other input's median was 10.5 counts. No swapped or
nonresponding channel was observed in this middle-travel check. Final readback
confirms sockets 4–11 commanded to 1500 us. Saved motor calibration fields were
unchanged; return to the original normal mode was requested. Feedback curves
and input mapping remain unchanged. No Home, Stand, firmware update or loaded
leg movement was commanded.

Together with the earlier tests of sockets 0–3, all twelve fourth-wire paths
have now shown a response to individually commanded loose-servo movement. This
is not full-range calibration or evidence of loaded standing performance. Noise
and repeatability still require characterization when calibrating. Detailed
observations remain outside the repo at
/tmp/ainekio-c8-c15-motion-test-results.json.

### 2026-10-17 — All twelve loose servos calibrated over 500–2800 us

Owner approved this range with all horns clear and linkages removed. Saved the
confirmed PCA9685 socket N → multiplexer C(N+4) mapping for all twelve joints.
Through the existing Body Control calibration owner, commanded each servo
individually to 500, 1650 and 2800 us. Captured an actual ADC observation nearest
the settled sample median at each point, including its scan/configuration
revision, and saved each three-point curve to the robot's feedback settings.
Live readback reports twelve calibrated joints, saved=true, acquisition enabled,
and measured Stand still disabled. Firmware remains 0.8.64-p4-lcd-restored.

Checked each completed curve at 2225, 1075, 1650 and 1500 us. Across 48 check
positions and 480 settled observations, the largest absolute median difference
between feedback-estimated pulse and command was 15.31 us; the largest individual
difference was 23.34 us. Both occurred on socket 8 / C12. All checked observations
were within the existing 30 us tolerance, which was not changed. Median endpoint
voltages across the twelve servos were 0.244–0.259 V at 500 us and
3.0815–3.174 V at 2800 us. This is unloaded command/feedback agreement, not an
independent angular accuracy measurement, sustained noise qualification, or
evidence that a loaded leg can lift the robot.

A Wi-Fi read timed out after socket 5's three points were saved. Readback
confirmed the robot remained online and those points intact; resumed only the
unfinished checks and remaining sockets. No firmware recovery or restart was
needed. Saved motor Home, direction, mapping and other motor-calibration fields
compare unchanged against the initial backup. Requested return to normal mode.
Sockets 1–11 finished commanded to 1500 us; socket 0 had returned to 1500 us in
its earlier calibration pass and its PWM was subsequently disabled by entry
into calibration mode for the remaining tests. No Home or Stand was commanded.

The 500–2800 us values define these feedback calibration points; no new firmware
travel restriction was added. Measured Stand remains off until linkages are
installed and a supported test can validate the assembled mechanism. Detailed
observations, backup, saved readback and summary remain outside the repository
at /tmp/ainekio-feedback-calibration-20261017/.

### 2026-10-18 — Assembly socket map and dedicated LSM6DS3 guide

Added SERVO_SOCKET_MAP.md and Servo_Socket_Map.svg/.png showing physical
shoulder/carrier/crank assignments for all twelve PCA9685 sockets and C4–C15
feedback inputs. Cross-checked joint labels against joints_v2.py and the saved
October 17 motor/feedback readback. Included a top-view orientation drawing and
the legacy CAD front/rear naming distinction. Corrected the older feedback
wiring table to lead with the saved mapping rather than unconfigured defaults.

Added LSM6DS3_IMU.md and LSM6DS3_Wiring.svg/.png with the existing GPIO7/8 shared
bus, local straps, mounting-axis evidence, level-reference operation and separate
stationary gyro-bias calibration. Checked calibration labels and behavior against
the current dashboard and firmware source. Linked both guides from the V2 index,
combined assembly reference and PCA9685 wiring document. This is documentation
work: no robot commands, configuration changes or firmware update were issued.

### 2026-10-18 — Full P4 header pinout refreshed

Updated ESP32P4_Pinout.svg and its PNG in place, retaining the board orientation
and physical header row positions. Added LCD GPIO20/21/22/23/26, LSM6DS3 on shared
GPIO7/8, and CD74HC4067 select GPIO27/28/29/30 plus SIG GPIO49. Marked module
ground connections and the shared 3V3 branches; replaced obsolete bench/startup
captions with current power and local-strap notes. Cross-checked against firmware
board constants, actual LCD sdkconfig, feedback acquisition source and media bus
source. Visually reviewed the rendered diagram and updated documentation links.
No physical wiring or firmware configuration was changed.

### 2026-10-18 — Installed-leg servo and feedback connection check

Owner installed all legs, reported the robot standing, and then confirmed the
frame supported with feet unloaded for small individual-joint movement checks.
Live firmware remains 0.8.64-p4-lcd-restored. All twelve C4–C15 mappings and
three-point feedback curves match the saved loose-servo calibration after a
restart. Initial 60 snapshots over 14.8 seconds were fresh (maximum input age
29.5 ms), with ADC status ESP_OK and every mapped input valid. The owner's
transition to support overlapped this observation period, so these are not a
controlled loaded-versus-unloaded comparison. C0–C3 remain unused floating inputs.

Used the existing Body Control calibration owner. Entering calibration mode
releases PWM; restored all retained command targets before the movement checks.
Each joint then received current target +60 us, original target, target -60 us,
and original target, with twelve snapshots per stage. Last-six medians compare
the high and low positions. All twelve expected inputs responded in the positive
direction and more strongly than any other connected input during that joint's
test: matching raw change 61.5–146 counts; largest other-input change across all
tests 26.5 counts. No swapped or nonresponding wire was observed. This verifies
the commanded output-to-feedback association, not independent identification
of the physical limb by vision.

| Physical joint | PCA / MUX | Measured high-to-low span for 120 us command | Final stationary target minus measured median |
| --- | --- | --- | --- |
| Rear left shoulder | 0 / C4 | 81.3 us | +21.9 us |
| Rear left carrier | 1 / C5 | 87.2 us | -15.5 us |
| Rear left crank | 2 / C6 | 99.2 us | -2.5 us |
| Rear right shoulder | 3 / C7 | 46.7 us | +14.9 us |
| Rear right carrier | 4 / C8 | 91.1 us | +1.3 us |
| Rear right crank | 5 / C9 | 105.1 us | +1.7 us |
| Front left shoulder | 6 / C10 | 109.6 us | -28.0 us |
| Front left carrier | 7 / C11 | 109.9 us | +0.6 us |
| Front left crank | 8 / C12 | 104.8 us | -18.0 us |
| Front right shoulder | 9 / C13 | 97.7 us | +18.6 us |
| Front right carrier | 10 / C14 | 100.3 us | +5.4 us |
| Front right crank | 11 / C15 | 99.1 us | -1.9 us |

The rear-right shoulder had the weakest small-reversal response; its low-stage
median error reached -46.6 us. Front-left shoulder stage errors reached -37.3 us.
A subsequent 30-snapshot stationary read had all median errors within 30 us but
individual excursions reached 88.4 us on front-left crank. These results do not
separate internal servo deadband, joint friction/load, supply/reference effects,
shaft hysteresis and acquisition noise. No stall diagnosis or calibration
adjustment is justified from these measurements alone. In particular, do not
silently widen the 30 us arrival tolerance or claim measured Stand is qualified.

All original pulse targets were restored and normal mode confirmed. Saved motor
calibration and feedback curves remained unchanged. Measured Stand remains off;
no Stand, walking or full-range linked-leg sweep was commanded. Evidence is
outside the repository at /tmp/ainekio-installed-feedback-20261018/ (initial
observations, per-joint stages, motion summary and final stationary readback).

### 2026-10-18 — Measured-joint stationary leveling candidate, 0.8.65

Owner requested combining gyro leveling with the twelve new shaft feedback
wires and approved continuing gyro-only leveling when measured feedback is
unavailable, with that state reported. During the supported axis check,
left-side raised measured roll +19.353 degrees and pitch +4.946 degrees. Owner
reported the right legs extending. This agrees with raising the low side toward
level with feet planted; no axis or servo-direction inversion was made.

Implemented stationary Stand tracking around the existing gyro-generated pose.
Saved feedback curves and per-joint mappings convert shaft readings to model
angles. The output adds half the desired-minus-measured joint error, without
integrating that trim or feeding it into the next gyro target. Existing linkage
and joint-speed feasibility logic reduces only the extra trim if it cannot fit.
Moving gaits keep gyro-only feedback. The existing Self-leveling switch controls
both stationary loops; the separate measured Stand sequencing setting is not
changed. No arrival wait, shutdown, or new motion-range restriction was added.

Body Control now displays tracking availability/activity, measured joint errors
and applied corrections in physical RL/RR/FL/FR order. Acquisition failure or
missing calibrated readings leaves gyro-only leveling active. Plausible floating
voltages from a disconnected wire are not reliably identified; the acquisition
interface also has no sample-age cutoff for this consumer. Do not describe this
as an unplug detector, foot-contact sensor, or proof of available lifting torque.

Validation: native balance, calibrated feedback-position conversion and targeted
body feedback tests pass, including left/right physical extension signs, persistent
error without trim accumulation, a one-frame delayed ideal actuator, correction
feasibility reduction, gyro-only fallback and switch-off behavior. Dashboard
motion-race tests and JavaScript syntax checks pass. ESP-IDF cross-build succeeds
as 0.8.65-p4-measured-leveling; application size 0x2c4de0 in an 8 MiB slot.
Source whitespace checks pass. These are targeted checks, not a claim that the
broader motion suite or loaded hardware is qualified. An earlier invocation of
the old broad body-test binary failed its listening-feedback pulse-range assertion.

Candidate is not installed yet. Supported physical correction and stability
remain untested; gain 0.5 is an initial proportional setting, not a measured
optimum. Existing firmware and saved calibration remain on the robot pending
the owner's readiness for the Wi-Fi restart. Build and test logs remain in
/tmp/ainekio-measured-level-* outside the repository.

Deployment and first live observation: owner confirmed support and servo power
off. Wi-Fi upload/activation succeeded; running and boot partitions are ota_1,
0.8.65-p4-measured-leveling, pending verification false. All twelve saved feedback
curves and joint mappings/calibration match the pre-update readback (excluding
transient ready state and commanded pulses). Display, camera, IMU and joint
acquisition report available. Self-leveling's saved Off setting was preserved;
the owner subsequently enabled it and reported correction still reversed.

This physical report supersedes any implication that the earlier single-axis
observation qualified the assembled robot's correction direction. Live telemetry
on the reported level surface showed the standing controller accumulating
43.70 degrees roll correction at measured roll -13.82 degrees, with modeled
left extension about +28 mm and right extension about -64 mm. Added shaft trim
was reduced to zero by pose feasibility. These extension values are calculated
from commands, not measured foot heights. Most shaft readings followed their
commands within several degrees; one earlier rear-left carrier discrepancy
of about 907 us later reduced to 62–67 us. Do not infer a permanent wire fault
or physical reversal from that transient alone. Requested physical body lean
to distinguish sensor orientation from joint geometry/mounting errors. Loaded
leveling remains unresolved; the installed candidate is not physically qualified.
Evidence: /tmp/ainekio-measured-level-20261018/.


### 2026-10-18 — Owner-requested reversal of both leveling responses, 0.8.66

Owner explicitly reported left-up causing left retraction/right extension and
requested the opposite, then confirmed front/back response also reversed. The
P4 output owner now selects -1 response polarity for both roll and pitch, for
standing and moving gait correction. Attitude-error and angular-rate terms are
reversed together. Sensor quaternions/rates, saved references, pulse calibration,
horn inversion, startup posture interpretation and measured-joint tracking are
unchanged. Saved zero-error poses still produce zero incremental correction.
No new timeout, stop, restriction or fallback was introduced.

The portable controller retains its conventional +1 response wrapper so existing
model convergence tests are not rewritten to assert convergence of the reversed
response. New direction tests exercise both polarities, both axes and standing/
moving modes using forward geometry. For the P4-selected -1 response, a raised
left side requests left extension/right retraction; a raised front requests front
extension/rear retraction. Rate-term reversal and reference preservation pass.
The production body feedback tests pass with mapped inverted servos and the
revised front/rear response, plus existing tracking, unavailable-feedback,
switch, stale-IMU and walking-continuation behavior. ESP-IDF builds
0.8.66-p4-level-direction successfully. These tests establish commanded behavior;
they do not prove a gyro hardware fault or physical closed-loop convergence.

The candidate has not been installed yet. The last live observation placed the
robot on the floor with outputs active; a fresh supported/power-off confirmation
is needed for restart. Physical direction and settling must be checked after
installation. Build/test logs are /tmp/ainekio-level-direction-*.

Deployment completed after the owner confirmed support and servo power off.
Uploaded and activated through the Wi-Fi Body Control OTA owner. Reconnected
running 0.8.66-p4-level-direction from ota_0; boot also ota_0, pending verification
false, ESP_OK. Compared before/after readbacks: all twelve feedback curves,
feedback/output channel mappings and saved joint calibration are unchanged.
IMU, feedback acquisition, LCD and camera report available. Outputs report ready
and armed with fault 0; Self-leveling remains enabled and reports measured-joint
tracking active. This confirms firmware/runtime integration, not servo power
state or physical convergence. No extra motion commands were sent during this
update. Both physical response directions and settling remain to be evaluated.
Artifact hash, OTA receipts and calibration readbacks are outside the repo at
/tmp/ainekio-level-direction-20261018/.

### 2026-10-18 — Measured shaft Home capture in Joint Calibration

Owner reports all four carriers and cranks physically at their furthest-back
positions and defines that pose as Home; shoulders are outside this change.
Owner requested fourth-wire readings inside Joint Calibration and the ability
to position a joint and save that measured position as Home.

Body Control now shows the selected joint's mapped mux input, ADC/voltage,
measured pulse-equivalent position, mapped model angle, current target and
target-minus-measured difference. It uses the existing feedback polling owner.
The previous command-copy button now reads feedback on click and captures the
measured position into the selected joint's Home draft. It does not issue a
movement, change other joint drafts, or automatically save calibration.
Apply & save uses the existing selected-joint set and device save/readback path.
Existing output-release behavior on apply/save is unchanged and remains labeled.

Choosing a new Home re-anchors the draft's Home pulse and model angle together,
preserving its angle-to-pulse mapping to the existing 0.01-degree storage
precision. This accepts an endpoint Home without treating it as the servo's
midpoint or silently shifting every gait command. It does not establish a new
horn mounting angle: a refitted horn still requires a known mechanical reference.
The three-point pot curves remain separate and unchanged. Unavailable calibrated
measurements are reported without substituting commanded pulses; extrapolated
measurements are labeled. Both installed leveling response reversals remain intact.

Production-handler tests pass for measured-versus-commanded capture, both
inversion directions, preservation of the motion mapping across the pulse range,
selected-joint save/readback, missing samples/calibration, and robot/joint/edit
changes during a pending read. Existing feedback, gyro-trial and motion-race
tests pass; JavaScript syntax and diff whitespace checks pass. A read-only live
browser check displayed fourth-wire measurements from the connected robot,
with no JavaScript errors or horizontal overflow at desktop/mobile widths.
Evidence screenshots are outside the repository at
/tmp/ainekio-measured-home-desktop.png and /tmp/ainekio-measured-home-mobile.png.
No firmware update, movement, or robot Home-save command was sent in this task.
Saving and physically returning to the owner's new endpoint Home remain untested.

Earlier manual gyro-guided trials were paused at the owner's request. Those
trials produced a near-zero attitude sample but did not establish reliable
automatic leveling or a general joint calibration. The browser trial controls
remain separate from measured Home capture; neither result qualifies loaded
gait performance or automatic leveling convergence.

### 2026-10-18 — Correct physical-reference Home capture and carrier mismatch

Owner saved their rearward leg Homes, rebooted, and observed the rear-left
carrier remaining near Home while the other carriers moved away. Live readback
confirmed persisted Home pulses but inconsistent Home angles: rear-left carrier
+1.17°, the other three -30.87°, all cranks -117.68°. Startup was issuing Stand,
not literal calibration Home; Self-leveling was off. The measured shaft readings
generally followed those different commanded targets. Thus the observed
carrier discrepancy had a demonstrated mapping cause, not a failed save.

The earlier measured-Home button preserved the previous affine mapping. That
was inadequate for the requested physical calibration: it could preserve a
wrong angle offset. Capture now explicitly associates the measured pulse with
the selected physical reference. Rearward assembly defaults for leg joints use
carrier -30.87° and crank -117.68°, as documented in the 0.8.59 deployment entry.
Custom uses the entered model angle unchanged; shoulders default to Custom.
Scale and inversion are retained, and capture changes only the selected draft.
Original matchmark guidance is labeled separately from rearward Home to avoid
mixing the two references. This supersedes the mapping-preservation behavior
described in the immediately preceding journal entry.

These are existing model references, not new measured absolute linkage angles.
Carrier -30.87° derives from the original 2444/856 µs mapping at 2800/500 µs;
the crank -117.68° remains photo-estimated. The owner's matching physical poses
are the reference assumption. No automatic inference of horn indexing from the
potentiometer is claimed.

After the owner confirmed frame support, corrected only rear-left carrier
home_cd from 117 to -3087 through the Wi-Fi calibration owner and saved/read back
the device settings. All twelve owner-set Home pulses, output channels, inversion,
scales and other Home angles were preserved, as were all twelve feedback curves
and mux assignments. Saved=true, dirty=false. Calibration entry released outputs;
no Home, Stand, Freestyle, restart or firmware update was sent. Device left in
calibration mode with outputs released. Receipts and before/after state are in
/tmp/ainekio-home-reference-fix-20261018/ outside the repository.

Tests exercise all eight leg joints with unequal measurements, different prior
angles and mirrored directions; corresponding reference angles now agree.
Custom/shoulder capture, selected-joint persistence/readback, missing feedback,
and robot/joint/edit/reference changes during capture pass. Existing feedback,
gyro-trial and motion-race suites pass. A native check using the production
startup Stand and joint mapper with the actual saved calibration produces
carrier pulses RL 2444, RR 796, FL 2359, FR 941 µs: each is 381 µs from its own
Home in the correct mirrored direction. Calibration Home maps exactly to every
saved Home pulse. This verifies software consistency, not physical standing.
Read-only desktop/mobile browser verification shows the corrected saved angle,
rearward reference selector and live fourth-wire readings, with no JavaScript
errors or horizontal overflow. Supported physical Stand remains to be checked.

### 2026-10-18 — Hard-right motion after enabling Self-leveling

Owner reported an immediate extreme rightward attitude when enabling leveling
after joint calibration. Read-only telemetry showed roll +32.275° and nose-up
pitch +8.260°, with saved targets roll -2.0112° / pitch +3.0183°. Standing balance
was active, roll correction +0.602589 rad (+34.53°), and correction reduction was
active. Measured-joint feedback was available/active but all twelve additional
tracking trims were zero in this sample. The corrected carrier Home angles
remained saved. One generated target was rear-right carrier 236 µs, demonstrating
that the leveling trajectory was driving beyond the owner's ordinary reference
span; this investigation did not add a pulse clamp or change the span.

The P4 calls balance_response_apply with response_direction=-1, introduced in
0.8.66 for the requested reversal of both physical responses. This multiplies
the entire attitude-error and rate terms, including the standing integral
increment. It is separate from each servo's saved invert mapping.

Reproduced the existing planted-body ideal-actuator convergence experiment
using the production balance library and both response polarities. With an
initial +4.584° disturbance and 200 ticks at 20 ms, -1 produced roll +51.304°
or pitch +29.948° and reduced further correction at the geometry boundary.
The +1 cases converged to approximately +0.005° on both axes. This establishes
positive feedback for the installed polarity under the model's body/IMU frame
relationship; it is not a new loaded-robot motion test. Live tilt and correction
signs are consistent with that failure. The saved nonzero level target alone
does not account for the approximately 32° tilt.

No settings, motion commands or firmware changes were sent. Owner was asked
to turn Self-leveling off. The earlier explicit instruction to retain both
reversals remains in force; a change to that response requires resolving it
with the owner. Readback and offline test artifacts are outside the repository:
/tmp/ainekio-level-after-home.json and /tmp/ainekio-level-polarity-check.c.

### 2026-10-18 — Approved negative-feedback correction, 0.8.67

Owner explicitly approved correcting the leveling direction after the hard-right
diagnosis, superseding the earlier instruction to retain both response reversals.
The P4 body owner now calls the configured negative-feedback controller instead
of selecting response_direction=-1. Both attitude-error and angular-rate damping
terms therefore act toward the saved body reference. Servo-specific inversions,
IMU axis transform/bias, saved level targets, Home settings, three-point sensor
curves, feedback tracking and motion speeds remain unchanged. No new timeout,
shutdown, limiter, fallback or sensor requirement was added.

Added a production-owner closed-loop regression in test_body.c: the real P4
scheduler, corrected unequal Home pulses, mirrored mapping and available shaft
feedback run against the ideal planted-body response. Positive/negative roll
and pitch disturbances converge toward nonzero saved references, with final
residual approximately 0.00019° after 300 model ticks; mappings remain unchanged.
The earlier P4-only reversed call would fail this test even though the portable
controller's separate convergence tests passed. Existing direction expectations
now require raised-front shortening/rear extension and opposing roll correction.

Targeted feedback tests, portable balance tests, servo-feedback mapping tests
and the full native production-body suite pass, including startup, all 23 stored
clips and locomotion/command behavior. ESP-IDF 5.5.4 builds
0.8.67-p4-level-feedback successfully. Frozen binary: 2,903,600 bytes,
SHA-256 f198671a7a5d19ebce6a251fd9cac13f5165133607b78ccb9396d05c3b754c64.
Artifact and deployment tools: /tmp/ainekio-level-feedback-20261018/.
Physical settling is not established by these model tests. Awaiting supported,
servo-power-off readiness before Wi-Fi activation; no new image installed yet.

Deployment completed after the owner confirmed readiness. Uploaded and
activated through the existing Wi-Fi OTA owner. The robot reconnected running
0.8.67-p4-level-feedback from ota_1, boot ota_1, pending_verify=false, ESP_OK.
Before/after comparisons confirm all twelve joint mappings, including the
corrected rear-left carrier reference and all owner-adjusted Home pulses, are
unchanged. All twelve fourth-wire curves and mux/output mappings are unchanged.
Feedback acquisition, IMU, display and camera report available; output fault is
zero. Self-leveling remains off as the owner left it before deployment. Startup
ran with servo power off per readiness confirmation. No additional movement
command was sent. Physical closed-loop leveling remains to be checked with
servo power restored; successful deployment is not that physical validation.

### 2026-10-18 — Level reference captured with physically level frame

After the 0.8.67 update the owner reported improved but imperfect leveling,
supported the frame and explicitly confirmed that the frame itself was physically
level. Self-leveling was off in live readback. Seven fresh IMU observations over
approximately 1.2 seconds ranged from +3.2962° to +3.3132° roll and +0.3290° to
+0.3490° nose-up pitch. Saved their median, rounded to four decimals, through the
existing Body Control balance owner: roll +3.3082°, pitch +0.3375°. Previously
saved targets were -2.0112° / +3.0183°. A separate readback confirmed saved=true,
tuning_saved=true, strength=1, damping=1 and enabled=false.

This compensates the observed mounting/reference offset at the owner-confirmed
level body pose. It does not change raw IMU orientation, gyro bias, sensor axes,
joint mappings or feedback curves. No movement, restart, or automatic enable
was sent. Raw angles therefore remain nonzero at physical level; error relative
to the saved reference should be near zero. Physical settling with leveling
enabled remains unverified. Receipt: /tmp/ainekio-level-reference-20261018.json.

### 2026-10-18 — Owner-requested quiet hold and shaft hunting tolerance, 0.8.68

Owner requested that leveling ignore the fourth-wire hunting range, reach level
and stop adjusting until needed again. A short read-only stationary sample with
Self-leveling off showed fixed commanded pulses but approximately 13–112 µs
peak-to-peak variation in measured pulse equivalents across joints. This does
not distinguish electrical noise from physical servo movement. Raw capture is
outside the repository at /tmp/ainekio-level-chatter-20261018.json.

Implemented 120 µs shaft-error tolerance for stationary measured-joint trim;
only error beyond that band contributes half-error correction. Raw readings,
curves, Home mappings and the approved negative-feedback direction are unchanged.
Stationary leveling settles within 0.5° on both axes with rates within 1°/s,
holds the achieved commanded pose, and wakes beyond 1° on either axis. While
settled it skips IK/FK, shaft-frame conversion and repeated PWM writes, retaining
lightweight tilt monitoring. Shared ADC/IMU acquisition remains available and
PCA9685 maintains holding PWM; this is not motor power-off. Moving gaits, motion
speed and travel range are unchanged. Body Control shows the settled state and
the active shaft tolerance.

The current live saved level targets had changed to roll 7° / nose-up pitch
1.5928°, strength/damping 1, Self-leveling off. These owner settings are preserved;
this change does not recapture the previously measured physical-level reference.

Production-body feedback tests, full body tests (23 clips and locomotion), portable
balance tests, dashboard motion-race tests and JavaScript syntax checks pass.
Tests verify no additional PWM writes or shaft-frame reads while settled despite
noisy measurements, immediate wake on tilt, moving-through-level behavior,
target changes, existing unavailable-IMU handling and new-command admission.
Ideal planted-body convergence now intentionally ends within 0.5° (about 0.493°
in the test) instead of chasing numerical zero. Physical chatter improvement
is not yet demonstrated. ESP-IDF 5.5.4 builds the candidate successfully.

Frozen artifact: 0.8.68-p4-level-settle, 2905296 bytes, SHA-256
dc53740ee9dcfe99ea7a26c4f08ca0c62498787df3450220b9cfbfbefe9eb969. Receipts and deployment tools:
/tmp/ainekio-level-settle-20261018/. Not yet installed.

Deployment completed after fresh supported/servo-power-off confirmation. Wi-Fi
upload and activation succeeded; the robot accepted 0.8.68-p4-level-settle on
ota_0 with pending_verify=false and ESP_OK. Twelve feedback curves/mux mappings
are unchanged. Comparison detected later Body Control saves during verification:
rear-left carrier Home 2825→2750 µs, self-leveling off→on, roll target 7→3°.
The dashboard audit records joint set/save and balance save operations; these
newer settings were retained, and all remaining compared calibration/settings
match. They are not silently described as unchanged. Pitch target remains
1.59280002°, strength/damping 1.

Live status exposes settle=0.5°, wake=1°, shaft tolerance=120 µs and reports
settled=true, balance active=false and shaft tracking active=false. A subsequent
readback reports roll 3.3581° / nose-up pitch 1.6208°, with no output fault; camera,
display, IMU and feedback acquisition are available. Repeated gateway reads may
reuse a status sample and are not independent high-rate physical observations.
Host tests establish skipped writes while settled; physical chatter reduction
and disturbance recovery still need the owner's observation. No movement or
level-enable command was issued by the deployment tools.

### 2026-10-18 — Direct active stationary leveling, 0.8.69

Owner explicitly requested direct corrective targets for active stationary
leveling while retaining hunting tolerance and settled/wake behavior. The body
attitude controller now requests the complete remaining tilt error scaled by
Strength, instead of the previous dt*2 approach (4% per 20 ms at Strength 1).
The existing per-update angular-rate damping term remains. Active stationary
correction bypasses the joint-speed ramp; stationary fourth-wire tracking also
passes its complete target/trim through without that ramp. The existing geometry
solver and correction-only feasibility reduction remain. No new guard, delay,
shutdown or fallback was added. Moving-gait balance, disabled/stale-sensor fade,
servo calibration, feedback curves and quiet-hold thresholds are unchanged.

Regression tests demonstrate identical first-update PWM targets at speed settings
3/2000 deg/s and update intervals 20/100 ms with zero angular rate. The shaft-trim
regression now runs at 3 deg/s and verifies that its 0.5 degree trim is sent whole,
not ramped. +/-120 us noise tolerance, no writes during settled hold, wake on tilt,
new commands, missing-feedback behavior and both-axis ideal planted-body
convergence pass. Final ideal-model residual is about +/-0.00536 degrees; this
is not measured hardware performance. The larger reachable correction required
updating the unavailable-sensor regression to verify monotonic completion of its
existing speed-limited fade rather than assuming the previous smaller excursion
could always finish fading in four seconds. Full native body suite (23 clips and
locomotion), portable balance tests and ESP-IDF 5.5.4 firmware build pass.

Direct position targets do not constitute a motor-current or torque setting.
Actual loaded speed, torque and settling remain to be checked on the robot.

Frozen artifact: 0.8.69-p4-level-direct, 2905344 bytes, SHA-256
99065e7a3a06f9024392ffef36575e336086a7ab926d031271dac010846d1f96. Deployment tools/receipts:
/tmp/ainekio-level-direct-20261018/. Not installed yet.

Deployment completed after supported/servo-power-off confirmation. The local
Body Control gateway initially refused connections; its existing user service
was stopped. Started that existing service, then captured calibration and
settings before uploading. Wi-Fi OTA accepted 0.8.69-p4-level-direct on ota_1,
pending_verify=false and ESP_OK. Exact before/after comparisons confirm all
twelve joint mappings, feedback curves/mux mappings and saved leveling settings
are preserved (enabled=true, Strength/Damping=1, target roll=3 degrees and
nose-up pitch=1.59280002 degrees). IMU, feedback acquisition, display and camera
report available; output fault is zero. Startup ran with servo power off per
the owner's confirmation. No extra movement or calibration command was sent.
Loaded direct-correction response remains to be physically tested.

### 2026-10-18 — Owner-requested taper after direct-response twitching, 0.8.70

Owner reported considerable twitching and a Stand/system failure after 0.8.69,
and requested tapering during corrections. Read-only inspection found the P4
online with output_fault=1 (existing emergency/failure classification), outputs
disarmed, zero I2C failures and last_esp_error=0. The available boot log contains
the 0.8.69 software restart and no subsequent panic/brownout record. This is
not sufficient to identify the exact failed target or exclude a separate power
problem. Captures remain outside the repository:
/tmp/ainekio-level-taper-20261018/status.json and firmware.log.

Replaced the full-error stationary update with an error-dependent response rate:
rate=2+6*r*r/(1+r*r), r=error/5 degrees, gain=1-exp(-rate*Strength*dt).
At default Strength and 20ms, the correction fraction tapers from 9.52% at 5°,
through 5.50% at 2°, to 4.36% at 1° and 4.04% at 0.5°. Existing angular-rate
damping remains. This deliberately requests smaller successive corrections near
level; it does not command a motor torque/current percentage. Accepted targets
still bypass the joint-speed ramp. Quiet hold and wake, 120us shaft tolerance,
shaft trim, walking balance, saved calibration and missing-sensor behavior remain
unchanged. No new stop, wait, timeout or fallback was added.

Added fault-path diagnostic messages for motion result/kind/stationary-hold state
and stationary target-to-PWM mapping failure. These add evidence, not a new
runtime gate. The prior log did not identify the cause; this update must not be
reported as a proven crash fix.

Portable tests verify decreasing correction fraction as tilt shrinks and unchanged
results across low/high joint-speed settings. A new delayed-actuator scenario
uses 40ms command latency plus a 200ms first-order physical response; both signs
on both axes converge without exceeding the initial 4.584° error magnitude.
These are explicit model assumptions, not measured servo characteristics.
Production-body tests retain settling/wake/no-repeat-writes, shaft noise tolerance,
command admission, missing-data behavior and actual mapper execution. Native
feedback, full body (23 clips and locomotion) and portable balance tests pass.
Physical loaded settling and recurrence of the output fault remain unverified.

ESP-IDF 5.5.4 build passed. Frozen artifact: 0.8.70-p4-level-taper,
2907664 bytes, SHA-256 2d753365ccdb8b6d32265cd3225084934c7e2531ee1557bd6b423251cddf8a7a.
Not installed yet; awaiting supported, servo-power-off readiness.

Installed after owner confirmed supported frame and servo power off. Wi-Fi OTA
accepted 0.8.70-p4-level-taper on ota_0 with pending_verify=false and ESP_OK.
Exact comparison confirms all twelve joint calibration mappings, feedback curves
and saved leveling settings unchanged. IMU, feedback, display and camera are
available; outputs report ready/armed with output_fault=0. Current status reports
settled=true and both gyro correction activity and measured-joint trim inactive,
with raw roll 3.017° and nose-up pitch 1.809° relative to saved targets 3° and
1.5928°. This confirms runtime state reporting, not loaded recovery performance.
No additional movement or settings command was issued. Physical twitch reduction
and whether the earlier output fault recurs remain for observation.

### 2026-10-18 — Chatter observed while distinguishing target changes from shaft readings

Owner reports 0.8.70 resolved the preceding problem but chatter remains and asks
whether motor corrections are observable. Recorded 80 read-only status/feedback
pairs over 27.71s, with 80 live feedback reads and six distinct periodic status
packets. For the first 15.88s (47 distinct feedback scans), all twelve commanded
pulse targets stayed exactly constant; the corresponding periodic frame/I2C
transfer counters also stayed at 5229/5250. Leveling reported settled with both
correction paths inactive. Fourth-wire pulse-equivalent ranges still varied by
about 21–69us peak-to-peak within that fixed-target interval: front-left carrier
2377us command versus 2431.2–2500.5us readings, rear-right crank 1509us command
versus 1566.1–1630.0us readings. These are calibrated electrical observations,
not proof that the shafts physically moved by the full inferred amount.

Later in the capture the counters rose to 5334/5355 and target changes occurred,
showing brief software activity between periodic snapshots even though the six
status snapshots all happened to report settled. No output fault appeared.
Thus continuous host-issued corrections are not established as the sole cause;
if audible chatter continued during the fixed-target interval, new leveling
commands cannot explain that interval. Internal servo holding behavior, actual
motion and feedback noise remain to be distinguished. Motor current is not
measured. No motion/settings commands were issued. Raw observations remain at
/tmp/ainekio-chatter-observation-20261018/capture.json outside the repository.

### 2026-10-18 — Scope of the 120us tolerance and proposed control improvements

Read-only source review confirms 120us is a shaft-tracking error deadband, not a
maximum correction or servo-internal deadband. Before existing geometry reduction,
additional trim is 0.5*sign(error)*max(abs(error)-120us,0), expressed through each
joint's mapping. Gyro-driven body correction is independent of this band. In the
previous 80-sample capture, rear-left carrier error exceeded 120us in 4 samples
(maximum magnitude 133.56us); rear-right crank and front-left carrier each crossed
once (120.99/123.46us). Those readings would qualify for excess-error trim only
when stationary tracking is active. They do not prove that trim was applied at
every crossing or explain audible chatter during unchanged-target intervals.

Current acquisition discards one ADC conversion after mux switching, averages
four conversions and publishes at 20ms scan cadence. There is no cross-scan
position/velocity estimator; feedback_frame sets modeled velocity to zero.
Standing body correction accumulates accepted commanded geometry, with separate
half-error shaft trim. It lacks measured-actuator tracking anti-windup for lag or
load, although it already avoids accumulating unreachable geometry increments.

Proposed, not implemented: per-joint noise/offset characterization and low-latency
position/velocity estimation; use measured actuator response to coordinate the
outer body controller with servo-local control and prevent demand accumulation;
extend explicit hold/hysteresis to meaningful joint-target changes. Tune these
against measured loaded response rather than only an assumed instantaneous
plant. Existing quiet hold already prevented new writes for 15.88s, so firmware
changes cannot be claimed to resolve all fixed-target chatter. Actual PWM
stability, power/ground and servo-local holding behavior remain distinct causes.

Primary references reviewed:
https://www.mathworks.com/help/simulink/slref/anti-windup-control-using-a-pid-controller.html
(cascaded actuator dynamics and tracking anti-windup),
https://www.pololu.com/blog/17/servo-control-interface-in-detail
(servo signal timing and measured electrical response), and
https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32p4/schematic-checklist-esp32p4.html
(ADC signal integrity). No firmware/settings changes made during this review.

### 2026-10-18 — Filtered fourth-wire measurements and actuator-aware leveling

Owner requested better measurement quality and actuator-aware feedback for the
constantly loaded MG90 servos. Implemented 0.8.71-p4-level-tracking. Acquisition
retains its four-conversion average and adds a timestamped One-Euro-style filter
per mux channel: 1.5 Hz resting cutoff, 5 Hz derivative cutoff, speed coefficient
0.002 Hz per ADC-count/s. Filtered position and estimated velocity are available
alongside unchanged raw voltage/counts, spread and calibrated raw position.
Calibration capture and measured-Stand arrival remain on their existing raw path.

Stationary leveling now projects measured joint lag through the local linkage
Jacobian into roll/pitch and back-calculates accumulated correction at 4/s. It
replaces the previous extra half-error servo trim. Each active episode records
the current loaded target-minus-measurement offset as a transient reference;
only subsequent changes outside +/-120us contribute to back-calculation. This
does not save offsets into calibration or demand that an existing loaded error
be removed. Body Control reports actuator tracking, projected body lag and no
added servo overdrive. Raw versus filtered positions are visible in feedback.

Preserved the 0.8.70 taper, mounting/polarity conventions, 0.5deg settle / 1deg
wake, angular-rate settle condition, immediate new commands, gyro-only behavior
when feedback is unavailable, moving-gait behavior and existing motion range.
No shutdown, timeout, waiting stage or new joint-speed restriction was added.
An unobservable local projection contributes no back-calculation.

Validation: native full body suite, balance model suite, feedback filter and
position suites, dashboard motion/feedback/measured-Home suites and ESP-IDF 5.5.4
build passed. Synthetic +/-40 ADC-count noise produced filtered RMS 0.177 of raw;
a 1000-count step reached >90% within 80ms. These are test signals, not measured
loaded hardware performance. Blocked-actuator simulations on both axes/signs
kept demand at about 0.032-0.035rad versus 0.329-0.815rad without tracking, then
converged after release with a modeled 200ms actuator response. Production-owner
tests cover existing loaded offset, +/-120us fluctuations, excess lag, feedback
loss/recovery and quiet holding. Actual loaded chatter reduction remains untested.

Frozen artifact: 2910416 bytes, SHA-256
c8f8e395944e0cad017a6fd6e9227ace97778c785b0901abc286909b2b5609de.
Not installed yet; awaiting supported frame / servo-power-off confirmation.
Primary algorithm references: https://gery.casiez.net/1euro/ and the MathWorks
actuator tracking anti-windup reference above. Parameters are initial engineering
choices; unchanged-target chatter inside the servo remains a separate issue.

Installed after owner confirmed supported frame and servo power off. Wi-Fi OTA
accepted 0.8.71-p4-level-tracking on ota_1, pending_verify=false, ESP_OK. Exact
before/after comparison confirms all twelve feedback curves, joint mappings and
saved leveling settings preserved. All twelve filtered position/velocity fields
and actuator_tracking mode are present. IMU, display and camera report available;
output_fault=0, and leveling reports settled with both correction paths inactive.
This is a supported, servo-power-off verification. Loaded chatter reduction has
not yet been physically verified. Artifacts and snapshots remain outside the
repository at /tmp/ainekio-level-tracking-20261018/.
