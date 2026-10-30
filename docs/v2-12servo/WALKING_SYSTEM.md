# V2 walking capabilities and neural-training integration

Source audit: **2026-10-27**. This records the existing Body Control/P4 execution
path and the capabilities a neural gait integration must preserve. It does not
claim that source-supported gaits walk successfully on the physical robot.
Start with [V2 specifications](SPECIFICATIONS.md) and the shared
[body capability contract](../../../metahuman/docs/robot/BODY_CAPABILITIES.md).

The running Body Control served `dashboard.js` byte-for-byte matching this
checkout during the audit. Browser automation had no connected browser, so this
was a served-source and handler audit, not a visual inspection or movement trial.
The neural service reported no active training and no selected policy. No robot
movement, firmware installation or Body Control restart was performed for this audit.

## Task-directed locomotion owns the purpose and endpoint

The shared [goal-directed locomotion contract](../../../metahuman/docs/robot/BODY_CAPABILITIES.md#movement-and-posture)
already assigns goal selection to MetaHuman and progress/execution to Core Active
Task. The owner reaffirmed this scope on October 28: the robot moves to follow a
line/person, investigate an object, explore, or perform another selected task.
Neural walking is the adaptive locomotion implementation beneath those tasks,
not a replacement task system based on cycle counts, elapsed time or distance
alone. An idle robot has no implicit marching task.

The existing source path is Core
[`active-task.node.ts`](../../../metahuman/packages/core/src/nodes/environment/active-task.node.ts)
plus [`evaluateLocomotionGoal`](../../../metahuman/packages/core/src/environment-interface/active-task.ts)
→ Environment Bridge → gateway
[`translation.py`](../../Master/gateway/environment_adapter/translation.py)
→ the same body motion owner. Perception/visual evaluation and attributed
`locomotionMeasurement` update that active task, which changes steering and
requests Finish. Follow continues according to its ending condition; proximity
alone does not complete it. Visual behavior has its own completion criteria.
Goal completion still requires endpoint evidence and the correlated movement
outcome, not a gait counter or inference receipt.

Neural integration must retain this path and its cancellation/recovery identity.
It supplies adaptive foot targets from the changing movement request and actual
joint/IMU/perception evidence. It does not introduce a second goal manager, a new
cycle counter, or a time/distance-only substitute for existing task semantics.
The manual native controls below remain available; their cycle/phase mechanics
are not requirements for the learned policy. Fixed-duration simulator trials are
bounded measurements of locomotion skills, not the robot's operational goals.

## Existing operator controls

Owners: [dashboard markup](../../Master/gateway/dashboard/static/dashboard.html),
[`walkingParameters`, `applyWalking`, `renderBalance`](../../Master/gateway/dashboard/static/dashboard.js),
and [gateway admission/receipts](../../Master/gateway/server/service.py).
Controls are exposed according to the connected body's advertised capabilities.

| Capability | Existing contract | Neural integration must preserve |
| --- | --- | --- |
| Walk | Forward and backward; finite cycles or continuous movement | Both signs and low/high percentage requests; no replacement with a single fixed forward velocity |
| Run | Explicit bounding Run; Walk speed above 100% transitions toward Run, with full Run stride at 200% | Distinct bounding behavior and continuous Walk/Run transition; fast walking alone is not evidence of running |
| Turn | Left/right in place and combined forward/turn axes | Curved travel, turning while reversing, live steering changes |
| Crawl | Separate gait exposed by the same walking form | Retain existing control and execution; current host optimizer excludes it |
| Crab | Wide stance and left/right sideways travel | Retain lateral semantics and existing advertised restrictions; current host optimizer excludes it |
| Speed | 0–100% for ordinary walk; extended range to 200% where Run is advertised | Existing percentage semantics; **not metres/second and not motor-power percentage** |
| Direct stride | 1–100% of selected gait; current UI sends legacy `rate:2` | Preserve stride control and compatibility; do not silently redefine rate as a new motor limit |
| Live update | `update` identifies the original active Walk sequence | Same owner and terminal receipt; no new movement task per inference or neural phase requirement |
| Finish | Speed zero requests the gait's stopping/settling transition | Complete through the original gait owner and correlate its terminal receipt |
| Stop | Cancel movement and hold the commanded pose | Cancel pending host inference/targets through existing command ownership; late recovery cannot undo Stop |
| Release/detach | Disable servo outputs | Preserve explicit release and ownership; do not treat it as Finish |
| Keyboard/gamepad | Held-direction controls and combined controller axes | Same public controls and updates; a neural backend must not orphan these consumers |
| Saved joint speed | Separate configurable shaft-speed setting | Train at the owner-selected advertised 60°/0.11 s ≈ 545.45°/s; retain Body Control's independent later adjustment |

The existing percentage control primarily changes stroke distance. The old Python
research helper describing stride-then-cadence is not sufficient evidence of the
current P4 behavior. The dashboard sends the current protocol and the executable
walking owner interprets it. A neural command adapter must retain that meaning or
present a concrete proposed change to the owner; mapping 90% to an invented
maximum m/s would change the contract.

## Existing correction and completion owners

The production walking chain in [P4 `body.c`](../../Slave/firmware/esp32p4-wifi6/main/body.c)
is:

```text
Walk start/update -> existing motion/session/sequence owner
  -> ainekio_v2_walk_feedback_tick (gait geometry and heading correction)
  -> balance_frame (IMU leveling)
  -> fit_motion_frame (selected device calibration / coupled linkage)
  -> ainekio_p4_learning_frame (saved learned corrections)
  -> calibrated PWM -> PCA9685
Fourth-wire acquisition and IMU acquisition continue independently.
Jam observations -> gateway body event -> existing Freestyle recovery owner.
```

| Function | Actual implementation | Qualification / integration requirement |
| --- | --- | --- |
| Auto-leveling | `balance_frame` and [model `balance.c`](../../Slave/software/models/v2-12servo/balance.c); saved enable, strength, damping, roll and pitch targets | Applies to Stand and native walking. Preserve the switch, tuning, nominal pose and feedback reference. Physical loaded effectiveness remains a measurement question. |
| Walking heading correction | `ainekio_v2_walk_feedback_tick`; separate saved Walking feedback switch | Uses usable IMU yaw and follows requested curves. Six-axis yaw is relative and drifts; it does not measure distance or foot slip. |
| Fourth-wire feedback | [acquisition](../../Slave/firmware/esp32p4-wifi6/main/servo_feedback.c), [filter/curve](../../Slave/firmware/esp32p4-wifi6/main/servo_feedback_model.c), [position/arrival/jam](../../Slave/firmware/esp32p4-wifi6/main/servo_feedback_position.c) | Measured shaft position and velocity, calibration domain, freshness/health and target error. Shaft position is not ground contact, torque or clearance. |
| Learned gait corrections | [P4 learning](../../Slave/firmware/esp32p4-wifi6/main/gait_learning.c) and [model learning](../../Slave/software/models/v2-12servo/learning.c) | Existing phase, sensor and command-conditioned policy; do not apply a second learned correction accidentally. |
| Target completion | P4 Freestyle endpoints and legacy posture/clip verification | Freestyle uses measured arrival. Native walking is a continuous trajectory with feedback corrections; it does not wait for every shaft to arrive at every 20 ms frame. These contracts are different. |
| Jam detection | P4 no-progress tracker uses configured error band, directional measured progress and observation window | Reports a jam without automatically releasing outputs. This is already implemented and must remain effective for a neural gait. |
| Jam/fall corrective motion | [Freestyle `event`, `submit`, recovery ownership](../../experiments/freestyle/bridge.py) | Enabled recovery accepts `servo_stall`, `servo_feedback_fault`, `tipped`, `rapid_movement`, `slip`; obtains observations and generates a replacement sequence. Same robot/session/command attribution prevents stale events overriding newer commands. Generated recovery is not proof of physical recovery. |
| Tip detection | [BodyEvents](../../Master/gateway/body_events.py) compares calibrated attitude with expected orientation and emits event episodes | Existing intended-motion treatment, episode clearing and notification settings must survive. |
| Slip detection | Freestyle accepts a `slip` event, but this audit found **no automatic slip-event producer** in the current gateway/P4 path | A consumer is not an implemented detector. Need measured body travel versus expected stance/motion evidence; do not infer slip from joint motion alone. |
| Recovery completion/resumption | Existing Freestyle generates and executes corrective targets with receipts | Automatic resumption of the original Walk after a generated correction is **not established** by the current event handler. Preserve owner/goal identity and explicitly qualify the eventual integration. |

**Critical finding:** the current Freestyle `motion_plan` branch calls
`freestyle_frame`; it does not run the native walking heading → balance → learned
correction chain above. Wiring a neural policy directly to repeated Freestyle
plans would bypass these responsibilities and reset finite-plan lifecycle state.
That is not an acceptable integration. Extend the existing walking owner with a
policy source and preserve its correction/state lifecycle; do not add a parallel
PWM owner, balance controller or recovery agent. The host policy observation must
include the applied corrections/configuration so it does not unknowingly fight them.

## Existing learning, recording and measurement

[**GaitLearningService**](../../Master/gateway/gait_learning_service.py) already
owns optional host recording, trace sessions, observation history, optimization,
model installation and restoration. It is independent of the browser.
[**gait_optimizer.py**](../../Master/gateway/gait_optimizer.py) searches
context-conditioned `gait_learning_v4` parameters using measured progress,
turning, tilt, acceleration and tracking. Forward, backward, turning and Run are
its categories. Its profile includes duty, sweep, phase, lift, landing and body
shape; it retains separate Walk/Run contexts and camera/calibration signatures.
This is a compact policy/parameter optimizer, separate from the host neural
policy. Fresh online neural training uses PPO; historical SAC artifacts retain
their recorded algorithm.

The neural experiment must reuse the existing recorder/history and hardware
configuration at the handoff. Existing policy upload, enable/amount, export,
restore and Analyze controls must retain a supported owner; they cannot silently
become controls for an unused correction layer. Current neural training has its
own simulation artifacts because those are simulated episodes, not physical
recordings; those artifacts must remain clearly distinguished.

[Camera motion](../../Master/gateway/depth_motion_worker.py) has metric-depth /
feature-map and [calibrated ground-plane](../../Master/gateway/ground_plane.py)
paths. Missing measurements remain unavailable. Real camera intrinsics, optical
to body transform, calibration/reference identity, image time and uncertainty
matter. IMU orientation is independently available. No ground-truth simulator
velocity should be substituted for a real visual estimate in policy observations.

## Hardware and latency contract

| Boundary | Source evidence | Required simulation / host evidence |
| --- | --- | --- |
| Body | Owner-measured 0.650 kg, 12 MG90S servos, four coupled 35/20/28/38 mm linkages and 55 mm lower legs | Current Wireless meshes/pivots, mirrored frames, installed calibration and contact geometry; total mass is known, COM/component inertia remain unmeasured |
| Servo capabilities | Recorded advertised 60°/0.11 s; saved calibration maps model degrees to per-servo pulses | Separate requested ramp, no-load motor speed, torque/load response and shaft measurement. Loaded speed/torque/backlash are not measured by the listing. |
| Limits | P4 calibration fits coupled carrier/crank targets; feedback calibration points are not universally physical stops | Reuse executable mapping and coupling; distinguish software command limits, sensor domain, CAD collision boundaries and measured physical stops |
| Servo output | Local 20 ms / 50 Hz body task | Keep local execution asynchronous with host inference; don't require network round trips per PWM tick |
| Feedback | Nominal 20 ms scan; individual channels have timestamps; recorded scan in the captured specimen ≈15.9 ms | Model acquisition skew, filtering, quantization, health and observation age; measured noise needs separate evidence |
| IMU | LSM6DS3 at 208 Hz, ±16 g, ±2000°/s; firmware estimator; network snapshot opportunity every 20 ms | Sample gyro/acceleration at sensor cadence, use the same attitude estimator and retain timestamps/status |
| Gateway trace drain | Current recorder drains batches at ~100 ms cadence when caught up | Recorder cadence is not a real-time policy transport. Reuse ownership without assuming that batched history is fresh feedback. |
| Inference | Host workstation initially, Q6A intended | Measure observation age, inference distribution, command-delivery and applied-frame latency separately on each host |
| Network/media | P4/C6 Wi-Fi shared with camera, audio, receipts and telemetry | Measure delay/jitter/loss and reconnect behavior with concurrent media; model command hold and stale observations, not ideal zero-delay feedback |
| Safety/lifecycle already present | Existing Stop, detach, Finish, replacement, heartbeat and event contracts | Preserve established behavior; no new arbitrary timeout, global execution barrier or silent fallback |

The current experiment has **not** qualified the Q6A control rate or network delay
budget. It must not advertise physical readiness based on workstation throughput.

## Required coverage before a neural gait replaces a production source

The owner requested at least Walk, Run, turns, reverse, and slip/fall correction.
The inventory above additionally requires retaining Crawl, Crab/lateral travel,
curved steering, finite/continuous operation, speed/stride updates, heading
feedback, auto-leveling, learned correction ownership and manual control.

Training/evaluation must exercise command diversity and transitions, slopes and
friction changes, stalls, loss of traction, different fallen orientations,
missing/delayed sensor samples, network jitter and host inference latency. Distinct
results must establish commanded direction/speed, measured displacement and yaw,
body roll/pitch, joint tracking, contact behavior, recovery outcome, and the
original operation's completion/cancellation. All training videos must identify
simulation, configuration, checkpoint and failed trials.

Maintained regression entry points include the gateway dashboard/service,
body-event, gait-learning-service and depth-motion suites in `Emulator/tests`,
P4 body/servo-feedback tests, and the V2 motion CMake tests for walking feedback,
balance, posture, learning and gait timing. The neural simulator suite must test
against these production owners rather than copying them into a second controller.
Physical trials and measured Q6A timing remain separate from software tests.

The gateway now has a host-neural target path into the existing P4 walking owner.
Training uses that gateway and a host build of the same body executor over the
real WebSocket protocol, with the CAD physics plant replacing hardware. See the
[gateway training/virtual-body instructions](../../Master/gateway/README.md#neural-walking-simulation-and-policy-service).
This verifies software ownership and sensor flow, not successful physical walking
or full perception-guided tasks. Historical direct-math artifacts retain their
recorded backend for replay; their results are not relabeled as connected trials.

Earlier direct-simulation evidence: the corrected CAD assembly passed a short
standing/contact check. Its five-second
native forward-request baseline remained upright but travelled 0.424 m backward
along the body X axis; this is a failed forward trial, not a coordinate relabeling.
A fresh 10,000-step independent-joint experiment then held still: all 100 sampled
policy requests were geometrically rejected. Its footage is retained as failure
evidence. Standing-relative foot offsets through the existing per-leg IK/residual
fit, calibration, ramp and PWM owners eliminated those rejected requests. The
first foot-space run learned settling; a revised travel reward and continuation
reached 60,000 steps. Its deterministic reference checkpoint still travelled
backward (0.148 m over ten seconds), with zero falls/rejections; it is not a
successful forward gait. The continuation's initial checkpoint travelled 0.284 m
backward over the same interval.

A separate native first-cycle check found eight of eleven planned swing samples
had nominal full-boot clearance at/below the floor. Calibration fitting changed
zero joint degrees; PWM rounding changed clearance by at most 0.063 mm, while
tracking error reached 9.3 degrees. Heading/leveling were configured but inactive
during this first cycle because the shared IMU estimator was still starting.
This identifies boot clearance and tracking/timing as concrete next investigations,
without establishing the cause of every backward trial. These forward-only
experiments establish neither the complete capability matrix nor physical walking
performance; remaining features are iterative work rather than prerequisites for
every initial offline trial.

Guided foot trajectories subsequently produced positive forward displacement in
the same CAD plant. A 64×64 actor fitted for10,000 imitation updates reproduced
forward movement directly from reset:0.083m forward and0.018m lateral over14s.
A separate60s rollout reached0.456m forward/0.160m lateral, minimum upright0.965,
with no falls, rejected frames or simulated jam reports. These results are
`build/neural-gait/cc3fe42ce50f4a56b92caab647f51d81` and
`build/neural-gait/guided-steps/bc-probe-long.json`. They demonstrate useful
learning progress, not clean foot clearance, heading control or physical success.
The demonstration initially omitted its2s stabilization samples; the published
14s evaluation deliberately starts directly from reset without that warmup.

Subsequent demonstration aggregation improved boot clearance, and a 128×128
actor reached 0.160 m forward over 60 s, still slowly and with heading drift.
Reward-based continuation learned faster motion but turned/slid instead of
following a straight request. The simulator now scores horizontal travel in the
commanded heading frame, measures actual unwrapped yaw and penalizes measured
loaded-foot slip. These are reward-only measurements; the policy still sees the
same 148 sensor/command features. Current training and videos, including failed
rounds, are recorded in the [October 27 gait journal entry](GAIT_RESEARCH_JOURNAL.md#2026-10-27--neural-walking-training-guided-steps-and-visible-progress).
Neither reward score nor a fall-free simulation establishes physical walking.

## Host neural integration: implemented path and qualification boundary

Source rechecked **2026-10-29**. The gateway/native-P4 neural path is implemented
and exercised through the real WebSocket interface in simulation. This does not
establish physical deployment, reliable learned walking, or Q6A timing. Task
completion remains owned by the existing goal system, not a neural cycle count.

1. **Admission and ownership.** Dashboard and Environment Bridge Walk requests
   reach `GatewayService.queue_intent` and `GatewayConnection.send_command`.
   `_prepare_neural_walk` uses the saved per-robot source to attach host reference
   geometry and commanded SI twist. `NeuralWalk` owns inference, consumed-action
   history and updates for the original Walk. The shared control codecs carry
   `walk_target` with owner sequence, sample, geometry and twelve foot offsets.
   P4 `body.c:accept_walk_target` replaces the current nominal target within that
   operation; it does not queue another movement. ACK means admission; telemetry
   identifies the sample consumed by a successful PWM write. Stop, Release,
   replacement and reconnect retire the producer through existing ownership.
   Late inference cannot restart the retired operation.

2. **Native corrections and physical mapping.** The host branch of
   `body.c:motion_frame` runs `ainekio_v2_nominal_foot_pose`,
   `ainekio_v2_walk_host_heading`, `balance_frame`, calibrated fitting and joint
   ramping before the existing PCA output. Shared nominal conversion constructs
   foot anchors for leveling. Physical order remains rear-left, rear-right,
   front-left, front-right. Saved native phase-based learned residuals remain
   applied only to native gaits: their phase/profile signature does not describe
   host-generated motion. Heading and balance switches retain their existing
   owners. Connected training runs this same body branch, including the selected
   balance/heading configuration; historical direct-math runs did not necessarily
   do so and remain identified by their artifact configuration.

3. **Finish, measured arrival and cancellation.** Speed-zero updates retain the
   original Walk receipt. `body.c:host_finish_begin` reconstructs the current pose
   from fourth-wire feedback when available and starts
   `ainekio_v2_posture_begin_landing` toward Stand. The body posture/arrival owner
   retains completion until measured arrival when configured. Landing/support
   estimates are geometry estimates, not measured foot contact. Existing native
   tests cover a stalled Finish remaining active, the attributed jam event and
   completion after measured progress resumes. Connection-loss Finish, Stop hold
   and Release detachment keep their original owners; loaded landing remains a
   physical qualification task.

4. **Feedback, IMU and depth.** Production IMU packets carry the paired calibrated
   joint scan: filtered position/velocity, commanded position, per-joint acquisition
   times, health and configuration identity. `body_sensor_observation` feeds the
   shared policy projection. The producer uses the device-consumed requested
   action as `previous_action`, not the most recently sent or fitted target.
   The v5 observation history belongs to the original Walk and survives steering
   updates. Preview is non-executing and begins with empty history. Both v4-depth
   and v5-history preview/execution use the existing camera's depth projection;
   valid depth does not require successful odometry. Depth demand is asynchronous
   and released when the producer exits. The normal 50 Hz body output does not
   wait for a host inference round trip. Simulation does not establish physical
   network delay/jitter, bus timing, or inference latency on Q6A.

5. **Events and recovery.** `body.c:output_step` calls the existing fourth-wire
   no-progress detector and reports `servo_stall` with joint and command identity.
   Gateway `BodyEvents` supplies tipped/rapid-movement events from IMU observations.
   The configured Freestyle recovery consumer receives these events and generates
   a replacement through its existing executor. Recovery replacement cancels the
   original neural producer; operator Stop also retires pending recovery generation.
   The real-socket/native-body test checks that handoff and measured recovery-target
   receipts with a deterministic generator fixture, not learned physical self-righting.
   Ordinary PPO episodes end on a fall/body terminal; the existing virtual recovery
   scenario separately continues ticking hardware while Freestyle responds.
   Automatic slip-event production and automatic resumption of the original walking
   goal after recovery remain unfinished. A registered `slip` consumer alone does
   not provide either capability.

6. **Public controls and goal consumers.** The dashboard stores native/neural source
   and forward/lateral m/s and yaw rad/s at 100%; these are requested command scales,
   not measured maxima. Neural walking retains continuous speed and steering updates.
   Native stride/rate, cycle counts and named gait styles remain native controls;
   the neural policy receives twist, not separate Walk/Run/Crawl/Crab style labels.
   A speed change is therefore not evidence that a running gait was trained.
   MetaHuman's translation, active-task steering and Finish use the same gateway
   path. Its visual goal evaluation and task lifecycle remain separate from low-level
   gait training. Forward/reverse/turn/lateral performance and complete goal execution
   require behavioral qualification, beyond the connected software tests.

Maintained checks for these boundaries are `VirtualGatewayTests` in
`Emulator/tests/test_neural_gait.py`, `VirtualBodySensorTests` and
`NativeWalkTests` in `Emulator/tests/test_neural_gait_sensors.py`,
`SensorTelemetryTests` in `Emulator/tests/test_gateway_service.py`, and the
neural preview/authentication tests in `Emulator/tests/test_gateway_dashboard.py`.
The adapter advertises `move` when the connected body advertises walking commands;
gestures retain `requestMotion` and do not expose the manual legacy command library.
MetaHuman's existing `active-task-gateway.spec.ts` scenario `paired spoken Stop
routed as cancel` checks this advertised goal-directed Walk route, steering on the
original owner, and cancellation reconciliation through its simulated body. The
full shared suite also contains obsolete gesture and graph-response fixtures;
those are not evidence of current paired qualification. No suite result substitutes
for physical walking.
