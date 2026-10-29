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

## Current position — 2026-10-28

The objective is a **neural walking system replacing the unsuccessful walking
behavior**, initially hosted separately beside Body Control, with possible P4
deployment after measurement. Forward walking is the first learning stage, not
the final feature set. Walk/Run, reverse, turns and curved steering, speed changes
and transitions, leveling, fourth-wire feedback, jam handling and slip/fall
recovery remain required. The existing operator controls and execution ownership
are inventoried in [WALKING_SYSTEM.md](WALKING_SYSTEM.md).

The full CAD dynamics environment now exists, and small neural policies have
demonstrated forward displacement in simulation. A slower guided example also
clears all four boots during steady horizontal swing. **No neural policy has
been activated on the physical robot, and physical walking is not established.**
The robot was last confirmed powered off on October 27; its current physical
state has not been rechecked. See the
[October 27 progress entry](#2026-10-27--neural-walking-training-guided-steps-and-visible-progress)
for measured results, failures, videos and remaining work. The
[October 28 continuation](#2026-10-28--training-handoff-and-optimizer-comparison)
records the resumed training investigation.

## Original problem tracker — recorded 2026-10-12 after owner clarification

The objective is useful weight-bearing locomotion and feedback-based improvement,
including learned control. Sensor bring-up is supporting work, not completion of
that objective. The owner can record external phone video for movement evaluation.

| Original concern | Evidence and status recorded on 2026-10-12 | What will establish improvement |
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

## Original approved work sequence — 2026-10-12

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

### 2026-10-19 — Reassessing walking with measured joint feedback

Owner requested comparison with Spot, Atlas and Pupper V3 before choosing the
next gait architecture. Source review: motion.c:ainekio_v2_walk_tick advances
the gait from elapsed time, including fast-stroke mode. body.c:balance_frame
reads the measured frame but applies actuator tracking only during stationary
balance hold. Walking uses the existing IMU trajectory-relative correction;
measured joints do not yet adapt walking phase or foot targets. Planned body
travel/contact flags remain model outputs, not measured odometry/contact.

Primary-source findings, checked today:
- Spot's published production approach combines model predictive control with
  reinforcement learning; learning complements the existing model controller.
  https://bostondynamics.com/blog/starting-on-the-right-foot-with-reinforcement-learning/
- Atlas architecture depends on generation and demonstrated behavior. Older
  hydraulic Atlas used MPC; electric Atlas demonstrations include simulation-
  trained RL using retargeted human motion. This does not establish every detail
  of its proprietary production controller.
  https://bostondynamics.com/blog/picking-up-momentum/
  https://bostondynamics.com/blog/can-football-teach-a-robot-to-move/
- Pupper V3's public neural controller uses IMU angular velocity/projected
  gravity, measured joint positions, requested motion, previous actions and
  observation history. Its position actions are accompanied by programmable
  kp/kd actuator gains. Its configuration uses a 520Hz controller manager and
  repeat_action=10, approximately 52Hz policy evaluation, targeting 50Hz.
  https://github.com/Nate711/pupperv3-monorepo/blob/main/ros2_ws/src/neural_controller/src/neural_controller.cpp
  https://github.com/Nate711/pupperv3-monorepo/blob/main/ros2_ws/src/neural_controller/launch/config.yaml
  Stanford's newer deployment repository also supports phase-clocked gait
  references with learned feedback: retaining a phase clock is not inherently
  obsolete. Observation layouts vary between policies; do not assume every
  policy consumes joint velocities or measured foot contact.
  https://github.com/cs123-stanford/pupper_gait_deploy

Recommendation, not implemented: retain verified linkage kinematics and add a
measured-state locomotion owner that uses shaft position/estimated velocity,
IMU, command and action history to adjust foot placement, clearance and support
posture continuously. A learned residual controller is a candidate after loaded
actuator identification, with training on a workstation and inference deployment
chosen by measured P4/Q6A latency. No Pupper policy can be transplanted unchanged:
fixed MG90 internal control, linkage topology, backlash, power droop, sampling
skew and latency need representation. Fourth wires provide shaft observation,
not torque control, current measurement or guaranteed contact detection. Camera
or external observation is still needed to distinguish useful travel from slip
when evaluating gaits. This review changed no firmware, settings or robot motion.

### 2026-10-19 — Learned-correction compute sizing

Owner asked whether to train a model and whether P4/Q6A resources suffice.
Proposed policy would be trained for this robot, using existing RL tooling rather
than directly deploying Pupper's weights. Simulation must include the measured
MG90 response and coupled linkage. Training belongs on a workstation; onboard
inference uses the resulting fixed weights. This is not yet implemented.

Illustrative dense networks, not selected/trained models: 64 inputs, two 64-unit
hidden layers and 12 outputs require 9,100 parameters including biases, 35.55KiB
FP32 weights and 0.448 million matrix multiply-accumulates/s at 50Hz. Two 128-unit
hidden layers require 26,380 parameters, 103.05KiB FP32 weights and 1.306 million
MAC/s. These figures exclude runtime, activations, sensing, kinematics and OS
overhead; operation counts are not measured CPU percentages or execution times.

Current sdkconfig selects 360MHz and 200MHz PSRAM. The equipment budget records
32MiB P4 PSRAM and a 12GB-class Q6A; the memory capacities were not remeasured
today. Radxa documents QCS6490's eight-core CPU and available 12GB configuration:
https://docs.radxa.com/en/dragon/q6a . The small candidate policy should be readily
CPU-feasible on Q6A; NPU acceleration is not a prerequisite. P4 deployment is
plausible but needs an integrated benchmark. Yesterday's accepted .71 snapshot
had maximum frame time 16.701ms, maximum calculation 14.863ms and ADC scan
14.013ms. Those are separate-task observations, not additive costs or steady-
state walking utilization. They do not establish spare time in every 20ms cycle.

Recommended target: keep fast joint feedback, gait execution and preferably the
small correction policy on P4 to avoid a Wi-Fi round trip; use Q6A for evaluation,
vision and development inference if useful. Placement remains proposed. No
claim that additional compute fixes insufficient mechanical leverage or power.

### 2026-10-19 — First loaded fourth-wire walking baseline

Owner approved beginning the learned-correction work and confirmed floor ready,
servo power on and supervision. Extended the existing gateway.gait_trials owner
with optional --feedback recording: independent camera/status/feedback readers,
raw feedback JSONL, per-joint CSV, firmware/calibration/leveling provenance and
sample-quality statistics. No controller behavior, gait, calibration, speed or
leveling setting was changed. Recorder duration ends capture, not robot motion.
Seven focused tests pass, including repeated samples, clock reset, calibration
revision, ambiguous boot, invalid measurements and passive read-only operation.

Read-only provenance confirmed accepted 0.8.71-p4-level-tracking, all twelve
calibrated feedback channels, leveling enabled at strength/damping 1 with saved
roll 3deg / pitch 1.5928deg. First recorded six seconds without a motion command,
then sent existing semantic Walk with dir=fwd, steps=2, gait=walk, stride=100,
rate=2. Sequence 10 received done; final sampled output_fault=0. Owner observed
forward movement and no foot dragging. Rear sag and metric travel distance were
not independently quantified; no current/energy measurement exists.

Walk recording: 12 seconds, 147 feedback responses with valid samples for every
joint, 199 distinct fresh IMU samples and 7 camera frames; no recorder errors.
Sampled excursion over the full recording, in pulse-equivalent microseconds:

| Joint | Command snapshots | Raw shaft readings | Filtered shaft readings |
| --- | ---: | ---: | ---: |
| Rear-left carrier | 602 | 559.5 | 500.8 |
| Rear-left crank | 1101 | 1015.7 | 960.0 |
| Rear-right carrier | 636 | 525.8 | 479.8 |
| Rear-right crank | 1159 | 1094.6 | 1069.1 |

These are observed ranges, not proved missed stroke, load torque or stall.
Raw versus filtered ranges demonstrate why estimator lag must be represented in
training. HTTP command snapshots do not carry exact PWM-write timestamps.
Feedback polling delivered approximately 12 responses/s with gaps up to 123.4ms;
nearest-IMU alignment offset reached 87.5ms and IMU sample gaps reached 181.2ms.
Camera receipt gaps reached 2.56s. This capture establishes a physical baseline
and transport limitations, not a synchronized 50Hz learning dataset. Exact
sample timestamps and signed pairing offsets remain in the CSV; no interpolation
or inferred contact flags are presented as measured truth.

Next required measurement improvement: capture target-write events, gait phase,
IMU and per-channel shaft timestamps locally on P4, then transfer batches without
making motion depend on network polling. Use these to identify loaded actuator
response before fitting a learned correction. Preserve this successful walking
baseline for comparison. No model has been trained or deployed in this step.
Artifacts: /tmp/ainekio-learned-gait-20261019/{stationary-01,walk-100-01}/.

### 2026-10-19 — Device-timestamped gait recording prepared (.72)

Implemented optional P4-local recording of output publications and complete
fourth-wire scans, with individual channel acquisition timestamps, raw/filtered
ADC values, estimator velocity, calibration revision, latest timestamped IMU
sample and planned gait phase. Output timestamps mark software publication after
output processing, not measured PWM edges. Planned phase does not prove contact.
No gait, leveling, calibration, speed or motion admission behavior was changed.

The explicit trace_start request allocates a 512-event PSRAM ring (216KiB with
the tested 432-byte event layout). The existing authenticated feedback endpoint
streams batches of up to 64 events. Readers use boot/session identity and a
sequence cursor; overwritten records are reported. trace_stop stops recording
only, retaining the buffer for download and reuse. Motion never waits for a
reader or depends on recording success.

Gateway --device-trace recording preserves raw batches outside the repository
and reconstructs commanded versus measured pulse-equivalent positions using
each channel's device timestamp. It does not carry targets across missing events
or convert a changed calibration revision using old curves. Recording remains
measurement infrastructure; no correction model has been trained or installed.

Validation: 13 Python gait-recorder tests, two native trace suites (including
actual runtime serialization), and the full native body-motion suite pass.
ESP-IDF builds 0.8.72-p4-gait-trace successfully; artifact is 2,916,304 bytes,
SHA256 bd2a5a1ab9813e48faea89a331879ee4522b4d4c1edbed6bd5bd6f4896d12914.
Artifact and installation tools: /tmp/ainekio-gait-trace-20261019/.
Not yet installed or measured on hardware. Scan completeness and motion-loop
overhead still require a live recording before using it as a learning dataset.

Subsequent installation and passive check: owner confirmed supported frame and
servo power off. First upload staged successfully, but the running .71 firmware
crashed before activation, clearing its in-RAM staged selection. Wi-Fi retained
boot log shows reset reason 4 and a register dump; root cause is not established.
Saved log outside the repository. Re-upload followed immediately by activation
succeeded: .72 is running in ota_0, pending_verify=false. Joint calibration,
all twelve feedback curves and saved leveling settings compare unchanged.
Self-leveling was off before and after this update; no setting was overridden.

Passive capture requested six seconds; concurrent camera completion and final
drain extended the recorded scan span to 7.14257s. Captured 358 complete scans
(49.982Hz average), 315 output publications and five camera frames, with no
skipped scan counters, ring loss, incomplete batches or recorder errors. All
twelve channels were valid. Maximum per-channel acquisition gap was 32.194ms;
the average 50Hz figure is not a claim of uniform timing. Median scan duration
was 16.195ms, maximum 23.907ms. Device-local IMU pairing offset was at most
19.919ms. The first scan had twelve unavailable IMU pairings. Ring reports
221,184 bytes. Motion-frame lifetime maximum stayed 16.541ms throughout this
passive check, and sampled output_fault stayed zero. This does not benchmark
loaded walking overhead. No motion command was submitted; recording stopped
normally without stopping or changing the robot's motion owner.
Artifacts: /tmp/ainekio-gait-trace-20261019/stationary-01/ and installation
snapshots in its parent. Loaded two-cycle trial awaits floor readiness.

Owner subsequently confirmed floor readiness. Sent the same two-cycle forward
Walk, stride=100 and rate=2, through the semantic intent owner (sequence 12).
Receipt was done. Owner reported forward movement with "no sad", understood in
the context of the question as no sag. No metric distance was supplied. Saved
606 complete scans, averaging 50.007Hz, with no skipped scans, lost records,
incomplete batches or recorder errors. All twelve feedback channels were valid;
seven camera frames were captured. No trained correction was active. Self-leveling
remained off. Motion-frame lifetime maximum remained 16.541ms and sampled
output_fault stayed zero. Scan median was 16.677ms and maximum 28.424ms; individual
channel gaps reached 32.031ms. This is average-rate capture, not a hard 20ms bound.

Both rear cranks received a 1,200us command excursion; raw measured excursions
were 1,109.6us left and 1,166.6us right over the recording. These measurements
are not interpreted as torque or a stall. An exploratory comparison restricted
to 192 planned-walking samples per joint found the lowest raw position error
when comparing against older commanded targets: 55–70ms for seven carrier/crank
joints and 95ms for the front-right crank (5ms search grid). For example,
rear-left crank RMS difference fell from 194.7us to 51.8us with a 65ms shift.
This supports investigating actuator response timing, rather than treating all
instantaneous error as a correction to add. It is not an isolated measurement
of pure delay: servo dynamics, loading, sensor calibration and output timing
remain mixed. One short trial cannot establish a general correction policy.

Loaded artifacts and exploratory analysis:
/tmp/ainekio-gait-trace-20261019/walk-100-01/.
Next modeling work should use repeated recordings and a separate evaluation
trial, retaining this successful unmodified gait as the comparison. Fourth-wire
signals now support synchronized gait analysis; gait execution itself is still
the existing controller, not a newly trained or phase-adaptive walking policy.

### 2026-10-19 — Repeated loaded trials and first learned response model

Owner requested the next step and confirmed floor readiness after the P4 had
restarted since the previous turn. Recorded two further unchanged, two-cycle
100% forward Walk commands, rate=2. Sequences 8 and 11 both returned done.
Captured 656 and 648 complete twelve-channel feedback scans, with no reported
ring loss, invalid joint samples or recorder errors. Sampled output_fault stayed
zero; lifetime motion-frame maximum stayed 16.590ms across both trials. Owner
reported no sag or stumbling, with a slight right turn of uncertain mechanical
or floor origin. Self-leveling remained off. No new gait commands, joint offsets,
calibration values or firmware were installed in this step.

Added gateway.gait_response for offline identification. Training uses recordings
walk-100-01 and walk-100-02; evaluation uses the separate walk-100-03 recording.
Six linear coefficients per joint predict change in raw measured position from
current measured position, filtered velocity, filtered/raw difference and past
targets. Prediction labels use actual future samples, at least 40ms later;
the evaluation intervals were 40.003–70.439ms. No future target or measurement
enters the input. Phase and scan-end IMU snapshots are not predictors here,
because the latter may occur after an individual joint's sample time.

Compared against a separately fitted command-history-only model, constant
position and constant filtered velocity. Both fitted predictors receive the
actual prediction interval. Fixed ridge=0.001; no search on evaluation data.
During analysis, corrected the command-only comparator to include the interval
and its interactions with target history, so sampling jitter was not an unfair
advantage for the measured-state model. This comparison was rerun on the same
evaluation recording; treat the results as exploratory, not a locked benchmark.
The measured-state model itself was not changed using the evaluation outcomes.

There were 4,410 joint-time training examples and 2,221 evaluation examples,
from short correlated trajectories, not thousands of independent walks.
Pooled position-prediction RMS error in pulse-equivalent microseconds:

| Predictor | Evaluation RMS error |
| --- | ---: |
| Learned measured-state response | 26.67us |
| Learned command-history response | 29.67us |
| Hold last measured position | 90.23us |
| Constant filtered velocity | 86.46us |

The measured-state fit improved over command history for ten of twelve joints;
both rear carriers were slightly worse (left 32.91 versus 29.66us; right 24.17
versus 23.39us). Front-right crank improved from 44.98 to 34.10us. This does not
prove a gait improvement or identify responses to new corrective commands.
The state predictor totals 72 coefficients, 288 bytes if stored as FP32;
history, features and execution costs are additional and have not been measured
on P4. It is trained on the workstation and is not deployed to either P4 or Q6A.
Nineteen focused Python gait/trace/response tests pass, including causal inputs,
variable intervals, missing scans, session/command separation, duplicate-trial
exclusion and IMU integration boundaries. Reports retain trace and metadata
hashes; weights and recordings remain outside the repository.

Owner asked whether the gyro/accelerometer were included, rather than relying
on repeated questions about sag. Both are recorded; their evidence should be
reported directly. The joint response predictor uses shaft feedback and target
history; it is not yet a learned IMU-based gait controller. An IMU does not
directly measure body height, so symmetric sinking remains unobservable from
attitude alone. Owner observation is complementary physical evidence.

Important IMU finding: in planned-walking samples of walk-100-02, all 189 unique
fresh IMU observations reported startup=true. In walk-100-03, 180 of 194 did.
The first baseline also had 189/189 startup observations. Fusion's no-magnetometer
update explicitly zeros heading during startup; fused yaw therefore cannot be
used as reliable turn measurement in these trials. Raw calibrated body-Z gyro
integration gave -15.11deg and -11.77deg over 3.813s and 3.844s in the two repeats,
consistent with a rightward turn under the saved x-forward/y-left/z-up convention.
This is approximate body-axis rotation from sampled rates, not absolute yaw or
odometry. Peak sampled acceleration norms were 19.42 and 21.56m/s^2, including
gravity; these do not by themselves establish impacts or their cause.

Source review: Slave/software/imu/imu.c restarts convergence on acquisition gaps
above its existing 20ms threshold. Actual gap-restart counters exist in the IMU
owner but are not currently included in network telemetry or trace samples.
Repeated gaps are a candidate explanation for persistent startup, not yet a
confirmed hardware diagnosis. Did not change timing thresholds, axis signs,
task priorities or calibration speculatively. Diagnose this acquisition/reset
path before using fused orientation to train body-level correction.

Artifacts: /tmp/ainekio-gait-trace-20261019/walk-100-{02,03}/,
response-model-v1.json and response-evaluation.txt in the same parent directory.

### 2026-10-19 — IMU acquisition/reset diagnosis in progress

Owner requested continuing through the next repair rather than stopping at the
model report. Built 0.8.73-p4-imu-counters, exposing the existing accepted_samples,
rejected_samples and gap_restarts counters in IMU telemetry. No estimator,
sampling, gait, task-priority or calibration behavior is changed in this
diagnostic image. Native IMU wire-telemetry and hardware-diagnostic tests pass;
ESP-IDF build passes. Owner confirmed supported frame and servo power off for
Wi-Fi installation. Artifact: 2,916,448 bytes; SHA256
9e72b4bfd548a65382cbc00f525808f770337482eeb53f95d863503bc153d6b1.
Installation and measurements are being saved outside the repository at
/tmp/ainekio-imu-diagnosis-20261019/.

The .73 upload staged, but activation was interrupted by a crash in the running
.72 image. It rebooted to .72 before selecting the successor. Decoding the saved
.72 ELF located MEPC 0x40161184 in _svfprintf_r, called by snprintf; MCAUSE=27 is
the P4 stack-protection interrupt. The retained log truncates the earlier task
name/backtrace, so the exact failing caller is not established from this dump
alone. Source showed authentication calling the 5KiB status serializer inside
the nested WebSocket receive/decode callback. Removed that nesting: welcome now
requests status atomically and the existing link task publishes it. No new
motion queue, wait, admission rule, timeout or output behavior was introduced.

Built 0.8.74-p4-status-stack with this asynchronous status publication and the
IMU counters. Five focused native IMU/protocol/gateway suites pass, and ESP-IDF
build passes. Artifact: 2,916,624 bytes, SHA256
3635cdfc4ad1a37dcb174e6db32215c7eb07ec23adf9fe0f82766ce26b886313.
Installing under the owner's still-current supported/servo-power-off approval;
artifacts in /tmp/ainekio-status-stack-20261019/. Runtime outcome pending.

.74 subsequently booted and was accepted in ota_1. Snapshot comparison confirmed
all twelve feedback calibration curves, joint calibration, and saved balance
settings were preserved. Display/camera readiness and all twelve measurements
were available. This successful update is evidence for the callback-stack repair,
not proof that every reconnect/crash path has been eliminated.

Passive .74 measurements with frame supported and servo supply off confirmed
real acquisition gaps: idle-01 accepted 3,162 samples over 18.922313s (167.1Hz)
and restarted the estimator six times. 263/297 distinct network observations
were still in startup. With camera plus local trace recording, recording-load-01
accepted 992 samples over 5.961239s (166.4Hz), with seven restarts and 96/96
network observations in startup. Network observation intervals are not the
sensor acquisition intervals; the cumulative device counters establish these
rates and restart counts. No servo movement was requested. No trace loss occurred.

The acquisition task was priority 3, equal to the multiplexed ADC scan and below
the priority-5 controller/network owners. Built .75-p4-imu-acquisition to test
priority 6 for this short, blocking sensor task; body_output remains priority 10.
No CPU affinity, gait, sensor calibration, estimator gap/freshness threshold,
ADC filtering, or motion admission behavior changes. Native acquisition and
wire-telemetry tests and ESP-IDF build pass. This is a scheduling hypothesis
being checked against the same idle/recording workloads, not yet a proven repair.
Artifact: 2,916,624 bytes; SHA256
770f7bbbb67125f6af8df811627592060f39f91b73c9025592b7f3ab83d5f524.
Artifacts: /tmp/ainekio-imu-acquisition-20261019/.

.75 staged but was not activated: the running .74 controller disconnected and
crashed before activation. It recovered into .74, with retained stack-protection
fault in _svfprintf_r/snprintf, integer "%lu" serialization. Thus .74's
callback change did not eliminate the observed OTA-time failure. The crash
occurred during automatic dashboard settings traffic while OTA was busy;
the gateway audit includes cancelled calibration/settings queries and repeated
reconnections. There was no .75 acquisition measurement.

Matched .74 disassembly showed control_task reserving 7,152 bytes, including
inlined calibration_status's JSON workspace even along an unrelated error path.
execution_failed adds 3,712 bytes, followed by the encoder, snprintf, and
_svfprintf_r (1,152 bytes by itself), exceeding the task's 12,288-byte allocation.
The retained dump again lacks the initial task/backtrace text, so the dump alone
does not prove the whole call chain; the compiled error path independently
demonstrates the stack-budget defect. Kept calibration_status as a separate
non-inlined function. .76 disassembly confirms control_task now reserves 4,512
bytes, and calibration_status's 4,432 bytes are present only when that function
is called. No task stack enlargement, weakened protection, command rejection,
or movement wait was introduced.

Built .76-p4-control-stack, including the priority-6 IMU acquisition experiment.
Five focused native suites and ESP-IDF build pass. Artifact: 2,917,248 bytes;
SHA256 bbc7e4d8fe9855b1b8402857f1a9731b7089eae961bbdceb2c75bc07c3024a11.
Asked owner to close the dashboard temporarily to avoid triggering the old
firmware's error path during installation; supported/servo-off readiness remains
current. Artifacts: /tmp/ainekio-control-stack-20261019/.

Extended offline gait recording summaries with per-boot counter deltas and
accepted acquisition rate, including stale observations; distinguish these
from dashboard polling intervals. Missing counters remain unavailable, boots
are never combined, duplicate snapshots do not count twice, and backwards
counters are reported rather than interpreted as a rate. Twenty Python
gait/trace/response tests pass. This reporting changes no robot motion behavior.

Closing the dashboard alone did not avoid the .74 crash: gateway reconnection
also requests settings. The local gateway had stopped when the owner closed the
app; restored its existing user service, then another proxied .76 attempt staged
and .74 crashed again before activation (same stack/register pattern). For
recovery, temporarily stopped that service and used the robot's existing bearer-
authenticated HTTP maintenance endpoint directly at the confirmed LAN peer
192.168.0.89. Direct .76 upload and activation both succeeded; gateway service
was restored in a finally block. No USB, partition erasure, calibration write,
or settings changes were used. Post-boot acceptance and IMU comparison pending.

.76 verified running/boot ota_0, pending_verify=false, ESP_OK. Retained log shows
the expected software restart (reason 3), with no current-boot panic. Settings
snapshot comparison confirms unchanged joint calibration, all twelve feedback
curves, balance settings, 120us hunting tolerance and settled/wake thresholds.
The supported robot's servo power remained off; outputs report ready with no
fault. This establishes successful installation and readback, not loaded gait
qualification or exhaustive error-path validation.

Passive comparison:

| Firmware/workload | Observed acquisition interval | Accepted rate | Estimator gap restarts | Fresh network observations in startup |
| --- | ---: | ---: | ---: | ---: |
| .74 idle | 18.922313s | 167.10Hz | 6 | 263/297 |
| .74 camera + trace | 5.961239s | 166.41Hz | 7 | 95/95 |
| .76 idle | 20.006028s | 203.94Hz | 4 | 166/319 |
| .76 camera + trace | 5.905979s | 204.88Hz | 1 | 47/99 |

Scheduling improved acquisition substantially, but did not eliminate the gaps.
The short sequential recordings are not a controlled long-duration benchmark.
.76 recording retained 307 scans for each of twelve calibrated joints, with no
lost trace records or recording errors. No gait or model correction was applied.
Do not claim continuous heading is repaired, or deploy learned orientation
corrections on the strength of these measurements.

Owner questioned the need for 208 samples/second. This is the inherited IMU ODR,
not a demonstrated requirement of this MG90 robot. PWM output and shaft feedback
are roughly 50Hz; gyro oversampling can support transient capture/filtering but
does not increase actuator bandwidth, torque, or ADC amplitude resolution.
The acquisition continuity and full estimator restart on >20ms gaps are distinct
issues from average sample rate. A lower ODR must be evaluated with matching
estimator configuration and measured motion, rather than chasing 208Hz as an
objective or merely relaxing the existing threshold. Rate remains unchanged.
Reviewed ST's LSM6DS3 driver for hardware acquisition options; no FIFO change
or new recovery/fallback behavior has been implemented:
https://github.com/STMicroelectronics/lsm6ds3-pid/blob/master/lsm6ds3_reg.c

### 2026-10-19 — Distinguishing the remaining IMU acquisition delays

Owner asked to continue after discussing sampling rates. Retained the existing
50Hz PWM/shaft feedback and 208Hz IMU configuration; no sampling requirement has
been established by actuator bandwidth alone. Added passive timing diagnostics
for the last raw-sample interval exceeding the estimator's existing gap threshold:
timestamp, interval, longest between-poll idle, longest status/data read, I/O
errors and no-data polls since the previous raw sample, previous sample's
processing duration, and acquisition CPU. I2C read duration includes waiting and
preemption, so it must not be labelled wire transfer time. Diagnostics observe
existing resets; they introduce no new reset, motion gate, timeout, or fallback.

The P4 telemetry serializer now accepts the full existing sensor-owner snapshot
and includes an acquisition object. Its buffer accommodates worst-case integer
counters. Native tests distinguish delayed scheduling, delayed status reads,
delayed data reads, and failed I/O while preserving old timestamps on failure.
Both focused IMU suites and ESP-IDF build pass. Built .77-p4-imu-timing:
2,918,304 bytes, SHA256
c42918f052fc34bb63e25fc3ad8f7777276d2343c00a0bae0f95f17d81fa8d7e.
Installing through the existing authenticated Wi-Fi maintenance endpoint with
the gateway running; the owner's supported/servo-power-off state is unchanged.
Artifacts: /tmp/ainekio-imu-timing-20261019/. Live measurements pending.

.77 upload/activation succeeded with the gateway running, but the larger local
IMU message buffer increased the link task's stack demand. It subsequently
restarted during status floating-point formatting. Matched ELF decoding shows
the stack-protection interrupt in allocator code reached through newlib's
_Balloc/__d2b/cvt path; retained stack contains the status JSON. The 30s gateway
watch collected no usable IMU observations. This is a diagnostic-update
regression, not evidence that the physical IMU or servo feedback failed.

Prepared .78-p4-status-workspace: allocate the existing 5KiB status JSON workspace
once with the controller's other buffers and keep it owned by the link task.
reply() already copies outgoing messages before that workspace is reused.
This removes the large nested local allocation while preserving status content,
queue behavior, existing allocation-failure handling, and stack protection.
Temporarily stopped the gateway to prevent repeated status-triggered restarts
while preparing direct authenticated Wi-Fi recovery. Servo power remains off.

.78 installed and accepted over Wi-Fi on ota_0. Image: 2,918,240 bytes,
SHA256 923e20d23a27049b040fb27ec79786cab4dc247bc151a3ab5e3578482828865a.
ELF disassembly shows telemetry's local frame reduced to 656 bytes, with the
link task at 4320 bytes. Snapshot comparison confirms all twelve feedback curves,
joint calibration, balance settings and hunting/settle/wake parameters preserved.
The current .78 boot remained continuous throughout the measurements below.
The retained previous-boot log contains a reset-path exception; do not describe
the activation restart itself as clean. No current-boot status-format crash was
observed. Artifacts and captures: /tmp/ainekio-status-workspace-20261019/.

The first 25-second stationary watch and six-second camera/trace capture had
zero estimator gap restarts (~205 accepted samples/s). The next 50-second watch
had four. New diagnostics localize these gaps to status-register I2C calls:
roughly 15–20ms, versus <2ms between-poll idle and ~0.4ms successful data reads.
One 60ms gap included two I/O errors. This does not distinguish wire delay from
driver lock waiting/preemption, and is not evidence of a required lower ODR.

The owner subsequently confirmed floor-ready with servo power on and nearby
observation. A gateway reconnect interrupted the first passive floor capture
before motion. The existing manually launched gateway owned the ports; the
service started by the recovery script was retrying against that instance.
Stopped only that duplicate service retry loop, preserving the manual gateway.
Retried the passive capture successfully, then sent two existing semantic Walk
commands (two cycles, forward, stride 100, rate 2), sequences 10 and 15. Both
returned done. Camera frames show forward scene displacement; calibrated distance
and electrical energy remain unavailable. No learned correction was applied.

| Recording | Accepted IMU rate | Gap restarts during recording | Per-joint trace scans | Lost records |
| --- | ---: | ---: | ---: | ---: |
| Walk 01, 12s | 199.45Hz | 8 | 619 | 0 |
| Walk 02, 12s | 205.60Hz | 1 | 645 | 0 |

All twelve joint channels remained valid. Whole-recording gyro startup counts
were 133/197 and 51/199 fresh network observations, respectively. The local
Walk-02 motion segment itself had no startup observations; its integrated
body-Z rate was approximately -12.74 degrees over 3.856s. This is not absolute
heading or odometry. Stationary mean body-Z rate before/between/after was
-0.341/-0.334/-0.321 degrees/s: residual bias accounts for about 1.3 degrees of
that four-second rotation, not the full turn. No gyro calibration was overwritten.

Evaluated the same response-fitting procedure trained only on the earlier
walk-100-01/02 against both new walks, without fitting to the new recordings.
Weighted joint-position prediction RMS at 40–69ms horizon: measured-state model
35.07us, command-only 45.16us, last-position 90.69us, constant filtered velocity
85.47us. Measured-state prediction improved over command-only on all twelve
joints (22.3% aggregate RMS reduction). These are exploratory holdouts, not an
independent policy trial: feedback helps predict observed joint response, but
this does not establish how changed targets affect support, distance or energy.
Report: response-evaluation-new-walks.json in the artifact directory.

Prepared .79 sensor scheduling change after examining the pinned IDF 5.5.4
driver: synchronous I2C holds bus_lock_mux across interrupt completion, and that
lock is a binary semaphore without priority inheritance. The priority-2 camera
can therefore retain it while priority-3 ADC or priority-5 network work delays
its completion and priority-6 IMU waits. This is a concrete possible priority
inversion matching the measurements, not yet a proven exclusive cause.
Camera register ioctl calls now temporarily use the existing IMU acquisition
priority, restoring camera priority on success and error. Pixel processing,
JPEG, delivery, sample rates, PWM, gait and estimator gap policy are unchanged.
The output task remains priority 10. Native tests verify normal capture plus
priority restoration after a failed exposure read; six focused suites pass.
Hardware comparison is pending. Driver and scheduler references:
https://github.com/espressif/esp-idf/blob/v5.5.4/components/esp_driver_i2c/i2c_master.c
https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/api-reference/system/freertos_idf.html

.79 ESP-IDF build passed: 2,918,336 bytes, SHA256
1e40a781260dbc248f2bb28e9df0a4b4cc9dcbd76389aefa501b4e3ab9a2d762.
Frozen binary/ELF and comparison scripts are under
/tmp/ainekio-sensor-scheduling-20261019/. Requested supported/servo-power-off
confirmation again because the owner had since enabled power for floor trials.
The retained reset-path exception's ELF prefix 5e7b5db57 matches .77, not .78.

.79 installed through authenticated Wi-Fi after the owner reconfirmed support
and servo power off. Running/boot ota_1, accepted, ESP_OK. Current boot log shows
the expected software reset reason 3. All twelve feedback calibration curves,
joint calibration and saved balance settings compare unchanged. The existing
manual gateway stayed running throughout this update.

Post-update measurements:

| Workload | Observed interval | Accepted IMU rate | New gap restarts | Trace result |
| --- | ---: | ---: | ---: | --- |
| Stationary watch (overlaps camera recording) | 49.990s | 207.04Hz | 0 | network observations only |
| Stationary camera + joint recording | 24.970s | 207.05Hz | 0 | 1264 scans/joint, 0 lost records |
| Two-cycle Walk with camera + joint recording | 11.834s | 207.03Hz | 0 | 683 scans/joint, 0 lost records |

These rows overlap and must not be added as independent durations. One 20.63ms
gap occurred at 22.489s during startup/connection, before these intervals; the
repair has not eliminated every startup or camera-reconfiguration delay. There
were no sensor I/O errors in the observed new-boot diagnostics. Current repair
applies to routine camera register access, not every format/stream ioctl.
The clean observations support the priority-inversion diagnosis for the
recurring runtime gaps, but do not establish exhaustive timing guarantees.

For the .79 Walk the owner again confirmed floor-ready and nearby. Existing
semantic two-cycle 100% forward Walk at rate 2 (sequence 12) returned done, with
no recorder errors, invalid feedback, lost trace records or new IMU startup
observations. The local motion interval contained 193 IMU observations over
3.840s, none starting/recovering. Integrated body-Z rate was approximately
-15.57 degrees, consistent with the ongoing rightward tendency; residual bias,
body-axis versus world-yaw differences and unmeasured foot slip still matter.
No calibrated travel-distance or electrical-efficiency claim is available.
The maximum network observation gaps are transport sampling gaps, not physical
IMU acquisition gaps; use device counters/timestamps to distinguish them.

On this additional whole-trial holdout, the unchanged fitting procedure trained
only on the original two walks gave 25.98us measured-state prediction RMS versus
28.66us command-only (9.35% improvement, 11/12 joints improved); last-position and
constant-velocity baselines were 91.40us and 88.37us. Saved response-evaluation.json
under the .79 artifact directory. Between the new .78 and .79 trials, feedback
improved aggregate prediction by 9–22%; these numbers measure prediction, not
walking improvement. No learned corrective policy is deployed. Next control
work must evaluate actual corrected walking, including turning/support/stride,
rather than equating lower prediction error with a better gait.


## 2026-10-19 — Independent walking heading feedback, candidate 0.8.80

Owner requested trajectory interpolation/correction during walking and selected
an independent Walking feedback switch, separate from Self-leveling. Implemented
P4-local relative-heading PI steering in the existing gait generator. The
operator's curve remains a separate reference; corrective steering never
rewrites it or repeatedly restarts its two-cycle interpolation. The quarter-cycle
feedback blend changes the body/landing trajectory, not the servo output rate.
Existing angular-distance timing, commanded stride and operator steering remain.
Forward and corrective turn share the already-approved available stroke budget.

The independent `walk_feedback` NVS value is written by the existing control
owner through `balance/op=walking`. It never writes joint/IMU calibration or
self-leveling settings. No saved selection means Off until explicitly selected.
Body Control includes its own selector/save button and live heading-error,
turn-correction and geometry-reduction readout. Feature: `walking_feedback_v1`.

Previously authorized behavior is retained: absent/recovering IMU data fades
only the corrective steering, and reacquisition establishes a new relative
heading without resetting gait phase. Geometry/representability search reduces
only the extra correction and reports that reduction. If the underlying
commanded gait itself fails, its existing failure handling remains. No new
elapsed-time stop, wait-for-joint stage, PWM easing or stall shutdown was added.
The pulse mapper checks the saved inversion/reference and timer representability;
it is not proof of collision clearance or loaded servo travel. The current
reported timer window is 3–19986us, not a measured mechanical envelope.

Verification:

- Firmware 0.8.80-p4-walking-feedback builds with pinned IDF 5.5.4. Frozen
  artifacts: `/tmp/ainekio-walking-feedback-20261019`; binary 2,921,104 bytes,
  SHA256 `10d53c54453a95f8993f4db60f9ec5c88d690d881d048ae0c4e015fcac2451aa`.
- 24 selected native gait, body, calibration, posture and gesture tests pass;
  additional core decode test passes. New tests exercise both yaw signs, wrapped
  yaw, requested curve reversal, IMU dropout/reacquisition, correction-only
  geometry reduction, all four gait families and multiple strides/directions.
- Disabled feedback produces identical nominal poses/phase. Production body
  tests run heading correction with Self-leveling off and verify independent
  disable without stopping the gait. NVS tests preserve joint settings and
  Self-leveling across saves, failed commits and reboot.
- An idealized yaw-response simulation with +/-0.065rad unwanted yaw per gait
  cycle converges with approximately -/+48.39% corrective turn. This tests
  control signs and reference handling, not real traction or physical performance.
- A separate `/tmp` replay uses the latest captured installed joint mapping;
  mapping and model checks pass. It does not establish physical travel margins.
- Gateway receipt/ownership tests and dashboard switch/navigation/gyro-joint/
  servo-feedback tests pass. Python and JSON-schema checks agree for the new
  walking operation. The broader protocol suite still has three pre-existing
  coverage failures: missing robot-settings schema types and missing motion-
  speed/robot-settings fixture coverage. HEAD and working schema show the same
  missing types; these are not walking-controller failures.

This change is gyro heading feedback only. Fourth-wire recordings and the
validated offline response predictor remain in place, but no learned corrective
policy is deployed. Model-prediction accuracy must not be confused with improved
physical walking. A paired feedback-Off/On floor trial, recording gyro, all
joint channels and camera, is still required. The first direct Wi-Fi read after
building returned no route to the robot's previous address; no upload, reboot,
setting change or physical motion was sent in this implementation turn.

Gateway readback also contains no entry for `ainekio-p4-e6ebe5`. Requested Wi-Fi
reconnection with frame supported and servo power off before activation.


### 0.8.80 Wi-Fi installation and live setting verification

Owner reconnected the robot and confirmed frame supported, servo power off.
Captured `before.json`, uploaded the frozen image using the existing gateway OTA
owner, activated it, then reloaded the single manually owned gateway with its
same arguments/environment. No duplicate service was started. P4 reports
`0.8.80-p4-walking-feedback`, running/boot `ota_0`, pending verification false,
ESP_OK. The post-boot readback preserves all twelve feedback calibration curves,
all joint settings and saved balance settings. IMU available/fresh, startup
false, calibration applied, zero gap restarts at readback; camera/display ready,
output fault zero. Servo outputs are logically armed after the existing startup
rise; physical servo supply remains off under the owner's confirmation.

Live `balance/op=walking` saves On and Off both return correct receipts and
readback while preserving Self-leveling enable/strength/damping/targets. Final
Walking feedback selection is saved Off; Self-leveling remains Off. This
verifies the switch/owner path, not walking performance. Asked owner to return
the robot to the floor with servo power on for two finite Off/On trials.


## 2026-10-19 — First physical Walking feedback Off/On pair

Owner confirmed floor ready and nearby. Issued exactly two semantic forward
Walk trials, each `steps=2, stride=100, rate=2`, with P4-local joint/IMU trace and
onboard camera recording. Self-leveling stayed Off for both. No calibration,
servo speed, geometry, or gait-range edits were made. Both commands returned
`done`; there were no recorder errors, lost trace records or new IMU gap
restarts. Data: `/tmp/ainekio-walking-feedback-20261019/walk-off-01` and
`walk-on-01`; analysis saved as `comparison.json` alongside the recordings.

| Measured outcome | Feedback Off (seq 22) | Feedback On (seq 28) |
| --- | ---: | ---: |
| Device-local walking interval | 3.820 s | 3.522 s |
| Relative quaternion yaw change | -11.42° | -1.99° |
| Integrated body-Z rotation (approximation) | -9.70° | -1.46° |
| Roll span during motion | 4.73° | 5.02° |
| Pitch span during motion | 5.21° | 4.92° |
| Local IMU observations during motion | 193 | 178 |
| Fourth-wire scans per joint, whole capture | 616 | 630 |
| Lost trace records / new IMU restarts | 0 / 0 | 0 / 0 |

Negative yaw denotes the observed rightward rotation. Relative quaternion yaw
uses unwrapped differences over the moving interval; body-Z integration is a
separate approximation because body tilt changes. Six-axis yaw still drifts.
Post-motion average body-Z rates were approximately -0.210°/s and -0.284°/s;
those residuals do not account for the roughly 9.4° difference between trials.
Network status captured an active +23.06% steering correction in the On trial,
with geometry reduction false at that observation. General status is too slow
to establish the full correction waveform or that reduction never occurred.

This one pair shows about 83% less heading drift, not established repeatability.
The trials were sequential on different floor patches and had different starting
poses; no randomized/reversed repeat or calibrated distance measurement has yet
been made. Camera frames are consistent with continued forward movement in the
On trial. They do not show feet well enough to establish dragging/contact, and
IMU tilt is not an absolute body-height or sag measurement. Asked the owner
whether the second Walk looked straighter while retaining useful progress.

Moving-interval raw shaft tracking errors remain substantial. Off/On crank RMS
errors: rear-left 186/190us, rear-right 188/182us, front-left 184/186us,
front-right 205/204us. Rear-left carrier rises from 142 to 157us; other carrier
changes are smaller. These include normal dynamic lag, electrical noise and
calibration uncertainty; they are not direct stall or torque measurements.
Heading feedback has not solved actuator tracking. Walking feedback remains
saved On after the comparison; it becomes inactive when no gait is running.


Owner's physical observation: **“Straighter, with good forward movement.”**
This supports the measured heading improvement and continued useful travel in
this pair. Retained Walking feedback On, Self-leveling Off; no additional
movement was sent after the two authorized trials.

The existing response-model fitting procedure, trained only on the original
walk-100-01/02 recordings, was evaluated against both new whole-trial holdouts:
4,238 examples; measured-state prediction RMS 26.70us versus command-history
29.04us (about 8.0% lower), with 9/12 joints improved. Hold-last-position and
constant-filtered-velocity baselines were 92.21us and 90.02us. Report saved as
`response-evaluation.json` under the .80 artifact directory. This remains
prediction evidence, not a learned motion policy or proof of reduced tracking
error. Physical heading feedback and offline actuator identification are now
separately documented results.

## 2026-10-19 — Fourth-wire learned trajectory execution, 0.8.81

Owner requested the planned learned walking system end to end, and specifically
approved preserving the current gait/gyro steering while smoothly removing only
the learned contribution when feedback or a matching model is unavailable.
Linkage-incompatible corrections may be reduced without reducing nominal gait.

Implemented a task-space iterative-learning loop, distinct from the previous
short-horizon joint-response predictor:

- P4 forward kinematics uses the existing measured fixed shaft locations,
  mirrored assembly transforms, saved shaft mapping and current four-bar branch.
- Per-leg potentiometer samples are interpolated to a common device timestamp;
  the reference is interpolated from the nominal path history at that time.
  Tracking records retain the applied residual separately from the nominal path.
- Host/Q6A training fits two harmonics per foot coordinate to
  `previous applied residual + learning fraction * (nominal - measured)`.
  Coefficients describe millimetres in body coordinates, not AI raw servo angles.
- P4 evaluates the 60 coefficients and solves the corrected material-point
  targets using its existing linkage. The underlying gait clock, Home,
  calibration, PCA9685 staggering and heading controller remain unchanged.
- Body Control adds record/download, train/load/download candidate, install,
  enable/amount, and per-leg tracking/error/status presentation. Model and settings
  persist in their own NVS namespace; an empty installation starts inactive.
- Initial profile coverage is forward Walk at its recorded stride. Command,
  calibration, geometry and leveling/heading context must match. Other commands
  continue normally with a reported reason for no learned correction.

Tests before deployment: geometry FK/IK round-trip and correction-only reduction;
exact nominal output when inactive; measured-time alignment and mirrored sensor
polarity; authenticated model upload and host training without movement;
NVS model reload; explicit unavailable-feedback/context reasons; synthetic
periodic-error fitting and iteration; selected-robot UI ownership. A synthetic
unit-response plant improved as expected; this is **not physical gait evidence**.
The first firmware build succeeded, 2,932,704 bytes, SHA256
`bea86b45bd4e2b474bde0269defcb4dbbeff196b9f7a70c02a04bd71b77cee93`.
Build/capture artifacts: `/tmp/ainekio-learned-walking-20261019`.

This design follows iterative-learning control's use of repeated tracking errors
to refine feedforward trajectories. Background: [KU Leuven learning for control](https://www.mech.kuleuven.be/en/pma/research/meco/research/learning-for-control)
and [robot path-following ILC research](https://www.dynsyslab.org/wp-content/papercite-data/pdf/ostafew-iros13.pdf).
These support the method, not a claim of demonstrated MG90 robot performance.

Remaining physical work at this entry: install/read back, measure runtime timing,
record baseline with the new tracking events, fit/upload a candidate, record a
separate candidate trial and compare it with the baseline. No new physical
improvement is claimed yet. Potentiometer/FK tracking is not measured contact,
force, body height, slip, energy efficiency or metric travelled distance.

### 0.8.81 deployment and first real tracking fit

Owner confirmed Wi-Fi connected, frame supported, servo power off. Upload
succeeded. First activation returned ESP_ERR_TIMEOUT before changing the boot
slot; after gateway reload/reconnection, a second activation succeeded. Readback:
0.8.81 in ota_1, pending_verify false, ESP_OK; all twelve shaft calibration curves
and joint mappings unchanged; IMU/camera/display available. Self-leveling remains
off and gyro walking feedback remains on. Gateway now runs the training/proxy/UI
changes (PID 3145411 at deployment).

Owner then confirmed floor ready and nearby for a four-cycle baseline and a
separately evaluated candidate. Baseline `baseline-01` completed (sequence 11),
8 camera images, 742 shaft scans per joint, 221 tracking events, no capture
errors or lost trace records. Common-time/FK valid-leg masks across tracking
events: all four 166; first three 28; first two 9; first only 2; none 16.
Unavailable entries remain unavailable, not invented contact or shaft data.

First fit (`candidate-01.json`, learning fraction 0.5) used 137/137/135/116 valid
post-entry samples for RL/RR/FL/FR, 31–32 of 32 phase bins. Baseline per-leg
reference-point RMS errors (x/y/z mm) were:

| Leg | X | Y | Z |
|---|---:|---:|---:|
| Rear left | 13.53 | 4.23 | 8.95 |
| Rear right | 13.60 | 5.37 | 7.65 |
| Front left | 12.57 | 8.10 | 8.12 |
| Front right | 15.58 | 3.90 | 5.78 |

These are inferred linkage tracking errors, including sensor/calibration/model
error; not ground-truth toe position. Runtime can execute the resulting model,
but **it has not yet been applied to the physical robot**.

Offline preview used the current installed mapping, four cycles, and heading
drift inputs of zero and +/-0.05 rad/s. Full learned amount could reach 3031 us;
at 25% amount, the no-drift preview reached 314–2871 us versus nominal 331–2870 us.
Therefore even a small global scale can extend an existing endpoint. The mapper
checks timer representability; successful IK does not establish physical servo
travel. Paused candidate deployment to ask the owner for a specific additional
behavior: reduce only learned additions that go beyond the existing Walk's
travel, preserving the base gait and reporting its existing outlying endpoint.
This is separate from the already-approved linkage-fit reduction.


### 2026-10-19 — confirmed carrier/crank travel and shoulder exception

Owner clarified that 2800 µs is the left rearward collision endpoint and
500 µs its right-side counterpart. The 500–2800 µs mechanical interval applies
to the eight carrier/crank joints; shoulders are centered with unknown physical
extrema and are explicitly excluded. Saved Home pulses are calibration
references, not new travel endpoints: do not rewrite them to alter the mapping.

The earlier .81 baseline/candidate remains historical evidence and has not been
installed as a learned model. Its preview exposed nominal outliers (331–2870 µs)
and learned targets up to 3031 µs. Owner authorized reducing only learned additions
beyond nominal travel; the confirmed collision range also requires fitting the
underlying generated poses. No additional physical trial has been sent yet.

Prepared 0.8.82-p4-learned-travel:

- Project generated carrier/crank targets into the feasible linkage workspace
  using the actual saved angle-to-pulse mapping, before PWM conversion. Optimize
  reference-point displacement at active bounds, retain shoulder targets and
  unchanged feasible frames. Startup and generated motions use the same fit.
- Preserve literal manual calibration/Home behavior and all calibration values.
  The generated-motion fit is not a general collision detector.
- Reduce learned offsets independently by leg. Model v2 records nominal pulse
  extrema by output channel; learned additions stay in that envelope while
  preserving the current steered nominal target. Physical carrier/crank bounds
  also apply to learned corrections; no physical shoulder range is invented.
- Add nominal pulses to tracking records, update host training/model import,
  report each leg's accepted correction fraction and travel reduction.

Offline four-cycle 100% straight Walk with installed calibration: all eight
carrier/crank targets fit 500–2800 µs; shoulders are unchanged. 86/284 generated
frames required adjustment; reference-point change RMS 1.214 mm, largest 9.210 mm
across all legs/frames. These are commanded model points, not measured foot
clearance or distance. The startup RR crouch carrier changes from 424 to 500 µs,
with its companion crank adjusted by the linkage solve. All 23 authored motion
clips sampled at 20 ms also fit with linkage closure in this installed mapping.

Validation: full native run initially 56/58 passed; the two failures were the
old v1 installation fixture and a timer-overflow fixture using an intentionally
impossible carrier reference. Updated the former for model v2; moved the timer
fixture to an unrestricted shoulder, preserving the original overflow assertion.
All nine focused native checks now pass, including runtime learning, calibrated
travel across gait directions/modes, independent leg correction, startup/body,
trace, OTA and calibration persistence. Python recording/training tests: 24 pass.
Authenticated training route and dashboard learning UI checks pass. ESP-IDF build
succeeded; artifact 2,936,416 bytes, SHA256
`f280760fc6dde9e9be3871b2a79027c1fb3fcb0a359eaba86dde7d4a53524e3f`.

Build/test evidence is not loaded walking qualification. Pending: Wi-Fi update,
fresh bounded-path baseline, model fit/preview, separately recorded physical
candidate comparison. Current .81 firmware remains installed at this entry.


### 2026-10-19 — .82 deployed; learned model trained and tested on the robot

Owner confirmed support and servo power off. Wi-Fi upload/activation completed;
0.8.82-p4-learned-travel booted in ota_0 and was accepted (pending_verify=false,
ESP_OK). Initial gateway reconnect lagged while the local maintenance server was
already available; authenticated boot logs and subsequent gateway status verified
successful startup, not a rollback. All twelve joint mappings and feedback curves
survived unchanged. IMU, camera and display available. Self-leveling remains off;
independent gyro walking feedback remains on.

Owner then confirmed floor-ready with power on and nearby supervision. Completed
five separately recorded four-cycle forward Walk commands, all at 100% stride,
rate 2: baseline-01 (seq15), candidate-01-half (seq22), baseline-02 (seq27),
candidate-02-half (seq36), candidate-03-full (seq40). All completed with no recorder
errors or lost trace records. All twelve feedback channels were recorded. Every
recorded carrier/crank output was inside 500–2800 µs. Shoulders were not subjected
to that mechanical interval.

Model `5cd27bdb456f100f8224421824dcf6b60ac4b70a1608ac655055ae643af9d1bc`,
context signature 155792265, was fitted from baseline-01 at learning gain 0.5,
previewed at correction amounts 0.25/0.5/1 and three simulated heading drifts,
installed through the authenticated maintenance API, and actually applied by the
P4. The host/Q6A trains; the P4 evaluates its 60 coefficients. No neural-network
pretraining or remote inference is involved. Validity is specific to this
geometry/calibration, forward Walk and 100% stride; the physical tests used rate 2.
The existing cadence remains unchanged.

Comparison uses equal weighting of phase bins available in all five recordings,
per-leg timestamp-aligned shaft-derived reference points and each trial's
unlearned nominal target. Combined RMS is the square root of mean per-leg vector
squared error. These are geometric tracking estimates, not measured foot contact,
travel distance, force or electrical efficiency.

| Setting | Trials | Reference-point RMS error | Heading change |
| --- | --- | --- | --- |
| Learned off | 2 | 17.20 mm pooled | -7.89°, -1.95° |
| Same model at 50% | 2 | 16.73 mm pooled | -4.36°, -3.58° |
| Same model at 100% | 1 | 16.83 mm | -12.26° |

The half-strength result is approximately 2.7% lower tracking error.
This is a modest initial result, not evidence of a dramatically improved gait.
Full strength did not improve it further and showed worse heading/pitch excursion,
so restored and saved learned enabled=true, amount=0.5. The model stays installed;
ordinary gyro steering remains enabled. No further movement was commanded after
that selection. The owner observed the first candidate as “Similar or better
forward movement; no dragging or sag.” Later results rely on the recorded data;
there is no separate owner observation of the full-strength trial.

Typical recorded tracking-frame intervals were approximately 22.9 ms both without
and with the model; no new gait-clock slowdown was introduced. The last trial's
IMU diagnostics showed 2885 accepted samples, zero rejected samples and zero new
gap restarts. Camera images show forward scene change, but metric distance and
energy remain unmeasured. Trial variation prevents claiming a repeatable heading
benefit from learning; existing gyro steering is the heading controller.

The record → train → range preview → install → physical comparison workflow now
has end-to-end evidence. Further model training/validation across other commands,
strides, surfaces and measured travel objectives remains separate work. Raw traces,
camera frames, model JSON and comparison scripts/results are retained outside the
repo under `/tmp/ainekio-learned-walking-20261019/travel-v2/`.

### 2026-10-19 — Longer independent training and repeated physical evaluation

At the owner's request, increased recordings from short commissioning trials to
sixteen steady walking cycles per trial, plus entry and normal Finish. The existing
finite Walk protocol accepts at most ten cycles; used its continuous Walk command
and sent its existing Finish update when recorded phase reached 18 (two entry
cycles plus sixteen steady cycles). No firmware cadence or motion limits changed.
The four evaluation walks each took approximately fourteen seconds. Gyro steering
stayed on and stationary self-leveling stayed off throughout.

The first long training capture lost 517 trace events during the idle tail,
several seconds after walking completed. Its entire walking segment was intact.
Preserved the original capture and exported the complete, consecutive batch prefix
through the last walking tracking batch as `training-window.jsonl`, with separate
hash/provenance evidence. Do not describe the original capture as loss-free.
Added optional host recorder `--until-done` support to finish recording on the
submitted command's matching terminal receipt. It does not send Stop or change
robot motion; another command's receipt does not end recording. Thirteen targeted
Python checks passed. All four subsequent evaluation captures have no lost trace
records or recorder errors. No firmware update was required for this recorder change.

Trained model
`6780d884c6ced0ab5267d9fa3589c176e6ba283a2b234810c9d805210296a17b`
only on the long training window, using 525/521/511/436 aligned observations for
RL/RR/FL/FR. Context signature remains 155792265. The held-out baseline predicts
roughly 92% of the recurring squared tracking-error pattern from the fitted model;
this is an offline prediction metric, not a 92% physical walking improvement.
All three offline heading preview cases passed at correction amount 0.5. Installed
this model and kept it unchanged throughout evaluation; no evaluation recording
was used to train it.

| Trial, in execution order | Learning | Estimated reference-point RMS error | Gyro heading change | Pitch span | Owner-reported travel |
| --- | --- | --- | --- | --- | --- |
| Evaluation baseline 1, seq11 | Off | 17.26 mm | -7.88° | 5.76° | Approximately 18 inches |
| Evaluation candidate 1, seq18 | 50% | 16.72 mm | -3.11° | 7.05° | Approximately 21 inches; no dragging or sag |
| Evaluation baseline 2, seq25 | Off | 17.21 mm | -3.10° | 6.48° | Approximately 21.5 inches |
| Evaluation candidate 2, seq32 | 50% | 16.77 mm | -4.23° | 7.49° | Approximately 30.5 inches; no sag |

Comparison equally weights shared phase bins and legs. Pooled estimated tracking
error changes from 17.23 mm to 16.75 mm, a 2.84% reduction. Both learned runs have
greater pitch excursion than both baselines. The repeat baseline already exceeds
the first learned run's distance: the initial 18-to-21-inch comparison does not
establish a repeatable travel improvement. Tape distances are owner observations
from the requested common starting position/reference point, not camera-derived
metric measurements. Contact, torque, energy consumption and absolute body height
remain unmeasured.

All twelve feedback channels recorded in each evaluation. IMU accepted sample
deltas were 2897/2892/3040/2953, with zero rejected samples and zero new gap restarts.
All recorded carrier/crank outputs stayed within 500–2800 µs; shoulder calibration
and travel remain unchanged. Final run completed normally and recorded 729 valid
samples per joint without invalid samples. Final saved setting: longer-run model
enabled at 50%, gyro steering on, self-leveling off. Learning's post-Finish status
reports `untrained_command`; corrections were recorded during Walk itself.

Raw traces, camera frames, model, operator observations and comparison results
remain outside the repository under the existing temporary experiment directory.
The recording/training/install/evaluation system works end to end. These tests
support a modest tracking improvement for this particular forward Walk. With the
final owner report included, average travel is 19.75 inches for the two baselines
and 25.75 inches for the two learned trials (30.4% greater observed mean). The
individual distances vary substantially, and two trials per setting do not
establish a general distance, stability or electrical-efficiency improvement.
The final report explicitly confirms no sag; it does not separately confirm
absence of dragging.

### 2026-10-19 — Autonomous evaluation gap identified after the longer trials

The owner requested that the robot measure progress, detect sag, correct its
heading and return to the start itself instead of repeatedly relying on manual
observations and resets. This is the intended evaluation workflow; existing
supervised trials do not yet implement that autonomy.

Source and read-only runtime audit:

- `gait_trials.py` still reports `distance_m: None`; the learning objective is
  timestamp-aligned linkage tracking, not measured forward progress.
- `ground_plane.py` already implements calibrated planar camera tracking and
  position/heading relative to a floor reference. It has no movement authority.
  The Environment Bridge exposes its measurements, but the gait recorder does
  not consume them. Runtime calibration status returned `calibration: null`,
  zero calibration samples, and unavailable measurement with reason
  `Measured calibration and floor reference required`.
- Gyro walking feedback is enabled. Self-leveling is disabled. The longer-run
  learned model remains enabled at 50%. No motion or settings change was made
  during this audit.
- Fourth-wire observations can support a linkage-extension/support-height
  estimate combined with body orientation and support-phase information. Shaft
  positions do not themselves establish foot contact or a fixed ground plane;
  gyro tilt alone cannot detect a level body sinking vertically.

Next integration should use the existing camera measurement owner for measured
travel and starting-pose error, the existing semantic walking/steering owners for
return, and phase-aware joint/IMU evidence for support loss. Camera calibration
and camera-to-body geometry must be measured before assigning metric meaning to
image movement. Reversing the outbound number of cycles is not a measured return
to the same pose. No autonomous return controller or sag classifier was added or
claimed operational by this audit. Raw observations remain outside the repository.

### 2026-10-19 — Motion-aware body notifications installed

The owner requested correction of rapid-movement reactions during commanded
locomotion and tipped reactions during intentionally tilted motions. Body Control
owns classification; the P4 continues supplying its existing IMU measurements.
Added timestamped execution context after successful output writes, with command,
entry/motion/hold phase and the authored expected body vertical. Context lookup
uses the IMU sample time so a later command cannot explain an earlier measurement.
Named-motion references use the same retimed source clock as motion playback,
including entry, reverse grounded recovery and held final poses.

Rapid-movement threshold crossings during executing Walk/Run/Crawl/Crab are
classified without requesting a rapid-movement reaction. They do not consume the
notification cooldown or produce a delayed reaction when locomotion finishes.
Tipped detection remains active, measuring deviation from the intended body
vertical when the calibrated IMU and authored reference are available. Manual
PWM/Freestyle without an authored chassis reference and older firmware retain
absolute-tilt behavior. Meaningful events carry this context through the existing
Environment Bridge. Existing thresholds remain editable; no command restrictions,
automatic stops, extra sensor tasks or MetaHuman prompt changes were introduced.

Validation: 17 Python event/bridge checks, three dashboard checks and six focused
native suites passed. Compiling the previous and updated clip compilers against
the same recordings produced identical values in all 115 joint-motion arrays
(23 clips, five arrays each). The added orientation tracks contain 4,446 knots,
62,244 bytes of constant values/knots before tables and alignment, stored in flash.
Motion trajectories, speed limits, IMU sampling and telemetry cadence are unchanged
by this notification change.

With the owner's explicit supported-frame/servo-power-disconnected installation
approval, restarted Body Control preserving its runtime arguments/environment and
installed only the application over its existing OTA route. Running/boot slot is
ota_1, version `0.8.83-p4-motion-events`, pending verification false, ESP_OK.
Application: 3,009,040 bytes; SHA-256
`3d1b89fbbd7437b03704f2f908c83597e064245d93a6cb722ccbe0cf0c1d956e`.

The robot reconnected and reported display, camera, microphone, speaker and wake
readiness. Twelve passive live samples carried calibrated, fresh IMU measurements
and unit expected-vertical vectors with context timestamps no later than the
measurement; held Stand reported upright. IMU accepted-sample rate during this
short check was 206.99 Hz, with zero rejected samples and zero gap restarts.
Before/after snapshots confirmed unchanged saved joint calibration, feedback
curves/settings, balance settings, network settings, camera settings and body-event
settings. Live pulses and sensor readings naturally differ after startup. Private
artifacts and deployment evidence remain under
`/tmp/ainekio-body-notifications-20261019`, outside Git. No additional powered gait
or tipping experiment was performed; physical false-event suppression under load
still needs owner testing. These passive checks do not measure incremental CPU
cost or qualify every motion on the assembled robot.

### 2026-10-19 — Reaction-face landmarks for repeat notifications

The owner requested suppression of further shake/tip events while the event's
reaction expression remains active, using the display lifecycle rather than body
motion completion. The existing MetaHuman initial event branch now generates a
`be_` token within the existing 32-character display-token format. Explicit token
handoff/release retains its identity; ordinary and completion replacement faces
retain ordinary tokens. No model prompt or graph ordering was changed here.

P4 IMU telemetry now carries the active selection token. The existing display
owner's release, replacement and expiry are authoritative; there is no second
host timer. A temporary listening/speech overlay retains the selection. Body
Control continues classifying episodes while suppressing new shake/tip emissions
for this token, so an already-observed shake does not reappear when the face ends.
New crossings after the measurements clear can report again. The existing
rapid-event cooldown still applies before the face arrives. Wake events and
command admission are unaffected. This is distinct from the previous execution
context used to recognize normal locomotion and intentional tilted poses.

Validation passed 21 Python event/bridge tests, three dashboard tests, two native
face/telemetry suites, 19 MetaHuman expression/fast-event tests and Core typecheck.
The full P4 application and a separate MetaHuman Site build succeeded; the compiled
Site runtime matched its source and validated the installed workflow definitions.
P4 candidate `0.8.85-p4-event-face`: 3,008,992 bytes, SHA-256
`f1a57e0cb507dfc4d4446a7260485d2ddaee49c2327dad76a1c5421b869a8e83`.
Private firmware/install artifacts are under `/tmp/ainekio-event-face-20261019`;
the Site build is under MetaHuman's ignored `out/event-face-20261019/site`.
Deployment and a physical shake/face-reset test remain pending. Body Control was
stopped at the final preparation check, with separate firmware installation work
recorded elsewhere in this journal; this task did not interfere with that work.

### 2026-10-19 — Connect trial measurements and support a measured paper reference

Implemented the next measurement integration after the owner requested autonomous
trial assessment and resets. Body Control now includes the existing camera
owner's position measurement in each robot's status. The gait recorder retains
that measurement, captures a pre-command status, and reports per-reference signed
forward/lateral displacement, heading change and starting-body-Z change. Repeated
camera frames are not counted as additional observations. Missing calibration,
unavailable observations and changed references remain explicit; they do not
become zero movement. Reported distance is endpoint displacement, not path length.
The camera owner now publishes its already-computed relative Z component.

Added phase-binned shaft-derived extension-shortfall assessment. The P4 trace now
includes the planner's grounded flag at the same historical target time as each
measured leg reference, plus calibrated-IMU status. Support labels are unknown
inside a history interval that crosses liftoff/touchdown. Source/model leg order
is mapped explicitly. The host projects extension deficit onto gravity using
bracketing calibrated IMU samples within the same command and continuous trace
segment. Swing samples do not become support-loss evidence. These remain modeled
leg-reference estimates, not measured foot contact or a confirmed sag classifier.
No new actuator writer, slowdown, timeout or automatic motion response was added.

The owner has no printer/checkerboard and has placed 9 × 12 inch sheets beside the
track, reporting 12-inch intervals. Saved sheet dimensions are 0.2286 × 0.3048 m;
whether the interval refers to matching edges or an empty gap is not yet known.
Added manual measured-rectangle capture to the existing camera calibration owner
and UI. Frozen image selection keeps the exact frame identity; users select four
corners in consistent order with measured width/height. Multiple tilted views fit
intrinsics; an actual floor reference and measured camera-to-body transform are
still required. Sparse manual points need validation against the tape. This uses
the same planar point-correspondence method documented by OpenCV:
https://docs.opencv.org/5.0/main_modules/calib.html .

Validation: 29 focused camera/recorder/assessment tests, all 38 dashboard HTTP
tests, three native trace/learning suites and four dashboard JS test scripts
passed. Synthetic tests cover known translation, camera lever arm and vertical
movement, manual-corner intrinsic recovery, fixed-frame selection during live
updates, phase-boundary ambiguity, unknown calibration, trace gaps and quaternion
projection. Native tests verify the source/model support-leg permutation. No
synthetic result is claimed as physical calibration.

Reloaded Body Control preserving its runtime settings. Live camera availability
reaches the recorder; a one-second passive capture reported missing calibration
and stale camera observations explicitly, with no errors, movement commands or
invented distance. A fresh camera image showed carpet/furniture without clearly
identifiable sheet corners, so physical calibration is still pending. No
autonomous return-to-start controller is implemented or active yet.

Built 0.8.84 with the exact sdkconfig from the installed .83 build. The initial
Wi-Fi upload was staged after owner support/power-off confirmation, but the
installed .83 crashed before activation and rebooted into .83. Retained Wi-Fi
panic log decodes to newlib floating-point diagnostic formatting. The old control
task's compiled static frame was 4592 bytes, before nested 3712-byte failure reply
and diagnostics/formatting frames. Moved the single-consumer command workspace to
startup allocation, reducing the compiled control-task frame to 1584 bytes while
preserving queue ownership and the existing allocation-failure behavior. No task
stack enlargement or motion restriction was introduced. The repaired image builds
successfully: 3,008,384 bytes, SHA256
`cc6aa0712fff0e3df7c8e2981efba3544b0431d38564e5b5434ddb1dcb3bc17c`.
Closing the dashboard tab was insufficient: the gateway audit still showed
another client issuing face and speech requests. A second .83 upload crashed
through the same diagnostic formatter. With the gateway stopped, direct Wi-Fi
upload stayed staged but activation reported `ESP_ERR_TIMEOUT`; the precise
internal operation causing that timeout was not established. Temporarily running
the existing gateway on its LAN address with dashboard port 8792 kept the robot
connected while excluding the observed localhost background clients. Authenticated
Wi-Fi upload and activation then succeeded. The robot reports
`0.8.84-p4-gait-observation`, running/boot slot `ota_0`, state `accepted`,
`pending_verify:false`, and `ESP_OK`. Normal gateway addresses were restored;
post-update measurement/calibration verification is complete. Saved joint
references, all twelve feedback calibrations, balance configuration and robot
settings match the pre-upload capture (only reply sequences, readiness and current
commanded pulse values differ). The learned model
`6780d884c6ced0ab5267d9fa3589c176e6ba283a2b234810c9d805210296a17b`
remains enabled at 50%.

A five-second stationary recorder run captured 341 device sample events and 299
output publications, all twelve feedback channels, zero reported lost records,
zero incomplete batches, and no recorder errors. All 341 sample events carry the
new `calibration_applied:true` IMU field. Acquisition counters advanced by 1031
accepted samples with zero rejected samples or gap restarts. No motion command
was submitted by the recorder. There are no walking tracking events in this
stationary test, so live support-phase serialization still needs a walking trial.
The boot ID remained unchanged during verification; logs also show one control
transport write failure/reconnection, not a reboot or proof of flawless transport.

Five fresh camera frames now clearly show the tape and paper references. Owner
confirmed the 12-inch edges run parallel to the tape, with 9 inches across it.
Sheet-gap semantics remain unknown and are not used. Camera distance remains
unavailable until physical calibration and floor reference are established. Asked
for a short, servo-power-off handheld sequence showing the nearest left sheet at
different camera angles; this is calibration setup, not an autonomous return test.
Private build, calibration-view and runtime evidence is under
`/tmp/ainekio-gait-observation-20261019`, outside version control.

### 2026-10-19 — First paper-target camera recordings

With the owner ready for camera calibration, recorded two passive sequences
without submitting any robot motion commands. The 25-second and 45-second
recordings retained 13 and 23 camera frames respectively, with no recorder errors.
The first sequence includes two close views with a complete sheet; most other
frames are floor-level views, and the close views have similar perspective.
The second sequence begins at floor level, then includes varied handheld angles
late in the recording; several are motion-blurred, while the final view shows a
complete sheet. The initial assessment based on early frames missed this later
motion and was corrected after inspecting the later frames and IMU spans.
Some received frames are 1280×960
while ordinary preview frames are 640×480; they must not be mixed blindly in a
single intrinsic fit. No camera calibration or floor-distance result was saved
from these observations pending corner quality and fit assessment. Switched the operator interaction
to held poses acknowledged before capture, avoiding timed movement prompts.
Recordings: `handheld-124058` and `handheld-124203` under the private evidence
directory above. The sheets measure 0.2286 m across the track by 0.3048 m along it.

### 2026-10-19 — Tape reference and robot-requested measurement photographs

Owner rejected repeated manual repositioning/calibration requests and directed
use of the robot's camera, IMU, joint feedback and semantic motion controls under
the existing authorization. The handheld procedure is discontinued. Last explicit
servo-supply state remains off; no physical movement was commanded in this work.

Reviewed the four long evaluation recordings: only 2–4 camera images were retained
per trial, with blurred end views. A received preview is not a guaranteed final
post-walk photograph. Added exact `cam_meta`/binary-counter association in the
gateway, preserving epoch and request sequence through camera HTTP responses.
The dashboard retains the latest requested still separately from previews.
`capture_snapshot` now retrieves its own request and saves bracketing status;
it does not issue gait or servo commands. Existing preview access is retained.
The host gateway was reloaded without changing firmware. Three live captures
matched request sequences 6, 7 and 9 to camera counters 5, 7 and 9 in epoch 17.
Their camera view has a close foreground object obscuring the tape; no distance
was invented from these frames.

Added a perspective ruler-pose calculation using identified inch marks and an
explicit camera matrix. Synthetic projection tests recover the known motion
under camera rotation and height change. An offline check on earlier clear,
stationary images used the visible 3/4/5 numeral centres as local ruler anchors,
SIFT matches within the tape region and a provisional centred-camera estimate
derived from the already-recorded paper views. Four frames had 72–80 inlier
matches and an estimated along-tape position spread of 0.03993 inch (1.014 mm).
This is repeatability under a provisional model, not calibrated accuracy or a
new walking-distance measurement. Absolute foot-number ambiguity, numeral-centre
offset, lens uncertainty and camera exposure timing remain unresolved. No
provisional intrinsics were saved to the robot or the live ground-plane owner.

Validation: 52 dashboard, snapshot, recording, ruler geometry and metadata tests
passed; `git diff --check` passed. Evidence, photos and the stationary tape result
are under `/tmp/ainekio-tape-measure-20261019`, outside version control.
Automatic tape reading through a complete walk and autonomous return remain
unfinished; the user-measured 18/21/21.5/30.5-inch trial results remain separately
labelled as operator observations.

### 2026-10-19 — Direct operator trials and removal of unused experiment code

Owner clarified that testing and returning to the starting area should use the
existing semantic controls, with the agent selecting each action from camera,
IMU and joint feedback. Do not add a dedicated autonomous test/reset behavior or
ask the owner to reposition the robot between ordinary trials.

Woke the controller from Doze using Idle. After a subsequent controller reboot,
Stand completed (epoch 18, sequence 10), with measured movement on all twelve
joint-feedback channels. A matching requested photograph showed the tape and
paper rows clearly. Forward Walk at full stride/rate 2 for two cycles completed
(sequence 14), followed by a separately issued backward two-cycle Walk
(sequence 18). Both recordings have zero recorder errors and zero reported lost
trace records; gyro acquisition reported zero gap restarts during each run.
The forward image shows a rightward deviation. Planned-support extension
shortfall projected onto gravity averaged about 6.27/3.21/3.46/1.40 mm for
RL/RR/FL/FR in the forward recording. These are model-derived leg tracking
shortfalls, not a direct measurement of body sag or floor contact. Backward
completion is verified; exact return to the starting location is not yet proven.
Private evidence: /tmp/ainekio-live-gait-20261019.

Cleanup audit found the provisional ruler solver had no runtime consumer.
Removed Master/gateway/tape_measure.py, its dedicated unit test and current README
entry; the historical research entry above remains as a record, not an active
capability claim. Retained requested-snapshot identity because it fixes receipt
of the wrong camera image, and retained the recorder/trainer actually used by
learned walking. No dedicated return-to-start behavior was implemented or
installed. Temporary operating scripts and recordings remain outside the repo;
no matching trial script was running at cleanup inspection. Firmware was not
changed or flashed by this cleanup. Twenty-four recorder, trace, learned-model
and assessment tests passed after removal.

### 2026-10-19 — Firmware diagnostic cleanup; camera session owns deployment

Owner requested removal of leftover experiment instrumentation. Removed the
extra IMU poll/scheduling/bus timing probes and their wire fields, including the
associated unused test shim. Kept sensor timestamps, attitude, calibration,
accepted/rejected sample counts, estimator gap-restart counts and existing I/O
health counts. Kept the scheduling fix and functional learned gait/feedback.

The device trace buffer now detaches under the existing producer lock and is
freed outside that lock once recording is stopped and its final response has
been successfully sent. Partial downloads and failed transfers retain data for
retry. Stopping/reading affects only recording, never robot movement. The next
recording allocates again; ordinary boot allocates no trace buffer. Tests cover
failed-transfer retention, multi-batch retention, final release, inactive
producers, empty reads after release and restart. This removes the previous
216 KiB retention until reboot after a completed recording.

Four focused native tests passed (trace HTTP/lifecycle, learned correction,
IMU wire telemetry and IMU hardware/calibration), plus 24 host recorder, trace,
learning and assessment tests. Full P4 firmware build passed, including the
current camera changes. No new limits, motion delays or special test/reset
behavior were added. Artifact and exact SHA-256 are recorded in
/tmp/ainekio-firmware-cleanup-20261019/artifact.json; application image is in the
same directory. Owner explicitly assigned the combined Wi-Fi deployment to
the camera session. This session has NOT flashed this cleanup or verified it
on the running robot. Preserve the source changes when that session rebuilds.

Removed the completed temporary live-gait-check.py, install-camera-measurement.py
and tape-camera.py helpers from /tmp after confirming none was running.
Recorded trial evidence, model artifacts and build receipts are retained.

### 2026-10-19 — Training-mode scope and resumed physical baseline survey

Owner clarified the intended outcome: an explicit real-world training mode,
initially on this workstation and eventually on Q6A, which improves walking
from actual outcomes and saves a compact model for P4 execution. Normal walking
uses the saved model and live feedback without ongoing training. A measured
plateau is not proof of a global optimum. Current Walk is a starting baseline;
the final foot paths and coordination may differ substantially. Preserve live
steering and compatibility with self-leveling. Do not replace the existing
command owners with a dedicated test/reset behavior.

The existing 60-coefficient model is periodic task-space iterative learning,
not reinforcement learning or a sensor-conditioned walking policy. Training
minimizes nominal-versus-measured reference-point error. Its inputs during
execution are phase and correction amount; feedback availability determines
eligibility, but measured joint error and attitude are not policy features.
Its recorded nominal pulse envelope also prevents it exploring arbitrary new
base trajectories. Calling repeated fits of this model optimal gait learning
would be incorrect. Existing Walk was authored and checked against a geometry
model, not trained by reinforcement learning in simulation.

Current execution ordering is heading controller -> moving balance controller
-> calibrated linkage fit -> periodic learned correction -> output. Fourth-wire
actuator-aware balance currently applies to stationary holding; moving balance
uses gyro-driven trajectory-relative correction. Sensor-conditioned learning
and joint-feedback coordination during walking remain work, not demonstrated
capabilities. IMU tilt cannot by itself measure common-mode body-height loss;
shaft-derived extension is a geometric estimate, not measured contact or load.

Resumed using existing semantic commands and private recordings in
`/tmp/ainekio-adaptive-20261019`. Servo supply was explicitly confirmed on.
Corrected an operator readout mistake: multiplexer C0-C3 are unused; servo
feedback occupies C4-C15. Stand completed at epoch 2, sequence 12, restoring
armed outputs with fault 0. Ten full-stride forward cycles completed at
sequence 16, then six backward cycles at sequence 20 returned toward the start
without asking the owner to move the robot. Both recordings report no recorder
errors. The forward run recorded no new IMU gap restart and approximately
-10.31 degrees integrated body-Z rotation, with 5.01/5.06 degree roll/pitch
spans. Photographs establish forward and reverse progress, but metric camera
distance remains unavailable; do not report optical motion as calibrated
travel or motor tracking as electrical efficiency.

Before this survey, comparing `adaptive-baseline-01` and
`adaptive-candidate-01` gave phase-weighted reference RMS 17.288 and 17.446 mm
respectively. Candidate pitch span was about 19.09 degrees versus 5.50 degrees;
its starting photograph also showed the tape housing in front after an
overshot return, so this was not a controlled matched-start comparison. It is
not accepted as an improvement. Learned correction is currently disabled for
the baseline survey; its installed model is retained. The live trace-release
check in `trace-release-check.json` reported storage_bytes 0 after final
download, verifying buffer release on the running firmware.

### 2026-10-19 — Broader baseline survey and live leveling compatibility

Completed forward Walk at 50%, 75% and 100% stride, backward Walk, left/right
turning, and repeated 100% forward Walk with saved self-leveling enabled. All
used existing semantic commands, rate 2, and gyro steering enabled. This is
baseline characterization, not an RL-trained replacement gait or an optimum.
Twelve completed survey recordings (including recovery Stand) contain 48,600
valid reconstructed joint observations. Private evidence and the consolidated
report are in `/tmp/ainekio-adaptive-20261019/survey-summary.json`.

| Trial | Requested cycles | Approx. integrated body-Z rotation | Roll span | Pitch span |
| --- | ---: | ---: | ---: | ---: |
| Forward 100%, leveling off | 10 | -10.31 deg | 5.01 deg | 5.06 deg |
| Forward 75%, leveling off | 10 | -1.01 deg | 4.62 deg | 3.66 deg |
| Forward 50%, leveling off | 10 | -0.91 deg | 4.36 deg | 3.23 deg |
| Left turn 100%, leveling off | 10 | +10.18 deg | 5.01 deg | 5.33 deg |
| Right turn 100%, leveling off | 10 | -20.64 deg | See raw report | See raw report |
| Forward 100%, leveling on | 10 | -0.31 deg | 4.34 deg | 4.38 deg |
| Forward 100%, leveling on, repeat | 10 | -1.09 deg | 4.94 deg | 5.35 deg |

Camera views show useful forward progress at full stride and less progress at
shorter stride. These are visual observations, not measured inches/metres.
Starting poses/floor locations were not identical across all runs; do not claim
causal improvement from this table alone. The first leveling-on run explicitly
reported simultaneous active leveling and heading correction, without reduced
level correction in the sampled telemetry. Its photographs also show lateral
offset from the tape: low gyro yaw does not prove straight ground translation.
Both leveling-on forward recordings reported zero new IMU gaps/rejections.

A controller-link interruption changed connection epoch 2 to 4 while preparing
the first right-turn recording. That attempt failed with HTTP 409 before motion
submission and is excluded. P4 uptime continued; outputs were released by the
existing connection-loss behavior. Owner confirmed no other session was
changing the connection. Stand restored outputs; the subsequent right-turn and
leveling trials completed. This event is not labelled a motor stall or gait
failure. No new shutdown, timeout or connection behavior was introduced.

Trained the existing offline joint-response predictor on forward 100%, forward
50%, backward 100%, and ten-cycle left-turn recordings, holding forward 75%
out for evaluation. It predicts approximately 40-68 ms ahead. Across joints,
measured-state RMSE was 28.68 us versus command-history-only 28.42 us and
hold-last-position 94.19 us. Thus this evaluation does not establish an advantage
from the measured-state features over command history. Saved privately as
`survey-response-model.json`; it is not installed and is not a walking policy or
a validated predictor of untried commands.

End state: self-leveling and walking heading feedback enabled, saved periodic
learned correction disabled, outputs armed with fault 0. Existing tuning values
were preserved (strength 1, damping 1, roll offset 3 deg, pitch offset 1.5928 deg).
No firmware upload or product-code changes were made for this survey. The
required next implementation is a sensor-conditioned gait policy and physical
performance optimizer capable of changing the base trajectory/coordination;
repeating nominal-tracking fits alone cannot deliver that request. Metric visual
progress remains unavailable in the current measurement owner, and low tilt or
small shaft error must not silently substitute for successful locomotion.

### 2026-10-19 — Active goal: sensor-conditioned policy and explicit host search

The end-to-end learned walking goal is active. The preceding acknowledgement
turn made no implementation progress; this turn changed the production policy
path, host training owner and tests. No robot motion, firmware activation or
gateway restart was performed. The current physical result is still the
baseline survey above, not a validation of the new policy.

Implemented `gait_learning_v3` alongside the existing version 2 format. It keeps
the 60 periodic task-space coefficients and adds 96 sensor coefficients. Each
leg's three correction axes can now depend on eight live inputs: aligned
shaft-derived reference-point error xyz / 10 mm, calibrated roll/pitch target
error / 0.1 rad, and body angular rate xyz in rad/s. Total float weights are
624 bytes; this excludes runtime history/telemetry. The saved level reference
uses the balance owner's existing axis signs; no IMU reversal was changed.
All output still goes through the existing linkage solver, calibrated mapping,
approved carrier/crank travel and learned-addition fit. The gait clock and PWM
owner are unchanged. The existing phase-only NVS blob loads with zero sensor
weights, preserving its enable setting and coefficients.

The sensor-policy context also identifies IMU mounting/bias and saved level
reference. Unusable joint or IMU inputs fade the last usable learned sensor
response with the existing contribution blend; underlying gait/heading/balance
owners continue. Version 2 models retain their previous sensor requirements.
The existing device trace records exact decision-time features, phase, IMU
timestamp, context and applied correction separately from the older delayed
tracking observations. This avoids reconstructing policy inputs using future
measurements. Recorder metadata now includes installed learning settings/model.
Body Control accepts version 3 candidate files and identifies sensor versus
phase-only models in its readout.

Added the explicit host `gateway.gait_training` owner: resumable start/propose/
advance/export operations, paired policy perturbations, repeated comparison
blocks, and a separate untested search centre versus best evaluated incumbent.
Only the evaluated incumbent is exported. Search changes periodic and sensor
weights; objective weights and exploration scales are explicit inputs. The
objective uses measured forward speed, calibrated body tilt and shaft-derived
tracking error relative to the **applied** target, including learned offsets.
It does not penalize departure from the old nominal foot path merely for being
different. No electrical efficiency/force measurement is claimed. This owner
has no motion/reset/return commands and adds no firmware test behavior. Normal
P4 execution does not train continuously.

Method reference: [Mania, Guy and Recht, Simple random search provides a
competitive approach to reinforcement learning](https://arxiv.org/abs/1803.07055).
This supplies the policy-parameter search approach, not evidence that this robot
is trained or optimal. Repeated-run differences and standard errors remain in
the training result. A missing camera distance cannot become a zero or a
tracking-only reward. Existing survey recordings lack the new decision-time
features and metric progress, so they have not been relabelled as successful
sensor-policy training.

Validation completed:

- 11 native tests passed: body execution with/without shaft feedback, motion,
  locomotion, Run, balance, heading correction, learned policy and trace owners.
- 21 host learning/search/recorder tests passed, including fixed-phase sensor
  response, reproducible paired proposals, matched repeated comparisons,
  missing-progress handling and exporting evaluated rather than proposed weights.
- 49 gateway/trace/assessment tests passed. The sandbox initially denied local
  test-server sockets; the authorized rerun outside the sandbox passed.
- Dashboard learning test passed. P4 ESP-IDF build passed; candidate binary is
  0x2df590 bytes with 64% of the OTA slot free. Build log remains private at
  `/tmp/ainekio-policy-build.log`. Firmware version/deployment ownership was not
  changed; this build is not an installed release.

Remaining requirements are explicit: integrate learned base gait phase/duty/
landing parameters with the existing contact planner; broaden trained command
contexts while preserving operator steering and leveling; connect the explicit
host search to physical trial orchestration using existing semantic commands;
obtain usable metric visual progress; then deploy and demonstrate repeatable
physical improvement and save the best demonstrated model. Version 3 currently
still inherits forward/recorded-stride eligibility and the recorded learned-
addition envelope. These software tests do not finish the walking goal.


## 2026-10-19 — Learned base gait profile and live reconnection

Extended the compact model to version 4 so training can change the underlying
Walk rather than only add offsets to an unchanged foot path. Its 33 profile
parameters adjust duty fraction, sweep, per-leg phase, lift and landing, and
body-position harmonics. Another 48 weights condition the response on operator
forward/turn/lateral/stride commands. Together with the periodic and measured
sensor terms, the model is 237 float32 values (948 bytes), excluding runtime
history and telemetry. This is a model interface and search implementation;
no new physically trained profile has been demonstrated yet.

A new Walk selects the saved profile before its first frame. Grounded anchors
remain committed; mid-command model changes report that the profile applies to
the next Walk. Existing steering/heading, balance and Walk/Run interpolation
remain in their owners. The profile blends out during Run, so this change does
not claim to train Run. Version 4 records operator inputs, context and the
executed profile hash; evaluation verifies the recorded profile. Version 2/3
models migrate with zero appended fields and retain their previous eligibility.
The joint calibration, IMU signs, nominal servo speed and owner-approved travel
remain unchanged. Sensor-dependent additions retain the approved fade behavior.

Validation: 11 native motion/runtime/recording tests passed; an additional
profile test covers curved Walk, transition into Run and back, heading feedback,
and balance application. Fourteen host policy/search tests passed. Offline
preview using the current saved calibration completed forward/backward/left/
right at 50 and 100 percent with a zero-addition profile. The preview now accepts
version 4 coefficients and specified sensor inputs; it does not simulate loaded
servo response. The ESP-IDF build passed, 0x2e1300 bytes, 64 percent OTA slot free.
The release label is 0.8.90-p4-learned-gait and includes the existing face-layer
work from 0.8.89. Deployment outcome is recorded separately below.

After the owner powered on, the live robot reported 0.8.89, calibrated readable
feedback on all twelve joints, and fresh IMU samples without acquisition errors.
The servo output release matched a logged control-connection loss and reconnect,
not an I2C transfer failure. Camera imagery showed the desk, so no walking was
commanded. The owner then confirmed frame support and servo power off for OTA.
Runtime evidence and camera captures remain outside the repository.

Remaining: deploy and verify the model interface, obtain usable metric visual
progress, conduct repeated physical candidate comparisons through existing
semantic commands, and save the best demonstrated model. No claim of improved
walking, measured sag, or optimality follows from these software checks.


### Deployment and measurement verification

The owner confirmed frame support and servo power off. Wi-Fi upload and activation
of 0.8.90 succeeded (application SHA-256
`34fb1d3da09a41e94ad951db58f4cf6eb63165867c87ec6d5073eb672cfe1662`).
A concurrent camera session then deployed 0.8.91-p4-highlight-wb, including the
gait changes. We retained that combined release; its live OTA status is accepted,
with no pending verification. The owner confirmed that deployment session has
finished. Live status exposes the sensor-policy feature, operator inputs and
both saved and selected gait profiles. Saved joint mappings and all twelve
feedback calibrations match the pre-update snapshots. The old saved learned
model remains disabled; no new candidate has been promoted.

A five-second stationary camera/joint/IMU recording completed with 259 sample
records, no reported loss, no incomplete batches, 1,032 accepted IMU acquisitions,
zero rejected acquisitions and zero acquisition-gap restarts. This was a passive
recording with no movement command from this session; it does not establish
loaded tracking, gait benefit or torque. Camera distance is still unavailable.

Updated the host support assessment to include the applied learned displacement
in its target, and to include version-4 eligible Walk commands rather than only
the older straight/full-stride subset. Otherwise an intentionally raised foot
could be misreported as an extension shortfall. Nineteen host assessment,
learning and training tests passed. Planned support remains distinct from
measured contact; no confirmed body-sag value is fabricated from these readings.


### First version-4 floor recordings and temporary candidate installation

With fresh floor readiness, enabled the existing self-leveling setting while
retaining heading correction. The unchanged baseline completed four forward
cycles and four backward return cycles through semantic Walk commands. Both
recordings completed without errors or lost trace records. The forward recording
had 291 joint sample events, zero IMU acquisition gaps during movement, and
roll/pitch spans of 7.42/16.21 degrees. Its phase-averaged planned-support extension
shortfalls were approximately RL 7.56, RR 2.53, FL 9.86, FR 0.46 mm; these are
shaft-derived tracking observations, not direct ground contact or confirmed sag.

Created and installed a zero-addition version-4 baseline with 123 usable eligible
decision samples. Model a5692a8d10ae9e69e9300459661f813fd059b46b7c612ab8c2cb47e990f04f5f
was enabled at amount 1. A two-cycle check completed, with zero applied learned
correction as expected. However, only 3 eligible policy decisions had all inputs
usable: the IMU was in startup for much of that short trial. The gap-restart
counter changed from 1 in the preceding recordings to 2 before this trial, not
during its acquisition. Snapshot captures and persistent model operations took
place between those recordings; the precise cause is not yet isolated.

The install/configure API previously wrote NVS on every candidate. Implemented
explicit `persist:false` for RAM-only training candidates, retaining persistent
behavior by default. Explicit `persist:true` saves the active model and settings.
Status exposes `model_saved`; Body Control labels temporary models. Runtime tests
verify RAM install/configure performs no NVS commit, reboot restores the previous
saved model, and explicit save survives reload. Targeted native and dashboard
tests passed. This is prepared as 0.8.92-p4-training-ram; deployment is not yet
claimed. Avoiding flash writes during candidate exploration must still be checked
on hardware; no arbitrary settling wait or gait stop was added.

Prepared mirrored candidate profiles and previewed them with the current joint
mapping at median and coordinate-wise extreme recorded sensor inputs. Paths
completed with the existing calibrated travel fit; this is not a learned
physical improvement. No candidate has received a fabricated visual reward.
The camera still has no fitted metric calibration. Walking previews show blur;
stationary requested stills are clearer. Existing Nod and turn commands are used
to obtain additional target views, with captures kept outside the repository.


### 0.8.92 installation and RAM-only hardware check

After fresh support/power-off confirmation, installed 0.8.92-p4-training-ram over
Wi-Fi. OTA accepted the image, running ota_1 with no pending verification;
SHA-256 `7ee29ae78c318e09dfe59b445bdad59db626e071d977891dc090b93bec91c58f`,
3,019,776 bytes. The saved zero-addition version-4 model survived reboot and was
reported saved/enabled. With servo power still off, installed the first candidate
using `persist:false`, then restored the zero-addition seed using `persist:false`.
The candidate reported unsaved as intended. The IMU gap counter remained 1 and
startup remained false across both operations. This verifies the temporary
installation path on hardware, but does not alone prove the cause of the earlier
gap. No altered gait was moved or promoted in this check. The permanently saved
model remains the zero-addition baseline; live RAM also holds that baseline.

The prior Nod and six-cycle left-turn commands completed. Their camera captures
provide additional views but still do not constitute a fitted metric camera
calibration. Physical optimization remains unfinished; the next floor session
must evaluate actual progress, tracking and attitude together.

### Recorded-image measurement sensitivity check

While awaiting floor readiness after the 0.8.92 installation, inspected the
existing stationary snapshots and their capture identities. The return and
standing snapshots are separate requested captures (epoch 70, request sequences
17 and 18, distinct image hashes), rather than the same cached JPEG.

Evaluated an offline alternative to intrinsic fitting: map the measured 9 by
12 inch paper through a planar homography and use assumed vertical furniture
edges to locate the camera's perpendicular projection onto that plane. This
approach is too sensitive in the existing shallow views. Perturbing manually
selected image endpoints by independent one-pixel Gaussian noise produced a
central 95% interval approximately 0.73 m wide in the paper's length direction
for the standing image, and 0.16–0.18 m for the later views. These are sensitivity
intervals under an assumed annotation-noise model, not calibrated confidence
intervals or measured robot travel; lens distortion and furniture verticality
remain unmeasured. They are inadequate for ranking these short walking trials.
No derived position was used as a training reward or saved as camera calibration.
Private analysis and images remain under /tmp, outside the repository. No
firmware or runtime camera changes were made for this experiment.

The next physical recordings need a better resolved metric reference view;
existing semantic motion commands can obtain it once floor readiness returns.
The last confirmed setup remains frame supported, servo power off. No movement
was commanded during this analysis, and no new candidate was promoted.

### Powered floor trials of version-4 sensor-conditioned gait profiles

After the owner returned the robot to the floor, all twelve mapped feedback
channels reported plausible powered readings and the calibrated IMU was fresh.
Stand completed and restored outputs from their released state. The initial
close camera obstruction cleared as the robot rose. Firmware remained
0.8.92-p4-training-ram throughout these trials.

Executed three ten-cycle forward Walk recordings: zero-addition baseline, the
positive generation-0 candidate, and its negative counterpart. Repositioning
used existing backward Walk, short forward Walk, and left-turn commands; no
manual reset or dedicated return behavior was introduced. Camera views show
forward travel, but repositioning did not reproduce identical starting poses.
These recordings are physical pilot observations, not matched training blocks.

| Recorded quantity | Baseline | Positive candidate | Negative candidate |
| --- | ---: | ---: | ---: |
| Usable eligible tracking decisions after phase 2 | 257 | 263 | 241 |
| Applied-target tracking RMS, mm per coordinate | 10.426 | 10.235 | 10.453 |
| Level-error RMS, degrees per roll/pitch coordinate | 2.218 | 2.372 | 2.463 |
| Peak reported heading error, degrees | 10.30 | 13.67 | 4.53 |
| Applied sensor/periodic residual RMS, mm per coordinate | 0 | 0.053 | 0.052 |
| Reported lost trace records | 0 | 9 | 0 |
| New IMU acquisition gaps | 0 | 0 | 0 |

Selected profile hashes were respectively 3785240341, 4074084110 and 3861731214,
confirming that both candidate profiles actually ran. The residual RMS excludes
planner-profile changes such as lift, landing and phase. Recorded carrier/crank
output extrema stayed within 500–2800 microseconds in all three recordings.
All three commands reported completion. These observations do not measure
contact, stall torque or electrical energy, and the filtered shaft tracking
numbers include actuator lag and sensor/filter effects.

The positive candidate's trace reader accumulated a backlog: batches of 64
records took roughly 0.6–0.8 seconds while the producer continued filling the
512-event ring. Its nine lost records were reported during final trace stop.
The recorder previously waited for an outstanding camera download before
stopping trace acquisition. Moved stop-and-drain into the trace reader thread,
which already owns its cursor, so camera completion no longer delays it. This
changes only host recording cleanup; it does not stop robot motion, reduce
sampling, or add a firmware behavior. A regression test holds a camera response
open and verifies trace stop occurs independently. Twenty-four focused recorder,
trace and training tests passed. The following negative-candidate ten-cycle
recording completed with zero loss. This single run does not establish sustained
streaming throughput for arbitrarily long trials; the observed transport backlog
still needs attention before longer uninterrupted recordings.

The body connection changed from epoch 71 to 72 between trials without a reboot
or firmware replacement. Each individual trial stayed within its own epoch;
recordings retain those identities. The saved and active model is again the
zero-addition baseline (active RAM restoration verified; persistent baseline
was not replaced). Neither candidate was promoted, and generation 0 was not
advanced: measured distance and repeated matched comparisons are still missing.
The negative candidate's lower peak heading error is promising but insufficient
by itself, especially with different starting poses and slightly worse tilt.
Private recordings and comparison metadata are under
/tmp/ainekio-floor-training-20261020, outside the repository.

### Trace transport repair and interrupted camera-view trial

The firmware trace response previously issued separate HTTP writes for each
JSON record and its one-byte newline. Packed the same NDJSON stream into 8 KiB
response chunks, without changing sampling, the 64-record batch, the 512-event
ring, or motion execution. Native trace HTTP tests verify complete record
parsing, chunk count, and retention after failed writes; the targeted test and
the P4 build passed. This session did not deploy this transport change. Another
session subsequently installed 0.8.93-p4-measured-motion; inclusion of this
change in that particular binary has not been verified.

On 0.8.92, an existing three-cycle left Crab command completed while recording
570 accepted IMU samples, zero new IMU gaps and zero lost trace records. Its
before/after stills show a lateral viewpoint change. The following right Crab
request was rejected because the body had entered Doze; its requested snapshot
was also rejected. The robot then disconnected and returned on 0.8.93. The
owner confirmed another session is working on it. Hardware commands and
deployment remain with that session; these 0.8.92 observations must not be
silently pooled with subsequent firmware comparisons.

Offline camera reconstruction used the existing sharp stills, including the
lateral view. A 15-view fit reached approximately 0.79 px mean reprojection
error, but low image residual alone does not establish correct metric shape.
The initial separate paper-check script omitted bearing-vector normalization;
its invalid projections were an analysis error, not evidence of a robot fault.
After correcting that temporary script, the four known paper edges imply scales
of 0.0668, 0.0375, 0.0438 and 0.1393 metres per reconstruction unit, with roughly
4.41 px paper-corner reprojection RMS. Their disagreement prevents a defensible
distance measurement. No resulting distance was used as a training reward,
no camera calibration was saved, and no candidate was promoted. Temporary
reconstruction code, dependencies and images remain outside the repository.

An additional offline fit used only the three observed paper rectangles, their
owner-reported 9-by-12-inch size, a centered principal point and equal focal
lengths. Across three focal initializations it converged near 656 px, but its
7.45 px reprojection RMS remains substantial. Perturbing corner annotations by
1 px over twenty repetitions produced focal estimates from 633 to 675 px;
this does not account for paper curvature, erroneous corner identification or
an inadequate lens model. These results do not qualify a camera calibration.

The saved pilot metadata confirms all three forward trials used 0.8.92 and
identical joint calibration anchors, with distinct requested model IDs. Baseline
and positive recordings used camera epoch 71; negative used 72. Each has seven
camera frames. Recorded request-to-receipt intervals reach 2.17 seconds and
include waiting for the next image; they must not be described as measured
exposure times or pure network latency. No optimizer generation was advanced.
The private provenance receipt is trial-provenance-check.json alongside the
recordings. Physical comparisons remain pending access to the robot after the
other session's work, and a defensible visual progress measurement.

### Resumed floor recording on 0.8.93 and overlapping deployment

The owner returned access to the robot on the floor. Firmware reported
0.8.93-p4-measured-motion, all twelve feedback channels responded, and the saved
version-4 zero-addition baseline was enabled at amount 1. Heading correction and
self-leveling remained enabled. A ten-cycle forward Walk at stride 100 and rate
2 completed (epoch 4, sequence 23). Before/after requested stills show forward
movement; no metric distance is asserted. Recording captured 479 valid samples
per joint, zero lost trace records and zero new IMU acquisition gaps. Median
trace response time was 0.454 s with maximum backlog 38 records, compared with
the earlier positive pilot's backlog of 418. This is an observed improvement in
this recording, not proof of indefinite loss-free streaming. Only one preview
frame arrived during this trial; requested endpoint stills were retained.

The planned backward repositioning was not submitted: its metadata request
failed while the robot disconnected. The gateway audit then showed a firmware
POST from outside this session, and the shared source advanced to
0.8.94-p4-independent-jam. The P4 log showed repeated controller reconnects
without a reboot during that interval, followed by Doze and released outputs.
No further movement or model installation was sent while the overlapping
deployment was being coordinated. This trial remains separate from 0.8.92 and
any later firmware results.

An offline affine following fit on the central portion of this new Walk found
best raw-feedback shifts of approximately 50–65 ms for the carrier/crank
channels; filtered-feedback shifts were 60–80 ms. Raw crank following gains
were approximately 0.95–1.00. Rear-left and front-left carrier gains were
approximately 0.745 and 0.761, respectively; right carrier gains were 0.960 and
0.857. These fit coefficients describe this periodic trial, not independent
servo speed, torque, contact or electrical power. Filtering, linkage load,
software output timing and actuation delay are confounded. They motivate testing
timing and carrier-trajectory changes, but do not justify promoting a policy
without measured travel and repeated comparisons. The analysis and recordings
are private under /tmp/ainekio-floor-training-resume-20261020.

### 0.8.94 floor follow-up, battery interruption and offline recording repair

After the owner confirmed the other session had finished, verified accepted
0.8.94-p4-independent-jam and resumed on epoch 38. The saved baseline model was
unchanged and no candidate was installed during this follow-up. Ten forward
cycles completed (sequence 21), followed by eight backward cycles (25) and two
right-turn cycles (31). Requested stills confirmed forward travel and a return
to the tape's starting area, but did not establish identical starting poses or
validated metric distance. The final planned two-cycle repositioning was never
submitted: feedback metadata acquisition failed after the connection vanished.
The owner then reported a depleted battery and requested completing offline
work before continuing later. No further robot commands were sent.

The ten-cycle 0.8.94 forward recording had 291 usable post-entry tracking
decisions, approximately 11.089 mm applied-target RMS error per coordinate and
2.413 degrees roll/pitch error RMS per coordinate. Peak reported heading error
was 4.93 degrees, and no new IMU acquisition gaps were recorded. However, twelve
trace records were lost with backlog reaching 443. The backward recording lost
625 records following a trace HTTP timeout. Those incomplete records remain
diagnostic evidence, not scored training trials. They cannot establish a gait
or firmware improvement, especially with battery state unmeasured. No model was
promoted and generation 0 remains unevaluated as a matched comparison.

The previously added response buffering is present in the uploaded 0.8.94
artifact, as confirmed by its distinctive allocation-error string; buffering
alone did not resolve sustained recording throughput. Inspection of the actual
cJSON dependency found a second cost: noninteger binary32 sensor readings were
printed with 15 significant digits, parsed back as doubles, and sometimes
printed again with 17 digits. Changed only trace float-array serialization to
nine significant digits, sufficient to recover the original binary32 values.
The wire representation remains numeric JSON arrays. Existing nonfinite-to-null
behavior and integer timestamps are preserved. No movement, sampling, ring
capacity, model, calibration or normal-runtime behavior was changed.

Validation: the native trace HTTP test passed, including a new wire round-trip
test covering 1,024 float bit patterns/extremes, signed zero and nonfinite
values; 24 host recorder/trace/training tests passed; the complete P4 build
passed. A three-repeat host benchmark of 20,000 representative tracking events
reduced mean event size from 2,218.44 to 1,714.44 bytes (22.72%) and median CPU
time from 1.243464 to 0.539307 seconds (56.63%). This is a host serialization
benchmark, not a P4 timing result or proof that live record loss is fixed.

The patch is built but not deployed. The build retains the shared checkout's
0.8.94 version string, so it must not be confused with the already-installed
0.8.94 binary; a release version should be assigned when deployment resumes.
Private build identity and evidence are retained with the resumed trial files.
Next physical work: install/version the recording repair, verify complete
recording on the charged robot, then resume matched candidate comparisons with
defensible visual progress measurements. Heading and self-leveling compatibility
still require candidate validation; the baseline remains the saved policy.

### Charged-battery resume: recording repair deployed as 0.8.95

The owner resumed testing with a charged battery and confirmed the frame was
supported with servo power off. Built and uploaded 0.8.95-p4-trace-float32
(3,026,192 bytes; SHA256
3e26b95beaaadf11e92d387418eda1f371dc549abc109b2a98ba749e1cc8f371).
The first activation returned ESP_ERR_TIMEOUT while the old 0.8.94 image
remained running. Retrying activation of the already-staged image succeeded;
the controller reconnected on epoch 19 and reported accepted 0.8.95, ota_0,
no pending verification and ESP_OK. No second upload was necessary.

Compared saved joint reference calibration, fourth-wire channel mapping and
calibration points, learned model identity/coefficients/amount, and balance
settings before and after activation: unchanged. The saved zero-addition
baseline remains selected; this update does not promote a trained candidate.

A 25-second passive recording, with no motion command submitted, captured
1,254 samples per joint, fifteen camera frames, zero lost trace records, no
incomplete batches and no IMU acquisition gaps or rejected acquisitions.
The frame orientation changed during the recording, so this is not a
stationary-noise measurement. With servo power off and no walking tracking
events it also does not establish sustained recording throughput during gait.
Private deployment receipts and recordings are under
/tmp/ainekio-trace95-20261020. The owner subsequently confirmed floor readiness
for a recorded ten-cycle baseline.

The ten-cycle forward Walk at stride 100/rate 2 then completed on epoch 20,
sequence 15. It captured 517 samples per joint, 453 output events, zero lost
records, no incomplete batches and no new IMU acquisition gaps. Median trace
response was 0.464 seconds. The 268 usable post-entry tracking decisions had
9.402 mm applied-target RMS error per coordinate and 1.894 degrees tilt RMS
per coordinate. These are diagnostic results, not an improvement comparison.

The requested pre-trial still failed, and preview subsequently stopped updating:
the camera task logged `camera unavailable: ESP_FAIL`. The one downloaded trial
image was stale, so there is no measured visual progress and this run is not
scored for training. No candidate was installed or promoted.

With fresh owner confirmation of support and servo power off, restarted the
controller through its existing settings-apply operation (revision 2, with no
pending settings changes). Preview resumed. Temporarily selected existing 960P
snapshot mode instead of AUTO to investigate format switching; that still also
failed, although preview remained available afterward. Preview shows horizontal
colored lines and substantial low-light noise even with servo power off.
The task exit, still failure and image artifacts are observed facts; a common
cause is not established. The owner raised a possible loose cable or nearby
magnet. Advised powering everything off before inspecting/reseating the ribbon;
no hardware change has yet been verified. Private evidence is under
/tmp/ainekio-floor-training-095-20261020. The diagnostic camera setting is now
960P for snapshots; preview remains VGA at 1 fps.

### Cable repair and renewed baseline

The owner identified a kinked camera cable, reported it fixed and confirmed
floor readiness with servo power on. On reconnect (epoch 25), 0.8.95 remained
installed. The new preview had no visible horizontal colored-line artifacts.
Both requested 960P reference stills succeeded, at 144,156 and 153,732 bytes.
This confirms successful captures after the reported repair, not indefinite
camera reliability.

A ten-cycle forward baseline at stride 100/rate 2 completed as sequence 9.
The recorder reported four camera frames, no errors, zero lost trace records,
and 2,103 accepted IMU acquisitions over 10.156 seconds, with no rejected
acquisitions or acquisition-gap restarts. The reference images show forward
travel. Distance remains unqualified: the tape is visible, but no validated
metric camera displacement was extracted or supplied to the optimizer.

The planned eight-cycle backward return was not submitted. Metadata acquisition
failed with HTTP 409 after the robot disappeared from the gateway. Repeated
read-only status checks still showed no connected robot. Asked the owner whether
power remained on; no reboot cause is inferred from a lost connection alone.
No candidate was installed, no model was promoted, and no generation advanced.

Offline following fits on the completed recording found raw carrier gains of
0.826/0.910/0.770/0.820 and crank gains of 0.982/0.970/0.990/0.939 in
rear-left/rear-right/front-left/front-right order. Best raw shifts were 45–70 ms;
filtered shifts were 65–90 ms. These periodic fits combine software timing,
filtering and loaded response; they are not torque measurements or independent
motor identification. Private images, recordings and fit analysis are under
/tmp/ainekio-cable-repaired-20261020. No firmware changes were made for this
follow-up; snapshot mode remains 960P.

The owner subsequently confirmed the robot was deliberately powered off for
maintenance. The disconnection above is therefore an owner-reported power-off,
not evidence of a controller crash. Physical comparisons await its return.

### Research refresh: owner-requested learning during ordinary locomotion

The owner requested a proposal for optional persistent gait logging and a
Body Control learning mode: vary motion, collect sensor/outcome data during
ordinary forward/backward/turning maneuvers, analyze and improve periodically,
then freeze the demonstrated policy at diminishing returns. Re-enable learning
after mechanical changes. This entry is research/proposal, not implementation
or authorization of new runtime restrictions.

Current audit: the live trace header reported active=false, session=0,
latest=0, capacity=0. Body Control provides browser-owned Start recording,
Finish/download, file-based Train/load and manual Install controls. These are
not a durable logging service or an automatic training lifecycle. The existing
UI trainer fits periodic tracking residuals. gait_training.py implements an
offline paired random search, but no gateway service invokes it automatically.
Its present objective requires forward speed, tilt and actuator error and does
not cover command-conditioned turning/backward objectives. Version 4 on P4
already supports command/sensor-conditioned Walk corrections and gait profiles;
its eligibility does not extend to Run/Crawl/Crab.

Primary references reviewed:
- Smith, Kostrikov, Levine, RSS 2023, Demonstrating a Walk in the Park:
  https://www.roboticsproceedings.org/rss19/p056.pdf
  Real A1 learning with SAC-family methods, onboard velocity estimation,
  contact inputs, controllable PD joint targets and GPU laptop training.
  Its continuous-learning result is relevant; its approximately twenty-minute
  result is not a prediction for MG90 linkage hardware.
- Widmer et al., Tuning Legged Locomotion Controllers via Safe Bayesian
  Optimization: https://arxiv.org/abs/2306.07092
  Hardware controller tuning and gait contexts support the proposed
  sample-efficient parameter-search direction. Its safety machinery is not
  implicitly adopted.
- Stanford Pupper v3 training/deployment:
  https://github.com/cs123-stanford/pupper-mjlab and
  https://github.com/cs123-stanford/pupper_gait_deploy
  Simulation-trained policies exported for execution; not evidence that a
  deployed Pupper retrains its policy during every ordinary walk.
- RMA: https://arxiv.org/abs/2107.04034
  Simulation-trained policy plus online adaptation, distinct from continually
  optimizing policy weights on the physical robot.
- Existing optimizer/estimator implementations:
  https://botorch.org/ and https://docs.openvins.com/gs-calibration.html
  Camera/IMU timing and calibration remain necessary for defensible metric
  progress; a working camera alone is not a functioning odometry estimator.

Proposed direction: host-owned persistent logger and contextual Bayesian gait
parameter optimization, initially on the workstation, subsequently Q6A after
benchmarking. Keep P4 motion, linkage IK, live heading/leveling and compact
sensor-conditioned policy execution. Start with a low-dimensional coordinated
parameter set rather than simultaneously searching all 237 policy floats.
Use ordinary commanded movement windows with model/context identities, retain
reference-policy observations across comparable contexts, and promote repeatable
improvements. Score commanded translation/yaw, unwanted drift, body tilt/impact
and measured following; do not call joint error a torque or energy measurement.

UI proposal: Log gait data, Learn while walking, Analyze now, learning progress,
per-maneuver coverage and saved-model history/restore. Training off preserves
the learned gait and live feedback. Plateau is evidence about covered contexts,
not a global optimum or an arbitrary motion timeout. Invalid/missing progress
must remain explicitly unknown; handling incomplete observations is a proposed
learning-data policy, not a new robot stop or movement restriction. No firmware,
dashboard or trainer changes were made during this research refresh.

### 2026-10-20 — owner-approved host learning implementation and priority correction

The owner approved using the computer running Body Control for training, with
training switched off on a laptop/smaller host. The owner clarified that the
current priorities are forward Walk, backward Walk, turning and Run, and reports
that these currently do not work satisfactorily. Earlier successful forward
trials are historical observations, not present qualification of these commands.
Crab and Crawl are experimental and excluded from the initial training scope.

Implementation now adds a gateway-owned persistent recorder, explicit logging/
learning switches, asynchronous Analyze now, model history/restore and automatic
candidate/evaluation/incumbent/plateau lifecycle. Private traces, images and
training state use the host's XDG state directory outside the repository.
The previous browser-owned recording loop was removed. No return-to-start
behavior or test-specific robot motion command was added.

The host optimizer uses BoTorch, with nine coordinated gait/feedback search
coordinates. Both fourth-wire reference-point response and gyro tilt response
can change, in addition to duty, sweep, front/rear lift and landing, and height.
It records actual model/profile/context identities, scores measured directional
progress, yaw trajectory error, lateral drift, body motion and joint following,
and compares matching command/stride/cadence conditions. Walk promotion requires
repeated forward, backward and both left/right turning observations. Run uses a
separate P4 model/NVS slot and retains bounding. Candidate weights are RAM-only;
only demonstrated incumbents are persisted. Ordinary motion does not wait for
analysis. Existing self-leveling, heading feedback and mechanical limits remain.

Validation so far: 61 focused host/dashboard tests passed before the final
telemetry refinements; nine new host-learning tests subsequently passed,
including browser-independent recording, signed backward/turn objectives,
missing-distance handling, model promotion, plateau and restore. Native trace,
learning-runtime and gait-profile tests passed with independent Run persistence
and actual Run inference. A real CPU-only BoTorch fit/proposal on synthetic
observations completed in approximately four seconds. These are software tests,
not physical gait improvements.

One wider native invocation selected an old Python without NumPy/SciPy; that
environment failure is distinct from motion-code failure. The source/reference
checks are being rerun with the repository's pinned scientific packages.
A separate Stand session advanced the shared firmware version during this work;
this session is building separately and has not flashed or restarted the robot.

Remaining qualification is explicit: the existing camera motion measurement
owner still needs usable calibrated metric observations on this robot. OpenVINS
was researched but has not been implemented by this change. Receipt-clock camera/
trace alignment is approximate and labeled. No new physical candidate has been
promoted, and the host learning mode has not been activated on the live robot.

Implementation verification completed later in this session:

- 66 host/HTTP/dashboard tests passed, including authenticated selected-robot
  logging, analysis and restore. The final twelve host-learning tests passed
  again after persistence and comparison refinements. Both learning dashboard
  JavaScript suites passed.
- Native trace serialization, separate Walk/Run learning execution and gait
  profiles passed. The pinned source/reference comparison also passed for
  3,889 poses; the earlier missing-NumPy result was an environment failure.
- The CPU BoTorch worker fitted twelve synthetic nine-dimensional observations
  and proposed a candidate in 2.75 seconds. This measures software execution,
  not robot improvement.
- The host now uses the existing production native linkage preview before
  installing an automatic candidate, fitting only the learned delta toward the
  incumbent when necessary. Real native previews of a small candidate completed
  forward/backward/left/right conditions for Walk and Run in approximately
  0.10/0.09 seconds using the existing calibration test fixture. Sensor inputs
  were zero; this does not predict load, slip, collisions or physical feedback.
- Requested motion rate, rather than resulting cadence, identifies comparison
  conditions. A faster candidate therefore remains comparable. Useful motion
  supplies the reward; stability/following costs reduce it, so quiet immobility
  cannot beat useful progress. Extra spinning past the planned turn is not
  rewarded. Logging history survives enabling training; restoring a model
  restores its search centre as well.
- The final integrated ESP-IDF build succeeded. Private artifact:
  `/tmp/ainekio-host-learning-20261020/build/ainekio_p4_body.bin`, 3,041,168 bytes,
  SHA-256 `7ee499eb9c2322e99e66a16840d0ba83fc9e26a3e109cb8049bf7cdda7c85dd8`.
  The concurrent Stand session owns the shared `.97` version; this session
  did not flash this artifact, restart the gateway or dispatch robot movement.

Read-only inspection of the physical gateway's saved sensing configuration
found **zero metric camera calibrations**. That is the concrete remaining
measurement dependency for this implementation's progress objective. The
logger can retain joint/IMU/camera evidence, but automatic physical improvement
cannot be claimed or ranked by distance until the existing measurement owner
provides qualified metric observations. No learned candidate was activated on
the robot by this session. Forward, backward, turning and bounding Run remain
the physical acceptance priorities; Crab/Crawl remain experimental.


## 2026-10-20 — Stand measured-progress repair, prepared for physical testing

Owner requested one existing motion foundation that steps toward actual Stand
joint targets, without the all-joint checkpoint deadlock or an intermediate
planner failure automatically releasing PWM. Optional jam release remains the
owner's independent choice.

A native replay using the recorded installed mapping reproduced a crank-branch
failure in the fixed contact trajectory. This was a geometric planning failure,
not evidence of a physical jam or exhausted PWM timer. The body-controller
regression now completes that case after one corrective path and retains the
original final joint target.

Changes in the existing owners:

- Measured startup engages carrier/crank outputs at their measured positions,
  then uses the existing stepping planner. It no longer commands a simultaneous
  fold and waits for all eight joints before starting to step. Shoulders engage
  after their own lifted-leg arrival and stay engaged through subsequent replans.
- Lift/place arrival checks the moving leg. Supporting joints are not a global
  barrier; lowering can transfer load before the next leg steps. Final Stand
  completion still requires all commanded targets to arrive.
- The same non-progress observer supplies corrective stepping and optional jam
  release. A missed stage or final target replans from measured positions, with
  the affected leg first. An unsolved contact path tries the four existing leg
  orderings and reports replanning if none currently solves. The request remains
  replaceable; this does not create a new stop, automatic release, or deadline.
- Joint-travel fitting participates in candidate sampling before path progress
  commits. Failed planning leaves progress/pose unchanged. Contact geometry is
  recomputed from the fitted frame rather than reporting unfitted clearance.
  One existing test fixture requests 8 mm lift but produces about 5.93 mm after
  its installed travel fitting; the test now checks positive commanded clearance
  and agreement with forward kinematics, rather than claiming 8 mm occurred.
- Removed the unused separate rise interpolation and obsolete checkpoint helpers.
- Feedback config version 4 separates `arrival_tolerance_us` from the existing
  jam `tolerance_us`. Migration preserves the owner's former shared value in
  both fields and preserves all calibration curves, mappings and enable flags.
  Body Control exposes both settings and displays replanning status/count.

Verification: six focused native suites passed (body execution, body feedback,
posture/contact geometry, joint calibration, feedback calibration/migration and
feedback arrival/non-progress), plus the feedback dashboard JavaScript test.
Coverage includes blocked active/supporting joints, missed final arrival, Stop,
transient mapping failure, transactional planning, four leg orderings, independent
jam/arrival settings, and a simulated unequal-rate servo plant that reaches all
final targets in 2.18 seconds. The simulated plant is not a torque/contact model.
The integrated ESP-IDF application builds as `0.8.97-p4-stand-progress`; all LCD,
camera and other currently integrated source remains included. Existing mechanical
travel bounds and physical PWM representability checks remain in their owners.

Prepared artifact and private replay/build evidence are under
`/tmp/ainekio-stand-repair-20261020`. At preparation the online robot reported
`0.8.96-p4-large-faces`, with coordination off, jam release off, both tolerances
400 us and the no-progress window 3000 ms. No movement was dispatched for this
repair. Installation and loaded standing remain unverified; physical readiness
was requested before rebooting the robot. Preserved arrival tolerance is an
owner-adjustable acceptance band, not proof of exact standing height.

Installation attempt after owner authorization: the complete 3,030,800-byte
`0.8.97-p4-stand-progress` application uploaded and returned `staged`. Activation
returned `ESP_ERR_TIMEOUT` through Body Control and on one direct maintenance
retry. The robot still reports `0.8.96-p4-large-faces`, running/boot `ota_1`,
with no pending verification. The new image is not active; a full physical
power cycle is needed before retrying installation. No saved feedback settings
were changed and no Stand test was dispatched. Private upload/activation receipts
are in the existing task directory. Artifact SHA-256:
`4357ece6f7677c91d97a9cbec6f9e32778076da4034dd2fbe86e75f28bf5e013`.

Owner-requested retry after power cycle: direct authenticated Wi-Fi upload
again returned `staged`, but activation again returned `ESP_ERR_TIMEOUT`.
A separate call to the existing recording stop endpoint reproduced the timeout
in 4.038 seconds, identifying the recording/storage command path as an
installation blocker. Readback still reports version `0.8.96-p4-large-faces`,
running/boot `ota_1`, no pending verification; saved coordination/jam flags
remain off and both tolerances remain 400 us. No USB serial device was present
on DNDIY. Application-only USB flashing is the next installation route; the
prepared `.97` image remains uninstalled.

Subsequent owner-requested Wi-Fi activation retry succeeded using the same
already-staged image. The robot rebooted into `0.8.97-p4-stand-progress` on
`ota_0`, reported `accepted` with `ESP_OK` and no pending verification, and
reconnected to Body Control. Readback confirms all feedback settings and all
twelve feedback calibration curves/mappings are unchanged: coordination off,
jam protection off, both tolerances 400 us, no-progress window 3000 ms.
Display, camera, microphone and speaker report ready. No additional motion
command was sent; loaded standing remains to be tested. This successful retry
does not establish that the intermittent recording-stop timeout is repaired.

## 2026-10-20 — Complete Stand passes with final verification

Owner replaced intermediate arrival-gated execution with complete movement
passes followed by final-pose checks, and explicitly approved removing
intermediate feedback waits throughout named motions and custom sequences.

The existing body output owner now executes the initial Stand fold and stepping
pass without requiring shaft readings to start or progress. After the final
commanded target is successfully written, one subsequent feedback snapshot
supplies both goal errors and the starting pose for a corrective stepping pass.
The original goal, sequence and completion receipt survive repeated passes.
There is no intermediate joint checkpoint, jam-timer dependency, artificial
settling interval, retry-count cap or added automatic release. Missing readings
cannot establish completion. Stop and command replacement remain available.

Named clips, custom sequences, finite gait endings and reverse lay-down recovery
run through their authored paths without feedback-arrival waits. Recovery into
Stand verifies only after its complete reverse/alignment path, then uses stepping
for correction. Removed the old checkpoint enum/branches, paused trajectory
clock, clip-landmark API and shared blocked-joint mask. The optional jam observer
retains its owner-selected release behavior and observes non-progress only when
jam protection is enabled. Acquisition remains available to telemetry, balance,
learning and final Stand verification. Existing saved flags, tolerances and
calibrations remain unchanged; the UI labels `stand_enabled` as final-pass Stand
verification and explains the new behavior.

Verification: ten relevant native suites passed (feedback configuration,
feedback observations/jam behavior, joint and clip calibration, body execution,
body feedback, posture contacts, V2 motion, clips and grounded steps). The
feedback dashboard test also passed. Tests cover complete initial/corrective
passes without intermediate reads, multiple final-goal corrections, missing
observations, fixed final targets, replacement/Stop, all named clips with
unavailable feedback, custom endpoints, reverse recovery and failed final PWM
writes. A deliberately lagging plant continued corrective passes for 20 simulated
seconds without false completion; completion was tested after explicitly placing
that simulated plant at the goal. This is not evidence of autonomous convergence
or loaded standing. The previously observed electrical/acquisition signal loss
has not been repaired by this change and still requires separate investigation.

Integrated application prepared as `0.8.101-p4-stand-passes`, 3,038,448 bytes,
SHA-256 `ff1cfb49ed222cd4ff88cd27426b467d91f192ad9c2b52d347739a8e74385d68`.
Private artifact, source manifest and build/test evidence:
`/tmp/ainekio-stand-sequence-20261020`. Not installed during this coding task;
no robot motion or saved-setting change was issued.

Owner-authorized Wi-Fi installation completed: the exact prepared application
was uploaded; two activation attempts returned the existing shutdown timeout,
and the next activation retry succeeded without another upload or power cycle.
The robot booted `0.8.101-p4-stand-passes` on `ota_1`, reported `accepted` with
no pending verification and reconnected to Body Control. Readback confirmed
unchanged feedback calibration/mappings and all saved feedback settings:
acquisition on, Stand verification off, jam protection off, both tolerances
400 us and no-progress window 3000 ms. Display/camera/audio report ready.
No extra Stand command or settings change was issued. Loaded standing and the
feedback signal issue remain unverified; the OTA timeout was not repaired here.

## 2026-10-20 — Installed vision audit and optional learned-depth odometry

Owner requested alternatives to Depth Anything and checking existing SLAM before
adding software. Read-only host audit found ROS 2 Jazzy (`ros_base` and
`image_transport`) but no discovered ORB-SLAM3, OpenVINS, RTAB-Map, Cartographer or
SLAM Toolbox installation. The queried ROS graph had no application nodes and only
`/rosout`/`/parameter_events`; no running SLAM service or container was found.
**Open3D 0.20.0 is installed in the ComfyUI interpreter**, and its RGB-D odometry
and dense-SLAM APIs imported successfully. ComfyUI also contains MoGe-2 code and
the existing 632 MiB converted weights. These libraries were not connected to the
robot's camera measurement owner.

Live Body Control was online, receiving camera frames, and reporting
`Measured calibration and floor reference required` for locomotion measurement.
Private sensing settings contain zero ground calibrations. The camera was set
to VGA at 1 FPS. Twelve existing stream frames were read without changing settings
or sending movement; their arrival intervals were about 1.2–1.3 seconds. Images
showed a tabletop/person working near the camera, not a controlled walking trial.
This session has not asserted that the robot was stationary or ready for motion.

Compared primary-source descriptions of MoGe-2, Depth Anything 3 (including the
metric nested 1.1 variant), UniDepth V2, Depth Pro, ORB-SLAM3 and OpenVINS. Detailed
links/tradeoffs are in `Master/gateway/README.md`, “Optional host depth and camera
odometry.” Existing MoGe-2/Open3D were used for the optional prototype instead of
downloading another large checkpoint. An inspected DA3 upstream source checkout
was removed after inspection; no DA3 model weights were downloaded.

Implementation adds an isolated host MoGe-2 worker and Open3D multiscale RGB-D
odometry, selected explicitly in Camera → Depth and camera movement. Existing
calibrated ground-plane tracking remains the other choice. Model outputs include
estimated depth preview, fixed-per-reference estimated intrinsics, local
camera/body pose (depending on supplied mounting transform), model identity,
registration diagnostics and original frame receipt time. Distances are marked
`learned-metric-estimate`, with unverified metric accuracy and unknown uncertainty.
No mapping/loop closure or calibrated visual-inertial fusion is claimed.

The selected source feeds the existing gait recorder and objective. Result
provenance is saved; changed camera calibration/source contexts begin a new
comparison bank and archive old observations rather than comparing unlike
measurements. The worker sends no motion commands. There is no inference deadline,
automatic camera setting change, guessed-optics fallback or firmware alteration.
P4 live correction, joint feedback and IMU scoring remain under their existing
owners. Disabling depth releases its model when no robot uses it.

Private benchmark material: `/tmp/ainekio-depth-20261020`, plus the existing four
VGA frames in `/tmp/ainekio-cable-repaired-20261020/baseline-10`.
The installed network's initial benchmark warmed up in about 1.74 s, then ran
in 76–78 ms/frame; peak Torch allocation was approximately 1000 MiB on the RTX
4080. Open3D's initial default solve took 22–29 ms/pair. Per-frame focal estimates
varied roughly 294–353 pixels, motivating fixed optics within a tracking reference.
The default solver also under-converged on a synthetic 20 mm image translation:
after correcting invalid warp-border depth, its error was about 3.1 mm; increasing
the multiscale iterations to 30/20/10 reduced that example to about 0.7 mm.
These are local implementation checks, not measured physical camera accuracy.
Sparse, blurred historical walking images do not validate travel direction,
scale, drift or a learning reward.

Deployment status: source integration and offline GPU worker exercised; the
running gateway was not restarted or reconfigured, and no robot commands,
training activation, saved robot calibration or firmware changes were issued.
Physical distance accuracy and whether this source improves forward/backward,
turning and Run training remain outstanding. This does not complete the learned
walking objective.

Validation receipt: 54 tests passed across depth integration, host gait learning,
ground-plane tracking/authenticated camera settings and camera perception. The
known-motion Open3D test, signed forward/backward/yaw transforms, measured lever
arm, source persistence, model release and error reporting are covered. Dashboard
navigation (four tests) and host gait-training UI checks passed; JavaScript
syntax and `git diff --check` passed. Tests exercise mocked robot transport and
synthetic images, not physical gait. Restricted-sandbox executor shutdown hung;
the same suites passed outside the sandbox, and only this session's three hung
test processes were terminated.


## 2026-10-20 — Sequential initial folding and completed-pass jam assessment

Owner requested reduced simultaneous servo travel while resolving the supply issue,
and explicitly approved assessing startup/Stand jams between complete passes.
The existing seconds-based jam observer is retained, including saved tolerance,
progress increment and no-progress duration. No runtime setting was changed.

Initial startup/detached Stand now engages one leg's crank/carrier together in
stepping order (front-left, rear-right, front-right, rear-left), each separated
by the existing full-travel transit estimate rounded to a 20 ms output tick.
This replaces the front/rear overlap of 20 ms. Engaged legs stay powered; each
shoulder still engages during its lifted-foot stage. The later contact-aware
body rise is unchanged and still moves supporting legs together. These are
command timings, not measured arrival or a guarantee of lower peak current.

During startup/Stand, in-pass samples no longer feed jam-progress history.
A fresh final-target observation begins that history; subsequent complete-pass
observations retain the same final goal and elapsed-time rule. If replanning
cannot proceed, assessment continues while holding the finished-pass target.
The threshold remains milliseconds (3000 = 3 seconds), not a pass count. A pass
can finish after the threshold. Jam-only mode does not introduce a missing-data
completion barrier; independent Stand verification remains the owner of goal
confirmation/retries. Other movement and idle holding retain continuous jam
assessment. Both assessment paths reuse the same release-and-body-event owner.

Validation: body_execution, body_feedback_execution, servo_feedback_measured_arrival
and dashboard servo-feedback tests passed; integrated ESP-IDF build succeeded.
Coverage includes complete-pass assessment, missing data with jam-only mode,
in-pass dip recovery, startup/command/idle release receipts, and a three-second
threshold with irregularly spaced pass samples. Source diff whitespace passed.
Firmware 0.8.109-p4-stand-pass-jam is built, NOT installed. Private artifact and
test evidence: /tmp/ainekio-stand-pass-jam-20261020. Supply sag and loaded
stand-up improvement remain physically unverified.

**Installation verified:** Owner requested flash. Wi-Fi upload staged the
3,039,232-byte image (SHA-256
`7776f77aa9496904df91d24cc9dd9dbde2752680f6b611abe5010f8273fc77fe`);
activation succeeded and the P4 reconnected with 0.8.109-p4-stand-pass-jam,
ota_0 running/boot, accepted, pending_verify=false, ESP_OK. All seven feedback
settings and all twelve feedback curves/channel mappings compare equal to
preflash. Startup reported final path progress 1, no replans and no stalled
joint mask. Outputs are released by the existing OTA acceptance path in
system_authenticated; no additional Stand command was sent. This verifies
installation, not physical arrival or resolution of the supply problem.


## 2026-10-20 — Live depth source activated in host gait learning

Owner requested putting the installed vision tools into use, then explicitly
confirmed floor readiness for recorded walking. MoGe-2/Open3D is now selected
in Body Control, the preview is requested at VGA/5 FPS, and persistent host
logging and learning are enabled. These are host/camera settings; this session
installed no firmware and changed no robot joint calibration or base gait.
Actual camera cadence can be below the requested rate.

Live activation exposed and repaired these owning-layer defects:

- Ultralytics CPU recognition sets CUDA_VISIBLE_DEVICES empty. The independent
  depth worker now preserves the launcher's allocation, with an optional
  AINEKIO_DEPTH_CUDA_VISIBLE_DEVICES override. Its lightweight module is loaded
  before recognition initializes. Live GPU use was about 1476 MiB; ordinary
  combined depth/odometry processing was approximately 123–154 ms per frame.
- Trace reads previously reused a cursor after controller restart, producing a
  permanent HTTP409 loop. Reads now include the existing boot/session contract;
  session changes reacquire metadata and start a separate observation context.
- A missing joint observation previously restarted the complete four-cycle
  window. Windows now retain their command context, count missing observations
  and use only actual usable samples. Missing readings do not become zero error.
  Statistics describe the measured subset, not unseen joint behavior.
- HTTP trace batches can carry old buffered history. Live status-clock receipts
  now align that history with camera receipts. Network latency remains unknown;
  this is not exposure-synchronized visual-inertial estimation.

A nearly black startup image established an unusable visual reference. An
explicit tracking restart from a clear image restored estimates. After a later
Open3D singular fit, the owner explicitly approved automatic recovery: retain
intrinsics/calibration, establish a new local reference, report the failed
interval unavailable, and resume with the next usable fit. No distance is
invented across a reference break and no robot motion is stopped. The recovery
worker is installed and live. Windows crossing a tracking break remain unscored.

Trial receipts and limitations:

1. Initial eight-cycle command (epoch 29/sequence 8) preceded explicit floor
   confirmation and used forward=1, which is 1 percent in this wire protocol.
   Both were operator errors by the agent. Placement is unverified; this is
   excluded from gait comparisons. No scored window/model promotion occurred.
2. After explicit floor confirmation and visual inspection, the current Walk
   ran eight cycles at stride=100, forward=100, turn=0 (epoch 29/sequence 9).
   The controller reported completion. The original recorder scored no window.
   Offline replay with the timing/window repairs recovered one window using
   70 usable observations out of 131; this replay installed no model.
3. After the host repair and another explicit floor-ready confirmation, a live
   eight-cycle forward Walk completed (new gateway epoch 1/sequence 7). The
   service saved its first forward baseline bank: one four-cycle window, 80
   usable observations of 136, four camera poses, and no lost trace records in
   that run. Its estimated camera-origin forward displacement was 0.0536 m
   over 2.112 s for that window only, NOT the whole command and NOT a calibrated
   physical distance. Reported lateral motion and about 55 mm kinematic tracking
   RMS require investigation; neither is treated as independently verified.
   This created an initial baseline, not an improved or optimal gait.
4. Eight-cycle backward Walk (epoch 1/sequence 8) was submitted to reposition
   without asking the owner to carry the robot. Its trace contains 98 tracking
   records, but the controller reconnected into epoch 2 and later received a
   Stand from another source. There is no verified completed backward return.
   No additional motion commands were sent after observing that reconnect.

The host continues recording ordinary forward/backward/turning/Run activity.
Automatic analysis still needs comparable repeat observations in the relevant
maneuvers before choosing a candidate. Physical depth-scale accuracy, camera
mounting transform, motion-blur robustness, incomplete joint observation coverage
and the apparent large tracking error remain unresolved. This receipt does not
claim locomotion improvement or completion of the learned-walking objective.

Validation: 60 targeted tests passed for depth geometry/recovery, host recording
and learning, camera settings/authentication and camera perception. Tests include
known synthetic translation, GPU allocation isolation, trace-session restart,
queued-data clock alignment and intermittent-observation windows. Logs, camera
images, activation receipts and replay results remain private under
/tmp/ainekio-depth-20261020 and ~/.local/state/ainekio/gait-learning; none were
added to the repository. Earlier live recording accumulated trace loss during
reconnections/backlog; those counts were reported, not erased or called valid
training. A sandbox-stalled replay process was terminated and rerun outside the
sandbox; no unrelated process was stopped.


## 2026-10-20 — Persistent measured Stand goal, not jam-triggered collapse

Owner clarified that target shortfall and environmental obstruction must cause
continued Stand correction, not servo release. The previous 0.8.109 test reached
Stand, emitted completion, then the independent holding observer flagged nine
joints roughly three seconds later and released all outputs. Stand used 400 us
arrival tolerance while that holding observer used 200 us. These were conflicting
owners of a single standing objective.

With Stand verification enabled, initial completion and retained standing now
use the same arrival_tolerance_us comparison. Shortfalls repeat complete
corrective passes. Reaching the goal produces one completion receipt and keeps
the goal active; subsequent drift re-enters the same posture planner with an
internal continuation and no duplicate external receipt. Stop/release, calibration
and replacement body motion relinquish that goal. Missing observations never
assert arrival or release output. Intentional listening gestures are not opposed
by Stand correction. Current commanded balance adjustments become the holding
target and require post-write observations before judging a discrepancy.

The separate position-based jam-release timer no longer overrides a verified
Stand goal, either during correction or after initial completion. It remains
available for other operations and for Stand with verification disabled. This
does not establish true current/temperature overload protection: those quantities
are not measured by the fourth wire. No saved settings or tolerances changed.
If measured geometry cannot produce a corrective path, the existing planner
reports replanning and retains output rather than inventing a pose or reporting
success. Poor feedback still cannot establish physical standing.

Removed the unrelated unconditional servo disable in system_authenticated's
OTA acceptance path. Firmware validation now observes the existing output state
without dropping a successfully started robot. Error/rollback decisions remain.

Validation: body_execution, body_feedback_execution, servo_feedback_measured_arrival,
dashboard servo-feedback tests, and two production-function OTA tests pass.
New coverage includes repeated shortfalls beyond the jam time, accepted-goal
holding, drift recovery without duplicate receipts, missing samples, Stop and
replacement, and OTA acceptance retaining armed outputs. Integrated build
0.8.110-p4-stand-goal completed; private evidence and exact artifact manifest
are in /tmp/ainekio-persistent-stand-20261020. Physical improvement is not inferred
from these tests.

Installation receipt: 0.8.110-p4-stand-goal was accepted in ota_1 with
pending_verify false; saved calibration and feedback settings were preserved.
The owner subsequently reported inaccurate corrections and intermittent jerking,
including after disabling jam protection. This is not a qualified Stand repair.
The initial postboot capture retained powered outputs but entered repeated
geometric replanning; completion of the intended recovery was not established.

Later passive observation found jam protection, Stand verification and stationary
leveling all disabled. Thirty feedback snapshots retained identical commanded
pulses on all twelve outputs and no Stand replan. The owner confirmed the robot
was standing, while the raw feedback channels were near/below their calibration
minima. Earlier captures from the same installed firmware had distinct in-range
shaft readings. The discrepancy therefore exists before angle inversion and
conversion; its electrical/acquisition cause remains unverified. ADC read success
currently establishes a sampled channel, not physical position accuracy, and
the position converter explicitly extrapolates beyond calibration. No new range
rejection, output release, calibration changes or movement commands were added
during this investigation. The passive capture does not establish that a reported
jerk occurred inside its observation window. Private evidence is retained in
/tmp/ainekio-persistent-stand-20261020/passive-134809.jsonl.

## 2026-10-20 — Stand verification repeats commanded stepping

The owner clarified that being upright does not mean the joints have reached
the standing target. Low reported positions alone do not establish defective
feedback, and the preceding passive capture did not establish the physical
cause of the shortfall or intermittent jerking.

The 0.8.110 final-pass handoff rebuilt its entire geometric trajectory from
measured shaft positions. That was different from the requested execute/check/
repeat behavior: a shortfall could replace the commanded support pose with a
substantially different origin, or produce an unsolvable measured linkage and
leave the request replanning. Version 0.8.111-p4-stand-repeat removes this handoff.
Every corrective pass continues from the last commanded frame toward the same
standing target. Final-pass feedback compares calibrated pulse equivalents
directly with the target; the remaining-joint mask chooses which leg to
prioritize and determines completion. The now-unused measured-frame return was
removed from that verifier. Live balance retains its separate shaft observation
API. This adds no retry cap, intermediate wait, output release or pulse limit.

A new production-body regression supplies large measured offsets, verifies
continuous commanded references, affected-leg priority, repeated complete passes,
unchanged final target and eventual completion receipt. It fails against the
previous body implementation because corrective replanning cannot start, and
passes against the new implementation. Three focused native suites and the
dashboard servo-feedback test pass; the integrated firmware builds. The existing
slow-plant test still verifies continuation rather than autonomous convergence;
neither test establishes successful weight-bearing standing.

A live Stand request (epoch 5, sequence 19) was recorded on 0.8.110 with the
owner's verification and jam settings off, and returned a trajectory completion
receipt. It is not proof of measured arrival. Private capture, before/after
regression evidence, build and installation receipts are retained under
/tmp/ainekio-stand-repeat-20261020 and the preceding persistent-stand directory.

Installation: Wi-Fi upload and activation succeeded. The P4 reported
0.8.111-p4-stand-repeat accepted, pending_verify false, connected, outputs armed
and output_fault zero. Saved switches, thresholds, input mappings and all twelve
feedback curves matched the preflash snapshot. Coordinated Stand and jam
protection remain off as the owner had saved them. Physical validation of the
new feedback-enabled corrective behavior is still outstanding.

## 2026-10-20 — Stand retest after owner repaired a ground fault

The owner found and corrected a ground fault and requested another live test.
The P4 retained 0.8.111-p4-stand-repeat. Distinct joint feedback readings returned.
For the test, Stand verification was temporarily enabled with the existing
400 us arrival tolerance; jam protection stayed off. Stand command epoch 11 /
sequence 7 completed with measured verification. During 65 subsequent snapshots
covering 19.22 seconds before another command replaced it, all twelve joints
remained inside the configured tolerance; maximum absolute filtered error was
175.74 us. There were zero corrective replans and no output fault. The owner
confirmed the robot stood correctly and remained steady without the previous
jerking. This validates this Stand-and-hold trial, not jam protection or recovery
from a deliberately introduced obstruction.

The owner also issued Neutral (8) and Stand (9) during the recording; both
returned completion, but they are separate from the sequence-7 hold measurement.
After recording, the original saved settings were restored: Stand verification
off, jam protection off. No release command was sent. Private measurements and
configuration receipts are in /tmp/ainekio-ground-repair-test-20261020-140055.

## 2026-10-20 — Feedback readings recover after ground inspection

Owner reported finding a probable ground fault and requested another voltage
check. Three successive live feedback snapshots (scans 1762, 1764, 1765) now
show distinct joint voltages spanning 0.601–2.735 V, rather than the previous
all-low 0.09–0.26 V pattern. All twelve channels were within their saved
calibration ranges; acquisition and voltage conversion reported ESP_OK.
Measured positions differed from commanded positions by at most approximately
94 us across these snapshots. The mirrored rear carriers now read approximately
2.66–2.74 V left and 0.60–0.62 V right, consistent with their respective
2369 us and 796 us commands. Outputs were reported armed.

This supports the owner's electrical-fault finding; it does not isolate the
exact failed connection or establish long-term stability. No movement or
calibration changes were commanded for this check. Loaded walking and learning
must be evaluated with the restored measurements rather than interpreting the
previous all-low samples as actual joint positions.

## 2026-10-20 — Feedback failure continues authored motion

Owner explicitly selected: finish programmed movement, retain powered targets,
report unusable feedback, and suspend measured corrections until usable readings
return. Missing feedback must not become a command-completion barrier.

Installed integrated `0.8.112-p4-feedback-fallback` over Wi-Fi; accepted in ota_1
with no pending verification. App SHA256:
`9f539dfe4dfa26208f28a907b36a3af7a5ed37d387e8aaef16426bfbe002be8a`
(3,040,688 bytes). Calibration and saved settings were preserved. Firmware now
finishes the authored Stand path when post-command observations are unavailable,
with `position_verified:false`, while retaining the powered goal. Valid measured
shortfalls still use corrective stepping; returned observations can resume this
without duplicating the original completion receipt. Feedback absence or
extrapolation cannot serve as evidence of a jam. Command pulse range is unchanged.

Body Control now displays current feedback health and fourth-wire millivolts.
It sends fault/restoration notices through the existing body-event bridge, with
fault notices using the existing cooldown and reaction-face suppression. These
notices never send a stop or release. The Environment Bridge retains the optional
position-verification field in action receipts. Out-of-calibration signals are
untrusted measurements, not proof of a specific electrical failure. The hardware
still does not measure servo-rail or battery voltage.

Validation:

- Three native suites passed: body execution, feedback execution, and measured
  arrival. These cover reader loss with coordination and jam enabled, completion
  without output release, holding, resumed correction, new-command admission,
  and all-low/out-of-range signals that cannot establish a jam.
- 57 gateway/body-event tests and nine subtests passed using pinned WebSockets
  10.4; dashboard feedback and body-event tests passed. Additional receipt and
  same-scan reader-failure cases passed after review.
- New protocol schema/validator test passed. The broader legacy protocol suite
  still has three pre-existing coverage failures: missing robot_settings schema
  entries and missing robot_settings/motion_speed fixture types. This was
  confirmed against the pre-task validator copy; unrelated contracts were not
  rewritten. The live gateway's ComfyUI interpreter has WebSockets 16, so the
  integration test harness used the repository-pinned 10.4 import path.
- Live Stand sequence 7 completed with the feedback reader disabled; outputs
  stayed armed and fault-free for the five-second follow-up. The settings API
  requires coordination/jam disabled when deliberately turning the reader off;
  unexpected reader loss with those features enabled is covered by native tests.
- Live Stand sequence 8, with reading and coordination enabled, completed with
  `position_verified:false` when the immediate post-write observation was not
  yet available. Outputs remained armed and fault-free during the five-second
  follow-up, with no correction replans. Feedback subsequently reported all
  twelve calibrated signals usable. This verifies graceful completion; the
  receipt deliberately does not claim measured arrival or physical standing.
- Restored the owner's settings: reader on, coordination off, jam off, arrival
  tolerance 400 us, jam tolerance 200 us, no-progress window 3000 ms, progress
  threshold 15 us. No release command or physical wiring fault was introduced.

Private build/install/capture evidence is in
`/tmp/ainekio-feedback-degraded-20261020`. No supply-voltage fault was injected;
actual power-rail monitoring remains unavailable with the current sensors.

## 2026-10-20 — Learning-window reset and recorder transport repair

Loaded forward and backward commands completed after the ground inspection,
but the learning service was not reliably producing observations. Two distinct
host defects were investigated:

- A trace HTTP request took 18.979 seconds during the earlier backward trial,
  overflowing the P4 recording buffer by 1,430 records. The host now reuses its
  per-robot HTTP connection instead of opening a TCP connection for every batch.
  Failed requests are surfaced without replaying model installations. The
  socket change addresses connection churn; it does not prove the cause of
  every network stall. Since the subsequent reload, completed forward, backward
  and turning trials have reported zero lost trace records. One peer reset was
  reported and the existing recorder resumed.
- `model_active` changed whenever a fourth-wire observation was briefly
  unavailable. Including that flag in the training-window identity repeatedly
  reset the window even though the selected model and commanded gait were
  unchanged. Availability is now recorded within the window. Unusable joint
  samples do not enter the tracking-error calculation; the result includes
  unavailable-observation and active-model counts. Command, calibration,
  profile and model changes still separate observations. Regression coverage
  now reproduces alternating usable/unusable feedback with an active model.

The camera worker now tracks fixed 3-D feature landmarks with OpenCV PnP,
using MoGe-2 depth for new landmarks, instead of interpreting independent depth
predictions as dense scene motion. Matched landmarks retain their world points;
new depth is aligned to their scale. Failed fits retain the previously approved
new-reference/unknown-gap behavior. Ordinary robot reconnection preserves
estimated intrinsics when image size and source settings are unchanged.
The old `moge-open3d` configuration value remains compatible; the reported
source is `moge2-landmark-odometry`.

Validation: 63 focused recorder, camera, depth and measurement tests passed.
Live recording `20261020-142345-edf0d844` produced scored forward, left-turn
and right-turn observations after the window fix. Other windows remained
unscored because camera tracking was lost; those are not zero-distance results.
The current shared Walk optimizer still requires repeated observations in all
four directions before proposing a candidate. At this checkpoint no new
candidate had yet been installed or demonstrated superior.

Camera exposures around 178 ms still cause motion blur. Learned metric depth,
estimated optics and camera-origin travel are not surveyed distance, body
height, foot contact or energy measurements. No claim of an optimal gait or
verified metric travel follows from these repairs. Changes in this section are
host-side; no test-specific code or flash was added to the firmware. Private
trial receipts and images remain under `/tmp/ainekio-depth-20261020` and the
existing private gait-learning state directory.

## 2026-10-20 — Preserve powered motion through controller loss

Owner requested finite work continue during a Body Control disconnect and
open-ended movement finish gracefully rather than dropping the robot.

Confirmed cause: P4 controller send failure, WebSocket loss, stale-control
handling and Wi-Fi disconnection directly invoked PCA9685 emergency disable.
This bypassed the motion owner and released powered supports. Automatic setup-key
creation and manual setup entry also had unrelated output-disable calls.

`0.8.113-p4-link-motion` removes connection-loss output release and routes the
retired connection identity asynchronously to the existing output owner. Finite
Stand, named clips, counted gaits and custom sequences retain local execution.
An open-ended gait uses `ainekio_v2_walk_update` with the existing zero-stride
Finish request, preserving its motion rate, committed foot paths and final
powered hold. No disconnect delay, new standing pose or polling dependency was
added. The retired-session watermark covers requests already accepted at loss
without allowing a delayed notice to affect a newer session. Session admission
still prevents stale/replayed remote work; reconnect does not fabricate an
unobserved completion. Explicit detach, power transitions and actual output
fault handling are separate and unchanged. This is P4-specific.

Validation: native body execution and feedback execution passed, including
identical write counts and final targets for finite Stand/Sit/counted Walk with
and without loss, continuous Walk/Crawl/Run/Crab loss during entry and mid-motion,
modeled grounded feet after Finish, retained armed outputs, and old/new-session
isolation. Gateway selection/session-fencing tests also passed. Integrated IDF
build passed. Physical disconnect testing is pending installation.

The owner said the concurrent full-speed-gestures agent will flash and requested
combination first. Both changes are already in the shared checkout. Verified
that `/tmp/ainekio-full-speed-gestures/p4/ainekio_p4_body.bin` is version
`0.8.113-p4-link-motion`, 3,396,464 bytes, SHA256
`48362864030f2923a5a19ba2a64642d8c29f44ce4ec59a5c5c597c81bcca133f`.
Its body/controller/network objects, with debug information stripped, match this
repair's tested build exactly. Generated clip data also matches exactly. Leave
flashing to that agent; do not install a competing image. Private build/test and
object-comparison evidence: `/tmp/ainekio-disconnect-motion-20261020`.

## 2026-10-20 — Live learning advances to candidate comparison

Further host repairs were required before the ordinary-walking learning loop
advanced reliably:

- Camera samples now enter the recorder from timestamped
  `locomotion_measurement` events. Polling the dashboard snapshot had inserted
  expired copies of previously valid frames into historical windows. Live
  freshness remains unchanged; historical measurements no longer expire
  retroactively. Actual image-fit failures remain unavailable.
- Camera optics are retained per image mode within the depth worker. A
  high-resolution still and return to preview had caused a different focal
  estimate, changing the measurement identity and archiving accumulated
  observations. Returning to a previously seen mode now reuses its optics.
  A worker restart still begins a new estimate and measurement context.
- An HTTP reconnect no longer clears a partly accumulated window. The device
  recording cursor and lost-record footer establish continuity. Boot/session
  changes and actual reported loss still separate observations.

All 65 focused depth, recorder, camera and ground-measurement tests passed.
Offline replay of original camera events with the saved trace recovered ten
scorable windows out of fourteen; four remained unscored for actual tracking
failure or insufficient camera observations. This replay did not send commands
or manufacture distance across gaps.

Live evidence in private recording `20261020-143739-5841d12e`:

- The Walk baseline accumulated two scored windows in each of forward,
  backward, left-turn and right-turn operation.
- The service automatically generated and installed RAM-only candidate
  `1812f6acaace5790c46c81b9c0eee95b846df0563244f5d0e0c4520cfcb7bfad`.
  The native preview accepted the full proposed change for all four observed
  command conditions.
- Two matched windows per direction completed the first evaluation. The
  candidate did not demonstrate improvement under the existing comparison
  rule. The incumbent was retained; the candidate was not promoted to saved
  firmware policy. The host recorded the comparison and automatically advanced
  to generation 1 with candidate
  `2f46ffc9b81845895f58dc22351334b063ff3d7e322377b0ecc961fa7031147a`.
- Run separately accumulated two baseline observations and automatically
  installed candidate
  `eb87ddc9327ba40c98b201d62440732c1ccc7e6e198573ef4f3d589cb0fa5acd`.
  Its full proposed delta passed the Run preview. This did not replace the
  Walk bank or change the command's bounding gait to a trot.

This demonstrates a live Walk record/propose/install/compare/next-candidate
iteration, not convergence or a better gait. Logging and learning remain
enabled on this host and consume ordinary Body Control commands. Run candidate
evaluation was still in progress at this checkpoint.

Remaining limitations: metric distance is an unverified MoGe estimate; motion
blur can make individual camera windows unusable. HTTP peer resets still occur,
and the recording reported 213 lost records cumulatively by the first Run.
The firmware HTTP server currently allows two open sockets with LRU eviction;
concurrent dashboard maintenance traffic and the recorder can contend for them.
No socket-limit firmware change was made in this work. Camera gaps, missing
joint samples and actual record loss remain visible and are not converted to
zero error, zero travel or successful trials. Tests and runtime results must
not be described as proof of optimal walking, physical energy efficiency or
collision qualification.

### Ordinary-use learning and interrupted recordings

The owner reaffirmed that normal operation includes failed walks and
interruptions: learning should use the valid data that arrives, without
requiring repeated dedicated forward/backward trials. No further dedicated
motion sequence was started after this clarification. The last in-progress
Run completed; its bank had three scored observations (two baseline and one
candidate), so its comparison remains incomplete. No improved policy was
promoted during this verification.

Distinguish measurement quality from walking success. Valid measurements of
poor progress, vibration or tracking error are evidence against a candidate;
discarding those outcomes would bias learning toward apparent success.
Missing or unreliable measurements remain unknown, rather than being scored
as zero travel or zero error. The current recorder preserves completed scored
windows across subsequent interruptions and excludes unavailable samples.
Actual record loss, changed commands and recording sessions separate windows;
unfinished windows are not currently scored. Thus a whole recording need not
be perfect, although short interrupted segments may not yield an observation.

Logging and learning were left enabled for ordinary Body Control locomotion.
The final verification checkpoint reported 326 lost records cumulatively and
an HTTP peer closure. A separate WebSocket protocol error (`reserved bits must
be 0`) also occurred before a reconnect; its cause is unresolved. These are
measurement/transport limitations, not evidence of a gait improvement or a
reason to repeat physical trials indefinitely.

### Combined image installed on owner request

The owner subsequently requested flashing. Installed the combined full-speed-
gestures image identified above over Wi-Fi. Upload staged successfully despite
a temporary control disconnect on the previous `.112` firmware; after reconnect,
activation succeeded. Confirmed `.113` running and accepted in ota_0, with no
pending verification and ESP_OK. Body Control reconnected (epoch 11), output
ready/armed, output fault zero, display ready, calibration saved/not dirty.
Feedback/jam settings match the pre-install snapshot exactly. Installation
receipts are in `/tmp/ainekio-disconnect-motion-20261020/install`.

This confirms installation and boot, not a physical disconnect-under-motion
trial. The inactivity-to-rest timer remains unimplemented and is not included.


## 2026-10-20 — Owner-configurable shared inactivity timer

Owner requested normal lay-down after three minutes of inactivity, then asked
for adjustment in Body Control. Implemented `idle_rest_v1`: saved robot-owned
seconds (default180, zero disabled), a Mode and power minutes control, and the
existing authenticated maintenance path. A one-shot ESP-IDF timer notifies the
existing output task; no extra polling task or stack. Active motion/listening
and long speech defer rest; user commands and audio completion restart idle.
Telemetry, camera frames and read-only queries do not. One normal lay-down
retains powered outputs; new commands remain available. Manual calibration and
explicitly detached outputs are not automatically moved.

Native tests passed for exact expiry, active movement, long audio, replacement,
disable/reconfigure, powered rest, non-repeating lay-down, NVS reboot persistence,
and HTTP input/storage errors. Dashboard tests covered selected robot changes,
minutes conversion, disabling and stale replies. Authenticated gateway proxy
test passed. Integrated IDF application build passed. Installation and physical
three-minute observation are pending. DNDIY subsequently confirmed the robot
online on `0.8.113-p4-link-motion`; the rest update has not been installed.

## 2026-10-20 — Navigable learning history

Added **Body Control → Recordings → Learning history**. The read-only view
shows performance by observation order, filters by gait/measurement context
and matching command settings, and offers score, camera progress, IMU tilt/
angular motion, acceleration deviation and joint tracking measurements. Points
and an accessible paginated table expose individual observations. Expandable
candidate entries show profile changes, sensor-response coefficient changes,
comparison uncertainty, and whether improvement was demonstrated. History JSON
can be downloaded without changing the selected policy or starting analysis.

Current and archived measurement contexts remain separate. New scored
observations and candidate decisions save their recording time and generation;
older records explicitly show that their timestamps were not recorded. Existing
history is also archived before learning-setting resets or saved-model restore
clear active observations. This changes history retention, not the optimizer,
its evidence rules, robot motion or mechanical limits.

Validation: 23 focused service and authenticated route tests passed, including
history reads with recording off, robot/context separation, preservation of old
records without invented timestamps and no robot/optimizer calls from history.
A real Chrome check against saved data verified four Walk command conditions,
Run selection, point inspection, candidate differences, empty history, and a
390-pixel viewport without overflow. History requests were read-only. No test
walk or firmware update was used for this UI work.

Activation verified: the host service was reloaded with its existing environment;
the robot reconnected and reports logging/learning enabled with state `learning`.
The live history endpoint returned seven separate contexts, including current
Walk (16 scored observations) and Run (3). Authenticated Chrome navigation
opened the new page, displayed the current Walk chart and downloaded matching
history JSON. No browser exceptions or motion requests occurred in this check.
Private screenshots: `/tmp/ainekio-learning-history.png` and
`/tmp/ainekio-learning-history-live.png`.


## 2026-10-22 — Release servo drive after automatic rest

The owner requested reduced holding power after the inactivity lay-down.
`0.8.117-p4-rest-release` marks only the timer-started lay-down for output release
on successful completion. The same motion's cancellation/replacement discards
that action. Explicit lay-down commands retain their powered hold. The final
face remains available, commanded pulses become zero, and the unpowered pose
is no longer treated as a known shaft reference. A subsequent movement command
uses its normal output engagement path.

The PCA output owner releases OE through the existing disable implementation,
without cancelling already-admitted commands. Explicit detach and fault paths
still retire their generations. This avoids rejecting a command admitted just
before the automatic rest finishes. No timer, polling task, or extra hold delay
was added. Disabling PWM removes active holding drive; this hardware does not
switch off the servo supply rail, so zero standby current is not claimed.

Focused native body/feedback and PCA driver tests pass: automatic release,
restart via Stand, no release while frame writes time out, normal manual
lay-down hold, replacement/cancellation, and command-generation continuity.
Integrated ESP-IDF application build passed. The installable app is preserved
in `/tmp/ainekio-rest-release-20261022/ainekio_p4_body.bin`. Physical power
reduction and installation remain pending.

## 2026-10-27 — Neural walking training, guided steps and visible progress

The owner requested continuing toward a walking robot, visible training videos,
and an update to this existing journal. The owner reaffirmed that the destination
is adaptive neural locomotion, including turning and transitions from a 10% walk
through full walking speed into Run. A useful forward gait is the starting
curriculum; it does not replace that complete objective with one fixed sequence.

### Robot representation and existing owners

The separate `Master/gateway/neural_gait` service uses the frozen read-only
Wireless CAD export, articulated linkage and boot collision surfaces. The model
has the owner-reported **650 g total mass and twelve servos**, with the maintained
35/20/28/38/55 mm mechanism and captured per-joint calibration. Training uses the
advertised **60 degrees per 0.11 seconds**, approximately 545 degrees/second.
It does not change the robot's saved speed setting. Component mass distribution,
loaded motor torque/gains, friction and electrical/network delay remain estimates
or unmeasured; matching CAD does not establish a physically identified plant.

The simulator reuses the existing foot IK/calibration/ramp/PWM helpers, production
fourth-wire filter/jam math and IMU estimator. Its policy receives 148 sensor and
command features and produces twelve standing-relative foot offsets. These
offsets are not twelve arbitrary independent joint angles. Sensor acquisition
cadence, channel skew, usability and sample ages are represented; unavailable
vision remains marked unavailable. Simulator displacement is reward/evaluation
evidence, not privileged velocity silently passed to the policy.

`GaitLearningService` remains the existing physical recording/history owner.
The standalone neural service owns simulation training and inference previews.
The physical integration must extend the current Walk motion/session/sequence
owner and preserve Stop, Release, Finish, updates, calibration, leveling and jam
events. The existing learned-residual hook is not an interchangeable destination
for an absolute standing-relative policy. Repeated Freestyle plans would bypass
parts of the walking correction chain and are not the planned integration.

### Results, including failures

All results below are **simulation**, not physical qualification. Forward is
body/world +X for the initial pose; sideways displacement and heading must also
be checked rather than counting any motion as walking.

| Experiment | Measured result | Interpretation |
| --- | --- | --- |
| Native forward baseline, full CAD plant | 0.424 m backward over 5 s; upright | Existing forward request failed in this plant. |
| Independent-joint neural output | All 100 sampled requests geometrically rejected | Replaced by foot-space output through existing IK; holding still was not learning success. |
| Foot-space SAC continuation, 60,000 total transitions | Final reference checkpoint 0.148 m backward over 10 s; no falls/rejections | More unguided cycles did not establish forward walking. |
| First 64×64 neural actor, 10,000 imitation updates | From reset: 0.083 m forward, 0.018 m sideways over 14 s; no fall | First useful forward neural rollout, with remaining foot scraping and drift. |
| Same first actor, longer evaluation | 0.456 m forward, 0.160 m sideways over 60 s; no falls/jams/rejections | Sustained movement, not straight or fully qualified walking. |
| More complex full-startup demonstration, plain imitation | 10,000 updates: 0.151 m backward; 40,000: 0.042 m backward over 14 s | Lower training error did not ensure a good executed trajectory. Failed candidates are retained. |
| Aggregated-state imitation prototype, best round 7 | 0.139 m forward, 0.013 m sideways over 12 s; no falls/jams/rejections | Neural-only evaluation after 17,000 supervised updates using 4,800 collected states; no teacher or elapsed-phase clock executed during evaluation. |
| Cleaner neural actor, best prototype round 4 | 0.0366 m forward over 16 s; no falls/jams/rejections | Learned-only rollout after 11,000 updates and 4,000 collected states. A 60 s test travelled 0.134 m forward but ended with 25.5 degrees heading error. |
| Cleaner guided stepping example, `immediate-supported-lift15` | 0.0467 m forward over 16 s; minimum upright cosine 0.992; no jams/rejections | Slower teaching example; after the initial 4 s amplitude ramp, all four feet have zero floor contact during measured horizontal swing. Startup contact is retained, not omitted. |

The aggregated-state prototype labels states encountered by the learner using
the next reachable point on a demonstrated cycle, selected from the preceding
requested foot action. This addresses rollout errors that plain imitation did
not cover. It is an offline teaching method; it does not add another physical
motion controller. The cleaner stepping demonstration is the next learning
source, not a claim that the faster neural candidate already has clean clearance.

### Why the rear feet scraped, and why the reward needed correction

The existing IK fitting reduces a requested offset when the coupled leg cannot
reach it. Larger requested lift therefore did not always produce larger actual
lift: one rear-leg example reduced a 30 mm request to 15 mm, while a 50 mm request
reduced to 12.5 mm. Moving the path without considering load transfer could also
leave the rear feet loaded. These were trajectory/workspace and support issues;
the comparison did not justify altering calibration or inventing different
physical geometry.

Targeted reachable paths and support transfer produced the cleaner guided
example above. During steady horizontal swing its minimum whole-boot clearances
were approximately **2.51, 0.77, 10.54 and 10.61 mm** in rear-left, rear-right,
front-left, front-right order. This is simulator contact evidence, including
soft-contact limitations; physical carpet clearance remains untested.

Compressing the same clean path to 1, 1.5, 2 or 3 second cycles produced backward
travel despite staying upright and accepting all targets. Even the 1 second
case cleared the boots during steady horizontal swing. Therefore clearance and
faster timing alone are insufficient: propulsion, coordinated tracking and
actual travel must be learned and measured together.

The earlier reward squared instantaneous translation/yaw error. It penalized
normal cyclic sway so strongly that a useful forward example scored below
standing. Environment version 6 changes the objective to the per-step change
in a bounded cumulative tracking score: mean travel and mean yaw track the
requested velocity and turning rate; standing for a movement request scores
zero, and wrong-direction travel remains negative. Positive accumulated travel
also depends on endpoint uprightness/body support. Effort and action-change costs
remain separate. This is training reward accounting, not a delay or a new robot
motion restriction. The maintained reward regression passed: recorded forward
crawl aggregates beat standing at two requested speeds, backward travel stays
negative, reset clears accounting, and ending fallen removes positive travel
credit. The focused 36-check suite passed after the reward change.

The forward neural results in the table were produced by imitation under the
earlier environment version; **they are not evidence that the revised reward
has already improved an RL run**. Version 5 sensor/action demonstrations remain
usable for imitation because physics and observations are unchanged. Its stored
SAC replay rewards are not interchangeable with version 6.

The aggregation method is now implemented in the existing trainer/replay owners,
with source-data hashes, immutable per-round checkpoints, retained failed rounds
and exact selected-policy publication. Its maintained eight-round run performed
19,000 updates and selected the 15,000-update checkpoint: only 0.0138 m forward
over 16 s, worse than the earlier cleaner candidate. Changing collection random
choices changed the result; the stronger prior checkpoint was retained. This
remains empirical training rather than evidence of monotonic improvement.

A subsequent fixed-data capacity comparison used the same 4,000 states and
batch schedule. A 128×128 actor reached 0.0449 m forward over 16 s without falling;
the 64×64 fit went backward. Its longer 60 s trial reached 0.160 m forward and
0.049 m right, ending 20.3 degrees off heading. It remained upright with no fit
reductions, but its 2.67 mm/s mean forward speed is far below the requested
80 mm/s. Its contended training times were 25.7 versus 23.6 seconds.

The subsequent 50,000-transition, two-worker SAC continuation completed under
reward version 6. It learned substantially more movement: 0.315 m forward and
0.387 m right over 16 s. However, it turned 122.5 degrees and slipped heavily;
a 60 s trial ended 1.226 m backward and 1.424 m right after turning 227.9 degrees.
The absence of falls or rejected frames did not establish a correct walk.

That trial exposed two reward-coordinate defects: forward travel rotated with
the actual chassis instead of retaining the commanded heading, and sampled
body-axis gyro Z undercounted world heading change. Version 7 measures horizontal
world displacement in the requested heading frame and unwraps actual world yaw.
Requested turning advances the reference; accidental turning does not. These
ground-truth values are reward/evaluation evidence only, never policy inputs.
Regression coverage includes accidental turns, commanded arcs, initial heading,
angle wrapping and vertical/body-gyro independence.

Foot slip now has an independent measurement: positive contact-force-weighted
tangential contact-point speed squared, divided by body weight, averaged over
every 500 Hz physics substep. The cleaner 128×128 policy measured 0.00210 m²/s²;
the sliding SAC policy measured 0.02586 m²/s², a 12.3× difference. The callback
leaves trajectories bit-identical but adds 35–38% wall time in the paired local
benchmark. It is simulation evidence, not measured physical slip or Q6A timing.

Paired 16 s evaluations of unchanged weights under the corrected coordinates
gave mean total reward per step of −0.00615 standing, +0.02405 cleaner64,
+0.03072 cleaner128 and +0.01639 sliding50k. A continuous slip cost coefficient
of **1 s²/m²** was selected for version 7: the same trajectories score −0.00619,
+0.02233, +0.02862 and −0.00947 respectively. Thus clean progress keeps over 93%
of its score while sliding is worse than rest. This is an offline learning
objective, not a robot restriction. Two 20,000-transition comparisons completed:
the cleaner128 initialization ended +0.061 m forward/+0.165 m lateral; the mobile
initialization ended −0.025 m forward/−0.216 m lateral. Both regressed relative
to useful straight walking and remain retained as failures.

A subsequent handoff audit found a concrete cause: deterministic imitation had
never trained the SAC `log_std` head. The clean128 actor's typical stochastic
action perturbation was about 47 times its intended inter-frame movement. Its
deterministic 16 s trial moved +0.0449 m, while stochastic collection from the
same weights moved −1.701 m with 37.6× more slip. Default entropy coefficient 1
also contributed a term around 13.96 on teacher states versus 0.0286 mean task
reward per step. This is a training-distribution/objective-scale defect, not
evidence that the physical robot needs a different controller. The audit is
`build/neural-gait/geometry-review/exploration-audit-env7.json`.

In parallel, a bounded twenty-candidate guided-data probe coordinated stride,
support shift and cycle duration. Its best teaching example reached 0.313 m in
16 s, −0.0036 m lateral and −2.76 degrees yaw, without falls, fit reductions or
jam reports. A lower-slip alternative reached 0.238 m. Both still show some rear
boot contact during early horizontal swing; neither is claimed physically clean.
The complete source and failures remain in
`build/neural-gait/guided-steps/speed-curriculum-probe-results.json`.

Training the 128×128 actor on the earlier 0.235 m guided candidate produced a
neural-only selected round that moved **0.252 m forward in 16 s**, 0.033 m lateral,
ending 3.37 degrees off heading. Minimum upright was 0.9935, slip score 0.00250,
maximum joint tracking error 10.16 degrees, with no falls, fit reductions,
rejected frames or reported jams. The run is
`build/neural-gait/4844fa3392fa4ca4b4376deac3794ead`, selected aggregation round 6.
It adds 15,000 imitation updates to its 15,000-update source; later failed-to-
improve rounds remain available. This is 5.6× the earlier clean128 forward
distance. Its 60 s neural-only test reached **0.983 m forward**, 0.078 m lateral,
ending −7.23 degrees off heading (maximum deviation 10.15 degrees). It remained
upright, with no fit reductions, rejected frames, jams or falls. Mean slip score
was 0.00236; peak shaft tracking error reached 15.66 degrees. The original
16 s evaluation is retained separately from `long-evaluation.json`; neither is
physical qualification.

Reward-only revisions preserve the sensor/action and physics contracts. Old
imitation data and inference remain usable, but old replay rewards are not reused
for version 7. The existing trainer now has explicit actor-only initialization:
actor weights and entropy temperature are retained; critics, replay, optimizer
state and RL counters start fresh. Source hashes and transferred state remain in
the new manifest. Exact resume still requires matching reward semantics.

### Distance, adaptation and the remaining curriculum

The reward must favor movement at the requested direction and speed, rather than
maximum distance regardless of the request. Gyro data measures rotation, not
translation. Accelerometer integration accumulates velocity/position error;
real distance verification needs an external motion reference alongside IMU and
servo feedback. The existing camera/depth `locomotion_measurement` owner is the
intended source, with actual calibration, timestamps and uncertainty. Its
connection to neural execution/training remains unfinished. See
[VectorNav's inertial navigation explanation](https://www.vectornav.com/resources/inertial-navigation-primer/theory-of-operation/theory-gpsins)
for the distinction between inertial measurements and aided position estimation.

Remaining training and integration work is concrete:

1. Teach the cleaner forward stepping example and verify neural-only startup,
   sustained travel, boot clearance and drift with videos and measurements.
2. Train command-conditioned forward/reverse, lateral and turning motion, then
   change commands within episodes: low-to-high walking percentage, Walk/Run
   transitions and turns while travelling. Preserve existing percentage/stride
   semantics; they are not an established metres/second conversion.
3. Include uneven support, slip, jams and falls with sensor-driven correction,
   preserving the existing body-event/recovery owner and manual Stop/Release.
4. Integrate through the existing Walk owner, compare live calibration with the
   training capture, measure host/Q6A inference and network timing, and perform
   owner-observed physical trials. No trained neural gait is in production yet.

### Throughput, videos and runtime status

Training currently uses CPU physics and a small CPU network. Physics-only
throughput measured approximately 179, 299, 316 and 309 environment steps/second
with one, two, four and eight workers. Two workers are the smallest useful gain.
A full SAC comparison collected 2,000 transitions and performed 1,000 optimizer
updates in both cases: 41.5 s with one worker and 24.3 s with two. Other CPU work
overlapped the first measurement, so the observed 1.7× gain is not an isolated
speed guarantee. Parallel training preserves one optimizer update per transition.

The following are local ignored artifacts, not media committed to the repository:

- [First forward neural trial, labelled](../../build/neural-gait/cc3fe42ce50f4a56b92caab647f51d81/progress-video.mp4)
  and [clean footage](../../build/neural-gait/cc3fe42ce50f4a56b92caab647f51d81/clips/000000000-trial1-clean.mp4).
- [More complex imitation attempt that regressed](../../build/neural-gait/6692821f1ed948a4a787cd4d22f4c641/progress-video.mp4).
- [Original guided example](../../build/neural-gait/guided-steps/guided-crawl.mp4).
- [All nine maintained aggregation rounds](../../build/neural-gait/0f6006293e084eceb7951893c6f8a2e8/progress-video.mp4),
  153 seconds including failed/later rounds; the directory also retains a
  selected-only replay and the full clean/labelled footage bundle.
- [Improved clearance example, labelled](../../build/neural-gait/guided-steps/guided-clearance-improved.mp4)
  and [clean footage](../../build/neural-gait/guided-steps/guided-clearance-improved-clean.mp4).
  Both verified as 16 seconds/400 frames; replay matched the saved trace's final
  position. This is a teaching example, explicitly not the trained network.
- [Faster aggregated-state neural trial](../../build/neural-gait/eded4cc029124e27b96e1be533830a9e/replay.mp4)
  and [cleaner neural stepping trial](../../build/neural-gait/6d8ee2a01343418caa1a0393b1c6d090/replay.mp4).
  Their UUID directories retain exact selected weights, aggregate training data,
  source hashes and footage bundles. The faster policy was trained under version
  5 and explicitly re-evaluated under version 6 without changing its weights.
- [Larger actor comparison](../../build/neural-gait/2e90f1579fc14d5e9f483c61a90e0971/replay.mp4).
- [Six SAC checkpoints through 50,000 transitions](../../build/neural-gait/14b21a9747df4fdc8fca235c70a98d10/progress-video.mp4).
  This shows increased movement with unacceptable turning/sliding, not a
  completed walking system.
- [New 313 mm guided example](../../build/neural-gait/guided-steps/speed-curriculum-p2.5-s40-x0-y16-z12.mp4)
  and [238 mm lower-slip guided example](../../build/neural-gait/guided-steps/speed-curriculum-p3-s40-x0-y16-z12.mp4).
  Each has a matching `-clean.mp4`; all four are verified 16 s/400 frames,
  labelled as teaching trajectories, with exact final-position replay agreement.
- [First improved neural round](../../build/neural-gait/4844fa3392fa4ca4b4376deac3794ead/clips/000000000-imitation000018000-round000-trial1.mp4).
  The run retains all nine rounds, selected weights and full training-data
  provenance; the selected round and montage are rendered by the same owner.
- [Selected improved neural round](../../build/neural-gait/4844fa3392fa4ca4b4376deac3794ead/clips/000000000-imitation000030000-round006-trial1.mp4),
  [clean selected footage](../../build/neural-gait/4844fa3392fa4ca4b4376deac3794ead/clips/000000000-imitation000030000-round006-trial1-clean.mp4),
  and [all nine rounds](../../build/neural-gait/4844fa3392fa4ca4b4376deac3794ead/progress-video.mp4).
  The completed montage is 153 s. Footage ZIP downloads are built on request;
  the original clean and labelled clips remain in the run directory.

The standalone neural service was refreshed from its stale v1 contract to v3;
completed simulation runs and videos are visible in its history. The improved
`4844fa3392fa4ca4b4376deac3794ead` checkpoint is selected for the existing
**non-executing inference preview**, verified through the service response with
no selection error. Selection does not install firmware or activate neural
physical walking. Body Control now distinguishes imitation updates from RL steps
and reports the actual evaluation episode count. The focused maintained Python
suite passed 45 checks after the version 7 reward and initialization changes,
including sensor/geometry parity, contact slip, reward coordinates, fresh learning
state, checkpoint preview compatibility and authenticated no-motion routing. No
firmware flash, physical command, calibration change or Body Control restart was
performed in this training work. The owner confirmed the robot is powered off.

## 2026-10-28 — Training handoff and optimizer comparison

The owner resumed the paused walking work. The service still has
`4844fa3392fa4ca4b4376deac3794ead` selected for non-executing preview; no training
process survived the pause. Its 0.983 m / 60 s neural-only simulation is the
selected preview baseline. No new physical robot state is assumed.

The BC-to-SAC handoff repair is now implemented in `training.py`, with regressions
in the existing neural gait suite. It preserves deterministic actor outputs,
calibrates bounded action perturbations to observed demonstration error, and
primes the existing replay buffer with executed current-reward transitions.
It uses the selected data prefix, correct worker/terminal/timeout semantics and
fresh optimizer state when changing from imitation to SAC. The initial entropy
budget is explicitly 10% of measured deterministic advantage over standing.
These are offline training semantics, not physical operating restrictions.

Run `4e9da513399a4ffba734b4b475bd0088` used 5,600 selected demonstration states
and 1,600 actual priming transitions across two workers. Its fitted bounded RMS
perturbations were approximately 0.006–0.013 per joint, matching measured target
errors. Initial alpha was 0.00034623 and target entropy −67.3244. Both priming
episodes completed without falling. The stochastic initial-policy audit moved
0.2270 m forward / 0.0203 m lateral in 16 s, ending 9.08 degrees off heading;
deterministic execution remained 0.2521 m forward. This demonstrates usable
movement during collection after calibration, not only deterministic inference.

Nevertheless, 2,000 subsequent SAC transitions regressed to −0.5595 m forward /
2.5199 m lateral, ending about −90.3 degrees off heading, with mean slip score
0.10696 and 728 fit-reduced frames. This candidate was not selected. Its video
and complete failed-run evidence remain in its run directory. Correcting
initialization did not correct the optimizer's subsequent behavior.

The bounded comparison investigated clipped on-policy updates from the
same calibrated actor, with exact deterministic-action parity checked before
training. It stays outside maintained implementation until results justify a
change. In parallel, the guided-data probe was extended to reverse and
turning examples using actual foot geometry and body-twist directions; these
are not yet learned capabilities. The existing forward preview remains selected.

The valid PPO comparison retained the exact initial actor and calibrated action
distribution, with a 3e-6 learning rate and the algorithm's existing target-KL
setting of 0.02. Its 16,384-transition final policy travelled 0.98338 m forward /
0.00482 m lateral over 60 s, versus 0.98323 / 0.07794 m for the saved imitation
policy. Slip decreased from 0.002362 to 0.002055; final heading was slightly
worse (−8.40 versus −7.23 degrees), and total reward was slightly lower. Thus
this is evidence of preserved walking and improved straightness, not an
unqualified replacement. The best short-trial checkpoint was at 8,192 steps.
Artifacts are `build/neural-gait/guided-steps/ppo-calibrated-kl002-lr3e6-16384`.

Earlier PPO attempts are marked invalid as optimization comparisons: a default
rollout-buffer sampling cast rounded saturated actions to float32, corrupting
their likelihood ratios. The corrected disposable experiment checks the actual
store/sample/recomputed-likelihood path and retains float64 stochastic actions;
deterministic actor outputs remain identical. These experimental classes have
not been installed as a second production gait implementation.

On the owner's request to continue training, a single focused continuation
completed another 32,768 transitions from the valid 8,192-step checkpoint,
retaining its optimizer and settings. The selected new checkpoint is at 40,960
total transitions. Its directory is
`build/neural-gait/guided-steps/ppo-continue-8192-to40960`; source, intermediate
checkpoints, likelihood/update audits and evaluation results are retained there.

| Same deterministic 60 s simulation | Forward travel | Final lateral displacement | Final heading | Mean slip score | Mean reward per step |
| --- | ---: | ---: | ---: | ---: | ---: |
| Selected imitation preview | 0.98323 m | +0.07794 m | −7.23° | 0.002362 | 0.22604 |
| Starting PPO checkpoint, 8,192 steps | 0.98970 m | +0.01585 m | −7.26° | 0.002313 | 0.23545 |
| Continued PPO checkpoint, 40,960 steps | 1.01168 m | −0.00547 m | −5.96° | 0.002161 | 0.23997 |

All three completed without simulated falls, jams or rejected targets. The new
candidate gains 2.2% forward distance over its starting checkpoint in this long
trial, but its 16 s result is slightly worse: 0.25881 versus 0.26548 m forward.
This is modest, horizon-dependent improvement in one deterministic forward case,
not evidence of speed, terrain, recovery or direction generalization. Actual
average speed remains about 0.0169 m/s against the requested 0.08 m/s.

The new [labelled video](../../build/neural-gait/guided-steps/ppo-continue-8192-to40960/clips/ppo-000040960-trial1.mp4)
and [clean video](../../build/neural-gait/guided-steps/ppo-continue-8192-to40960/clips/ppo-000040960-trial1-clean.mp4)
show the 16 s evaluation, followed by a labelled one-second display hold.
Both are 1280×720 at 25 fps. Rendered displacement matches the saved evaluation;
`video.json` records checkpoint hash and provenance. PPO remains an experimental
saved candidate, not an activated physical controller or replacement service
model. The existing service preview remains on the imitation model.

The owner also requested consolidation to prevent agent churn. One implementation
agent completed command-conditioned curriculum support, one reviewer reviewed
the completion milestone, and the primary agent owns training, integration,
selection and videos. Supporting agents have finished their scoped work.
No additional parameter searches are queued.

The existing trainer now retains each demonstration's SI command, collects and
evaluates every selected command per aggregation round, and preserves command
sets through saved manifests and continuation. The existing renderer includes
each evaluated command rather than dropping cases that reuse evaluation seeds.
Review found one source-integrity gap: observation commands were validated only
for multi-command input. That check now also applies to single-command input,
with regression coverage. These changes enable a multi-command curriculum;
they do not mean this forward-only candidate has learned reverse or turning.
Final focused verification passed all 53 neural-gait, sensor and authenticated
dashboard/no-motion tests. No Body Control restart, firmware change or physical
robot command was performed.

Reverse/turning teaching probes remain **rough data, not promoted training**.
Completing a larger nominal lift did not clear the rear boots: 652 of 660 examined
rear horizontal-contact samples already commanded the quantized boot at/below
the floor under actual body tilt. At the same body height with level orientation,
the corresponding clearances were positive. Some larger lifts also required
IK fitting reductions. This identifies support/attitude and reachable workspace,
not merely slow shaft tracking.

The missing neural moving-balance handoff is now implemented in the simulator:
`simulation_foot_target` uses the shared frame-to-pose conversion, selects nominal
contact anchors, and calls the existing `balance_configured_apply` before
calibration/ramp/mapping. Posture's former private conversion moved into the
existing geometry owner and its callers now use that function. No competing
balance controller was added. The captured device profile contains calibration
and feedback, not saved balance enable/tuning; the new comparison explicitly
enables balance with strength/damping 1 and zero roll/pitch offsets. Older runs
retain disabled behavior. No physical robot settings or firmware were changed.

The paired 16 s baseline with the same 40,960-step policy reproduced the old
disabled result exactly (0.25881 m forward). Enabling balance produced 0.26098 m,
reduced the slip score from 0.002820 to 0.002511 and lateral travel from 13.5 to
8.8 mm, but heading worsened from −2.90 to −5.25 degrees. This is a measured
handoff comparison, not a claim that all foot-clearance issues are solved.
Continuation retained that policy and optimizer for another 32,768 transitions,
finishing at 73,728 total steps. Its best 16 s checkpoint was at 45,056:
0.26511 m forward, +12.6 mm lateral, −3.71° heading, mean reward 0.23527.
Over 60 s it travelled 0.99358 m with −18.7 mm lateral, −9.87° heading and
mean reward 0.22526. The starting policy with the same balance setting travelled
0.99921 m with −41.5 mm lateral, −12.65° heading and reward 0.22899. Thus the
continuation improved final drift/heading but slightly reduced forward travel
and reward and increased slip; it is not an overall improved replacement.
Neither trial fell, jammed or rejected targets. Results and video belong to
`guided-steps/ppo-balance-40960-to73728`; the service selection remains unchanged.

The three existing reverse/turning teachers were also compared with balance
enabled, without a parameter sweep. Rear-foot contact during intended horizontal
swing remains substantial (roughly 46–70% of samples). Existing moving balance
is now connected, but that alone does not fix the support/clearance trajectories.
The probes remain rough data outside the promoted curriculum; repeated training
on them would reinforce the remaining defect. Comparison evidence is
`guided-steps/balance-direction-comparison.json`.

### Training storage correction

The owner's storage report exposed large unnecessary binary storage, not repeated
training from random weights. The preceding PPO run retained the 8,192-step
checkpoint and optimizer, and the current run retains the 40,960-step checkpoint.
Source paths and SHA-256 hashes are recorded in their experiment metadata.

The storage audit found roughly 2.2 GiB of compiled simulator binaries, 1.3 GiB
of uncompressed SAC replay buffers, 352 MiB of duplicate footage bundles, and
only 45 MiB of NPZ data. Existing owners now write losslessly compressed caches
and replay buffers; historical replay remains readable. All twelve completed
replay buffers were compressed with decompressed SHA-256 equality checked before
original removal, reclaiming 1,223,942,544 bytes. The compiled-cache migration
also checked byte identity. Videos, model checkpoints, calibration, datasets and
source/evaluation metadata remain preserved. Footage downloads are now generated
on request into a temporary file instead of retaining another copy after every
render. No cleanup service or age-based deletion was introduced.
Fourteen existing bundles were removed only after every archive member matched
its retained source file by size and SHA-256, saving another 354,964,370 bytes.
Two older bundles remain because their manifests differ; they retain historical
evidence rather than duplicate bytes. The training tree fell from about 4.6 GiB
to 2.0 GiB while the next training continuation was running.

The separate neural service was restarted to activate the storage/download
changes; Body Control was not restarted. Its selected model remained
`4844fa3392fa4ca4b4376deac3794ead` with no selection error. A real 76,991,043-byte
footage download matched the retained clean selected clip, and left no ZIP on
disk. Final focused validation passed 57 Python tests and both maintained C
balance/posture tests. The nominal frame conversion and disabled neural path
retain previous behavior; enabled balance uses estimated IMU, including stale
sensor handling and reset. Physical operation remains unverified.

### Goal continuation: support-corrected curriculum

The owner cleared the stale goal and explicitly activated the complete neural
walking objective, including existing-owner integration and physical verification.
The next step addresses the deficient reverse/turn teaching data before another
learner update. No new physical robot state is assumed.

Exact replay of the reverse teacher confirmed that, even restricting to frames
with all three intended supporting boots positively loaded, the COM lies outside
their support triangle by mean 4.6 mm during rear-left swing and 7.1 mm during
rear-right swing. Front-swing margins remain positive. A support-shift correction
reduced rear drag substantially but exposed premature transfer toward the next
leg while the current swing was still landing. Correcting that timing eliminated
35 calibrated workspace fit reductions. Remaining late-swing drag is recorded
explicitly; these are improved candidates, not physically verified gaits.
Evidence is in `guided-steps/reverse-support-diagnosis.*` and
`reverse-supported-com-*.{json,npz}`, retaining actual phase windows rather than
using the old horizontal-swing mask for the changed timing.

The existing weights-only initializer now supports an explicitly changed command
or existing balance setting while preserving the observation/action meaning,
geometry, calibration and other physics. It records the changed task settings
and retains learned actor parameters; critics, optimizer and replay start fresh.
Exact replay resume remains strict. A regression caught and fixed inherited old
command pools overriding a new initialization command. Updated examples still
must match the new controller configuration; historical labels are not relabelled
as new observations. Focused initializer/curriculum tests pass.

Holding the full 25 mm rear lift through the corrected swing did not solve the
remaining problem: rear-right contact increased to 24.6% and 45 frames required
workspace fitting. This `reverse-supported-com-full-lift` trial is retained as
failure evidence, not selected data. It confirms that increasing lift alone is
not the next repair. The corrected-timing, shaped-lift candidate remains the
better support example, with zero fit reductions and roughly 15% rear drag;
reachable swing shape and support geometry still need joint treatment.

### First forward/reverse neural curriculum

Run `a13dd6c6cff04289ae2bfdc612a8acc7` transfers the selected
`4844fa3392fa4ca4b4376deac3794ead` actor's 30,000 imitation updates into the
explicit balance-enabled forward/reverse curriculum. This is not random
initialization. It adds 3,000 initial updates and three 4,000-update DAgger
rounds, collecting/evaluating both commands in every round. Fresh critics and
optimizer belong to the explicit weights-only task transfer; no RL replay is
mixed across task configurations.

The forward teaching trajectory requests +0.015 m/s. The improved but imperfect
reverse trajectory was executed again with a −0.03 m/s request, near its measured
−0.0323 m/s travel; its sensor observations were newly recorded, not edited in
place. Rear drag remains about 15% during its intended horizontal swing, so it
is explicitly experimental data, not an approved clean physical gait. Trying
this improved example tests command learning without making perfect teacher
clearance an artificial barrier to all model development.

| Checkpoint, 16 s trials | Forward request X / Y | Reverse request X / Y |
| --- | ---: | ---: |
| Starting actor, same new configuration | +0.25164 / −0.02676 m | +0.25703 / +0.00312 m (wrong direction) |
| 33,000 updates, round 0 | −0.491 / +0.062 m (wrong direction) | −0.560 / +0.006 m |
| 37,000 updates, round 1 | +0.115 / −0.007 m | +0.015 / +0.094 m (wrong direction) |
| Selected 41,000 updates, round 2 | +0.08879 / −0.03348 m | −0.39329 / −0.00417 m |
| Final 45,000 updates, round 3 | −0.081 / −0.022 m (wrong direction) | −0.484 / +0.022 m |

Selection preserves round 2, not the latest optimizer state. The model now
distinguishes both requested directions in those fresh-start trials, but forward
travel regressed and longer qualification is inadequate. Over 60 s the selected
model travels +0.48336 / −0.10841 m for Forward and −0.42708 / +0.01482 m for
Reverse; reverse progress largely stops after its initial movement. A continuous
Forward → Reverse → Forward trial without resetting state moves +88.8 mm,
−1.3 mm and +109.8 mm along X in its respective 16 s segments. Neither test
fell, jammed or rejected targets, but that does not make the failed reverse
transition successful.

The next curriculum must include longer execution and command transitions from
the current physical state, rather than only independent command resets. These
results do not justify physical activation or a service-model replacement.
`long-evaluation.json`, `direction-transition-evaluation.json`, initialization
evidence, full aggregation data and per-command videos remain in the run.

The completed [four-round comparison video](../../build/neural-gait/a13dd6c6cff04289ae2bfdc612a8acc7/progress-video.mp4)
contains all eight command trials (136 s), including failed rounds. Selected
[Forward](../../build/neural-gait/a13dd6c6cff04289ae2bfdc612a8acc7/clips/000000000-imitation000041000-round002-command1-trial1.mp4)
and [Reverse](../../build/neural-gait/a13dd6c6cff04289ae2bfdc612a8acc7/clips/000000000-imitation000041000-round002-command2-trial1.mp4)
clips each contain 16 simulated seconds plus a one-second final display hold;
clean counterparts are retained. The goal remains active and physical execution
has not been enabled.

### Outcome learning and continuous request changes — October 28

The owner clarified the objective: fluid movement, useful distance and efficiency,
with IMU/feedback informing what is happening, without requiring a particular
leg sequence or shoulder pattern. New prescribed-cycle teacher experiments have
stopped. Existing learned actors remain warm starts; imitation fit is not the
criterion for future improvement.

The selected two-command actor's `shoulder-audit.json` confirms the observed
synchrony: shared lateral foot action explains 99.9997% of lateral-action
variance; nominal shoulder velocity correlations have magnitudes 0.964–0.972.
Nominal shoulder standard deviation is about 14 degrees, compared with roughly
0.4 degrees RMS from existing moving-balance corrections. The shared teacher
body translation, rather than a large gyro correction, dominates this pattern.
This is evidence about the source of the movement, not a requirement to eliminate
all simultaneous shoulder movement. Gyro/acceleration are inputs, but that alone
does not establish that the learned actor uses them effectively.

Continuous request evaluation now uses `GaitEnvironment.set_command` without
resetting physics, fourth-wire history, IMU, previous action or global time.
Per-request reward accounting begins afresh so earlier travel is not recredited
under a new command. Collection/evaluation records each segment's displacement,
heading and outcome; replay follows that same schedule. Regression coverage
compares evaluated and replayed physical displacement and heading, and verifies
that each action sees the intended command. The 58-test neural suites passed;
the additional replay parity test also passed independently.

The bounded `guided-steps/outcome-transitions-32768` experiment transfers the
41,000-update actor exactly into the previously audited squashed PPO policy.
It adds no teacher targets. Four simulators issue Forward/Reverse/Forward and
Reverse/Forward/Reverse over continuous 48-second episodes. Actor parameters
are retained; the PPO value function and optimizer start fresh. Exploration
uses the previously validated bounded distribution, and all hardware/physics
settings are unchanged. The runtime-selected model remains unchanged.

The reward still has a known learning limitation: cumulative travel, elapsed
request steps and command-reference heading affect its potential but are absent
from the actor/critic observation. Its practical contribution to poor learning
has not been established. A late support change can also alter accumulated
potential. The current bounded experiment should establish an outcome before
changing this objective or adding critic state; it is not evidence that the
reward-history issue is resolved.

The 32,768-step outcome run completed in 299 seconds of training/checkpoint
evaluation, excluding its initial baseline and subsequent rendering. Its highest
mean-return checkpoint is 8,192 additional RL steps. In Forward/Reverse/Forward,
the three world-X displacements changed from +88.8/−1.3/+109.8 mm to
+151.2/+4.6/+137.1 mm. Reverse after Forward still makes negligible requested
progress and drifts laterally by 37.9 mm; this is a failed transition despite
improved average reward. In Reverse/Forward/Reverse, displacements changed from
−393.3/+125.8/−151.1 mm to −332.7/+104.7/−188.3 mm. Neither evaluated episode
fell. These are mixed results, not a walking qualification or production promotion.
The selected checkpoint and both 48-second transition videos are retained in
that run; later checkpoints remain evidence of regression.

The evaluator/video command-transition repair passes the full 59-test neural
suite. One experiment-only monitoring field was removed: collected mean reward
had been read after SB3 cleared its rollout buffer. Evaluation returns, measured
displacement and before/after policy likelihood audits were independently
computed and remain valid. The executed script and correction note are retained
with the experiment; the disposable script was corrected for later reuse.

An independent `imu-distance-audit` on the earlier two-command actor recorded
3,329 simulated IMU samples over 16 seconds. It integrates calibrated body
acceleration after orientation/gravity compensation, with no contact or visual
correction. The simulated IMU mounting point travels +86.6/−48.4 mm horizontally
(different from torso-origin displacement because of its mounting lever arm).
Direct integration using simulator-truth attitude still has 4.88 m horizontal
error; using the production attitude estimate has 82.60 m error. This is a
simulation diagnostic, not measured LSM6DS3 accuracy: the first simulated
acceleration sample initializes attitude about 87.9 degrees from truth, and
impact sampling/integration error remains even with true attitude. Startup and
sensor bandwidth need qualification before this can support inertial odometry.
The additional 1 mg bias case is illustrative, not an installed bias measurement.
The raw samples, diagnostic script and explicit limitations are preserved. These
results must not be supplied as valid physical distance labels or used to claim
that camera/contact-assisted state estimation is already implemented.

Saved footage: [Forward → Reverse → Forward](../../build/neural-gait/guided-steps/outcome-transitions-32768/clips/outcome-008192-command1-trial1.mp4)
and [Reverse → Forward → Reverse](../../build/neural-gait/guided-steps/outcome-transitions-32768/clips/outcome-008192-command2-trial1.mp4).
Each labelled/clean pair is 49 seconds at 1280×720, including the one-second
presentation hold. Both replays exactly match their evaluated displacement and
heading; the command overlay was visually inspected after a direction change.
The experiment occupies 33 MiB, references existing source models/collision
assets, and creates no duplicate footage archive. The training/render process
completed successfully; the goal remains active and no physical execution was
performed.

### Reward-observation and IMU initial-state discrimination — October 28

Before changing the controller or reward again, a fixed-policy audit collected
six stochastic 48-second transition episodes from the selected 8,192-step
outcome actor. Four complete episodes trained value estimators; two complete
episodes were held out. Identical discounted realized returns, normalization
from training rows only, 128×128 networks and three optimizer seeds were used.
No policy or physical command changed during this audit.

| Value estimator inputs | Held-out return RMSE, three seeds |
| --- | --- |
| Current 148 observations | 72.05 / 71.88 / 73.72 |
| Observations plus full reward bookkeeping | 48.44 / 48.44 / 49.47 |
| Observations plus elapsed request steps only | **47.21 / 47.15 / 47.15** |

The clock control explains the practical benefit at least as well as the full
bookkeeping vector. This does not prove that cumulative reward alone caused
failure: elapsed time also predicts the scheduled command changes. It does
justify comparing a training-only clock critic against an equally fitted
sensor-only critic before adding more runtime inputs or changing reward terms.
`critic-history-audit.json/.npz` preserve the exact split and samples under the
existing outcome run. The synthetic experiment is small and not a physical gait
qualification. Training-only extra critic inputs are an established approach
([asymmetric actor-critic paper](https://arxiv.org/abs/1710.06542)); this experiment
still has to demonstrate better walking.

The paired continuation uses the same saved motion actor, reward, physical model,
two simulator workers per arm, and 16,384 additional PPO steps per arm. Both
critics are fitted to the same four training episodes before policy updates.
The experimental clock critic sees one additional scalar; the actor's feature
extractor removes it before any learned layer. Exact actor transfer and output
invariance under deliberately varied clock values are checked. Thus this is not
a phase clock or required leg sequence supplied to the motion policy, and it
does not enlarge the deployed actor or add a physical waiting rule. Experimental
artifacts are `outcome-transitions-32768/critic-control` and `critic-clock`.

The separate initial-state test holds the existing standing reference in actual
simulation physics for five seconds, then requests walking for 16 seconds; it
does not fabricate gravity samples or initialize attitude from ground truth.
After the first three walking seconds, mean tilt error falls from 3.12 degrees
in the cold-start case to 1.10 degrees with this prior sensor history. Forward
travel nevertheless falls from 88.8 to 59.3 mm. Better IMU startup alone therefore
does not fix this actor. The result describes two initial conditions, not a
runtime requirement to wait. `imu-standing-start-audit.json` and its source are
retained beside the earlier IMU audit. No firmware, physical IMU calibration,
Body Control lifecycle or robot motion was changed.

Both 16,384-step comparison arms completed. Their best saved checkpoints were
at 8,192 additional steps: mean transition return 904.79 for the fitted
sensor-only critic and 1,015.45 for the clock critic, versus 1,055.15 for their
starting actor. Both still fail Reverse after Forward. The clock-critic change
is therefore **not promoted at this training budget**. The method is not ruled
out: better held-out value fit did not yet establish a better walking policy.
The audit used finite-episode return targets while PPO
bootstraps time-limit endings; this shared limitation is retained with the
comparison. No experimental critic is registered in the production service.

The next bounded test addresses input conditioning. With all measured inputs
held fixed across 14,400 recorded states, switching the requested direction
changes foot targets by a median largest-component 1.30 mm; most individual
components change by less than 1 mm. The actor is not wholly insensitive to
commands, but the direct response is small. The request's forward values are
only +0.015 and −0.03 in the raw input vector, alongside much larger features.
`command-sensitivity-audit.json` records the counterfactual output measurements.

`actor-normalized` tests train-only input mean/scale with the first learned layer
algebraically transformed to retain the existing actor's initial function.
It adds no sensor fields, clock, prescribed motion labels, or runtime restriction.
The same critic initialization and PPO settings as `critic-control` make input
conditioning the intended comparison. Initial floating-point output difference
and a new baseline are recorded before updates; normalization statistics exclude
the held-out episodes. Small importable policy dependencies are retained once
in the parent run's `sources/` folder, with hashes, so future loading does not
depend on disposable `/tmp` scripts.

Input normalization preserved the initial actor within 0.00000370 normalized
action units. Its independently rerun baseline return was 1,053.79 versus the
source's 1,055.15. After 8,192 and 16,384 further updates, mean returns were
830.09 and 1,038.33. The starting policy therefore remains selected. The final
candidate improved Reverse-first travel to 601 mm and the later reverse segment
to 361 mm in the request frame, but Reverse-after-Forward still moved 10.2 mm
in the wrong direction and 43.3 mm sideways. This is not an overall improvement.

The failed normalized candidate is retained for inspection; no normalization or
critic variant was installed in production. Duplicate baseline video rendering
was intentionally interrupted after training completed, and only its unpublished
temporary files were removed. The 16,384-step candidate is rendered instead so
the owner can inspect the actual failed learning result. The next useful training
comparison should emphasize direction changes from diverse already-moving states,
while retaining complete Forward/Reverse transition evaluation; it should not
add another prescribed cyclic teacher.

The [rejected-candidate video](../../build/neural-gait/guided-steps/outcome-transitions-32768/actor-normalized/clips/failed-normalized-016384-command1-trial1.mp4)
shows the complete 48-second Forward/Reverse/Forward trial, plus the one-second
presentation hold. Its clean counterpart is retained. Both files are 1280×720,
1,225 frames, and replay exactly the evaluated displacement and heading. The
overlay was visually checked during Reverse. The normalized and both critic
policies were also loaded successfully using the retained source directory with
`/tmp` excluded from Python's module path.

`motion-start-curriculum` continued the saved 8,192-step actor, critic and
optimizer for 32,768 more on-policy steps. Four simulator workers first use the
frozen source policy for a sampled 0/4/8/12/16 seconds of either direction, then
request the opposite direction for 16 seconds from that actual reached state.
Native feedback, IMU and physics are not reset at the command handoff; the
preceding motion supplies no imitation labels. This increases experience of
direction changes from different poses without prescribing a joint sequence.
Qualification remains the unchanged complete 48-second F/R/F and R/F/R trials.
The run completed. Its best new mean return was 907.70 at 24,576 total PPO
steps, below the inherited checkpoint's 1,055.15. Every evaluated candidate
still moved forward during the Reverse-after-Forward segment. At the final
40,960-step checkpoint that segment moved 9.7 mm in the wrong direction. The
starting checkpoint remains selected; this budget did not establish improvement
from the moving-start curriculum. No physical model was changed.

### Timestamped host feedback handoff — October 28, source only

The existing 20 ms IMU event now optionally carries compact joint feedback from
the completed ADC scan, using the same calibrated filtered-position conversion
as firmware balance. The gateway projects one current-epoch packet through
`body_sensor_observation`; neural preview no longer invokes Freestyle's serial
HTTP observation requests. Measured and commanded angles, velocities, mapped
acquisition timestamps, scan/revision and health remain distinct. Missing values
are null on the wire, and old packets/reconnects cannot retain stale joint data.
Acquisition, the independent slow health event, jam/completion and Stop owners
are unchanged. The protocol and walking-system owners document paired activation.

The packet fixture is 1,798 bytes, about 89,900 bytes/s at 50 Hz, fitting the
existing 5,120-byte serializer workspace and 4,096-byte WebSocket buffer. New
snapshot/view storage is heap allocated (1,088 bytes in the host measurement).
Real P4 compilation reports 3,808 bytes static link-task stack plus a 928-byte
serializer frame against the existing 14,336-byte task allocation; dynamic libc
depth and live network timing remain unmeasured. The existing reply queue and
one-IMU-message cadence are retained.

Validation passed 52 gateway/observation tests, 29 body-event tests, two dashboard
preview tests, two native tests, and the root's subsequent 59-test neural suites.
Changed C units compile with the P4 SDK. Four broader protocol-suite fixture/
coverage failures reproduce with the unchanged schema and are baseline failures,
not claimed fixed here. No firmware was flashed, Body Control restarted, saved
calibration changed or physical movement requested. Physical packet cadence and
end-to-end latency are still required before a host neural Walk executor can be
qualified.

### Training lineage and fair comparisons — October 28

The owner challenged whether newer methods were being compared fairly with an
older trained model. The comparator in these recent runs is the best saved
**experimental** walking actor, not a continually updated production policy.
It remains frozen at 41,000 inherited imitation updates plus 8,192 outcome-PPO
steps. All recent motion actors inherited those learned weights; none was a
randomly initialized movement network. The independently selected preview
service still points to `4844fa3392fa4ca4b4376deac3794ead` and has not been replaced.

There are nevertheless important fairness limits. The two critic comparisons
and normalization trial initialized a new value function/optimizer and ran only
16,384 additional steps. The moving-start trial retained actor, critic and
optimizer for 32,768 additional steps. A short run below the frozen baseline
does not establish that its method is inferior or has reached diminishing
returns. Earlier rejection language applies to promoting those checkpoints,
not permanently rejecting the training approaches. The fixed transition cases
are development regressions, not an untouched generalization benchmark.

The active adaptive-exploration run now has a matched unchanged continuation,
`matched-baseline-65536`: same source hash, retained actor/critic/optimizer,
65,536 additional transitions, four simulators, seed1, request schedule, episode
length, reward and evaluation checkpoints. The experimental arm changes only
exploration's initial spread and whether it is learned. Both learning curves
and per-motion outcomes must be compared at equal added experience; a frozen
baseline remains a deployment reference, not the sole method comparator.
This first pair still has one training seed, so it cannot establish statistical
superiority or a learning ceiling. Both jobs completed their equal budgets; results are recorded below.


The partial matched results expose a selection limitation: mean episode return
can improve while one requested direction change still fails. At 24,576 total
PPO steps, the unchanged continuation scores 1,156.41 but moves 12.4 mm forward
and 31.9 mm sideways during its Reverse-after-Forward segment. Adaptive
exploration at 16,384 total steps scores 833.20, yet achieves 69.3 mm backward
with 6.3 mm lateral travel in that segment. Its later Forward segment drifts
115.5 mm sideways, so this is a learned capability with unresolved defects,
not a qualified gait. These differently timed checkpoints illustrate the
score's limitation; the matched learning curves compare equal additional steps.
The source's reverse segment achieves only 4.4 mm backward in the request frame
with 37.9 mm sideways; world-X alone is not the direction measure.

The adaptive 49,152-step checkpoint reaches mean return 1,075.49, with all six
requested-direction segment signs correct, but Reverse-after-Forward remains
slow (26.1 mm over 16 seconds), and another reverse segment drifts 94.0 mm
sideways. At that partial checkpoint the unchanged run was still catching up in wall
time. Those partial results did not establish a final winner. The reviewer recommends retaining useful
transition checkpoints independently of mean-score selection, then testing
consolidation with narrower exploration while preserving the learned actor,
critic and optimizer. No follow-on training choice is implied before this
comparison finishes.

[Matched learning curves](../../build/neural-gait/guided-steps/outcome-transitions-32768/matched-learning-curves.png)
show return, weakest requested-direction segment, heading deviation and contact
slip against **additional** training transitions. The figure now contains both completed budgets. A separate evaluation probes 12- and
20-second command switches for the source and both 16,384-step candidates;
it changes no weights. These are new developmental timing probes, not broad
held-out physical qualification. The adaptive 16,384-step F/R/F trial has finished rendering through the
existing replay owner; R/F/R rendering continues. The first clip is linked below. No firmware or runtime model
has been activated.


### Completed equal-budget comparison and next continuation — October 28

Both runs inherited the same 8,192-step outcome checkpoint and received 65,536
additional transitions. The unchanged continuation's best mean return was
1,156.40 at 24,576 total steps; adaptive exploration's best was 1,075.49 at
49,152 total steps, versus 1,055.15 at the inherited checkpoint. Their final
checkpoints were not automatically their best. The unchanged reward-best still
moves 12.4 mm in the wrong direction after Forward; adaptive reward-best moves
26.1 mm backward with 6.4 mm sideways in that segment. Adaptive also has a later
reverse segment with 94.0 mm lateral drift. Equal training budgets therefore
show a real tradeoff, not a uniformly superior method or a learning ceiling.

The first alternate-timing probe completed for the source and both 16,384-step
candidates. With 12-second switches, the source's first reversal travels 412.7 mm
backward; with 20-second switches it moves 7.1 mm forward and 52.6 mm sideways.
The adaptive early checkpoint also misses one Forward segment at 12 seconds.
This is state/timing-dependent transition failure, not absence of all reverse
ability. A second probe evaluates each completed run's reward-best checkpoint
at those same timings in parallel. Results remain developmental evaluations.

The useful next training direction is to preserve the learned actor/value/
optimizer, consolidate it with the original narrower exploration distribution,
and vary request-switch timing during collection. Wide exploration stayed near
its initial standard deviation while collected reward remained poor, despite
useful deterministic actions. This is an outcome-training change, not new
prescribed leg patterns. The maintained training owner is being extended to
resume PPO so continued work no longer depends on a disposable experiment driver.

[Adaptive Forward/Reverse/Forward video](../../build/neural-gait/guided-steps/outcome-transitions-32768/adaptive-exploration/clips/adaptive-016384-command1-trial1.mp4)
is 49 seconds including the one-second presentation hold, 1,225 frames at
1280×720. Its clean counterpart is retained. Replay displacement, heading and
command segments match the saved evaluation exactly; the Reverse overlay was
visually inspected. This footage illustrates both improvement and remaining
drift, not physical qualification.

The existing neural service/replay loader now supports explicit PPO artifacts
alongside existing SAC artifacts. The bounded-action precision distribution,
rollout buffer and frozen/learned exploration setting now have maintained
training-owner classes. The 40-test neural suite passes, including full-state
round trips and a clean-process load without temporary import paths. PPO training
continuation is the next owner extension, not claimed implemented by loading
alone. No running service or selected model was changed.


### Owner correction: task-directed walking, not legacy cycle reproduction

On October 28 the owner explicitly rejected framing neural completion as a choice
between distance/time targets and foot/cycle counts. The intended robot uses
existing MetaHuman goals, YOLOE/visual evidence, navigation, depth, body events
and feedback to follow a line/person, investigate an object, explore and adapt.
It does not march while idle. The shared body capability contract already states
this, and Core Active Task already owns goal progress, continuing follow/visual
behavior, steering updates and Finish. The integration discussion had narrowed
too far to legacy manual controls; that was an error in task focus, not a missing
owner decision. WALKING_SYSTEM now leads with the existing task-directed path.

Neural cycle counting is not being implemented. Native manual cycle controls
remain native. The neural source serves the existing continuous movement owner;
the task owner supplies changing movement intent and determines the endpoint
from evidence. The current straight/transition simulation results qualify only
low-level skills. They do not establish person/line following, exploration,
recovery or achievement of a physical task. Those remain required end-to-end
qualification, alongside actual geometry, sensors, calibration and latency.

The owner also reiterated using established robot walking systems rather than
continuing an open-ended series of local training variations. PPO is an
established optimizer, but selecting PPO alone is not adoption of a proven
locomotion pipeline. The next design comparison must trace published locomotion
implementations against our observations, actor/critic inputs, rewards, actuator
model, disturbances, command curriculum and deployment interface, and identify
specific reusable components. Existing trained artifacts/footage are retained;
no additional exploratory training run was launched during this correction.


### Established locomotion implementations: renewed source comparison

Primary implementations inspected after the owner's correction:

- [DeepMind MuJoCo Playground Go1 task](https://github.com/google-deepmind/mujoco_playground/blob/main/mujoco_playground/_src/locomotion/go1/joystick.py):
  separate commanded linear/angular velocity tracking, noisy deployable state,
  a richer privileged training state, action-change/energy/slip terms, and
  disturbance training. Its actor includes local linear velocity; our physical
  deployment cannot substitute simulator truth for an unavailable velocity
  estimate. The reusable target is the locomotion-task structure, not Go1
  dimensions, motor gains, pretrained weights or every morphology-specific term.
- [ETH legged_gym](https://github.com/leggedrobotics/legged_gym) and its
  [robot task implementation](https://github.com/leggedrobotics/legged_gym/blob/master/legged_gym/envs/base/legged_robot.py):
  command-conditioned velocity tracking, observation noise and randomized
  friction/mass/pushes, with actuator transfer treated explicitly. The project
  states that its maintained successor is Isaac Lab; the older repository is a
  research reference rather than an unexamined new dependency.
- [ETH perceptive locomotion](https://leggedrobotics.github.io/rl-perceptiveloco/):
  combines terrain perception with body/joint information through a recurrent
  encoder. This is evidence for adapting locomotion to environmental sensing;
  it does not make YOLOE detections a finished terrain map or task controller.

The current bespoke cumulative-mean reward differs from the direct commanded
velocity tracking in those implementations and carries history outside the
actor observation. Current trials also use a narrow command set, mostly fixed
conditions, no deployed aided velocity estimator, and no qualified recovery
curriculum. Further variations of the same short fixed-transition experiment
are insufficient as the main development strategy. Reuse must be explicit at
these owning components, retaining Ainekio's actual linkage/calibration/servo
model and the existing task-directed execution path. No off-the-shelf robot
asset or pretrained Go1 policy is a valid substitute for the 650 g V2 body.

The next implementation choice is to adopt an established locomotion-task
training design at the existing training/environment owner, with a source-backed
mapping of actor-available measurements, privileged training-only state,
command curriculum, reward, actuator/latency model and disturbances. The full
robot qualification remains task-directed adaptation, including actual follow/
investigate/explore execution and recovery, not simply matching a velocity in
simulation. This source review does not claim that migration or physical
qualification has already occurred.


### Preparing the owner-requested physical coffee-cup trial

The owner requested moving to actual recorded trials and correcting training from
physical inadequacies. The robot is ON and SUPPORTED; the selected task is to
walk to a coffee cup on the ground. No floor movement has been sent. Live TCP
and authenticated maintenance confirm `ainekio-p4-e6ebe5` at `10.42.77.48`,
firmware `0.8.129-p4-local-rest`, fourth-wire feedback enabled and no reported
stalled joints at the read. The existing recording's calibration matches the
candidate's twelve mappings exactly for channel, inversion, model Home, pulse
Home and microseconds/degree. This comparison uses the recording metadata;
physical arrival and loaded actuator behavior remain unverified.

The existing gait recorder omitted body-event fault notifications and new host
sample fields. Its command allowlist now preserves the host source/reference,
SI twist and foot sample; its existing event stream retains body events and NAKs.
The existing diagnostic subscription records neural inference/model/input-time
attribution in the same recording, while paired telemetry establishes which
sample was actually consumed. No new recorder or training-data store was added.
All33 maintained gait-learning-service tests passed, including a requested→
consumed→stall/rejection attribution case and absence of movement/optimizer
side effects. The running process has not yet been restarted with these changes.

The native learning setting was found enabled alongside logging. During the
controlled gateway restart it was changed to logging=true, learning=false in
the existing settings file. The existing sensing-controls owner now selects
neural walking for this robot, with requested 100% scales of 0.03 m/s forward,
0.03 m/s lateral and 0.3 rad/s yaw. These are experimental request scales, not
measured capabilities: 50% forward corresponds to the candidate's 0.015 m/s
training request. Turning and lateral performance are unqualified. The original
task/perception owner supplies steering and Finish; the learned controller does
not count cycles or declare the cup reached from an action receipt.

The inference service was restarted and loaded PPO candidate
`35be5800c94d45299dc8f793ee34914a`, with no training process running. The candidate
is the packaged adaptive 49152-step deterministic policy described above, not a
new training run. Gateway integration now handles producer errors through the
same Walk's Finish and reports failed execution to Core while retaining the
actual body terminal. Normal sensor advancement does not discard a valid
inference. A Walk fixes the model's yaw origin and quaternion sign once; updates
preserve them without resetting physical IMU tilt or body-frame readings.
Consumed-action attribution excludes entry frames, including the last entry
frame, until a host target actually supplies a successfully written output.
Gateway/dashboard/adapter checks passed 167 cases across the full run and two
corrected-import-path reruns; 61 native cases and 33 recorder cases passed.

**Activation incident, unresolved at this entry:** image
`0.8.130-p4-neural-walk` was uploaded once and restart requested once, but the
robot did not reconnect. The uploaded binary SHA256 was
`3e7426c20dd95fe22f8b63576b3ef84dc5d2e4acb54c2d7fcbf8a4abeecd402e`.
Inspection found the generated build configuration selected ESP32-H2 with SPI,
not the installed ESP32-C6 with SDIO, and omitted the committed rollback option.
The board defaults already specify C6/SDIO and rollback; successful compilation
was incorrectly treated as sufficient build qualification. This image is not a
valid installed-board build. Rebuilding from the complete board defaults and
recovering connectivity take priority over the trial. USB debug connection was
requested because Wi-Fi is unavailable. No neural Walk or coffee-cup trial was
sent, and no physical locomotion success is claimed. The retained hardware
heading correction versus the candidate's ENV7 training remains an explicitly
unqualified transfer difference after recovery.

Recovery preparation: after one owner power cycle the LCD showed odd static;
authenticated Wi-Fi reads still timed out. USB was unavailable, and the owner
was told to leave the robot off until recovery. The firmware's existing
acceptance owner requires an authenticated gateway Welcome and device startup
checks; that path was not observed. The installed bootloader's actual rollback
configuration remains unknown, so rollback success is not claimed.

The corrected application is now built as `0.8.131-p4-neural-walk` at
`Slave/firmware/esp32p4-wifi6/build/ainekio_p4_body.bin`, 3,415,168 bytes,
SHA256 `387439d4342597389c0703e884d9ad954d3a93db19f1c06cdbf6bb93ce8801b5`.
All 68 explicit committed board defaults match the regenerated configuration.
The owning build documentation now explains the full ESP-IDF export and why
reconfigure does not replace incorrect generated settings. The neural weights
remain exclusively in the host inference service, not in this firmware.
IDF reports static DIRAM 176,194/576,464 bytes; this is link usage, not evidence
of runtime heap, task-stack margins or absence of a hardware crash. USB recovery
is recorded below; physical locomotion qualification remains pending.

### USB recovery verified, servo power off

The owner connected USB with servo power off. Serial logs identified the failed
`0.8.130` image and its ELF prefix `46b7c3bad`, then the repeated assertion
`hosted_spi_init port_esp_hosted_host_spi.c:80 (ret==ESP_OK)`. This establishes
the observed reboot cause at the incorrectly selected radio transport; it is
not evidence of neural inference running on or exhausting the P4.

USB identified P4 revision 1.3. Reading the installed partition table and OTA
selection confirmed the full two-slot layout and selected `ota_1` at `0x820000`
(sequence 96). Both OTA entries had undefined image state (`0xffffffff`), not
pending-verification state; successful rollback was not observed. Recovery
wrote only the corrected application to that selected slot. Esptool verified
the flash hash; before/after reads proved the partition table, NVS, PHY and OTA
selection bytes unchanged. Bootloader, other application slot and asset storage
were not written.

Live boot reports `0.8.131-p4-neural-walk`, ELF prefix `b80abc5b7`, C6 firmware
2.12.8 and successful SDIO slot 1 startup on the specified pins. Authenticated
Wi-Fi maintenance at `10.42.77.48` reports running/boot `ota_1`, ESP_OK and the
new version. Body Control reports an authenticated connection; paired IMU and
joint telemetry resumes. The reboot loop is resolved in this observation.
Startup console measurements were 8,856 body-task stack bytes free, 99,043
internal heap bytes free and 54,571 minimum internal heap bytes. These are
startup observations, not loaded neural-walking resource qualification.

Actual saved controls differ from the candidate environment: joint command
speed is 2,000 deg/s, balance is disabled, and saved balance trims are roll 3°,
pitch about 1.593°; walking feedback is enabled. Candidate training used
545.45 deg/s and balance enabled with zero trims. These existing settings were
preserved, not silently overwritten. Their transfer effect still needs to be
resolved for the physical trial. With servo power off, joint usability is zero;
telemetry transport is verified, physical angle tracking is not. Existing wake
Freestyle submitted a startup motion, but no neural Walk was requested and no
walking success or training-quality motion evidence is claimed.

The USB bridge resets the P4 when this serial session opens, as documented for
the console. Diagnostic reconnections therefore created additional boot/session
epochs; these are distinct from the earlier repeated SPI assertion. The final
existing console `disable` command reported output ready=0, armed=0, fault=1
(the deliberate emergency-disable latch), while the controller remained
authenticated. Temporary raw flash backups and serial captures were removed
after the preservation comparison and these findings were recorded.

### Virtual training resumed while the body is disassembled

The owner reported that USB access required complete disassembly and that
physical testing will be unavailable for more than a day. Physical trials are
on hold. Training run `00015b799ed445bfaad58b2e4dae252e` was started from packaged PPO
candidate `35be5800c94d45299dc8f793ee34914a` for 65,536 additional transitions
with four simulation workers. Actor, critic, optimizer and learned counters
are preserved. The planned consolidation replaces the fixed 16-second request
schedule with recorded random 12–20 second intervals; forward/reverse requests
are unchanged. This does not newly qualify turning, Run, slips or falls.

The training service directly runs MuJoCo plus the existing native binding of
production kinematics, calibration, servo filtering/arrival/jam calculations,
IMU estimation and balance. Body Control can launch and display the run, but
each learning step does not traverse its live gateway. This is also not a
complete simulated MetaHuman/task/perception/transport session. Existing
gateway/adapter lifecycle tests are separate, and the simulator's foot-target
path still omits the deployed host heading correction described above. The
known saved-control differences also remain explicit. This run is limited
locomotion-simulation training, not full-system or physical qualification.
The currently selected inference model was not changed by starting training.

### Training through Body Control and the production body executor

At the owner's request, the direct run above was interrupted for the connected
execution change. Its last fully published checkpoint is
`checkpoints/000086016-imitation000041000.zip` (86,016 transitions, 111 PPO
optimizer epochs). The run's interrupt status is not a lost checkpoint or a new
random initialization. Its published checkpoints and videos remain historical
direct-math evidence.

New run `c1c63d0467b344e0abe6499a278266a2` resumes that exact checkpoint for
65,536 additional transitions with four workers and the same 12–20 second
forward/reverse request changes. Actor, critic and optimizer are retained;
rollouts now pass through actual GatewayConnection inference production,
WebSocket admission, the host-compiled P4 body executor, actual PCA pulse
generation, CAD physics, fourth-wire acquisition and IMU telemetry back into
the gateway observation owner. This explicitly changes execution dynamics;
the manifest records it. Initial checkpoint evaluation precedes optimizer work.
The first connected evaluation has since published, and the live run reached
94,880 collected transitions while continuing optimization. Initial checkpoint
footage is rendering through the existing owner.

The old snapshot omitted `stand_enabled`; its named feedback capture contains
`true`. Connected configuration restores that field with capture provenance,
so Finish uses the real arrival mechanism instead of silently skipping it.
Stop/Release admission and receipt serialization are shared with the firmware
controller. No physical flash or robot command was performed in this phase.

The maintained neural/sensor suite passed 81 cases; the added one-worker PPO
training plus concurrent parent-evaluation regression also passed (all three
connected-training cases). Gateway/environment-adapter suites passed 114 cases,
and both native body execution suites passed.

The native body/transport regressions exercise target ACK versus consumption,
feedback-held Finish and jam reports, steering, Stop/Release, session replacement,
stale-link handling and failed inference. Connected Gym rollouts are repeatable;
historical noisy-video replay remains repeatable after selecting the recorded
backend. A two-second full-CAD check of the resumed checkpoint moved
(+0.0181,+0.0233)m for forward and (-0.0706,-0.0248)m for reverse, with no fall,
target rejection or body terminal. Lateral drift remains a failure to improve;
these short checks do not establish good walking.

A separate normal Body Control runs at `http://127.0.0.1:8891`, gateway8890,
with virtual identity `ainekio-virtual-v2` and ignored runtime data under
`build/gateway/virtual-v2`. It uses the existing dashboard password. Its normal
Environment adapter accepted a goal-bearing move, the actual inference service
produced targets, and an explicitly leased Stop completed while the original
Walk received cancellation. An initial Stop request omitted the Coordinator
lease and was rejected; the valid leased request verified the normal contract.
The adapter is available to MetaHuman at `ws://127.0.0.1:8890/environment`; its
private token is in that runtime directory. No MetaHuman LLM/perception goal
completion was claimed, and the physical gateway configuration was unchanged.

Remaining fidelity limits: the simulator starts at an explicit reference pose;
component inertia, loaded torque/friction and contact dynamics are estimates;
bus/network delay and RTOS preemption are not reproduced; media/perception
devices are not advertised. Switching to hardware reuses command/feedback
owners but still requires current calibration/settings and physical/Q6A timing
qualification. New checkpoint clips use the existing video/retention owner and
identify body/producer failures rather than calling every stopped trial completed.

### Connected-run monitoring and progress publication

Monitoring `c1c63d0467b344e0abe6499a278266a2` found that its old progress writer
continued to display `training` during several-minute checkpoint evaluations.
The existing Progress owner now reports evaluation purpose and completed/total
trials, preserving step/update counts. Final candidate reporting reuses the exact
final checkpoint evaluation; standing-baseline evaluation remains separate.
These training-process changes take effect on the next process start; the
already-running optimizer was not interrupted to reload reporting code.

The video owner previously waited for every checkpoint in a rendering batch
before publishing the combined video. It now publishes a completed prefix after
each newly finished checkpoint, retaining usable footage if a later clip fails.
The service reads the existing renderer lock to report automatic renderer
activity, and completion checks published identities rather than a coalesced
child's zero exit code. The dashboard now displays mean trial reward instead of
average signed forward velocity across mixed forward/reverse requests. These
are reporting/publication repairs, not new movement constraints or controllers.

Completed comparable evaluations at this monitoring point:

| Saved transitions | Mean trial reward | Falls | Rejected targets / jam frames |
| --- | --- | --- | --- |
| 86,016 | 54.13 | 0 | 0 / 0 |
| 98,304 | 100.95 | 0 | 0 / 0 |
| 110,592 | 45.64 | 0 | 0 / 0 |
| 122,880 | 174.56 | 0 | 0 / 0 |
| 135,168 | 228.83 | 0 | 0 / 0 |
| 147,456 | 13.19 | 0 | 0 / 0 |
| 151,552 | 110.20 | 0 | 0 / 0 |

The newest evaluated checkpoint regressed. The 135,168 checkpoint remains
preserved as the best observed reward in this run; no production selection was
changed. Its forward-start trials average only 3.6 reward versus 454.1 for
reverse-start trials, and mean absolute final heading change is about9.4°/11.2°
respectively. The aggregate gain is not proof of balanced directional skill or
physical walking. The final 151,552 checkpoint scored110.20 overall; forward-start reward remained
negative(-164.50), while reverse-start reward was384.91. The running process is
finishing its old baseline/final reporting and footage path; optimizer work for
this65,536-transition round is complete.

The monitoring repair also found that an interrupted source run’s error-only
`progress.json` hid its41,000 prior imitation updates from new display labels.
Resume now takes that count from the exact published checkpoint when available,
while retaining legacy status compatibility. Weights and optimizer state had
been preserved; this was a provenance/reporting error, not erased training.
The existing PPO continuation regression now exercises this interrupted-source
case and verifies the exact checkpoint and inherited count.

Per-command aggregation identified the actual directional failure hidden by
combined reward. Across all command segments, the final policy's +0.015m/s
forward request produced -0.001308m/s measured command-frame forward progress;
the -0.030m/s reverse request produced -0.005204m/s. Even the best-reward135,168
checkpoint averaged -0.00161m/s during forward requests. This is wrong-direction
behavior, not successful forward walking. The evaluation owner now publishes
duration-weighted per-command measurements and the dashboard displays requested
versus measured values. The same projection of the live artifacts was checked
through Runtime.status without modifying their recorded evidence.

Validation:87 maintained neural/sensor tests passed, including actual connected
PPO rollout/evaluation, checkpoint lineage after interruption, progress phases,
partial-video publication, renderer-lock visibility and command grouping. The
dashboard test passed for phase/trial counts, reward and visible negative travel
on a positive forward request. No motor-controller or hardware behavior changed.

### Sustained-progress reward correction (October 28)

The owner observed repeated loss of stepping near six seconds. The connected
48-second evaluations continued consuming all 2,400 targets without body terminal,
rejection or jam. A repeated forward trial of checkpoint 86,016 reduced mean
absolute policy change from 0.02334/frame during seconds 4–6 to 0.00230 during 6–8;
checkpoint 135,168 continued/resumed movement later. This is not a six-second
execution cutoff, and reward causation is not established solely by that trace.

Version 7's cumulative-average potential could grant positive movement credit
while stationary: six seconds at requested 0.015 m/s followed by two stationary
seconds increases its movement potential from 300 to361.66 (before costs).
Version 8 removes that potential and accumulated reward state. Each transition
now scores the normalized negative distance between measured and requested twist,
in the existing requested heading frame. Rest gets zero travel credit immediately;
a concave score prevents zero-net rocking from earning positive undiscounted
travel reward. Support, effort, slip and action-change costs remain. Ground truth
is still reward-only; joint feedback and estimated IMU remain policy inputs.
There is no prescribed limb order, movement timeout or controller change.

Maintained regression cases exercise move for 6 s → rest for 6 s → move again,
forward/reverse, symmetric/asymmetric zero-net rocking, command replacement,
requested-heading arcs, support loss and the connected Body Control executor.
Evaluation now retains one-second progress intervals, split at request changes,
so sustained travel can be compared without relying on total reward. Known
reward-only PPO continuations retain learned parameters and optimizer but collect
fresh rollouts; the manifest records reward_changes. SAC cannot reuse replay
rewards across this change. Old reward numbers must not be compared to new ones.

The owner's terrain question exposed a qualification boundary: current physics
has a flat floor, depth is unavailable in simulated observations, and the policy
contract has only nearest depth plus availability/age, not a terrain map. Falling
terminates an episode, so this curriculum does not teach self-righting. Rough
terrain, trips/slips, blocked progress and post-fall recovery remain untrained.
Perceptive training would need spatial terrain evidence from the actual camera
geometry, acquisition/delivery delays and missing/noisy readings. Existing goal
and navigation owners retain route selection; the gait policy owns locomotion.
This correction does not claim to implement those additional scenarios.

Validation: 88 neural/sensor tests passed (43.18 s), including the move/rest
regression, actual connected PPO transitions, reward-version continuation with
optimizer preservation, SAC replay incompatibility, and progress-interval sums.
The dashboard test and diff whitespace check passed. No physics or policy input
contract changed. The prior run finished rendering successfully before the
neural service was restarted to load these changes.

Continuation 13d620ad5b67467989ed7a9305b828da starts from the prior run's exact
151,552 checkpoint for 65,536 additional transitions with four Body Control
workers, 48-second episodes and the inherited 12–20 s forward/reverse requests.
It reevaluates the source under version 8 before updating, producing a comparable
baseline and subsequent footage through the existing owners. Production model
selection is unchanged. Improved sustained walking is not yet established.

### Terrain, spatial depth and recovery integration (October 28)

The owner authorized adding varied scenarios now while flat-ground learning
continues. The existing MuJoCo/Body Control environment now supports explicit
slopes, rocks, walls, friction patches, finite physical pushes and fallen starts.
Reset selects an authored scenario; collision, support height, slip and contact
measurements use that active terrain. No limb order, runtime avoidance rule or
additional motion controller was introduced. Empty scenarios retain the flat
environment. The experimental magnitudes are curriculum choices, not measured
properties of the owner's floor or obstacles.

Spatial observations share the physical camera owner's 8x8 optical-Z depth
format. The simulated camera raycasts from an explicit camera pose, samples at
the configured acquisition rate, queues delivery latency and retains original
frame times. Missing observations remain missing. Joint fourth-wire feedback,
IMU, ranges, events and previous actions retain their meanings. The optional v4
input has 295 features; v3 remains 148. PPO input expansion copies learned
actor/value weights and starts the new spatial inputs, plus previously inactive
scalar depth columns, at zero. An actual populated-depth regression verifies
that transfer alone does not alter the old policy's actions. New dimensions use
a fresh optimizer/rollout buffer; compatible subsequent PPO resumes preserve
their optimizer and collect fresh terrain rollouts.

Physical acquisition remains CameraFramePlugin's responsibility. The existing
neural Walk producer requests/releases its own depth consumer without awaiting
inference or imposing a motion barrier. Virtual training uses that same producer
and native feedback/execution path. Saved raw dense images are not required for
the policy observation. The production gateway has not been restarted for this
experiment, and no model was promoted or hardware commanded.

Camera assumptions are recorded in build/neural-gait/camera-experimental.json:
the retained real 640x480 frame's estimated intrinsics, configured 1 fps, and one
178 ms inference measurement. Exposure/network latency, noise, lens distortion
and true camera-to-body optical calibration remain unmeasured. The CAD envelope
center and forward/upright optical axes are explicit raycasting assumptions;
cameraToBody remains unknown in policy observations, matching physical exports.
This is perception plumbing and experimental training, not calibrated depth
qualification.

Zero-update transfer baseline 28b1aa507b66407a84cd469fced21996 preserves the
151,552-step source from c1c63d0467b344e0abe6499a278266a2 and evaluates ten
16-second cases: flat, 5-degree slope, 8 mm rocks, low-friction patch and a
0.8 N lateral push, each with forward/reverse requests. All ten avoided falling;
direction tracking remains inadequate. Identical flat/rock traces showed that
the initial rocks missed the foot paths, so those results do not establish rock
traversal. The next curriculum moves rocks beside the measured boot paths and
places slippery patches in both travel directions. The baseline's saved
environment/evidence is retained unchanged. Footage includes labeled and clean
clips in its existing clips directory.

Virtual recovery trial 37f71cbb49d644d4b2521c65a4576404 used the configured
Freestyle generator at port 8794 through the existing BodyEvents/FreestyleBridge,
compiler and native P4 command executor. At about 82 degrees tilt, the generated
program was Release only. Its acknowledged release cancelled the original Walk;
no pose target or stand-up was executed. Passive settling to upright cosine
0.9113 at root height 0.0329 m is not successful self-righting. The saved
recovery-evaluation.json is failure evidence, not a positive training label.
Left/right/back fallen starts and a blocked-wall scenario are available through
the existing virtual trial CLI. Walking PPO still terminates falls; these trials
exercise the existing recovery owner separately, not a claim that PPO learned
post-fall recovery.

Validation: 114 maintained neural/sensor/gateway checks passed; 99 camera, depth
and dashboard checks passed with three MuJoCo-only cases skipped in that Python
environment (those three passed in the training environment). The dashboard
JavaScript check and an extended training-API input-transfer regression passed.
Native recovery/readback regressions exercise real compilation/execution,
Stop/Release during generation, and original Walk completion ownership.
Terrain clearance measurement was optimized at its existing owner: the same
20 full-CAD steps dropped from 5.198 s to 0.101 s of measurement work, with
identical contact/validity and maximum clearance difference 7.3e-17 m. This
changes neither physics cadence nor sensor cadence. Unreliable separated-mesh
distance results remain explicitly invalid rather than inventing contact.

The corrected rock encounter replay consumed 800 native target samples and
registered physical contact with three authored rocks on 42 frames, without a
fall. The new terrain phase is 3f17c2bfb4ab4274b97fa1d89fd6f230: 16,384 additional
transitions, two Body Control workers, 48-second episodes, fixed 16-second
forward/reverse request changes and the five-scene curriculum. It transfers the
same completed 151,552-step source used by the zero-update comparison and
reevaluates it with the longer horizon before optimization. It does not restart
from random weights. The ongoing corrected-flat run is retained separately for
comparison. Existing service processes are left running while their training
and footage jobs finish. The terrain run uses the maintained training CLI;
the HTTP transfer extension loads on the next neural-service restart. No new
dashboard transfer control is exposed to the old running HTTP handler. The
current physical model selection remains unchanged.

### Backward drift diagnosis and excessive evaluation (October 29)

The owner requested causes of poor learning and excessive footage. Controlled
read-only comparisons identify a native execution problem before changing the
learner. With the saved 13d620 environment and a constant zero foot-offset
request, measurements during seconds 6–12 were:

| Existing feedback settings | Maximum joint target range | Mean absolute target change per frame | Body yaw-rate standard deviation |
| --- | ---: | ---: | ---: |
| Heading and balance enabled | 25.02 degrees | 0.42788 degrees | 0.4454 rad/s |
| Balance enabled, heading disabled for diagnosis | 0.09 degrees | 0.00625 degrees | 0.01026 rad/s |
| Both disabled for diagnosis | 0 degrees | 0 degrees | approximately zero |

Fixed PWM in the same plant also settled. The existing host heading correction
in motion.c:ainekio_v2_walk_host_heading applies cumulative heading error as an
Euler correction to each nominal pose; body.c applies it before balance. This
isolates self-excited stationary oscillation to that loop in this configuration,
not transport or an inherently unstable fixed-output plant. Exact gain/delay
repair still needs validation; diagnostic disablement is not a production fix.
All four legs reproduce requested +/-30 mm X and +/-20 mm Y with the correct
sign. Large +/-30 mm vertical requests fit to +/-15 mm. A short policy trace
consumed all 250 samples and reduced only 4/1000 individual leg fits; that does
not explain the directional failure.

An unchanged final 13d620 policy, seed1000, a single +0.015 m/s request and
12-second Body Control trials produced -0.000767 m/s with heading enabled and
+0.008439 m/s with heading disabled, while retaining balance. With heading
disabled, a -0.030 m/s request produced -0.033275 m/s. These demonstrate
translation and controller interference in simulation, not physical walking or
verified nonsliding foot placement. Neither trial fell. No deployed setting,
checkpoint or firmware was changed.

Reward8 compounds this problem. It combines instantaneous 20 ms translation
and yaw errors, then normalizes by requested twist magnitude. At exactly the
requested +0.015 m/s translation, only 0.04743 rad/s (2.72 degrees/s) unwanted
yaw cancels all travel credit, making it equal to ideal rest. In the unchanged
policy's last six seconds with heading enabled, mean travel score was -5.558;
counterfactually removing only yaw from scoring the same samples gives -0.564.
The better-directed heading-disabled trial still scores about -6.138 per step.
Thus improving translation can remain heavily punished by oscillation; repair
the executing loop before treating a reward adjustment as sufficient.

On 1,029 retained observation states, initial/final deterministic foot outputs
changed only 0.0473 mm RMS over the flat run and 0.0478 mm over the terrain run
(depth masked for like-for-like comparison). Commands are present and changing
them changes outputs. Optimizer starvation was considered but is unproven;
actual on-policy minibatches were not retained. These measurements establish
small actor changes, not their sole cause.

The workflow also reports results without selecting demonstrated improvement:
ordinary PPO saves the final checkpoint as policy.zip even when an earlier
checkpoint scores better. The final terrain policy was worse than its initial
baseline. This is not production promotion; the live service still selects
35be5800c94d45299dc8f793ee34914a. Reward alone is presently inadequate to select
walking quality.

The two completed runs simulated 6144 and 1893.66 seconds of evaluation versus
1310.72 and 327.68 seconds of learning experience (4.69x and 5.78x), before
video replays. Automatic per-checkpoint/per-scenario/per-direction rendering
created 56 and 60 labeled/clean clip files, plus two cumulative compilations.
The next repair should address the existing heading owner and reward scaling,
then use compact numeric comparisons and a small before/after video selection.
No further training or rendering was started during this diagnosis.

### Heading repair, pace scoring and resumed learning (October 29)

The owner authorized repair and continuation. The host heading owner now reuses
moving balance's existing scalar attitude response (.4 proportional error,
.05 s rate damping, .25 s response) instead of reapplying the full heading
error to every rebuilt nominal pose. Requested yaw rate is subtracted from the
observed rate for damping; the requested turn is not treated as a disturbance.
Only accepted correction is retained; existing correction-only geometry fitting
and feedback dropout/reacquisition semantics remain. The shared helper replaces
the existing roll/pitch expression without changing its arithmetic. No second
controller, heading disablement, gait clock or new actuator limit was added.

Under the original stationary Body Control trial, late target variation fell
from 25.02 to0.09 degrees, mean target change from0.42788 to0.00542 degrees/frame,
and yaw-rate standard deviation from0.4454 to0.00999 rad/s. The unchanged13d
actor then traveled +93.51 mm in16s forward and -125.01 mm in16s reverse.
Lateral travel was -6.17/+62.00 mm: that remaining tracking error is not declared
qualified walking. Evidence: build/neural-gait/geometry-review/heading-repair.json.

The first reward correction separated cross-axis scales, but an actual12s
comparison still preferred standing over productive forward motion because
individual20ms propulsion pulses were penalized as overspeed. That measured
failure was addressed before training. Version9 now credits signed directed
displacement immediately; only the overspeed penalty uses the last one second
of measured twist. The default excess-pace cost2 makes sustained overspeed
worse than requested steady pace. Cross-track cost .1 uses independent .03m/s
and .5rad/s scales, not requested travel speed. These are explicit experimental
objective parameters, not measured hardware limits. Pace history resets on a
new command; it contributes no positive credit, including after stopping.
Zero-net motion has zero directed progress and nonnegative penalties. Support,
slip, effort and action-change terms remain; no limb order is prescribed.

The unchanged saved terrain policy under the repaired execution moves
+6.613 mm/s and -15.411 mm/s in separate12s forward/reverse trials, no falls.
With final pace scoring those actual trajectories score +10.831/+4.936 reward
per second; both directions now earn positive movement credit. The
reward changed; the same measured travel did not. This establishes that the
objective now credits the observed useful movement, not a learned improvement.
Both intermediate and final comparisons are retained as reward9-heading-
comparison.json and reward9-pace-comparison.json in geometry-review.

Training run9087a0d4d9484a8a87518918b3780c0d resumes the saved PPO policy,
optimizer and counters from3f17c2bfb4ab4274b97fa1d89fd6f230 for32768 additional
transitions using four Body Control workers,48s episodes and16s request
changes. The first continuation uses flat ground to measure directional repair;
depth inputs remain active and the authored terrain/recovery cases are retained.
Heading and balance remain enabled. Its manifest records environment9, source
motion/balance hashes, reward migration8→9 and the explicit scenario change.
Fresh on-policy rollouts are used; old replay rewards are not reused.

Routine checkpoint evaluation now uses one seed/scenario per command. Full
numeric evaluation remains at completion. Automatic rendering runs only at the
end, with one matched initial/final trial and clean/labeled versions (four clips
plus the combined video). Explicit detailed replay remains available. Historical
clips are preserved: new execution versions use distinct clip names/cache keys
and visible training/replay version labels. Dashboard counts and render receipts
now describe this comparison rather than reporting it as incomplete detailed
footage. Final policy publication is explicitly labeled final state, not an
automatic claim of improvement or a production promotion.

Validation:118 maintained neural/sensor/gateway tests passed, plus the dashboard
regression. All34 native motion/protocol tests passed after building their
normal targets, including the heading/balance/timing regressions for both
disturbance signs, delayed response, requested turns and feedback loss/recovery.
The isolated neural service was reloaded before launching the continuation;
no physical gateway connection was present. Firmware source is repaired, but
the physical robot was not flashed or commanded. Physical qualification remains
outstanding.

The first repaired continuation finished:32768 additional transitions,803s
including its single matched video comparison. The final48s flat-ground trials
averaged +1.191mm/s for forward15mm/s and -6.463mm/s for reverse30mm/s, with
no falls. The initial checkpoint averaged +2.360/-4.443mm/s under the same
compact evaluation. Reverse improved, forward regressed; the final state is not
declared a better walking model and was not promoted. The comparison video is
build/neural-gait/9087a0d4d9484a8a87518918b3780c0d/progress-video.mp4.

Optimizer inspection found only24 Adam minibatch updates across those32768
transitions and eight first-epoch stops, despite ten configured PPO epochs.
The saved rate was3e-6 and target KL.02. PWM quantization did not erase
exploration:2048 sampled actions from recorded states changed at least one
joint PWM in99.95% of frames, averaging5.28 changed joints, without target
rejections. Before-update likelihood replay was also consistent:1024 states
per source/final model gave approximate KL below3e-10 versus the existing
stop threshold.03. These rule out those two suspected defects on the sampled
states; they do not yet establish the best learning rate.

The maintained trainer now retains standard SB3 optimization.jsonl summaries
and accepts an explicit learning-rate override through the existing CLI/API,
with source/target provenance. Without an override, saved schedules remain.
Changing rate retains learned weights, Adam moments, counters and exploration;
the existing PPO trust-region setting is unchanged. The existing continuation
regression verifies inherited/changed rates, preserved optimizer state and
logged KL/value loss. No alternate trainer or raw rollout archive was added.

One matched4096-transition Body Control rollout then tested the inherited
weights and Adam state at three rates, with the same buffer and minibatch order.
At3e-6 PPO stopped after4 minibatch updates, full-buffer KL.03220. At3e-7 it
completed all160 updates/ten epochs with KL.009710;1e-7 also completed160,
with KL.006153. The initial KL was2.53e-10 for all arms. This demonstrates
update overshoot at the inherited rate on these actual transitions, not an
action-likelihood storage defect. Evidence:geometry-review/ppo-matched-learning-
rates-9087.json. Only the compact report remains; the disposable script and
in-memory candidates were removed. Better optimization is not yet better gait.

Run7e266a175fd4485b96b3cc9573f18a22 now continues65536 transitions at3e-7
from9087/checkpoints/000016384.zip, preserving that checkpoint's learned
weights and Adam state. This chooses the initial checkpoint's better weaker-
direction progress rather than assuming the last saved checkpoint is best.
Four Body Control workers,48s episodes,16s forward/reverse requests, depth
inputs, heading and balance remain. The manifest records the rate change.
The full118 maintained neural/sensor/gateway tests passed after these trainer
changes; the dashboard regression also passed. The physical production model
selection was not changed and no physical movement or flash was performed.

Live continuation check: at12288 new transitions, the optimizer counter advanced
from58 to88 epochs: all ten epochs completed in each of the first three rollouts.
The first two logged approximate KL values were.01182 and.00864 at3e-7.
The run was evaluating its first new checkpoint; these measurements establish
that training is updating normally, not yet that directional walking improved.

Owner video review confirmed the initial clip becomes stationary at about8s.
The matching initial-checkpoint telemetry advances79.81mm during0–8s and
recedes0.79mm during8–16s, despite an unchanged +15mm/s request. There are
no jam frames, rejected targets, body terminal event or producer failure; the
recording continues for48s. This is lost locomotion progress, not a video end
or requested stop. The completed65536-transition continuation still fails:
final forward trial advances71.65mm during0–8s, then retreats108.13mm during
8–16s. Its full evaluation averages -1.271mm/s for requested forward and
-5.470mm/s for reverse. Intermediate checkpoint53248 sustains forward for
16s (119.33mm), but then advances56.17mm while reverse is requested, so that
checkpoint also does not establish directional control. The optimizer fix
enabled updates; it did not solve sustained/request-responsive walking. The
finite run is complete, no further run is currently active, and no candidate
has been promoted. Next learning work must address sustained movement and
request transitions, not treat aggregate optimization activity as gait success.

### Saturated exploration and value learning repair — October 29

The owner authorized repairing sustained movement and request transitions.
A32s trace through the existing Body Control/native executor reproduces the
initial policy's collapse: maximum joint-target variation falls from73.8degrees
during second8 to1.08degrees during second10 and0.54degrees during second32.
Measured joints follow those targets. No transport/terminal event explains the
loss of progress. Evidence:geometry-review/sustained-progress-trace.json.

On these actual states, all four lateral foot outputs saturate above.99 after8s.
Their sampled variation shrinks from about.21mm RMS while walking to
.00035–.00049mm RMS afterward. The underlying Gaussian means reach3.961–4.111
with standard deviation about.049; getting below action.99 would take a27–30
standard-deviation sample. A reversed request changes saturated lateral targets
by only.0075–.010mm RMS. This specific failure-state evidence supersedes the
earlier generic-state inference that PWM exploration was adequate everywhere.

The existing GaitPPOPolicy now supports explicit exploration in normalized
foot-action coordinates. Its deterministic mean remains tanh(existing head),
with the learned actor and value weights retained. Noise is applied around that
bounded mean, and SB3's existing PPO path clips only executed/predicted commands
to the existing range; the rollout buffer retains raw Gaussian samples for
correct likelihoods. Historical artifacts retain their original latent-noise
parameterization. This is a saved policy setting, not a second runtime motion
controller or a narrowed motion range. Only noise-parameter Adam moments reset
on explicit handoff because that parameter's units changed.

A paired32s probe calibrated noise to the source's observed0–8s walking action
variation. Action-space exploration produced +35.63/+13.75mm in the two forward
eight-second intervals, then -26.61/-136.56mm after Reverse, without falls. The
old distribution produced +15.07/-7.61mm then -39.16/-110.31mm under the same
seed. This single stochastic comparison demonstrates useful exploration; it
does not establish deterministic learned improvement or generalization.
Evidence:geometry-review/action-space-exploration.json.

The value estimator was also nearly constant across walking/stopped states.
Reducing the policy learning rate had reduced value learning too. A matched
fit using identical recorded observations/GAE labels and copied Adam state,
ten epochs and an80/20 held-row split, reduced held MSE148.812→129.899 with
value rate3e-4 versus148.793 at3e-7. Actor weights were unchanged. Correlated
held rows are fitting evidence, not new-episode qualification. Evidence:
geometry-review/critic-fit-learning-rates-7e266.json. Separate actor/value rates
are established in [Spinning Up PPO](https://spinningup.openai.com/en/latest/_modules/spinup/algos/pytorch/ppo/ppo.html).
Our maintained GaitPPO retains SB3's training/rollout implementation and changes
only its existing optimizer's actor/value group rates; parameter identities and
Adam moments survive the split and reload. No competing trainer was added.

Runae2dc0829b694f94a4435aacb14fd522 continues65536 transitions through four
Body Control workers from7e266/checkpoints/000016384.zip. That checkpoint has
the least-wrong weakest request segment among that run's checkpoints; the final
regressed state is not assumed best. Actor rate3e-7, value rate3e-4, calibrated
action-coordinate exploration, and varied6–24s request intervals are explicit
training settings. The interval range samples changes before and after the
observed collapse; it does not add a robot gait clock or stop rule. Geometry,
calibration, sensor/actuator contract, depth inputs, balance, heading and reward9
are unchanged. The manifest records rate/distribution/source changes. Only the
usual single before/after comparison will render after the run.

All119 maintained neural/sensor/gateway Python tests passed, including unchanged
legacy behavior, inward exploration at saturated means, valid clipped execution,
raw-sample likelihood parity, exact retained actor/value parameters and moments,
separate rates after save/reload, resumed learning and API forwarding. Source
review found and corrected value-rate provenance before activation. The neural
service was reloaded with no physical connections; no physical robot movement,
firmware flash or production-model promotion occurred. Disposable probe scripts,
raw state archives and test logs are removed after the evidence is summarized.

The first launch643016edf6604f568d971c17814058d9 failed before sampling because
`python -m` defined duplicate `__main__` policy classes while loaded artifacts
used canonical module classes. The CLI now dispatches through the canonical
training module; a fresh-interpreter regression covers that entrypoint. Two
focused entrypoint/exploration checks passed after the repair. The failed run
contains only its error/provenance, no trained model or footage. The active run
above uses the repaired entrypoint; simulation startup is not physical motion.

At12288 additional transitions, checkpoint000028672 shows an actual directional
improvement under the same seed/request schedule as its initial checkpoint.
The18.74s forward request travels149.5mm versus78.8mm initially, and forward
progress continues during8–16s instead of settling stationary. Its first reverse
segment now travels -12.0mm versus +2.4mm previously. The reverse-start trial's
first switch to Forward now travels +31.7mm versus -68.7mm previously. Later
switches still fail: the third segment travels -34.3mm during Forward in one
trial and +17.9mm during Reverse in the other. Both trials remain upright.
These are same-schedule developmental measurements, not physical qualification
or generalization proof. The full65536-step run remains active; no candidate
is promoted solely because early segments improved.

### Continued direction-conditioning refinement and deployment size — October 29

The owner requested continued refinement and asked about Q6A/P4 inference cost.
The action-space/value-rate continuation completed its65536 optimization steps,
but final compact direction tracking regressed. Checkpoint53248 has the strongest
worst normalized request segment among that run's checkpoints (-.039 of requested
travel); this is a comparative initialization choice, not a qualification gate.
It is used instead of assuming policy.zip is best. Broad final evaluation of
the previous run is still completing independently.

Recorded-state analysis shows command RMS.0237 versus median joint-velocity
input.998. The final actor's command-column Adam gradient RMS is43.6times
smaller than its typical sensor-column gradient. Across2560 minibatch updates,
its forward-command column changes only.00565percent and same-state forward/
reverse action difference remains1.291→1.289mm RMS. The faster-trained critic's
command-column norm instead grows.552→6.673. These measurements use1029 retained
proprioceptive observations with depth unavailable, not a claim of new closed-loop
performance. They support conditioning the small SI commands for learning.

The existing policy now accepts explicit command reference units [.03,.03,.5]
for vx/vy/yaw. Each command feature is divided by its reference unit; matching
first-layer actor/value weight columns are multiplied by the new/old unit ratio,
and their Adam first/second moments are divided by that ratio/its square.
This retains starting predictions and history while changing future optimization
conditioning. It adds no parameters, motion patterns, clocks, limits or sensor
requirements. Input normalization is an established locomotion practice, for
example [legged_gym's command scales](https://github.com/leggedrobotics/legged_gym/blob/master/legged_gym/envs/base/legged_robot.py).
The chosen physical reference units reflect this robot's existing training
objective; they are not advertised hardware limits.

A regression caught SB3 prediction/value convenience paths bypassing the feature
override before activation. Both now route through the same policy feature owner
as collection and likelihood evaluation. All121 maintained neural/sensor/gateway
Python tests pass, including unchanged raw observations, preserved initial actor/
value predictions, transformed optimizer moments, save/reload and continued
learning. No alternate trainer/controller or diagnostic script remains.

Runbdabb1156fc04511aabadb8f6d9ce221 continues65536 transitions from
ae2dc/checkpoints/000053248.zip through the existing training CLI and four Body
Control workers. It inherits action-coordinate exploration, actor3e-7/value3e-4,
48s episodes and6–24s request changes. The CLI permits learning while the preceding
service-launched run completes its final evidence; both use the same training
implementation and report into the existing run directory/UI. After that child
completed, the service was reloaded with no established physical/inference
connections, activating the command_units API and canonical policy classes.
The independently launched CLI evaluation continued. Production selection is unchanged.

Measured current inference network:295→128→128→12,55948 actor parameters,
223792bytes FP32 weights (218.5KiB),55680 multiply-accumulates per prediction,
2.784million MAC/s at50Hz. A recent full checkpoint is1370471bytes including
critic/Adam and artifact overhead; all training parameters total110489. On this
i9-9900K, one-thread PyTorch model.predict over2000 warmed zero-input requests
measured196.63us median and279.67us95th percentile. This excludes transport,
sensor processing, camera/depth inference, kinematics and servo execution.
Q6A CPU inference is expected to be practical, but SSH to192.168.0.88 was
unreachable so it is not a measured Q6A latency. A native P4 actor port is plausible
at this size but requires actual memory/timing qualification alongside firmware;
the full Python training checkpoint is not a deployable P4 artifact. No P4
installation, firmware flash, physical trial or model promotion was performed.

The normalized-command run completed all65536 optimization steps and entered
its final16-trial evaluation. All ten PPO epochs ran per rollout; the critic's
last logged explained variance reached.605. That optimizer improvement did not
produce a reliable gait: the compact final checkpoint moves26.4mm backward
during the same18.74s Forward request where the starting checkpoint moved
119.1mm forward. No compact checkpoint establishes reliable direction tracking.
The model is not promoted; final broader evaluation is still in progress.
