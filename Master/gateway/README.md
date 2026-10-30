# Ainekio Gateway

The gateway owns the brain side of each protocol-v1 robot WebSocket. Production
mode authenticates robot sessions, assigns epochs and command sequences, tracks
command lifecycle results, and serves the password-protected local operations
dashboard. Robot tokens, the dashboard password verifier, and the bounded audit
log live under the ignored `build/gateway/` runtime directory by default.

Connection-close events preserve the received or locally sent WebSocket close
code and its underlying protocol error, including when the peer does not finish
the closing handshake. This prevents a malformed-frame failure from being
reported only as an unexplained 1006 disconnect. Malformed control JSON also
reports its existing validator reason. No heartbeat or transport timeout changes
are involved.

## Body Control workspace

The **Tools** sidebar groups controls under Operate, Perception, Recordings,
Maintenance, and Settings. Expand a group and select a tool. The camera stays
beside the tool on desktop and above it on small screens; robot selection,
connection state, and Signal stop remain visible. Tools can collapse the sidebar.
The browser remembers the selected tool and expanded groups. Switching tools
preserves form drafts and does not send robot commands or stop the camera.

Use **Recordings → Video and SD card** for recording and downloads,
**Maintenance → Firmware updates** for uploads and activation, and
**Maintenance → Robot logs** for diagnostics. **Settings** in the header opens
Connections. Refresh an existing dashboard tab to load this layout.

## P4 recording and firmware in Body Control

P4 firmware advertising `servo_feedback_v1` also exposes **Maintenance → Servo
feedback**. It displays all twelve measured/commanded joint positions, sixteen
raw multiplexer inputs, calibration and Stand progress. Reader enable, joint
mapping, three-point calibration and verification settings persist separately
from motor calibration. The existing `stand_enabled` field selects Stand
lift/place and final verification; `arrival_tolerance_us` is the joint-goal tolerance.
`jam_enabled` independently selects no-progress detection;
`tolerance_us` is its error band. Existing settings migration preserves enable
flags, calibration and both tolerances; it never tightens saved settings.
Firmware without `jam_enabled` exposes the older coupled behavior.

Freestyle is the default motion owner. Its generated targets use the P4's
existing measured target executor. The model receives shaft positions and gyro
observations on reassessment; a command receipt alone does not prove foot contact
or carpet clearance. Generated Stand acquisition uses short lift/place and body
correction targets, including rising above the standing target before settling.
Training and simulation evidence do not establish physical success.

The legacy native Stand remains available through explicit manual library
selection. It retains the 0.8.125 moving-leg lift/place checkpoints and its final
verification setting. Its stored-pose transitions and native standing hold are
legacy behavior, not the default Freestyle procedure. Stop, release, calibration
and replacement relinquish ownership; event recovery cannot undo those commands.

Feedback health appears in Robot status and Servo position feedback. The body
publishes health on the existing telemetry cadence; Body Control reports one
`servo_feedback_fault` per episode and `servo_feedback_restored` when it clears,
through the existing body-event/Environment Bridge route. Fault notices share
the existing event cooldown and reaction-face suppression. Current health stays
visible even when a repeated notification is suppressed. These reports never
send a stop, release outputs or reject a command.

Missing samples, ADC rail values, and raw or filtered readings outside the saved
calibration curve are unavailable for position correction and jam inference.
Diagnostic extrapolation remains visible. This confidence classification adds
no command pulse limit: authored motion retains its full configured travel.
`signal_millivolts` measures the fourth-wire signal, not the servo power rail;
`supply_voltage_available:false` is explicit. A low signal cannot by itself
distinguish actual joint position, wiring trouble, or a supply-voltage problem.

The optional jam observer remains available for other movement, manual control,
and holding without a verified Stand goal. With Stand verification disabled,
jam-only Stand retains its completed-pass observation and subsequent holding
checks. Its editable no-progress window defaults to 1000 ms with 5 us of new
shaft travel; a zero window disables release. Feedback does not measure current,
temperature or foot contact. Neither goal recovery nor a position-based jam
heuristic guarantees that the power supply or feedback voltage is reliable.

The initial fold engages one leg's crank/carrier together, following the existing
stepping order, instead of both front legs followed by both rear legs 20 ms later.
Each leg receives the existing full-travel transit estimate before the next starts.
Previously engaged legs remain powered; shoulders still engage at lifted-foot
landmarks. This reduces overlapping initial travel commands but neither measures
current nor guarantees a shaft has arrived. The subsequent contact-aware rise
still coordinates supporting legs to raise the body.

From firmware `0.8.120-p4-recovery-first`, observed non-progress emits a
nonterminal `servo_stall` notification while the current motion or powered hold
continues. A joint reports once per episode and rearms after measured progress
or arrival. Pending reports retain the command's receipt queue capacity.
Older firmware releases outputs on detection; the feedback readback reports
`jam_policy: recovery_first` on the new firmware. Body Control uses the existing
`body_event` path to the environment bridge (`metadata.perceptionEvent=body_event`).
The workflow sees `state.bodyEvent.data` with:

```json
{"kind":"servo_stall","joints":[{"id":4,"name":"rear_right_carrier"}],
 "joint_mask":16,"command_sequence":0,"clock_us":1234567,
 "outputs_released":false,"reason":"no_position_progress"}
```

Joint IDs use the physical V2 joint order, independent of PCA output and ADC mux
channel mappings. Sequence zero covers startup/no active user command. The outer
`event_id` combines the firmware boot identity and occurrence timestamp. The
reaction workflow remains owned by MetaHuman; firmware does not choose an
expression or recovery movement. When Freestyle body-event recovery is enabled,
its trained generator receives current observations, the interrupted action and the compact unfinished plan; full programs and packet buffers are not repeated in recovery input.
Current execution continues during inference; only an available correction
replaces it, with fresh measured positions. Model errors retain current execution.
The first stall remains internal to Body Control/Freestyle. If the admitted
correction stalls again, Body Control releases outputs through its existing
Stop/detach owner without another generation. The failed-correction event then
reaches Environment Bridge for help, retaining joint and command identity,
`correction_failed:true`, actual `outputs_released`, and any `release_error`.
The model is not responsible for selecting that release. A delayed event cannot
release an unrelated replacement command. This is attempt-based, not a new timer.
Manual Stop/replacement and existing driver-fault shutdowns remain immediate.
No model-time cutoff, retry-count limit or changed jam threshold is added.
Shake/tip notification suppression does not hide this observation. Existing calibration curves survive the NVS
configuration upgrade. These
controls use the existing authenticated maintenance proxy
`/api/robot/servo-feedback?robot_id=…` → `/api/servo-feedback` (GET/POST JSON);
they never issue motion commands. See the
[wiring and commissioning procedure](../../docs/v2-12servo/PCA9685_WIRING.md#mg90-fourth-wire-feedback--october-16-2026).

The SD card section starts/stops onboard video recording while preview streaming
continues, lists clips, and downloads a selected clip to the computer. The card
stays inside the robot. Downloaded clips remain until rolling recording reuses them. Near capacity,
firmware 0.8.34 automatically overwrites the oldest completed video in its existing
space, with no review or bulk deletion. Active recordings/downloads are excluded. Clear logs/captures does not delete video.

The Robot firmware section uploads a compiled P4 application `.bin`, then offers
activation on next boot or an explicit restart. Upload enters Doze and finalizes
recording. The existing robot display reports update progress. C6 firmware is
separate. The dashboard uses its existing login and CSRF protection; the pairing
token stays server-side. Transfers use the selected authenticated LAN peer and
bounded chunks in the existing HTTP server threads. The robot requires the
[recording/OTA firmware and one-time bootloader setup](../../Slave/firmware/esp32p4-wifi6/RECORDING_OTA.md).

The Robot logs section reads or downloads bounded current/previous-boot diagnostics
over the same authenticated Wi-Fi path. Retention covers warm resets, not power loss.

## Physical Robot Gateway

### Freestyle plans

The authenticated Body Control API accepts `POST /api/motion-plan` with the
existing dashboard session and CSRF header. The JSON body supplies `robot_id`,
`frames` (V2 compact `[speed_centidegrees_per_second, [joint targets]]` arrays), and `end`
(`hold`, `stand`, or `neutral`). It returns the command sequence; submission
does not mean execution is complete. Normal ACK and terminal receipts track it.

For a P4 advertising `motion_plan_v2`, targets are twelve signed model-angle
centidegrees in the [map 2 joint order](../../Slave/software/protocol/joints_v2.py).
The gateway selects map 2 automatically. V1 continues to use map 1 and eight
targets. The default Environment Bridge exposes `requestMotion`; explicit numeric target
plans use the same P4 executor. V2 frames use `speedDegS`; V1 retains duration frames. See the [wire contract](../../Slave/software/protocol/README.md#p4-twelve-joint-freestyle)
for timing, units and balance behavior. This API adds no gait optimizer or
camera-distance estimator.

### Walking heading feedback

P4 firmware advertising `walking_feedback_v1` has a separate **Walking feedback**
switch in Body Control's Self-leveling panel. It saves independently through
`POST /api/balance` with `{"op":"walking","enabled":true,"robot_id":"…"}`.
The normal `get` response adds `walking_enabled` and `walking_saved`; existing
self-leveling `save` requests do not change either value. An installation with
no saved walking selection reports Off until the owner enables it.

The body adjusts the ongoing gait's steering using relative gyro heading.
Operator-requested curves remain the heading reference. Corrections blend in
trajectory space, sharing the existing forward/turn stroke budget; the semantic
gait retains its full nominal joint movement rate. Missing or recovering IMU
data fades only this correction while the requested gait continues. Status
`walking_feedback` reports enabled/active/reduced, `heading_error_rad`, and
additive `turn_percent`. This is relative heading correction, not absolute
heading, distance estimation, measured foot contact, or a trained policy.
Fourth-wire model evaluation and local trace recording remain separate.

### Neural walking simulation and policy service

`Master/start-neural-gait.sh` runs the independent `gateway.neural_gait.server`
on loopback port 8796. `Master/ainekio-neural-gait.service` provides its user-service
lifecycle. Body Control uses `AINEKIO_NEURAL_GAIT_ENDPOINT` (default
`http://127.0.0.1:8796`) through its authenticated `/api/neural-gait` route.
**Learning history → Neural walking** exposes new/resumed simulation training,
checkpoint selection, evaluation, rendered rollout video and a non-executing
preview from the connected robot's existing calibrated Freestyle observations.
The gait interpreter uses `Emulator/requirements-gait-training.txt`; it does not
load Torch or MuJoCo into the gateway process. FFmpeg provides replay encoding.

Training progress distinguishes rollout collection, checkpoint evaluation (with
completed/total trials), standing-baseline evaluation and final rendering. The
checkpoint table shows mean trial reward; averaging signed forward speed across
forward/reverse tasks is not a success score. The latest checkpoint also shows
requested versus measured velocity and turn rate separately for each command,
weighted by its sampled duration, including command transitions. Earlier
artifacts are projected from their existing command-frame measurements without
rewriting history; missing measurements stay unavailable. Optimizer updates and simulation
steps remain separate counts. Routine checkpoints use seed 1000 and the first
configured scenario for every command. Completion evaluates the published
candidate and held-reference baseline across the full configured scenario/seed
suite. Checkpoint probes and final qualification are labelled separately;
publishing the final training state does not mean it improved.

Automatic footage is produced once, after training: the initial and published
final policies each run one matched command/scenario/seed trial. Detailed replay
remains an explicit request. Its existing artifact lock reports both automatic and manual
rendering; cached clips and already published prefixes are reused. A later clip
failure leaves the last complete video available. Renderer exit alone does not
establish publication: the final result records whether all expected checkpoint
identities are actually in the video metadata.

Neural walking uses the existing gateway producer and P4 walking owner. The
configured walking source selects native or host neural targets; host targets
retain one Walk operation, heading correction, leveling, fourth-wire progress,
jam observation and the existing Finish/Stop/Release contracts. Physical walking
and Freestyle recovery effectiveness still require real-robot qualification.

New training requests use `execution_backend: "body_control"`: the PPO/SAC
learner answers the real gateway's inference requests, the gateway sends actual
`/robot` WebSocket commands, and a host build of production P4 `body.c` writes
PCA output into the MuJoCo plant. Modeled ADC and IMU acquisition return through
production filtering, Fusion, execution history and telemetry serialization.
ACK and consumed target sample remain separate. Each training worker owns one
isolated gateway and one body process; even a single worker is separate from
checkpoint evaluation. The gateway and firmware do not import MuJoCo or Torch.

Historical artifacts without that backend retain their original direct-math
replay. PPO may explicitly migrate to the connected backend with fresh rollouts
while retaining actor, critic and optimizer. `execution_changes` records the
transition, including any standing-feedback setting recovered from the original
named capture. Old SAC replay cannot migrate across executor dynamics. Use
`--resume-checkpoint checkpoints/NAME.zip` (API `resume_checkpoint`) to continue
a published checkpoint from an interrupted run without copying its artifacts.

The standalone V2 virtual body can connect to a normally configured Body Control:

```bash
PYTHONPATH=Master:Slave/software build/gait-training-env/bin/python \
  -m gateway.neural_gait.virtual --environment RUN/manifest.json \
  --endpoint ws://127.0.0.1:8890/robot --robot-id ainekio-virtual-v2 \
  --token-file PRIVATE_ROBOT_TOKEN_FILE
```

Register that virtual identity through the existing gateway pairing owner and
select its neural walking source normally. MetaHuman uses the same authenticated
`/environment` adapter on that gateway. Switching bodies changes the connection
and captured hardware settings, not the motion controller. The virtual body
advertises movement/feedback only: camera/depth scenes, speech and complete
perception-driven goal trials are not implemented by this locomotion plant.
Initialization places the plant in an explicit reference pose; it is not a boot
or physical Stand test. Bus delay, network jitter and RTOS preemption are not
modeled, and workstation results do not qualify Q6A timing.

The repaired MuJoCo environment reads V2 `geometry.json` and the read-only
Wireless assembly export under `Slave/software/models/v2-12servo/simulation`.
It retains twelve servo shafts, eight passive joints and closed four-bar loops.
The 2026-10-27 independent comparison matched twenty exported joint/pickup/rod
frames to the native mechanism within 0.000103 mm and unsigned hinge axes within
0.000084 degrees. Actual CAD surfaces provide visuals; separately derived
collision pieces and volume-based component inertia are still being qualified.
Total mass is owner-measured at 650 g. Component mass distribution, loaded torque,
servo gains and friction remain estimates. Training can omit visual-only meshes
without changing collision or inertia; the source Blender assembly is unchanged.

`native.c` binds production calibration, coupled target fitting, coordinated
ramping, fourth-wire filtering/health/jam detection and Fusion IMU estimation.
The simulator uses the advertised 60 degrees / 0.11 s servo speed without changing
the device's saved speed setting. Feedback includes recorded acquisition skew;
sensor noise settings are explicit, currently unmeasured. The native Walk
baseline additionally runs the existing walking/heading/balance/mapping math
with actual wire commands, live updates and Finish. It does not reproduce the
body-task entry transition or saved-policy admission/history. See the complete
[walking capability and latency audit](../../docs/v2-12servo/WALKING_SYSTEM.md).

Neural foot targets can also use that existing moving-balance owner through
`EnvironmentConfig.balance_enabled` and `balance_tuning` (strength, damping,
roll degrees, pitch degrees). The simulator constructs nominal contact anchors
from the accepted joint frame, applies estimated-IMU balance, then calibration,
ramp and PWM mapping. Disabled preserves earlier runs exactly; omitted fields
in historical configurations mean disabled. These are explicit training settings,
not a reading of the physical robot's saved balance configuration. Inference
preview reports nominal targets. The connected virtual body uses the production
Walk executor; installed physical behavior still requires hardware qualification.

SAC learns a small 64×64 MLP actor from physics rollouts. It consumes joint angles,
velocities, targets, observation usability, IMU, desired motion and explicit
vision/event fields. Outputs are twelve normalized foot offsets relative to the
standing reference, translated by the existing per-leg foot IK/residual fit,
calibration, coordinated ramp and PWM conversion. The initial search span is
±30 mm forward, ±20 mm lateral and ±30 mm vertical per foot; it is an explicit
training setting, not a restriction on the physical robot's capabilities.
Requested and fitted offsets are recorded separately. Camera/body-event
records accompany physical previews. Spatial depth can be consumed by the
explicit v4-depth policy contract below; camera velocity extraction and learned
self-righting remain unqualified. Policy joint inputs use
filtered fourth-wire observations; simulated ground-truth displacement is used
for scoring only. Per-joint acquisition ages and estimator quality/age have
explicit known/missing indicators in the shared policy contract. Host/network
delay, all public gait controls and the final neural/native-walking handoff remain
unfinished. The initial independent-joint experiment produced impossible coupled
targets and learned to hold still; the foot-space producer replaces it without
weakening firmware command validation. Neither experiment replaces the native
walking owner. Earlier checkpoints are incompatible with this
changed observation/dynamics contract and are not physical qualifications.
Do not interpret an available input field as evidence the policy learned to use it.

The same trainer can warm-start its actor from guided simulator demonstrations:
`--demonstration <trace.npz> --imitation-updates 10000 --steps 0` runs behavioral
cloning followed by independent closed-loop evaluation and video publication.
Each trace contains sensor `observation` and normalized `action` arrays; its JSON
sidecar records the exact environment, schema, version and representation.
`imitation.json` retains source hashes and fit error. A low fit error is not a
walking qualification: the actor must reproduce movement from reset and over
longer rollouts. Videos distinguish imitation updates from RL transitions.
`--cycle-start <row> --cycle-steps <rows>` extends that same trainer with
demonstration aggregation. The cyclic teacher selects a successor from the
preceding requested action, and labels states visited by mixtures of teacher
and learner; it is not an elapsed-time phase input to the learned policy.
`--expert-mix` and `--updates-per-round` control the recorded collection rounds.
The run retains exact aggregate data, teacher cycle, immutable round checkpoints
and selection provenance, including rounds that perform worse.
For command-conditioned aggregation, repeat `--demonstration SOURCE.npz` with
`--demonstration-cycles --steps 0`. Each source sidecar supplies its SI command
and `recommended_cycle_rows: [start, end]` (end exclusive). One selected cycle
per command avoids ambiguous teacher choices. Only command variation is allowed;
hardware, geometry, calibration, action scales and sensor/physics settings must
still agree. Every aggregation round collects every selected command, and
evaluation covers each command/seed pair. The manifest retains the command set;
later initialization/resume samples it at resets and evaluates the whole set.
`--command-switch-seconds SECONDS` collects and evaluates continuous request
changes without resetting physics or feedback. Alternatively,
`--command-switch-range MIN MAX` samples each next interval uniformly from the
requested seconds range, using the environment's seeded RNG at each boundary.
The actor receives the next requested twist before choosing its next action;
the preceding transition's reward still describes the preceding request. These
are offline task requests, not leg timing or prescribed gait shapes. The same
request owner is used by rollout collection, aggregation and evaluation; replay
uses the recorded segment boundaries. Evaluation retains per-segment commands,
displacement, yaw and outcomes. Resume inherits saved timing when omitted;
explicit replacement timing is recorded in `task_changes`. Longer imitation
episodes can reuse compatible source data; exact
SAC replay resume still requires the original episode configuration.
This does not define a conversion from Body Control's percentage/stride controls
to metres/second. Videos identify each requested translation/yaw command and its
actual travel. Automatic comparison footage shows one matched trial; detailed
progress replay includes each command.
Evaluation also records one-second `progress_intervals`, split at command
changes, so early movement followed by rest is visible rather than hidden in
an episode average. These intervals only report measurements; they do not
schedule motion or impose a gait period.

Environment version10 scores directed progress from each transition's horizontal
ground displacement and unwrapped heading change. Linear and angular scales
are explicit objective parameters (`reward_velocity_scale_m_s` and
`reward_yaw_scale_rad_s`), not hardware limits. Directed travel earns credit
immediately; excessive recent pace subtracts credit using `reward_overspeed_cost`.
Pace uses `reward_speed_window_s` (one second), not each20ms propulsion pulse;
it only contributes a penalty and never credits old travel after stopping.
Cross-track error uses
`reward_cross_track_cost` independently of requested speed. Thus slow forward
commands no longer magnify yaw noise. Zero-net motion has zero directed progress
and nonnegative costs, so rocking cannot beat rest. Productive bursts can earn
credit; sustained excess speed is penalized. The default overspeed cost2 makes
steady requested pace score higher than steady overspeed. Request changes clear
pace history without resetting physics or delaying execution.
The requested heading remains continuous across Walk updates, matching P4;
only a new Walk establishes a new reference. Version9 incorrectly reset the
reward heading on each twist change. Compact evaluation intervals now include
the additive progress, overspeed, cross-track, slip, effort and action-change
components so a regression can be attributed without retaining raw rollouts.
Positive-score support, slip, effort and action-change costs remain. No foot
order or gait period is prescribed. These experimental normalization scales and
costs are recorded in each environment; they are not physical qualification.
Version9 also repairs native host-heading oscillation using moving balance's
existing damped attitude response. Heading and leveling remain enabled.
Scores from earlier versions are not directly comparable; reevaluate saved
weights under the repaired execution/reward and retain the recorded version.
The current development direction is outcome-based reinforcement learning from
the saved actors. Historical cyclic demonstrations remain reproducible warm-start
data, not a required gait shape or new training target. Distance, fluidity and
efficiency should determine improvement; joint order and shoulder synchrony are
not acceptance criteria. The experimental PPO continuations and their provenance
are recorded in the gait journal. The existing inference and video-replay service
loads both SAC and PPO artifacts through the same loader. A PPO run explicitly
records `algorithm: "PPO"` in its manifest; existing SAC and aggregation manifests
remain compatible. Unknown algorithm names are rejected rather than interpreted
as SAC. The maintained `GaitPPOPolicy` stores whether its exploration standard
deviation is learned or frozen and whether noise is sampled before or after
bounding the mean foot target. Historical latent-coordinate models retain
float64 sampled actions through the squashing inverse. Explicit `action_noise_std`
(`--action-noise-std`, twelve normalized values) moves exploration into action
coordinates: the existing bounded deterministic mean stays the same, while
inward exploration remains possible near an action limit. SB3's standard PPO
path retains raw Gaussian samples for likelihoods and clips only executed/predicted
commands to the existing action range. The handoff preserves actor/value weights
and their Adam moments; only `log_std` moments reset because its units changed.
The manifest records both distributions; ordinary resume retains the saved one.
Model saves include critic and optimizer
state for continuation; loading or packaging an artifact does not select it for
production. The same training CLI and `/train` endpoint resume a saved PPO run
with its actor, value function, optimizer, exploration setting and counters intact.
PPO collects fresh on-policy rollouts and does not load or save SAC replay buffers.
It can continue across the known reward and host-heading revisions with its
learned parameters and optimizer retained, recording `reward_changes` in the
manifest. Its value function must adapt to the revised objective; no historical
rollout rewards are reused. SAC replay resume still requires the same reward
version. The manifest records the native motion/balance source hashes as well
as the environment version; version9's heading repair changes execution dynamics.
Resume starts fresh simulation episodes; it is not an exact mid-rollout restart.
The source PPO rollout length, batch size and epoch settings remain in effect and
are recorded in the new manifest. PPO update counts are optimizer epochs, unlike
SAC gradient-step counts. From-scratch training and imitation remain SAC
operations. Weights-only initialization preserves the source algorithm: SAC
transfers actor weights, while PPO supports the explicit input extension below.
For example, `--resume RUN --directory NEW_RUN --steps 65536
--command-switch-range 12 20` continues a packaged PPO run with varied requests.

#### Terrain, perception and recovery trials

The existing `EnvironmentConfig.scenarios` list defines explicit experimental
scenes. An empty list preserves the original flat physics and sampling sequence.
Each scene has a unique `id`, optional `slope_deg: [roll,pitch]`, `start_rpy_deg`,
`start_xy_m`, `geoms` and `pushes`. Geoms use world `position_m`, `size_m`
(half extents), optional `rpy_deg` and `friction`; kinds are `rock` (ellipsoid),
`block`, `friction_patch` and `wall`. Friction patches have explicit thickness,
not overlapping coplanar floors. Pushes specify `start_s`, `duration_s`, world
`force_n` and optional `torque_nm`. These are curriculum assumptions, not claimed
measurements of the owner's floor. Reset samples scenes deterministically from
the seed; `options.scenario` selects an exact scene. Evaluation covers every
configured scene/command/seed and replay retains that identity in its filenames
and footage. Contact/slip measurements use active terrain and contact normals.
Unqualified native clearance queries carry validity/lower-bound evidence;
evaluation never reports them as exact peak clearance.

`observation_schema: "ainekio-neural-gait-v4-depth"` adds an8×8 optical-axis
depth grid, validity, intrinsics and available camera-pose evidence. Existing
v3 checkpoints keep their exact148 inputs. The physical producer is the existing
MoGe/depth owner, which now publishes `depthSpatial`; it is not a second vision
model. Neural Walk registers depth demand without waiting for inference and
releases the same consumer on completion/cancellation. Original frame identity,
epoch, timestamp and existing camera freshness rules survive projection. Spatial
depth validity is independent of odometry success. Unknown depth/pose remains
explicitly unknown. Preview and actual Walk use the same projection.

Simulation `depth_camera` requires explicit `cameraMatrix`, `imageSize`,
`cameraToBody` (relative to the torso root), `capture_hz`, `latency_s`,
`dropout_probability`, `noise_std_m` and `provenance`. Optional
`max_frame_age_s` reproduces the camera owner's freshness setting.
`publish_camera_to_body:false` uses a stated assumed pose to generate rays but
keeps that unmeasured transform out of the policy observation. Acquisition and
delivery are distinct: the controller does not get fresh perfect depth every
servo frame. This samples optical geometry, not the MoGe neural estimator;
physical perception errors still need measurement and later qualification.

To retain learned actions when introducing these inputs, use the existing
`--initialize-from RUN` operation with the edited configuration (HTTP
`initialize_from`).
PPO transfers actor/value weights, initializes newly active depth weights to
zero and starts a fresh optimizer/rollout buffer; it does not discard the actor.
Source learning counters and transfer assumptions are recorded. Same-schema
PPO `--resume` can extend the scene curriculum while retaining optimizer state.
SAC cannot reuse historical replay across a changed environment. Loading and
training do not select a new physical inference model automatically.

Post-fall recovery is a separate qualification through the existing Freestyle
Bridge, not a second neural motor controller or PPO action label. The normal
Gym walking trial still reports a fall/body terminal. The existing virtual-body
CLI can continue ticking hardware while Freestyle responds:

```bash
PYTHONPATH=.:Master:Slave/software MUJOCO_GL=egl build/gait-training-env/bin/python \
  -m gateway.neural_gait.virtual --environment SCENARIO.json --recovery-scenario \
  --policy-run build/neural-gait/RUN --recovery-endpoint http://127.0.0.1:8794 \
  --directory build/neural-gait/TRIAL
```

`recovery-evaluation.json` retains actual body events, original Walk terminal,
generator provenance, separate generated programs/receipts and physical
trajectory. A completed Release or accepted plan is not a standing recovery.
The shared P4 calibration/speed/feedback read serializers supply the unchanged
Bridge's observations; Stop/Release/replacement keep their normal owners.
The current standing-relative foot action domain is not asserted sufficient
for arbitrary self-righting. Blocked-wall trials expose recovery/navigation
failures; they do not silently turn a forward request into obstacle avoidance.
Walking training's commanded-twist exercises qualify low-level locomotion, not the final task
scope: following, investigation and exploration belong to the existing perception,
navigation and goal-execution owners.
`--workers 2` (or the training API's `workers`) runs independent simulators in
subprocesses while retaining one SAC update per collected transition. Resume
retains the original worker count/replay layout. On the October27 workstation,
two workers increased physics-only throughput from179 to299 steps/s; this excludes
learner updates, rendering and IPC, so it is not an end-to-end training speed claim.

Measured **October29** on the four-core workstation, stepping the Body Control
backend end to end (`environment.json` from run `2300c113`, 40 vector steps per
point, `OMP_NUM_THREADS=1`):

| `--workers` | 1 | 2 | 4 | 8 | 16 |
| --- | --- | --- | --- | --- | --- |
| transitions/s | 48 | 86 | 119 | **151** | 165 |

Throughput saturates by eight workers; sixteen buys ~9% more for twice the
processes and resident memory, and oversubscribes four cores. Use `--workers 8`
here. The ceiling is the physics plus native P4 executor cost per control step,
not the learner. At ~151 transitions/s the 1e8 transitions this class of recipe
reports would take about 7.7 days, so a sample budget in that range is not
currently reachable on this host; raising worker count will not change that.

Artifacts stay under ignored `build/neural-gait` by default (override
`AINEKIO_NEURAL_GAIT_DATA_DIR`). Each run contains the exact environment, geometry
hash, checkpoint, held-out evaluation and progress. SAC runs also retain their
resumable replay buffer.
Replay buffers are stored losslessly as `replay.pkl.gz`; resume also reads older
`replay.pkl` files. Compiled simulator caches use `.mjb.gz` and are loaded through
MuJoCo's binary asset interface. Both retain exact contents and avoid storing
large empty or repeated binary regions uncompressed.
Only the explicitly selected checkpoint is loaded; training never promotes it
automatically. The observation schema, kinematic geometry and CAD/collision
source fingerprint must match for load, resume and replay. Compatible revisions
retain policy input/action meanings; replay metadata distinguishes training and
rendering versions. Replaying an old model with the version9 heading repair is
a new execution comparison, not an exact reproduction of its historical trace.
Previously saved footage retains that historical evidence. SAC resume requires
the same reward/execution version so old replay transitions cannot be reused.
`--initialize-from <run>` starts a new learner from compatible learned actor
parameters with fresh replay rather than reusing scores from an older reward;
the manifest records the source hash and transferred state. If an
initializer changes its requested command or explicitly configured existing
balance settings, learned actor parameters can still transfer; `task_changes`
records those differences and no old replay or optimizer state is loaded.
Sensor/action meaning, geometry, calibration and other physics must still agree.
Exact replay resume retains its stricter same-configuration contract. When a zero-RL
imitation source has archived training data, its first SAC run additionally
prepares the stochastic policy and current-reward replay through the existing
trainer. Explicit demonstration input with zero imitation updates can request
the same preparation. Demonstration provenance must match the new configuration;
after a balance-setting change, collect compatible examples rather than relabel
old observations as if they came from the corrected controller. Bounded-action exploration is fitted to demonstrated
action error without changing deterministic means; endpoint labels are not
inverse-tanh transformed. The selected checkpoint's data prefix is retained.
Actual deterministic rollouts populate the existing replay buffer, preserving
terminal/timeout semantics and worker layout, before random startup collection
is disabled. Entropy targets come from that fitted distribution, with an initial
entropy contribution budget of 10% of measured advantage over standing. An
unmeasurable/nonpositive advantage reports an offline preparation failure.
`handoff.json` records the calibration, real transitions, source hashes and
optimizer resets. Ordinary nonzero-RL resume keeps its learning state. This
repairs initialization; it does not guarantee that later optimization improves
walking, so the independent rollouts remain authoritative. Thus
changed assets cannot silently replace the robot used in a recorded run.
Existing rendered footage remains available without rebuilding that environment. `/render`
produces the recorded evaluation trials, including terminal poses; `/replay?id=...`
and `/image?id=...` serve the video and initial frame. Training saves compactly
evaluated checkpoints without starting renderers. The initial interval is10,000
transitions; `checkpoint_every` (`--checkpoint-every`) selects a different
interval, and resume inherits its source interval unless explicitly changed.
This adjusts evidence frequency only, not control timing or robot motion. Each run's
`optimization.jsonl` retains SB3's compact PPO/SAC optimizer measurements, including
PPO approximate KL, clipping and value loss; it does not store raw rollout buffers.
An explicit training `learning_rate` (`--learning-rate` in the CLI) changes the
existing optimizer's step size and records the source/target rate in the manifest.
Resuming without it preserves the saved schedule. Weights, Adam moments, counters,
exploration and PPO's existing trust-region setting are retained in either case.
PPO also accepts `value_learning_rate` (`--value-learning-rate`) for its existing
value network and `exploration_learning_rate` (`--exploration-learning-rate`)
for a policy with learned standard deviation. The maintained `GaitPPO` keeps
SB3's rollout/update implementation and uses one Adam optimizer with actor,
value and exploration parameter groups. Their identities and moments are
preserved; canonical group order keeps save/load mapping independent of option
application order. Value/exploration can adapt without increasing the movement
mean's update rate. Exploration changes follow PPO gradients; the option does
not force noise to increase/decrease or change deterministic deployment. Saved
rates/groups survive resume.
Explicit `command_units` (`--command-units vx vy yaw`) normalizes SI commands
inside the saved PPO policy, using metres/second and radians/second reference
units. It transforms the corresponding actor/value first-layer columns and
Adam moments so initial predictions are preserved. Raw sensor/request contracts,
motion limits, network dimensions and parameter counts do not change. All
collection, inference, likelihood and value-prediction paths use the same
normalization, recorded in `command_preconditioning`; ordinary resume inherits it.
The optional `ainekio-neural-gait-v5-history` schema extends the existing depth
snapshot with ten past proprioceptive observations at 100 ms spacing, their
actual ages/availability, and sine/cosine of requested heading error. This is one
second of causal sensor history, not a movement period or an inference wait.
The existing `NeuralWalk` owns that history; command updates retain it, while a
new Walk/connection gets a fresh instance. Physical and virtual gateways use the
same `ObservationHistory` projection and device timestamps. Missing history is
marked unavailable; simulator truth is never inserted into a sensor measurement.
Five additional training-only coordinates give the PPO critic recent simulated
pace and reward-reference heading. The actor masks these coordinates on every
collection/inference/likelihood path; physical inference supplies zeros. This
is an asymmetric actor/critic input within the existing PPO implementation.
`initialize_checkpoint` (`--initialize-checkpoint`) selects an existing source
checkpoint without copying its run. Explicit input expansion preserves learned
actor/value weights and zeroes new columns, with fresh optimizer state/rollouts.
Matched experiments initialize both control and expanded policies this way.
History command columns use the same saved command units as the current request.
Legacy v3/v4 artifacts retain their original input dimensions and inference.
Fresh online training now uses `playground-ppo-v1`, adapting the published
MuJoCo Playground/ETH PPO locomotion recipe within the existing training owner.
Explicit `recipe` / `--recipe` selects it; resumes inherit their saved recipe.
The failed least-squares mean-head conversion and its CLI/API option were removed.
Historical distributions remain readable for existing model artifacts.

This baseline starts a new PPO policy instead of converting a saturated actor:
ELU actor/critic networks [512,256,128], linear Gaussian mean, learned initial
standard deviation 0.5, entropy coefficient 0.01, learning rate 3e-4 and five
optimization epochs. Parameters are recorded in the manifest.

The rollout is sized by **transition budget, not steps per worker**. The published
recipe pairs 24 steps per worker with thousands of GPU-parallel environments, so
its per-update sample count comes from parallelism that this host does not have.
`locomotion_rollout_geometry` therefore targets 2048 transitions per update
(`n_steps = 2048 / workers`) and keeps the recipe's four-minibatch divisor, giving
`batch_size` 512. A requested step budget caps the rollout so a short run never
collects more transitions than it asked for; only this recipe's own resumes are
resized, and a historical artifact keeps the geometry it was recorded with.

`target_kl` is 0.08. The former 0.02 made SB3 abandon the epoch loop *before*
`optimizer.step()` on ~93% of rollouts, so roughly one of twenty intended gradient
steps landed per update while the logs still looked healthy. `clip_range` 0.2
remains the per-step trust region. Compare recorded `optimizer_updates` (epochs)
against `n_epochs × rollouts` when judging whether a run actually optimized.

SB3 running observation moments are saved **inside the policy**. Moments update
from the preceding rollout, then remain fixed during the next rollout and its
optimization; gateway inference, replay and evaluation share the saved transform.
Normalized observations are clipped to ±10, matching the reference `VecNormalize`
bound. Coordinates that are constant under a request set — an unused command axis,
an absent depth grid — keep near-zero running variance, and without that clip
their noise is amplified by ~1e4 into the first layer.
The existing privileged-critic mask still excludes simulator-only data from the
actor. No separate runtime observation estimator or fabricated feedback is added.

`reward_profile: "locomotion"` selects robot-scaled exponential linear/yaw
tracking, balance, measured servo acceleration, action-change, load, mechanical
energy and contact-slip terms. Tracking widths are configured in m/s and rad/s;
reward weights and profile are saved with the environment. Historical artifacts
without a profile retain their previous reward. No foot order or gait waveform
is prescribed. Physical progress remains separate from this training score.

`commands` accepts multiple SI velocity/yaw requests through the training API;
repeat `--command VX VY YAW` in the CLI. These go through the existing real
Gateway Walk/update path and native P4 execution. The learned model retains the
shared v3/v4/v5 observation and foot-action contracts, calibration, feedback,
heading, balance, stop and recovery ownership. CPU workers still execute native
firmware and MuJoCo physics; CUDA accelerates the learner, not those workers.
This is an adaptation of the published recipe, not a claim of the thousands of
GPU physics environments or training throughput reported by its authors.

Raw Gaussian samples remain in PPO's likelihood buffer; SB3 clips only executed
and predicted commands to the unchanged action range. Evaluation reports mean
squared requested-foot changes, native P4 target changes/acceleration, and raw
mean clipping incidence in episode summaries and one-second intervals. Native
targets are commanded logical angles, not proof of physical joint acceleration.
No extra motion smoothing, leg order, runtime delay or new servo limit is added.
At completion,
`/progress-video?id=...` compares the initial and published final policies using
one matched trial each. The replay CLI's `--progress --comparison` selects this
compact view; explicit `--progress` retains detailed checkpoint replay. Full final
numeric evaluation uses one seed without variation, or eight when variation is
configured, across all commands and scenarios. Scores report the actual number of evaluated trials. Individual
720p H.264 clips have labelled and clean versions;
`/footage?id=...` builds a temporary ZIP download containing those clips,
comparison videos and provenance, with no model weights or optimizer replay
buffer. Rendering does not retain a duplicate ZIP on disk. A one-second display hold at each
terminal pose is labelled and documented in the clip metadata. Unrendered older
checkpoints are rendered once; later updates concatenate their existing clips. Renderer work is separate
from inference/training. A simulation episode ending after a fall or configured
horizon is a training boundary, not a robot stop policy.

Validation uses the maintained tests, including mirrored foot/loop-closure parity
against the existing mechanism, stationary contact, checkpoint delivery and
Body Control authentication/no-motion behavior:

```sh
PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests:. \
  build/gait-training-env/bin/python -m unittest \
  Emulator.tests.test_neural_gait \
  Emulator.tests.test_neural_gait_sensors \
  Emulator.tests.test_gateway_dashboard.GatewayDashboardTests.test_neural_gait_routes_are_authenticated_and_do_not_command_robot
```

### Supervised gait trial recording

`gateway.gait_trials` records camera JPEGs, device-timestamped IMU/status data,
the submitted command and its terminal receipt through the authenticated
dashboard. For example, from the repository root:

```sh
PYTHONPATH=Master python3 -m gateway.gait_trials \
  --session-file /tmp/private-dashboard-session \
  --robot YOUR_ROBOT_ID --output /tmp/gait-trial-unique \
  --seconds 12 --command motion-plan --payload /tmp/trial-plan.json
```

The session file contains the existing dashboard session cookie value; keep it
private. Omitting `--command` records without sending movement. The recording
duration ends recording only; it never sends Stop or changes balance settings.
Use an explicitly finite plan when a finite physical trial is intended.

`summary.json` reports distinct fresh device samples and maximum sample gaps.
The device's `fresh` flag describes acquisition at publication time, not the
age of a cached dashboard response. A gap across movement can hide the peak
angular rate or impact; a small sampled peak alone cannot establish improvement.
General gait/balance status is slower than IMU telemetry and may remain unchanged
through an entire short motion. Command receipts establish controller completion,
not measured servo tracking. Camera timestamps are host receipt times, not
exposure timestamps. The recorder now retains the camera owner's
`locomotion_measurement` from authenticated dashboard status. `visual_motion`
reports signed forward/lateral displacement, heading change and starting-body-Z
change between distinct calibrated frames. `distance_m` is net endpoint
displacement, not path length, and remains null when calibration, continuity or
matching references are unavailable. Per-segment evidence and unavailable reasons
are retained. Electrical energy remains null without current measurements. Store
recordings and credentials outside version control.

With a device trace, `support` reports phase-binned measured-versus-target leg
reference extension. Firmware 0.8.84 adds timestamp-aligned planned support labels
and IMU calibration identity to the trace. This permits gravity-projected
shortfall during planned stance, excluding swing and ambiguous phase transitions.
Older recordings retain body-axis extension evidence without invented support
labels or calibration. These estimates do not measure foot contact or prove sag;
camera height change and body orientation provide complementary evidence. No
motion decision, automatic stop or new servo writer is part of this assessment.

Camera calibration is under **Camera → Metric ground-plane calibration**. A
printer is optional: choose **Four measured rectangle corners**, measure a flat
rigid target's width and height, freeze each image, and select the same corners
in order around it. Capture roughly ten views with varied tilts and coverage;
four manually selected corners are less precise than a checkerboard. Fit with
the measured camera-to-body transform, then place the target on the actual floor
and select its corners to establish the reference. Refreshing the live preview
does not replace a frozen selection. New status/freeze requests do replace the
server's retained calibration frame; select again if another session replaced it.
Reference tracking needs visible features and does not yet implement autonomous
return-to-start. Validate physical distance against a measured reference before
using it as a gait-training outcome.

Add `--feedback` for fourth-wire gait research on firmware with
`servo_feedback_v1`. It records `feedback.jsonl`, a deduplicated per-joint
`joints.csv`, and `metadata.json` containing firmware, joint calibration and
leveling settings read through their existing owners. Each channel keeps its
own device sample timestamp; the summary reports observed tracking error,
sample gaps and commanded/measured excursion. Invalid readings stay invalid.
Clock resets and calibration revision changes start separate analysis segments.
`--no-camera` omits camera requests when only telemetry is needed.

```sh
PYTHONPATH=Master python3 -m gateway.gait_trials \
  --session-file /tmp/private-dashboard-session \
  --robot YOUR_ROBOT_ID --output /tmp/feedback-baseline-unique \
  --seconds 12 --feedback
```

This mode uses the existing polling API, not a synchronous 50Hz training stream.
The IMU pairing uses nearest device timestamps with explicit signed offsets;
the feedback boot ID is inferred only from agreeing bracketing status reads.
The command is observed at HTTP-response construction, with no exact PWM-write
timestamp. Consequently `observed_error_us` includes timing mismatch and filter
lag and must not be labeled measured motor torque or stall. Raw JSON preserves
all responses even when the CSV deduplicates repeated sensor samples. Inspect
the actual sampling gaps before fitting actuator dynamics. The recorder sends
no automatic Stop and does not alter the current gait or leveling settings.

Firmware **0.8.72** adds `--device-trace` for local device-time recording. This
replaces feedback polling for that recording; camera/status capture stays
concurrent. The P4 records output publications and feedback scans in an optional
512-event PSRAM ring (216 KiB), then downloads up to 64 events per batch through
the existing authenticated servo-feedback endpoint. No SD card is required.
The 20ms acquisition cadence is unchanged; delivered timing is measured, not
guaranteed by the recorder. Start/stop affect this journal only, never movement. After stopping, storage
is released when the final batch has been successfully downloaded. A failed
transfer retains the stopped recording for retry; a new recording allocates its
own buffer. No trace buffer is allocated during ordinary boot.

```sh
PYTHONPATH=Master python3 -m gateway.gait_trials \
  --session-file /tmp/private-dashboard-session \
  --robot YOUR_ROBOT_ID --output /tmp/device-gait-trial-unique \
  --seconds 12 --device-trace
```

`trace.jsonl` preserves every downloaded batch. `joints.csv` associates each
channel's sample time with the preceding output publication and includes the
IMU's original timestamp/offset, planned gait phase and command sequence.
These are software output-publication times, **not physical PCA PWM-edge times**.
ADC timestamps mark completion of each channel's averaged conversions. Planned
phase and walking flags are not measured contact. Raw values and estimator
outputs are both retained. Calibration revision changes invalidate conversion
until matching calibration is provided; raw events remain available.

The ring overwrites its oldest diagnostic events if downloading falls behind.
Sequence gaps and reported loss remain explicit, and analysis does not carry a
target across a gap. Records are independently timestamped rather than falsely
described as simultaneous. The API operations are `trace_start`, `trace_read`
and `trace_stop` (POST JSON `op`); reads carry `after`, `session` and `boot_id`.
Responses are newline-delimited JSON: schema/session header, events, then
`next`/`lost`/`more`. A stop retains buffered records for draining; allocated
storage is reused until reboot. Session/boot checks protect recording identity,
not robot command admission. Recording state and buffers are never saved to NVS.

`gateway.gait_response` fits an **offline actuator-response predictor**, using
NumPy on the analysis host. It does not connect to the robot or produce servo
commands. Supply separate complete recordings for training and evaluation:

```sh
PYTHONPATH=Master python3 -m gateway.gait_response \
  --train /tmp/walk-training-1 /tmp/walk-training-2 \
  --evaluate /tmp/walk-evaluation \
  --output /tmp/gait-response.json
```

For each joint, six learned coefficients predict raw measured position change
from current shaft position, filtered velocity and past targets. The label is
the first actual scan at least 40ms later; the report retains the actual interval
and both predictors receive that interval. Comparison models use command history
alone, unchanged position, or constant filtered velocity. Features never use
future targets, future feedback, or an IMU snapshot acquired after the joint
sample. Invalid samples, scan loss, trace/session and command changes split
examples. Identical trial files cannot count as independent evaluation. These
rules describe offline analysis; they add no restrictions to robot movement.

Reports preserve trial hashes, calibration/firmware provenance, recording
quality, IMU startup/recovery counts, acceleration and approximate body-Z gyro
rotation. Body-Z rotation is not absolute heading, distance or body height.
Trial summaries also report acquisition-counter deltas and accepted sample rate
per device boot when the firmware supplies them. Dashboard observation spacing
is separate from sensor acquisition timing; stale snapshots can still carry
useful cumulative counters. Missing counters are not interpreted as zero resets.
Startup attitude must not be treated as a converged orientation estimate.
Raw shaft readings include noise and calibration error. Improved prediction
on repeated Walk recordings does not establish a better gait or a reliable
response to new corrective commands; neither model is deployed to firmware.

## Physical Robot Gateway operation

The physical robot and the Environment Bridge share one authenticated,
full-duplex gateway process. Ainekio connects to the LAN-facing `/robot` route;
MetaHuman OS connects from loopback to `/environment`. Non-loopback peers are
rejected from `/environment`, as are requests carrying Cloudflare relay
headers. Once established, either side can send data,
so the fact that the ESP32 initiates its connection does not make communication
one-way.

A replacement robot session becomes commandable after its welcome is sent.
The gateway reads the new epoch's heartbeats and receipts while retiring the old
socket and notifying connection subscribers; old-socket teardown does not delay
the new receive loop. Retirement and reception share the connection handler's
lifetime, and replaced commands keep their existing cancellation receipts.

On first pairing, supply a strong robot token. Configure a separate Environment
Bridge token when using MetaHuman on this host; standalone Body Control does not
require MetaHuman. Do not commit either value:

```sh
export AINEKIO_ROBOT_ID='ainekio-01'
export AINEKIO_ROBOT_TOKEN='<strong generated robot token>'
export AINEKIO_ENVIRONMENT_ADAPTER_TOKEN='<strong generated environment token>'
# Optional first-run password; later launches reuse the saved password.
export AINEKIO_DASHBOARD_PASSWORD='<strong local dashboard password>'
./Master/start-physical-gateway.sh
```

The launcher listens for the robot and Environment Bridge on `0.0.0.0:8790`
but permits `/environment` only from loopback and keeps the dashboard on
`127.0.0.1:8791`. In the default local mode the
launcher advertises `_ainekio._tcp.local` with a host-specific service name. P4
firmware advertising `gateway_switching_v1` tries the saved addresses for its
associated Wi-Fi, then discovered protocol-v1 LAN gateways on that subnet. It
keeps an authenticated connection until that connection fails or the gateway
stops. Discoveries are bounded to eight and stay in RAM for that network
association. A
same-computer MetaHuman OS process continues to use
`ws://127.0.0.1:8790/environment`. Runtime tokens and password verifiers remain
under ignored `build/gateway/physical/` storage.

Older P4 firmware retries one configured URL and requires an update for this
switching behavior. The S3 consumer retains its single-candidate ambiguity result.
The [distributed foundation](../../docs/DISTRIBUTED_ROBOT_FOUNDATION.md) records
the remaining cross-installation work and control-grant design.

This one-off home deployment intentionally uses authenticated `ws://` on the
owner's private WPA2 LAN. It is the smallest local path, but the LAN is part of
the trust boundary: do not use it on guest, shared, or public WiFi. Remote
endpoints remain explicitly configured `wss://` addresses with certificate
verification. TLS-only Wi-Fi profiles never fall back to discovered plain WS;
configure a LAN address on that same network to opt into discovery there.
The dashboard reuses its saved operator password across launches. A first run
without `AINEKIO_DASHBOARD_PASSWORD` generates and prints a password once when
launched in an interactive terminal; an unattended first run requires that
environment variable. Later launches do not generate or print another password.
Use **Settings → Password** to change it with your current password.
The environment variable seeds a missing password store only; it cannot undo a
later password change. Only the verifier persists; plaintext passwords are not
saved by the dashboard. Browser sessions last 30 days and survive server
restarts. Logging out revokes the session. A password change keeps the current
browser signed in and signs out other browsers.
Session token hashes and CSRF state are stored in the owner-only ignored runtime
file `dashboard-sessions.json` alongside `dashboard-auth.json`.
Dashboard authentication is separate from robot WiFi setup and is never
presented by the ESP32 setup portal.

**Settings → Robot Wi-Fi** reads and edits P4 settings over the
existing authenticated connection when firmware advertises `robot_settings_v1`.
Older firmware shows an update message. The operator can save four connection slots,
each with Wi-Fi credentials and a Body Control URL, remove a connection,
change the robot setup-hotspot password, and change its pairing token. Passwords
are write-only: unchecked password options preserve the saved secret; checking
an option with an empty Wi-Fi password explicitly selects an open network.
WPA2 passphrases follow the radio's 8–63 ASCII requirement (station profiles also
accept a 64-digit hexadecimal PSK); the dashboard login has no such policy.
With `gateway_switching_v1`, two slots may name the same Wi-Fi and different
computer/tunnel addresses. They share one Wi-Fi password; changing it updates
all slots for that network. Adding another address may omit the already saved
password. Duplicate network/address pairs are rejected. Older firmware is
explicitly rejected before a same-network alternate is written.

Read the robot settings before editing. Saves carry the device revision so a
stale browser cannot overwrite another editor's changes. Saving disables output
and persists settings without dropping the running connection. **Restart robot
to apply** is a separate confirmed action; normal startup can move servos to
saved Home positions. A save/restart response confirms that operation, not
successful reconnection. Secrets are omitted from readback, status and audit.

Pairing changes persist the old and new credentials on this server before the
robot receives the write. Both survive a gateway restart or ambiguous device
result. The first authenticated connection using the new token promotes it and
retires the old one. Reuse that pending token when retrying an uncertain save;
apply/reconnect before starting another rotation. Other server installations
must be given the matching token separately. The existing Generate/Revoke
controls still manage server pairing only. Startup environment tokens seed
missing identities and never overwrite a saved token.

## Using more than one computer

The robot identity belongs to the robot. Each host runs the same gateway and uses
the existing robot token and Body Control password. Transfer those credentials
once using the existing security owners; copying `.env` alone is insufficient.
On the working computer, from the repository root:

```sh
./Master/start-physical-gateway.sh --export-pairing /tmp/ainekio-pairing.json
```

Privately transfer that owner-only file to the other computer, then run:

```sh
chmod 600 /tmp/ainekio-pairing.json
./Master/start-physical-gateway.sh --import-pairing /tmp/ainekio-pairing.json
./Master/start-physical-gateway.sh --check
```

Import starts no listeners or services and is idempotent for the same credentials.
It validates both stores before writing; different existing credentials are
preserved with an explicit error. A disk failure can leave one newly imported
store; repeating that same import completes it. The bundle contains tokens and
the password verifier, including any pending token transition. It excludes
browser sessions, tasks, action receipts, logs, Python paths, MetaHuman credentials
and Cloudflare tunnel credentials. Delete the transfer file when finished.
Later password/token changes are local to each installation; copy the matching
credentials to other hosts again rather than assuming automatic synchronization.

Both hosts install their own gateway dependencies and use their own checkout's
`.venv`. Keep machine paths out of shared configuration. Each optional MetaHuman
Bridge retains its matching adapter token. The robot relay hostname remains
`/robot` only. A separate Cloudflare Access TCP hostname can connect a remote
MetaHuman desktop as described below; its credentials/configuration stay local.

- **Same LAN:** a paired gateway with local discovery enabled can be found after
  the current gateway stops. Multiple advertisements are candidates, not an
  error or permission for simultaneous controllers.
- **Different hotspots:** save their SSIDs/passwords and server addresses once.
  P4 cycles distinct networks when Wi-Fi is offline, then selects gateways on
  the associated network. Turn off the previous hotspot when switching SSIDs;
  a still-working Wi-Fi connection is retained. With `AINEKIO_HOTSPOT=1`, the
gateway stops its managed hotspot on shutdown.
- **Cloudflare/remote:** save the `wss://.../robot` endpoint on the relevant Wi-Fi.
  It uses the same pairing and command/result contract with verified TLS.

Start Body Control on the desired host and stop it on the current host using
`./Master/stop-physical-gateway.sh` (or Ctrl+C for a foreground launcher).
A returning host does not seize a healthy connection. The P4 destroys the old
WebSocket and closes admission before opening another. On P4 firmware
`0.8.113-p4-link-motion`, connection loss preserves powered output and locally
accepted finite motion. Open-ended gaits use their existing Finish trajectory
and hold the settled pose. Retired-session commands are not replayed; the gateway
still reports an unknown/disconnected outcome for receipts it could not observe. Connection switching does not transfer a MetaHuman objective,
replay movement or copy a durable execution database.

A phone browser can use an available host's password-protected dashboard when
that host's `AINEKIO_DASHBOARD_HOST` is bound to its private LAN address. The
default dashboard remains loopback. Direct on-P4 browser control is separate
from its setup portal and is not implemented by this change.

The launcher stays in the foreground. Press Ctrl+C to stop it. For normal
owner operation it can instead be supervised by the included user service.
The launcher uses `.venv/bin/python3` from this checkout; `AINEKIO_PYTHON` can
select another absolute interpreter path with the gateway dependencies installed.
Check local prerequisites without opening listeners or printing credentials:

```sh
./Master/start-physical-gateway.sh --check
```

This checks the interpreter, dependencies, discovery executable when enabled, and
saved pairing/password-store validity and recognition/Bridge configuration.
It does not verify network/port
availability or a physical connection.

Install the user service for this checkout without enabling or starting it:

```sh
./Master/start-physical-gateway.sh --install-service
systemctl --user daemon-reload
```

The installer preserves unmanaged existing units. After `.env` contains the
required tokens and the check passes, explicitly enable operation with:

```sh
systemctl --user enable --now ainekio-gateway.service
```

After that, the gateway and its discovery advertisement start when the owner
logs in and restart after a process failure. Rerun the installer and daemon reload
after moving the checkout. The unmodified tracked template assumes `~/Ainekio`.

On a host with the Ainekio hotspot services installed, set `AINEKIO_HOTSPOT=1`
in the ignored `.env` to select hotspot mode at startup. In Body Control,
**Settings → Robot connection mode** switches between the existing Wi-Fi network
and the configured robot hotspot immediately, saving the choice in `.env`.
The running gateway starts `ainekio-hotspot-dhcp.service` and its dependencies,
then stops `ainekio-hotspot-interface.service` and its dependent services only
when switched to Wi-Fi. The hotspot stays up across gateway restarts. Switching
does not restart Body Control. A robot using the hotspot reconnects through its
saved Wi-Fi profiles when that hotspot is turned off.
The operator needs permission to
start/stop those specific system units without an interactive prompt. Disable
their independent boot enablement when using this connection-mode setting.
The default is `0`, so other hosts need no hotspot services. Body Control's
dashboard login and robot pairing authentication continue to use their existing
owners. The launcher loads `.env`; a direct `python3 -m gateway.server` invocation
uses `AINEKIO_HOTSPOT` from its process environment and saves UI choices to `.env`
in its working directory.

To install these missing services on Ubuntu, install the packaged dependencies
and run the existing-contract installer once as root:

```sh
sudo apt-get install --no-install-recommends hostapd dnsmasq-base iw iproute2 network-manager polkitd
sudo python3 Master/install-robot-hotspot.py --interface wlan0 --operator "$USER" \
  --credentials /private/path/hostapd.conf
```

Run from the repository root; select the actual station interface and an
owner-only (0600) hostapd file containing the existing `ssid` and either
`wpa_passphrase` or `wpa_psk`. Privately copy that identity from the working
host to reuse the robot's saved Wi-Fi credentials. The installer copies only
those fields; desktop interface names and other hostapd settings are not imported.
It preserves unmanaged existing files with an explicit error and installs
no independently boot-enabled hotspot. Stop the gateway before updating the
installed configuration. Set `AINEKIO_HOTSPOT=1` in `.env` and use the normal
launcher to start it.

The radio must support an AP alongside its station connection; inspect `iw list`
for valid interface combinations. The installer adds `aineap0`, leaves the
station connection intact and defaults to 2.4 GHz channel 1. Use `--channel`
for another permitted channel (1–11); hardware limited to one channel requires
a compatible uplink channel or another adapter. Verify actual radio operation.
The hotspot enables 802.11n with WMM at 20 MHz. Both settings belong in
`/etc/ainekio-network/hostapd.conf` (`ieee80211n=1`, `wmm_enabled=1`): the Q6A
AIC8800/P4 link exhibited repeated TCP stalls with the former legacy-mode
configuration. Check `iw dev aineap0 station dump` for an MCS rate after the
robot associates; an active hostapd service alone does not verify the mode.
The separate interface serves the private `10.42.77.0/24` robot LAN, with the
gateway at `ws://10.42.77.1:8790/robot`. DHCP is confined to that interface and
does not advertise Internet routing or DNS. This is the robot-to-gateway link;
the Q6A gateway and configured remote services use the Q6A's existing uplink.
The installer does not configure NAT, remote MetaHuman execution or Cloudflare.
Operator permissions allow only starting/stopping the three named hotspot
units. Stopping the gateway removes its AP and DHCP/hostapd services together.

Updated P4 firmware tries distinct saved Wi-Fi networks in order, allowing 15
seconds per network while offline. It keeps a working Wi-Fi connection; gateway
failure selects other computers on that same network without Wi-Fi roaming.
An unauthenticated gateway attempt expires after 10 seconds, with a 1-second
retry delay and a bounded 2.5-second discovery query after configured candidates.
These are source limits, not measured physical handoff latency. Each slot supplies its own server
URL (for example `ws://10.42.77.1:8790/robot` on the computer hotspot). This uses
normal Wi-Fi association, not Wi-Fi Direct. If no saved network works, the
existing timed setup AP becomes available after 60 seconds; with no networks it
opens immediately. Wi-Fi/controller loss preserves P4 powered motion: finite
tasks continue locally, continuous gaits finish gracefully, and standing holds
remain powered. Stale-command fencing remains; reconnecting never replays movement.

The AP-only setup page at `http://192.168.4.1/` remains the recovery path. For an
already configured P4, it can replace a network and optionally change its server
address or token; blank address/token inputs preserve those values. Portal
saves restart immediately, as before. The serial configuration path also remains.
Existing single-network NVS configuration and setup passwords are retained when
upgrading; the first save creates the new P4 settings record. No NVS erase is
needed. Board-level switching and provisioning still require device testing.

The physical dashboard uses the selected robot's authenticated JPEG stream as
its first panel; enable the camera in **Camera and audio** if the panel is
waiting for frames. The emulator stack keeps the visual robot simulator in that
position instead. For bring-up testing, the body microphone starts enabled with
the VAD gate; the same panel can turn it off or select another supported gate
and shows the live input level. Camera streaming is local to this dashboard and
is not forwarded as a continuous image stream to MetaHuman.

The robot controller now originates one fresh still after completed physical
actions and VAD-delimited microphone utterances. The gateway receives the
firmware correlation metadata and JPEG, validates them, and forwards one
correlated Environment observation; it does not send a second automatic
snapshot command. MetaHuman can still request `captureImage` directly. These
bounded snapshots share the camera service with the dashboard but are the only
camera images admitted to the Environment observation path.
When MetaHuman selects visual context, it sends `environment.visual.read`
with `version: 1`, `requestId`, and `sessionId` through the same bridge.
The adapter replies `environment.visual.result` with the same identities and
`visual` containing the latest already-received selected-body frame, or `null`
when none is available. The frame retains its original gateway receipt time
and robot/gateway/epoch/counter identity. This read does not trigger a capture,
wait for a new frame, or publish an observation. Session errors return `error`.

Bodies advertising `camera_profiles_v1` expose separate **Stream resolution**
and **Snapshot resolution** controls in the existing panel. Stream output is
QVGA or VGA at the selected frame rate; P4 snapshots also support XGA (1024×768),
native 960p (1280×960), cropped 1080p, and Auto. Auto meters in the native mode
and may change to cropped 1080p in bright light. Selecting 960p preserves the
wider field of view and avoids that additional sensor-mode change. The P4 still
profile defaults to Auto and stays unchanged when a gateway caller omits
`snapshot_resolution`. Saved dashboard settings are restored on connection.
Exposure stability is measured during preview and reused for subsequent
snapshots in the same sensor mode. Exposure changes invalidate that stability;
a sensor restart or mode change restarts the assessment. Shutter and gain remain
automatic. Both profiles are runtime settings. One P4 camera
task and JPEG encoder serve both outputs, with no additional image-buffer
allocation. Disabling preview leaves requested snapshots available. A still
has explicit request/action/audio correlation, independent of preview FPS.

P4 camera transport uses JPEG chunks on the existing connection, allowing
microphone packets and control messages between chunks. Body Control reconstructs
one complete image before notifying the existing camera consumers; image quality,
resolution and capture correlation are unchanged. Complete JPEG frames from V1
and older firmware remain supported. Activate this Body Control version before
the corresponding P4 firmware. TCP loss can still delay transmission; chunking
removes whole-image scheduling monopolization, not physical network constraints.

This supports a local P4→Q6A preview and occasional remote LLM stills through
the existing gateway and Environment Bridge. Continuous video is not sent to
the remote LLM. Selecting a frame from a low-resolution preview would limit
remote image detail to that preview resolution; requesting a separate encoded
still preserves the option of more detail from the same sensor capture mode.

Run the production gateway with development credentials supplied through the
environment on first startup:

```sh
export AINEKIO_ROBOT_ID='ainekio-emulator-01'
export AINEKIO_ROBOT_TOKEN='local-development-token'
export AINEKIO_DASHBOARD_PASSWORD='local-operator-password'
PYTHONPATH=Master:Slave/software python3 -m gateway.server
```

The dashboard is then available at `http://127.0.0.1:8791/`. If its password
store does not exist, an interactive launch can generate and print a random
one-time password instead of using `AINEKIO_DASHBOARD_PASSWORD`.

The scripted gateway stub remains available for focused body-client tests:

```sh
export AINEKIO_ROBOT_TOKEN='local-development-token'
PYTHONPATH=Master:Slave/software \
  python3 -m gateway.server --stub --commands stand,walk,neutral
```

To expose the generic environment adapter, configure a dedicated adapter token:

```sh
export AINEKIO_ENVIRONMENT_ADAPTER_TOKEN='shared-environment-adapter-token'
PYTHONPATH=Master:Slave/software python3 -m gateway.server
```

The endpoint is `ws://127.0.0.1:8790/environment`. The connecting environment
agent authenticates in its first protocol message. Ainekio does not contain a
MetaHuman URL or call MetaHuman APIs directly.

Completed microphone utterances and completed physical actions arrive with one
firmware-originated correlated still when the camera is ready. Future typed
safety or sensor events should opt into the same controller-owned trigger and
correlation fields. Routine status, heartbeat, individual PCM frames, and
dashboard preview traffic do not produce Environment snapshots.

## Desktop MetaHuman connected to a Q6A through Cloudflare

Run MetaHuman OS and its Environment Bridge on the desktop. Run only the Ainekio
gateway and its Cloudflare connector on the Ubuntu Q6A. The robot connects to
the Q6A gateway's `/robot` endpoint over its local Wi-Fi. No phone is involved.

The existing `Master/start-physical-relay.sh` can add a separate TCP hostname to
its named tunnel. TCP forwarding preserves the inner WebSocket request and the
Q6A connector opens a loopback connection, so `/environment` retains its existing
loopback and adapter-token checks. An HTTP tunnel to `/environment` is rejected
because it adds Cloudflare relay headers. TCP forwards the gateway port, including
both `/robot` and `/environment`; it is not a path-filtered HTTP route. The
dashboard remains on its separate, unrouted port.

### Q6A setup

On Ubuntu, install `python3-venv` and `avahi-utils` for the existing launcher,
then create this checkout's Python environment:

```sh
python3 -m venv .venv
.venv/bin/python3 -m pip install -r Emulator/requirements-host.txt
```

Run the pip command again after pulling dependency changes. These requirements
include NumPy and headless OpenCV for the gateway's ground-plane camera processing;
the launcher checks their availability before starting services.

Install `cloudflared` using Cloudflare's
[download instructions](https://developers.cloudflare.com/tunnel/downloads/).
Import the existing robot pairing/password as described under **Using more than
one computer**. Runtime stores and `.env` do not arrive through Git sync.

Use a locally managed named tunnel with the existing relay launcher. If creating
one for the Q6A, run:

```sh
cloudflared tunnel login
cloudflared tunnel create ainekio-q6a
cloudflared tunnel route dns ainekio-q6a bridge.ainek.io
```

Use `bridge.ainek.io` on your Cloudflare-managed domain. Login opens a
browser, or prints a URL you can open on the desktop. In Cloudflare Zero Trust,
create a self-hosted Access application for this exact hostname and an Allow
policy for your login identity before starting the connector. Dashboard login
alone is not the application's Access login.

Set these in the Q6A's ignored `.env`, using the UUID/credentials file generated
on this host and the same adapter secret configured on the MetaHuman desktop:

```dotenv
AINEKIO_CLOUDFLARE_TUNNEL_ID=<tunnel UUID>
AINEKIO_CLOUDFLARE_CREDENTIALS_FILE=/home/<user>/.cloudflared/<tunnel UUID>.json
AINEKIO_CLOUDFLARE_ENVIRONMENT_HOSTNAME=bridge.ainek.io
AINEKIO_ENVIRONMENT_ADAPTER_TOKEN=<shared adapter secret>
```

Keep tunnel credentials outside the checkout. `AINEKIO_GATEWAY_PORT` selects the
gateway origin port when changed from 8790. The legacy robot HTTP hostname is
still configured, but only the separate TCP hostname needs a DNS route for this
desktop-to-Q6A setup. Do not run the same tunnel's connector simultaneously on
another host: Cloudflare can send connections to either installation.

Start the gateway and connector in separate terminals for the first test:

```sh
./Master/start-physical-gateway.sh --check
./Master/start-physical-gateway.sh
# In a second terminal:
./Master/start-physical-relay.sh --check
./Master/start-physical-relay.sh
```

`--check` validates the local relay configuration; it does not prove the Access
policy, DNS, Internet connectivity, or a robot connection. Keep both processes
running. The gateway's existing user service is documented above. For unattended
connector startup after reboot, use Cloudflare's documented
[Linux service setup](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/linux/)
with the generated `build/gateway/cloudflare/ainekio-robot.yml` config. Regenerate
it with the relay's `--check` after changing `.env`, then restart that service;
use either the service or the foreground relay launcher to own the connector.

To have every Body Control launch also start the installed Cloudflare user
service, save its unit name in this Q6A checkout's ignored `.env`:

```dotenv
AINEKIO_CLOUDFLARE_RELAY_SERVICE=ainekio-cloudflare-relay.service
```

This applies to foreground and supervised gateway launches. The launcher queues
an idempotent start through systemd; the existing service continues to own the
connector and its restarts. `--check` starts no services. This setting controls the
MetaHuman connection independently of the local/LAN/Cloudflare dashboard access
choice. On the MetaHuman desktop, select **Environment Bridge Remote** for startup;
that bridge owns the Access forwarder and reconnects when the Q6A returns.

### Desktop setup and test

Install `cloudflared` on the desktop, then in the MetaHuman checkout run:

```sh
./bin/connect-environment bridge.ainek.io
```

This opens local port 18790. Configure MetaHuman's ignored `.env` with
`MH_ENVIRONMENT_ADAPTER_URL=ws://127.0.0.1:18790/environment` and
`MH_ENVIRONMENT_ADAPTER_TOKEN` matching the Q6A's adapter secret.
`MH_ENVIRONMENT_BRIDGE_TOKEN` remains the desktop's existing internal service
token; it is separate from the adapter secret. Restart MetaHuman to load changed
environment variables. Alternatively set **Agent Monitor → Environment Bridge
→ Adapter URL** when `MH_ENVIRONMENT_ADAPTER_URL` is absent; the environment
variable takes precedence over that setting.

When the Bridge connects, the desktop connector opens a browser for Cloudflare
Access authentication. A desktop shortcut can run the forwarding command.
Keep the forwarder running, and use Agent Monitor's existing Bridge state and
diagnostics to verify the returned gateway session and connected robot. Test an
owner-selected command and its returned receipt, followed by the intended camera,
microphone and speech paths, before calling the demo ready. No motion is started
by the tunnel or desktop forwarding launchers.

This transport uses Cloudflare's
[Access TCP workflow](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/non-http/cloudflared-authentication/arbitrary-tcp/).
Cloudflare recommends Client-to-Tunnel for
[long-lived connections](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/protocols/).
The local TCP-forwarding regression test establishes gateway compatibility, not
Cloudflare authentication, Q6A performance, Wi-Fi latency, or physical behavior.

## Updating an ongoing movement

The authenticated Environment adapter accepts `environment.action.update` for
an already-admitted, ongoing V2 walk. It updates the original command through
the same gateway and body lease; it does not submit another cognitive action or
take task ownership from MetaHuman. The original action must have passed the
existing accepted-feedback admission gate before updates can be sent.

The `bridge.ready` observation exposes `state.activeMovementUpdates`. Updates
are available only for an online, motion-ready V2 body advertising ongoing
locomotion and command deadlines. Composed steering additionally requires
`walk_steering_v1`; use only the advertised `controls`. Older supported bodies
keep speed/stride/rate updates and explicitly reject steering before dispatch.
Use its `gatewayInstance`, the body's current
`robotId`/`epoch`, the original `actionId`, and the exact original `bodyLease`:

```json
{
  "type": "environment.action.update",
  "version": 1,
  "sessionId": "ainekio-01",
  "gatewayInstance": "<current gateway instance>",
  "robotId": "<connected robot ID>",
  "epoch": 7,
  "actionId": "<original action ID>",
  "bodyLease": {
    "bodyId": "ainekio-01",
    "executionId": "<original execution ID>",
    "generation": 1
  },
  "revision": 1,
  "validForMs": 500,
  "controls": {"speed": 70, "forward": 80, "turn": 25}
}
```

`controls` accepts `speed` **or** both `stride` and `rate`, using the existing
walking protocol ranges. Optional paired `forward` and `turn` percentages
(-100 through 100) compose translation and yaw in the running gait. Positive
forward advances; positive turn turns left. The original direction and gait
identifiers stay attached to the original command; composed steering is
interpolated over a gait cycle without resetting its phase. Finite movements cannot be converted into ongoing
walks. Servo targets and additional control fields are rejected. The body retains
its existing gait interpolation, coordinated timing and calibrated limits.

Use increasing positive integer revisions, up to 2,147,483,647. A revision
reserved for dispatch is stored in the original receipt and cannot be replayed,
including after reopening the receipt store. Send one update at a time and await
its result; a second concurrent update is rejected rather than queued.

`validForMs` is an integer from 1 through 2000, measured from receipt at this
adapter. The gateway's configured action-age limit can shorten it. Expiry,
lease, cancellation and connection identity are checked before dispatch; the
remaining validity also reaches the P4 through its existing command deadline.
Queueing and body receipt do not restart that validity. Upstream observation age
and transport delay before adapter receipt are separate and remain the sender's
responsibility.

The reply is `environment.action.update.result`, with the same `actionId` and
`revision`, a wire `sequence` when assigned, and status `acknowledged`, `rejected`
or `outcome_unknown`. An acknowledgement confirms body acceptance of the update;
it does not complete the parent task or verify measured motion. If the body's
reply times out after dispatch, further updates are blocked until that sequence
has a terminal receipt. Cancellation remains available while awaiting a reply.
Update results are not cognitive feedback and are not replayed to a new bridge.
The original action retains its normal completion/cancellation receipt.

MetaHuman's canonical active task executor now produces these updates through
the existing Coordinator and Bridge. The Bridge correlates each update receipt
to its finite settings job while leaving the original movement active. Task
programs use semantic moves, rather than a new body-level search command. Object-recognition model
comparisons are deferred to the assembled prototype.

Desktop coverage includes an authenticated WebSocket bridge, the real gateway
command path with a simulated body, parent-action lifetime, cancellation and
ownership changes, expiry, replay, reconnect identities and lost receipts:

```sh
PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests \
  python3 -m unittest Emulator.tests.test_active_movement
```

## Continuous camera processing

`gateway.plugins.CameraFramePlugin` processes camera images outside the robot
receive loop. It retains one image being processed and one waiting image; each
new arrival replaces the waiting image. Synchronous consumers run on one worker
thread, and async consumers run in a separate task and must yield during I/O.
Slow inference therefore does not make the receive loop await the model.

An optional `observe` callback receives a `CameraAnalysis` containing the
backend's result, robot ID, connection epoch, frame counter, and monotonic
receipt/completion times. The backend can return detector boxes or a vision LLM
description; the gateway does not reinterpret either as verified identity or
task completion. Consumers must not treat model scores as measured probabilities.

The plugin drops frames/results that exceed `max_frame_age_s` (default one
second), belong to an ended connection epoch, or have a stale control heartbeat.
Set this limit for the intended observation use before selecting a backend.
Receipt time is **not** sensor capture time: it excludes age accumulated before
the gateway received the image. Acquisition timestamps and frame-associated
robot pose remain necessary before using image geometry for motion control.

The owner must await `plugin.aclose()` on removal or shutdown. Closing
unsubscribes the plugin, discards waiting frames/results, and joins its worker.
A running native inference call cannot be killed by coroutine cancellation;
shutdown waits for that call, so inference backends need their own bounded
request deadlines. This thread separation does not establish hard real-time
behavior for CPU-bound Python code or under system-wide load.

At the current 256 KiB JPEG transport cap, the two retained input images use at
most 512 KiB of payload storage. Model weights, decoded images, intermediate
tensors, results, and runtime overhead require a separate measured budget.

## Configured recognition and MetaHuman handoff

The production gateway can connect the camera worker to an explicitly configured
local or remote vision service. It uses the Chat Completions image/JSON interface supported
by services such as [vLLM](https://docs.vllm.ai/en/latest/features/multimodal_inputs/).
The model must support images and JSON output. No model, weights, package or
inference server is installed or started by this gateway.

```sh
export AINEKIO_VISION_URL='https://your-recognition-host/v1/chat/completions'
export AINEKIO_VISION_MODEL='your-served-vision-model'
# Set AINEKIO_VISION_API_KEY in the ignored .env or the service environment.
# Start the existing authenticated production gateway with these settings.
```

Equivalent CLI options are `--vision-url`, `--vision-model`,
`--vision-timeout-s` (default 2), and `--vision-max-frame-age-s` (default 1).
The frame-age limit must be 0.1–30 seconds and includes inference time; choose it
for the consumer's freshness needs. The URL and model must both be configured,
and the authenticated Environment Bridge must be enabled. Omission disables
recognition while leaving preview and correlated stills available.

An optional local detector uses `--vision-yolo-weights /absolute/path/to/existing.pt`
instead of the URL/model pair. `--vision-yolo-device` defaults to `cpu` and
`--vision-yolo-image-size` to 640. It uses the same camera worker, freshness limit,
`RecognitionResult`, authenticated bridge and behavior owner. Ultralytics must
already be installed in the explicitly selected Python environment; the gateway
does not install packages or resolve a model name into downloaded weights. Only
detection/segmentation checkpoints are accepted. Labels come from that checkpoint's
class map, and segmentation supplies boxes, not distance estimates. The model
identity includes the weights SHA256. This option does not enable camera capture.

Optional generic continuity uses `--vision-yolo-tracker bytetrack.yaml` or
`AINEKIO_VISION_YOLO_TRACKER=bytetrack.yaml`. A local ByteTrack YAML can supply
its association settings. Install the optional `lap` dependency in the selected
Python environment before enabling this option; it is not installed at runtime.
The same camera worker commits tracking only for accepted frames. Every detection
remains visible, including boxes without a confirmed track. `trackId` is scoped
to the camera session and recognition generation, survives the existing bridge,
and appears in the detection overlay tooltip. It estimates continuity, not
personal identity. Named-face recognition uses that association when available.
This option alone does not select targets or command movement.

Prompted YOLOE checkpoints support selecting a detection in the camera's
**Show detections on their source image** view. Selection sends the exact image
and region as a visual reference. Text search additionally requires a local
MobileCLIP encoder selected by `--vision-yolo-text-encoder /absolute/path/mobileclip2_b.ts`
or `AINEKIO_VISION_YOLO_TEXT_ENCODER`, with its CLIP tokenizer installed in the
selected Python environment. Choose encoder weights compatible with the YOLOE
checkpoint. The camera panel advertises the operations available from that
backend; **Release target** restores its original class configuration. A search
or selection does not enable the camera, recognition, or robot movement.

For prompted checkpoints distributed with placeholder class names, prepare the
desired default vocabulary before deployment. For example, the desktop pilot
preserves its previous `person` detector by computing that label's embedding
with the configured local encoder, calling `set_classes`, and saving a local
checkpoint. Remove `model.clip_model` before saving so the encoder remains a
separate file. Configure the gateway with that prepared checkpoint; startup and
**Release target** then restore the same meaningful default vocabulary. Do not
interpret numeric placeholder labels as a known class map. The pilot's prepared
weights and validation are recorded in the integration audit.

MetaHuman uses the same finite `environment.visual-read` request over the
Environment Bridge for search, visual selection and release. The existing task
program can acquire candidates through the configured vision model, select a
retained image region, and observe while stationary. Results carry the target
query ID; detections and track IDs continue through ordinary perception telemetry.
Visual references improve matching but do not prove that a similar object is
the same physical instance. Target configuration is session state, not a saved
user preference; production deployment and actual-device qualification are
tracked in `docs/audits/VISION_TRACKING_INTEGRATION.md`.

To retain the local detector across normal launcher restarts, set
`AINEKIO_VISION_YOLO_WEIGHTS`, `AINEKIO_VISION_YOLO_DEVICE` and
`AINEKIO_VISION_YOLO_IMAGE_SIZE` in the existing ignored `.env`. Command-line
options override these values. `AINEKIO_PYTHON` selects the existing interpreter
with Ultralytics installed. Body Control's camera panel reports whether recognition
is configured, observation age, fresh-result rate, received frames and errors.
These ages start at gateway receipt, not camera exposure.

Body Control's **Perception** group separates three saved choices under
**Camera settings**, **Recognition**, and **MetaHuman control**:
camera settings are stored per robot in the gateway data directory and reapplied
on that robot's next connection; recognition can be switched off without stopping
preview (queued and late inference results are discarded); MetaHuman robot control
uses Core's existing saved Environment Bridge setting over the authenticated bridge.
Switching robot control off cancels the active owner's robot executions through
the Coordinator and keeps unresolved command receipts available for reconciliation.
Switching it on permits new instructions, without restarting cancelled executions
or changing the configured Reactive/Semi/Full mode. Manual controls remain independent.
An off setting or cancellation request does not establish physical rest.

On bridge reconnection, the adapter replays saved deliveries while reading their
acknowledgements. Producing new feedback sends that receipt only, not the pending
backlog. Recovery follows an existing command's wire identity without resending
the command. A recorded unknown outcome remains unknown; reconnecting alone does
not create another observation of it. A new correlated result, or a result whose
observation was not persisted, produces its own observation through the same
receipt owner.

### Named people (optional local models)

The existing camera worker can combine YOLO person boxes with OpenCV YuNet face
detection and SFace embeddings. Explicit local paths select the additional models:
`AINEKIO_VISION_FACE_DETECTOR=/absolute/path/face_detection_yunet_2023mar.onnx`
and `AINEKIO_VISION_FACE_RECOGNIZER=/absolute/path/face_recognition_sface_2021dec.onnx`.
Both are required alongside the existing YOLO configuration. Nothing downloads
automatically, changes the selected detector, starts capture, or issues commands.
OpenCV must provide `FaceDetectorYN` and `FaceRecognizerSF` in the selected Python.
Model sources and licenses: [OpenCV YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
and [OpenCV SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface).

In **Vision and robot control → Recognition → Named people**, enter a name and
upload a clear single-face JPEG of at most 256 KiB. Add different views using the
same name, up to four samples per person and 16 people. The authenticated gateway
processes the selected file on its host; it discards the photo and stores names,
stable person IDs and embeddings in owner-only `known-people.json` alongside its
existing private settings. Do not commit or publish that file. **Forget** removes
the enrolled features and invalidates inherited names. Enrollment persists across
restarts, but live track IDs do not. Changing the recognition model requires
explicit re-enrollment, not reinterpretation of old features.

Fresh typed observations retain `label: person` and add an optional `identity`:
`trackId`, and `state` (`unknown`, `face_match`, or `tracked`). Named estimates
carry `personId`, `name`, and `faceAgeMs`; a fresh face match also carries cosine
`similarity`, not a probability. The paired Core perception validator must support
these fields before enabling the face models. The composite observation model
hash binds YOLO, YuNet and SFace; dashboard status exposes the two face model hashes.

Matching uses SFace's reference cosine threshold 0.363 with a 0.08 separation
from the next enrolled person. These are starting parameters, not measured
accuracy on this robot. Tracking accepts mutually unambiguous box overlap and
color continuity, for gaps no longer than 1.5 seconds and up to 3 seconds after a
face match. Fresh unmatched faces, ambiguous crossings and simultaneous duplicate
identity matches lose the name. Missing detections emit no visible track. Reconnect,
recognition off/on, and gallery changes reset continuity; stale or discarded
inference never commits tracking state. Reappearance can be named again by a fresh
face match, with a new track ID.

**Limit:** short box/color association is not robust body re-identification.
Similarly clothed people replacing each other without a visible face can still
produce an incorrect `tracked` estimate. Small/turned/occluded faces, lookalikes,
photos and displays can defeat recognition; there is no liveness verification.
The UI separates these estimates from fresh matches and hides expired results.
This addition does not change behavior selection, automatic stopping, manual
ownership, or the existing single-person loss policy. Named-person following in
crowds is not qualified by these observations or by deterministic tests.

Focused software checks (no body connection, synthetic face embeddings):
```sh
PYTHONPATH=Master:Slave/software:Emulator/tests python3 -B -m unittest \
  Emulator.tests.test_person_identity Emulator.tests.test_camera_perception \
  Emulator.tests.test_gateway_dashboard Emulator.tests.test_yolo_backend
```
Qualification still requires approved model files, actual face inference, enrolled
person recordings including crossings/occlusion/replacement, and measured latency.
Do not interpret synthetic matching/ownership tests as recognition accuracy.

The evaluated desktop checkpoint `person_yolov8m-seg.pt` supports **person only**,
not the general COCO class set or personal identity. Offline evaluation used
Ultralytics 8.4.36, PyTorch 2.11.0+cu130, OpenCV 4.13.0, Python 3.12.3, and an
i9-9900K with four CPU threads (GPU unused). On the packaged public bus image,
ten warm predictions measured median 210 ms, maximum 247 ms and 4.64 serial fps;
peak process RSS was about 1.02 GiB. Cold library import took 68.6 seconds with
observed filesystem waits; first prediction took 496 ms. These are desktop
measurements, not Q6A performance, accuracy qualification or response guarantees.
The recorded-image trial requires a preexisting isolated `YOLO_CONFIG_DIR` and
sets `YOLO_OFFLINE=true`, `YOLO_AUTOINSTALL=false`, and `OMP_NUM_THREADS=4`.

Do not activate this option on a live installation or direct its frames to a
new inference endpoint without operator approval. For the intended split, one
Q6A Core/Coordinator and gateway keep task ownership while an explicitly approved
desktop endpoint supplies inference. The existing remote provider contract is
retained; no second scheduler, takeover or desktop controller is introduced.
`AINEKIO_VISION_API_KEY` supplies a Bearer authorization header; it is required
for a remote service and optional for a loopback service. Remote endpoints must
use HTTPS with normal certificate and hostname verification. Private certificate
authorities can use Python's standard `SSL_CERT_FILE` trust configuration; there
is no TLS-disable option. HTTP is retained only on a loopback IP (or `localhost`,
pinned to 127.0.0.1). URL credentials, queries, fragments and control characters
are rejected. Proxies and redirects are not followed. Images go only to this
operator-configured endpoint; observations cannot supply another destination.
The gateway's one bounded camera worker handles transport and validation while
the remote server performs heavy perception. The existing correlated remote
snapshot path is unchanged; no second runtime or task authority is added.

[`RecognitionResult`](perception.py) contains a bounded summary, up to 32
candidate objects, and up to 8 uncertainties. Object labels may carry optional
scores and normalized top-left `x/y/width/height` boxes. Missing scores or boxes
stay absent. Scores are estimates, not calibrated probabilities; a label does
not verify physical identity, task completion, distance or walkability. A
detector can return the same result type through the existing camera consumer
without changing the bridge or MetaHuman. Backend errors, incomplete JSON and
oversized responses are failures, not empty successful observations. Current-body
failures reach the existing `environment.observation` route as
`metadata.recognitionFailure` with robot/epoch/frame/gateway correlation and an
explicit reason (including HTTP authentication failures and timeouts). They do
not fabricate objects, body completion, or an automatic stop policy.

The adapter emits `environment.telemetry` with `kind: "vision.recognition"`
and a compact `perception` record: version 1, robot ID, connection epoch,
gateway instance, frame counter, backend/model, receipt-based `observedAt` and
`expiresAt`, summary, objects and uncertainties. `timeBasis: "gateway_receipt"`
explicitly excludes unmeasured sensor/transport age. Results expire from frame
receipt, not inference completion. Recognition metadata has no image data and
is not replayed after bridge reconnection.

The existing `environment.visual.read` response also carries frame-bound recognition
under `visual.metadata.recognition`. When `CameraFramePlugin.latest_analysis`
has a retained result for the selected connected body, the adapter reads its cached
JPEG and recognition together, including after that result's live freshness expires.
This can be slightly older than the latest unprocessed video frame, and retains
its original receipt timestamp. No new capture or inference wait is introduced.
Without an available analysis, the read still returns the raw camera cache without
recognition metadata. Requested snapshots join their exact frame’s analysis on
the same camera worker before delivery when recognition is enabled. Preview
replacement preserves requested stills. Body receive, microphone input and
movement do not wait for inference; failed recognition is reported with the
photo. Disabled recognition returns the photo without an inference dependency.
Frame identity and original receipt time remain unchanged. The record carries
backend/model, objects, scores, boxes, identity estimates, uncertainties and source
identity/time; enrollment images and face embeddings are not transmitted. Live
telemetry retains its existing expiry, while metadata on an attached image describes
that dated image rather than claiming a new live recognition measurement.

Recognition telemetry also carries optional `processing` diagnostics outside
the unchanged perception-v1 payload. `CameraFramePlugin.metrics()` reports input,
completed processing attempts, fresh results, drops, stale frames and errors;
queue depth; latest queue/inference durations; age since host receipt of the last
fresh processed result; and processing/fresh-result rates since the first frame.
Failed attempts count as processed but not fresh. Fresh-result counts describe
the camera worker, not confirmed bridge admission; they include the current result.
These counters cover the worker, including all robot streams it subscribes to. Host-receipt age excludes
unknown camera exposure and transport delay, and changes continuously even when
no new frame arrives. No diagnostic count establishes a fresh observation.

The opt-in paired test `perception-gateway.spec.ts` in Core launches
`Emulator.tests.perception_harness`. It reuses the existing in-memory body and
gateway receipt owners, rejects all Python socket connects/binds/listens, and
accepts only explicit local weights and a recorded image. Commands cannot reach
a physical robot through this test path. It exercises real detector output and
Core behavior while instruction and conversation inference are deliberately
pending. The paired Core command `tests/run-visual-control.sh GATEWAY PYTHON
WEIGHTS BUS_JPEG OUTPUT` produces an HTML frame/steering report and correlated
JSON traces. It translates one person cropped from the packaged public photo,
runs actual recognition, includes target loss and expired input, and checks
confirmed cancellation versus a missing original receipt using the production
confirmation budget. Fresh target loss returns to the selected base motion;
expired required feedback requests cancellation. Task selection is scripted,
so this does not qualify unresolved language-model interpretation failures,
natural video accuracy or physical rest. No image is sent to an LLM. See Core's
`docs/technical/visual-control-demo.md` for exact setup and remaining gates.

MetaHuman's existing Environment Bridge coalesces recognition delivery to one
active and one newest pending result, independently of control receipts. Core
validates its contract and robot/session identity, rejects old frames, and stores
it in the existing observation's `state.perception` without replacing its still
image or renewing its control heartbeat. The existing **Environment Bridge
Input** exposes a fresh `perception` output; live observation reads remove
expired recognition while recorded evidence remains intact. Recognition arrivals
create no new objective or independent body job. An existing MetaHuman local
task can resume on recognition through its execution ledger and Work Coordinator.
MetaHuman retains task and movement decisions through the same body leases.

MetaHuman's sole active task executor accepts complete ordered programs from
Environment Mode and the autonomy selector. It advances saved gestures from
physical receipts without additional model calls, and can retain an ongoing gait
while fresh recognition steers it. Target identification uses free-text phase
criteria and finite asynchronous snapshot/model jobs. A confirmed identification
requests Finish on the original gait; its terminal receipt precedes subsequent
gestures, which run before the
whole task is complete. This replaces the temporary repeated-motion local-task
route and the per-movement Action Result model workflow. MetaHuman remains the
commander; processing services do not acquire another motion channel.

Stage 1 stopping policy (source/software only, 2026-10-07): normal Finish is a
speed-zero update, preserving concurrent speech. MetaHuman allows 5 seconds for
the original gait's terminal receipt, then uses owned cancellation. Failed or
expired required feedback requests cancellation promptly. Adapter cancellation
has a 2-second send/confirmation budget and requires the original command's
terminal receipt; a Stop ACK alone cannot terminate older action records.
MetaHuman also bounds its confirmation wait and retains `outcome_unknown` when
transport or receipt confirmation is unavailable. These bounds depend on the
existing Coordinator and transport; they are not a firmware feedback watchdog.

Cancellation and steering validate the immutable action/lease, gateway instance,
robot epoch and latest body dispatch inside the same send lock as manual control.
An unguarded manual update also invalidates autonomous cleanup authority. Speaker
cancellation is separately fenced. Capture cancellation never issues a body-wide
Stop. An uncertain action retains its historical `outcome_unknown` result. When
an authenticated replacement body session ends its execution, the same receipt
owner records `data.executionEnded: true`, the previous/current session identities
in `data.sessionReplacement`, and `data.priorOutcome`. MetaHuman settles that
command's ownership without claiming success. Disconnect alone does not establish
this transition; old motion is never replayed. Ended computer playback is similarly
settled when its owning gateway process has been replaced. The committed receipt
survives replay/restart, and a later correlated body result can add factual evidence.
A correlated terminal receipt establishes commanded execution outcome, not sensed
physical rest or measured servo position. Emergency Stop still sends the existing
P4 output-disable command and can interrupt speech.

Stage 2 instruction interpretation (software only) runs as finite Coordinator work
alongside the same MetaHuman execution. The approved pending-turn policy combines
all unanswered messages in order and attributes the response to the newest turn.
An interpretation-origin body command carries `metadata.interpretationBody`
(session, gateway instance, robot, epoch, last body sequence). The adapter checks
that fence under the existing wire-send lock; manual commands and body-session changes
invalidate late proposals. Every body command in an interpreted program keeps
this check. Admitted body dispatches persist `data.interpretationBody` in their
correlated receipt; Core advances its expected ownership from that receipt, never
from a newer live status snapshot. Steering updates keep the original action's
owner, and owned cancellation advances it to the Stop dispatch. Failed admission
cannot mint successor ownership. Stored receipt replay keeps the same evidence
across adapter recovery; a different gateway session or robot epoch invalidates
old commands. Emergency Stop remains independent of interpretation.
Owned cancellation records its Stop dispatch fence in `data.cancellationBody`,
including unknown results, so MetaHuman can distinguish its cleanup from a later
manual takeover. That ownership evidence never substitutes for the original
command's terminal receipt or proves physical rest. No firmware change is needed.

Before deployment, identify the actual MetaHuman/gateway/P4 versions and reconcile
old active executions. Supervised checks must cover normal Finish with speech,
required-feedback expiry, Stop plus original cancellation receipt, missing/late
receipts, manual takeover and reconnect. No firmware or service was changed on a
running robot during Stage 1; IMU and vision setup remain separate work.

Metric navigation, tracking, live IMU feedback and hardware qualification remain
separate work. Model comparisons remain deferred to the assembled prototype.

Desktop replay and WebSocket tests cover newest-frame delivery, stale/session
rejection, processing failures, shutdown, and command/stop receipts while
synchronous inference is blocked:

```sh
PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests \
  python3 -m unittest Emulator.tests.test_recognition_backend \
  Emulator.tests.test_camera_perception \
  Emulator.tests.test_gateway_service Emulator.tests.test_environment_adapter \
  Emulator.tests.test_action_receipts
```

These tests use synthetic observations and the host emulator. They do not
qualify object-recognition accuracy, Q6A throughput, Wi-Fi latency, or physical
movement.

## P4 assembly calibration

Body Control uses the connected body's advertised capabilities. The P4 joint
panel reads twelve saved/staged device records through `body_calibration_v2`;
it does not reuse the eight-servo angle contract. Select the joint, enable
calibration, then use a pulse target or ±5 µs adjustment. With `servo_feedback_v1`,
the same panel displays the selected joint's fourth-wire ADC/voltage, measured
pulse-equivalent position, model angle, current target and target-minus-measured
error. **Use measured position as Home** reads the sensor again and stages its
measured position locally; it never substitutes the commanded pulse. Capture
works without enabling calibration or releasing outputs. **Apply & save to
robot**, in calibration mode, applies the selected joint's fields, commits them
and displays the controller's readback. A pulse entered for **Move
joint** is not automatically a Home setting. Saving disables outputs without rebooting; **Home
selected joint** or an explicit move resumes that joint. **Read from body** is
available without enabling calibration. Home and pulse targets use µs; the live
shaft measurement uses the separately saved three-point feedback curve.

Home may be an end-of-travel pose; it need not be the travel midpoint. Choose
**Rearward assembly pose** (the default for carriers/cranks) to assign the
measured position to the common assembly reference: carrier -30.87°, crank
-117.68°. These come from the documented assembly mapping, with the crank
reference originally photo-estimated. Position the corresponding joints at
matching physical poses. **Custom model angle entered above** assigns the
measurement to that explicit angle; shoulders default to this option.
Capture replaces the old angle offset instead of deriving a new reference
angle from that old mapping. Direction and scale remain unchanged. Editing the
angle field selects Custom. The reference choice and joint drafts persist in
this browser. Capture changes only the selected joint's draft; other joints are
unaffected. A physically refitted horn still requires a known mechanical pose:
the wiper cannot identify horn indexing. Missing or
uncalibrated feedback is reported without changing Home. Extrapolated positions
remain visible and are explicitly labeled. No movement is sent by capture.

The pulse slider previews a calculated model angle from the controller's Home,
direction and µs/degree mapping, and sends one movement request after release.
Its view includes the owner's observed 300–2900 µs span and expands for Home,
the last commanded pulse or typed targets; this does not change saved calibration. Numeric
entry remains available across the reported PWM capacity.
The selected robot/joint, pulse target and joint-setting drafts are retained in
this browser across reconnects and reloads. **Resume calibration** requests mode
entry explicitly; restoration never replays a movement or saves settings.
Controller readback is shown separately. **Use controller values** discards the
selected joint's local draft without moving it.

Channel -1 disables a joint. Staging Home, direction or channel does not move
outputs. P4 motion uses the model angle at Home, pulse direction and µs per degree
from the same records. The P4 mapping form has no minimum or maximum pulse fields.
Manual and generated motion use the body's actual PWM timer capacity.
The owner sets Home, direction and angle scale from actual positioning behavior.
Named poses
come from the body's installed catalog; walk/crawl exposes direction, continuous
or finite cycles, speed/stride/rate and Finish when `walk_controls_v2` is present.
Calibration mode does not block semantic motion. A pulse outside the PWM timer's
capacity is rejected by the body rather than silently rescaled.
Unsupported or disconnected media controls show the body's reason;
V1 controls retain their existing wire protocol. `/api/calibration/body` requires
the dashboard session and CSRF token; Environment Bridge exposes no raw joint
calibration action. The former `/api/diagnostics/output` bench route is removed.

The P4 SD panel reads controller capacity, mount/busy state and dropped records.
**Retry mount** works with an unmounted card. **Clear logs and captures** requires
an explicit confirmation and controller readback; it does not reformat the card.
Media controls follow current capabilities reported in regular body status, so
a camera that finishes initializing after the handshake becomes available
without reconnecting. Speaker PCM is paced at 20 ms per frame with at most
100 ms of prebuffer/catch-up lead; cached utterances cannot be sent as an
unbounded burst into the controller's playback queue.

### V2 mounting references

Current P4 calibration readback separates saved per-joint mappings from recommended mounting offsets and reports `servo_profile_id` and `profile_confirmed`. Calculated targets and fourth-wire measurements are labeled separately. The observed 300–2900 µs span has arithmetic midpoint 1600 µs; the historical mounting reference is 1300 µs. The panel shows the recommended model offset without overwriting restored drafts or transmitting settings automatically. Review the mapping and Save before semantic motion; after outputs are disabled, establish a known reference with Calibration Home/Move. See the [assembly guide](../../Slave/software/models/v2-12servo/SERVO_ASSEMBLY.md).

### Physical gateway startup connection choice

See [Restarting Body Control and remote MetaHuman OS](../../docs/STARTUP.md)
for the restart routine on both computers and connection checks after a reboot.

Running `Master/start-physical-gateway.sh` in a terminal asks how you will open
Body Control: **This computer**, **LAN / Wi-Fi**, or **Cloudflare**. Press 1, 2 or
3 and Enter, or press Enter to keep the saved choice. After 10 seconds without
input, it uses the saved choice automatically. The first start defaults to
**This computer**. Noninteractive/service starts use the saved choice immediately.

The startup choice is stored on the gateway machine in
`build/gateway/physical/dashboard-connection.json` (or under the configured
`AINEKIO_GATEWAY_DATA_DIR`) and survives closing the program and rebooting.

- **This computer** binds the dashboard to loopback and prints its local address.
- **LAN / Wi-Fi** binds the dashboard to `0.0.0.0` and prints a LAN address.
  Existing dashboard login still applies. It uses the computer's current network;
  it does not select an SSID or change the robot's saved Wi-Fi settings.
- **Cloudflare** binds the dashboard to loopback and prints its configured public
  address. The existing tunnel must already be running and route that address
  to the dashboard port. This launcher does not create or manage another tunnel.
  Choosing Local or LAN does not disable an independently running tunnel.

Configuration:

```bash
# Supply your own already-configured dashboard hostname; saved after selection.
AINEKIO_DASHBOARD_PUBLIC_URL=https://body.example.com Master/start-physical-gateway.sh
# Override the saved choice without prompting (also accepts lan or cloudflare).
AINEKIO_DASHBOARD_CONNECTION=local Master/start-physical-gateway.sh
# Optional timeout in seconds; default is 10.
AINEKIO_DASHBOARD_CHOICE_TIMEOUT=5 Master/start-physical-gateway.sh
```

Explicit `AINEKIO_DASHBOARD_HOST` still overrides the selected listen address;
check the printed bind address when using it. Prerequisite checks, pairing
transfer and service installation do not prompt or rewrite the startup choice.
No automatic browser opening or remote gateway startup is performed.

The browser **Settings → Connections** controls remain available. Their saved
addresses belong to each browser and dashboard origin; they do not overwrite
this machine's startup default. Clicking **Save and open** persists those browser
settings, while merely changing the dropdown does not.

### Saved dashboard connections and desktop bridge settings

In Body Control **Settings → Connections**, save dashboard addresses for a local
or forwarded port, LAN/Wi-Fi, and Cloudflare. Each slot can point to any configured
machine; none assumes a Q6A. Opening a destination uses a new tab and its normal
login. Saved addresses belong to this browser and this dashboard origin. On
another device or dashboard origin, configure them there too. These are address
bookmarks, not gateway failover or task migration.

A local address means the device running the browser. A LAN dashboard must be
reachable or already forwarded. A Cloudflare dashboard address needs its own
configured route; the existing `/robot` HTTP relay and Environment Bridge TCP
route do not expose the dashboard. The selector does not change listeners,
install services, create tunnels or select Wi-Fi networks.

Save the stationary desktop's existing MetaHuman web address and use **Open
desktop bridge settings**. This opens `/monitor#body-connection` on that host,
where the MetaHuman owner chooses **This computer**, **LAN / Wi-Fi via SSH**, or
**Remote via Cloudflare**. The desktop's own authentication and bridge lifecycle
remain authoritative; Body Control never receives its credentials. This page
can be reached even while the robot bridge is disconnected. MetaHuman needs the
paired connection-selector source update; older versions open Agent Monitor
without the new selector. Its local option means the MetaHuman host, while its
SSH destination can be any configured machine running Body Control.


### Speech destination

MetaHuman's chat audio control selects **Off**, **Browser**, or **Body Control**.
Body Control's Audio panel separately chooses **Robot speaker** or **Body Control
computer**, persisted in `speech-output.json` beside the adapter receipt database.
This local choice can be changed while MetaHuman is disconnected. It no longer
changes MetaHuman's browser output preference.

Both destinations consume the same authenticated PCM speech messages and action
receipts. Computer output plays through the selected PulseAudio or PipeWire-Pulse
sink, or **System default**, using `paplay` (16 kHz mono signed 16-bit PCM); the executable
must be installed on the gateway host. Playback errors remain failed receipts.
Cancellation terminates the owned playback process; interrupted gateway recovery
retains an unknown historical outcome and never replays the audio. Computer
playback needs no connected robot or body clock. Robot playback keeps the existing
P4 speaker transport and completion receipts.

The Audio panel lists computer outputs and provides Bluetooth discovery,
pair/connect/disconnect controls through the gateway host's `bluetoothctl`.
Operations run as background jobs with visible outcomes. Pair the speaker, connect
it, then save its output in **Computer / Bluetooth speaker**. The sink name is
saved as `computerDevice`; this does not change the computer's global default.
A disconnected selected sink reports a playback failure rather than silently
switching speakers. Bluetooth belongs to the computer, not the robot's ESP32-C6.

For computer speech, host microphone intake is suppressed immediately and the
P4 receives a transient `external_speech` notification over the authenticated
controller connection. Playback never waits for delivery or acknowledgement.
The existing welcome/ping/pong traffic also carries the current state, so a lost
end notification is corrected by the next delivered heartbeat. The matching P4
also receives `external_speech_ms`: remaining PCM duration plus two existing
heartbeat intervals. Its existing microphone loop checks a 32-bit local-clock
expiry, so listening recovers even without a later message. Existing heartbeats
renew the expiry while the playback process is still running or draining; normal
completion clears it immediately. This expiry never stops playback or motion.
Disconnect clears the firmware's transient flag. No extra task, polling timer,
cooldown, motion pause, servo
release or saved microphone/wake setting change is introduced. While speech is
active, host input drops microphone PCM and wake/VAD events; camera and movement
continue. Overlapping playback owners keep suppression active until all finish.
Playback failure/cancellation releases host suppression independently of transport.

This applies equally to Bluetooth, wired and built-in computer speakers **when
speech is routed through Body Control**. MetaHuman's separate **Browser** output,
other browser tabs and other applications bypass this playback owner and are not
covered. Select **Body Control** in MetaHuman and **Body Control computer** here
for normal computer speakers with robot listening suppression. The firmware needs
the matching external-speech update; older firmware still receives host-side
suppression but continues its local wake processing.


### V2 body events and IMU status

The P4 reports timestamped IMU snapshots on its existing controller connection.
Body Control detects threshold crossings and publishes structured `body_event`
observations through the Environment Bridge. Sensor telemetry updates status;
it does not itself invoke an LLM. The separate MetaHuman **Body Event Trigger**
workflow interprets events and delegates its selected intention to Environment Mode.
No phrase or motion sequence is selected in firmware or gateway event detection.

Firmware `0.8.83-p4-motion-events` adds execution context to each IMU sample:
command, device connection/sequence, phase and the intended body vertical.
The body output owner publishes target context only after a successful PWM
write. A short snapshot history pairs the sensor timestamp with the preceding
execution state, including entry, retimed playback, reverse recovery and held
poses. Queued commands, requested playback rates and face selections are not
used to infer movement.

Rapid-movement crossings during commanded entry, motion or replanning update
the detector's episode state but do not request a reaction or consume its
cooldown. This includes locomotion, Stand/Neutral, clips, manual movements and
Freestyle programs. A crossing is not deferred until the movement finishes;
a new disturbance after the measurements clear remains reportable. Unexpected
tipping remains reportable during commanded movement. For a
calibrated body-frame observation, tipping is the angle between measured and
authored body vertical rather than absolute tilt from upright. The same saved
trigger/clear angles and hold duration apply; absolute tilt remains in the
event alongside `unexpected_tilt_degrees` and execution evidence. A completed
or stopped intentional pose retains its last intended orientation while held.
Older firmware, unverified sensor axes, and manual/Freestyle motion without
an authored chassis orientation retain the existing absolute-tilt calculation.
These notification decisions neither cancel nor change a robot command.

Firmware `0.8.85-p4-event-face` also reports the active expression's `face_token`
with IMU telemetry. MetaHuman's Face Expression node marks the initial body-event
branch expression with a `be_` token; ordinary expressions and subsequent
replacement faces retain ordinary tokens. While that reaction selection remains
active, Body Control updates the shake/tip episode state without emitting more
shake/tip events. Release, replacement or the expression's existing local expiry
ends this suppression. Temporary listening/speech overlays do not release the
underlying selection. No host timer duplicates the firmware's expression timer,
and reconnect reads the current selection from telemetry. Suppressed episodes
are not queued for later reaction. Wake notifications and user commands continue.
The shared configurable shake/tip cooldown still applies, including before
the reaction face arrives; an event still awaiting its face is not considered an
active displayed reaction.

All 23 named motions reuse the recorded body quaternion, compressed separately
from their unchanged joint tracks. Reference data lives in flash. The existing
IMU acquisition, balance/learning consumers and telemetry cadence are retained;
no second sensor task or extra LLM/workflow is introduced. Only unexpected
events enter the existing Environment Bridge reaction route.

In Body Control, **Perception → Body events** saves enable switches and thresholds
per selected robot in the existing `sensing-controls.json` settings store. Changes
apply immediately on this Body Control host and survive its restart. Defaults:
60° tilt for 300 ms, clearing below 45°; acceleration magnitude differing from
1 g by more than 0.75 g or angular-rate magnitude above 180°/s, clearing below
0.35 g and 90°/s. Continued readings above a threshold are one episode until it
clears. Shake and tip reporting share one per-robot cooldown, defaulting to
10 seconds. **Shake and tip cooldown (seconds)** sets the minimum time between
either kind of notification; 0 disables the cooldown. Crossings during the cooldown
are not queued or emitted later. A new crossing after clearing is required.
The interval uses Body Control's monotonic clock and survives settings edits and
robot reconnects; restarting Body Control starts a fresh interval history. Old
saved rapid-only cooldown settings retain their interval under `motion_cooldown_s`;
settings without a cooldown gain the 10-second default. Wake notifications do not
consume or wait for this interval. If both detectors cross in the same sample,
the existing tip-first order uses the interval for the tip notification.
These settings do not change actuator control or balance behavior.
**Good morning** submits an explicit wake request through the same event workflow.
Firmware reports boot/wake once at its source; reconnect is not a new wake. The
Environment adapter submits “Stand up, stretch, and finish standing” through the
existing Freestyle owner and requests a correlated snapshot. Motion generation
does not wait for the image; greeting delivery does not wait for movement
completion.

**Poses and emotes → Manual motion controls** defaults to Freestyle. Selecting
**Legacy library** affects only explicitly pressed manual pose/emote buttons.
MetaHuman `requestMotion`, older named pose/emote requests, and automatic startup
requests always use Freestyle. Inference failure is reported; there is no native
library fallback. Shared P4 gait, kinematics, calibration, servo output and target
feedback remain execution services, not competing behavior selectors. Native
library playback remains available for manual operation.

The adapter tracks the original Freestyle job through completion, cancellation
and reconnect. Submission is not completion; a lost dispatched receipt retains
an unknown physical outcome. Generated programs and observations remain in the
existing Freestyle recordings. Removed `gesture`/native `stand` shortcuts cannot
invoke a prerecorded library motion from a generated program.

Startup motion belongs to this host workflow. Inactivity belongs to the existing
P4 one-shot timer: after the configured interval (three minutes by default), the
body plays its built-in Lay Down and releases outputs after it finishes. No model
request is used. Stop and new commands retain their existing immediate replacement
semantics. Firmware 0.8.127/0.8.128 delegated inactivity through `idle_rest`;
the restored body-local behavior requires the updated firmware and gateway.

New wake observations are not retained for an absent
bridge; already-admitted delivery retains its existing acknowledgement lifecycle.
 Event capture requires the Body Control connection;
this transport does not replay sensor samples lost while disconnected.

IMU readings retain acquisition time, reception time, gyro rad/s, acceleration
m/s² (including gravity), quaternion, calibration and source freshness flags.
`body_nominal` identifies saved mounting/bias calibration; `sensor_unverified`
identifies its absence. Six-axis yaw has no absolute heading reference.
Balance corrections exist in the V2 body code; these changes do not add a
fallen-body get-up sequence. Firmware build/flash and physical qualification
are separate from host-side tests.

For longer supervised trials, the recorder's `--until-done` option ends capture
when its submitted command's completion receipt arrives. It does not send Stop
or change motion duration. The P4 finite Walk protocol currently accepts at most
ten cycles; longer experiments can use continuous Walk and the existing Finish
update. Retain complete raw recordings, distinguish any loss during motion from
later idle loss, and keep evaluation runs separate from training.

### Learned walking: fourth-wire trajectory corrections

Firmware `0.8.82-p4-learned-travel` advertises `gait_learning_v1` and accepts
`gait_learning_v2` candidate models with recorded pulse envelopes. Body Control's
**Learned walking corrections** panel records, trains, downloads and installs a
small model. Training runs in the gateway Python environment (NumPy required);
the P4 executes the model locally. Internet inference is not involved.

1. Leave learned corrections off for the baseline. Keep the selected heading
   feedback and Self-leveling settings consistent between trials.
2. Start recording, issue forward Walk through the normal controls, then finish
   recording. Allow complete strides after the existing two-cycle entry. The
   recording controls neither start nor stop motion.
3. Select the downloaded `trace.jsonl`, choose the learning fraction, and train.
   This downloads a candidate JSON with its training report; it does not install
   or activate it automatically.
4. Install the candidate, enable learned corrections and set the correction
   amount. Record the same commanded gait again. Compare tracking errors, gyro
   motion and observed forward progress, including whether feet drag.
5. A subsequent fit learns from the **applied correction plus remaining tracking
   error**. Save baseline/candidate recordings separately. Repeated independent
   trials establish benefit; a training fit alone does not.

The model is specific to forward Walk at the recorded stride and installed
calibration. It includes 60 float coefficients: constant plus two sine/cosine
harmonics for three body-coordinate offsets on each of four feet. P4 inference
uses the existing fixed-shaft linkage solver and calibrated output mapping. It
does not change nominal phase/cadence, Home, steering ownership or servo timing.
Model coefficients occupy 240 bytes; runtime history and measurements require
additional RAM. Hardware runtime timing is reported separately from this size.

Fourth-wire samples are interpolated to a common timestamp for each leg, and
matched to the nominal target history at that timestamp. Forward kinematics
tracks a fixed material point on Part 027. This is a geometric estimate, **not**
measured contact, ground clearance, torque, load, slip or travelled distance.
Training smooths repeated errors with two harmonics rather than feeding every
ADC fluctuation back into the servos.

If the selected command, geometry, calibration or feedback does not match,
only the learned contribution fades away; normal gait and heading control
continue. A correction that does not fit the linkage/output mapping is reduced,
independently for each leg, with accepted fractions and travel-boundary reductions
reported. Learned additions stay within the recorded nominal pulse envelope; a
steered nominal pose can extend that envelope for the current frame without
allowing the learned layer to extend it farther.

The owner confirmed 500–2800 µs mechanical travel for **carrier and crank only**.
Left 2800 / right 500 is the rearward endpoint. Shoulders are centered, their
physical limits are not established, and this range is not applied to them.
Generated motion targets (including Walk and startup rise) are fitted in
Cartesian space to feasible linkage poses inside these carrier/crank bounds
before mapping to PWM. Feasible targets pass through unchanged. This can alter
an infeasible nominal foot path; it does not slow the gait clock. Saved Home,
inversion and angle-to-pulse references remain unchanged. Literal manual joint
calibration/Home commands retain their existing behavior; they are not covered
by this generated-motion fit. These are not general collision-avoidance checks.
No model has physical qualification merely because it fits the linkage.

Authenticated maintenance API (gateway proxy preserves the selected robot):

- `GET /api/robot/gait-learning?robot_id=...`: model and latest walking observation.
- `POST` same URL, `{"op":"configure","enabled":true,"amount":0.5}`: save settings.
- `POST` same URL, `{"op":"install","model":{...}}`: save the downloaded model;
  preserve the enable setting. Installing while enabled changes the ongoing or next walk's
  correction and should be treated as a real motion change.
- `POST /api/gait-learning/train`, `{"batches":[...],"gain":0.5}`: host-only fit;
  never submits a motion command. Body Control sends only tracking records,
  trace headers and loss receipts. Maximum training upload is 8 MiB.

`gait_trace_v1` has an additional `tracking` event, with per-leg timestamps,
phase, nominal/measured reference point, applied correction, context signature,
stride, command sequence, nominal output-channel pulses (`nominal_pulses_us`)
and validity mask. Version 2 training requires these nominal pulses; record a
fresh baseline on 0.8.82 or newer. Older sample/output consumers ignore
this event. The trace header now includes the geometry identifier. The UI labels
telemetry as the **last walking observation**, rather than a live measurement
while idle. Calibration/geometry changes require a new matching recording/model.

Offline fitting/evaluation uses the same trainer as Body Control:

```bash
PYTHONPATH=Master python -m gateway.gait_learning /tmp/baseline/trace.jsonl \
  --gain 0.5 --output /tmp/walk-candidate.json
PYTHONPATH=Master python -m gateway.gait_learning /tmp/candidate/trace.jsonl --evaluate
```

Use separate paths for captures and model artifacts outside the repository.
The ILC update assumes a locally consistent response to task-space displacement;
a model may worsen walking and must be evaluated physically. The separate
`gait_response` predictor remains diagnostic and is not inverted into commands.

The sensor-policy implementation adds `gait_sensor_policy_v1` and accepts
`gait_learning_v3` models through the same install endpoint. This is an extension
under physical development, not a qualified replacement gait. It retains the
60 periodic coefficients and adds 96 feedback coefficients: for each leg/axis,
the eight inputs are shaft-derived reference-point error xyz divided by 10 mm,
roll/pitch target error divided by 0.1 rad, and body angular rate xyz in rad/s.
The saved level reference uses the same signs as the balance owner. Coefficients
occupy 624 bytes. P4 inference includes no optimizer, Python or network call.
Version 2 NVS models migrate with zero sensor coefficients, preserving their
enable setting and output behavior. Sensor-conditioned models include IMU
mounting/bias and the level reference in their context signature. On unusable
joint/IMU data, the last usable learned sensor response fades with the existing
learned-contribution blend; the underlying gait/heading/balance owners continue.

Tracking records now contain `policy` with schema `gait_policy_input_v1`, the
exact 32 decision-time features, decision phase, IMU source timestamp, context
signature, input usability, and the applied correction at that decision. These
are separate from the older per-leg tracking samples aligned to earlier sensor
timestamps. Host fitting must not replace decision-time inputs with future
measurements. The recorder saves the installed learning configuration alongside
the other run metadata, and Body Control can import/export version 3 candidates.

`gateway.gait_training` is the explicit host training owner. Its `start`,
`propose`, `advance` and `export` operations keep resumable JSON outside the
repository. Search scales, optimizer step size, number of perturbation directions
and objective weights are explicit arguments. Paired candidates vary both
periodic and sensor coefficients. Repeated candidate/incumbent runs in matching
comparison blocks provide measured rewards; a new untested search centre is
never exported as the best evaluated model. Trials use the existing semantic
motion and recording owners; this module adds no robot reset/return behavior.

The objective uses measured forward metres/second, calibrated tilt error and
shaft-derived error relative to the **applied** target, including learned
displacement. It does not reward staying close to the old nominal foot path.
`recorded_metrics` consumes the existing visual assessment and device trace;
unavailable camera distance remains unavailable, rather than becoming a zero
reward or a tracking-only surrogate. This is neither a force nor energy estimate.
Each comparison reports paired differences and uncertainty; the current best
evaluated model is not called globally optimal. Normal operation executes only
the installed model; training runs solely when these host operations are invoked.

```bash
PYTHONPATH=Master python -m gateway.gait_learning /tmp/baseline/trace.jsonl \
  --policy-seed --output /tmp/policy-seed.json
PYTHONPATH=Master python -m gateway.gait_training --help
```

Version 4 (`gait_learning_v4`) additionally learns the underlying Walk profile:
duty fraction, sweep, four phase offsets, four foot lifts, eight landing offsets
and fifteen body-position Fourier coefficients. Its 33 profile parameters are
deltas from the current gait; zero reproduces the baseline exactly. It adds 48
response weights for operator forward/turn/lateral/stride inputs. All 237 floats
occupy 948 bytes, excluding runtime history and recording. The model still runs
locally on the P4; training runs on the host.

Training can send `persist: false` with model `install` or `configure` to apply
a candidate in RAM without writing flash. The last permanently saved model
returns after reboot. Omitted `persist` retains the existing persistent behavior;
`persist: true` explicitly saves the current installed model and configuration.
Status reports `model_saved`, and Body Control identifies a temporary model.

### Host learning during ordinary locomotion


**Recordings → Learning history** opens the read-only progress view. It graphs
scored observations by gait and matching command settings, keeps archived
measurement contexts separate, and shows candidate decisions and changes from
the reference model. Available metrics include camera-estimated progress,
joint tracking error, body tilt, angular motion and acceleration deviation.
The observation table and JSON download expose the underlying history.
New observations/decisions include timestamps; older data use observation order
and explicitly indicate missing timestamps. Opening this view never submits a
motion, installs a policy or triggers training. It refreshes when the existing
status stream reports changed observations or learning state.


`gateway.gait_learning_service` now owns the optional persistent recorder and
training lifecycle. Body Control exposes **Log gait data**, **Learn while
walking**, **Analyze now**, progress by maneuver, exploration radii, and saved
policy restore. The settings belong to this host; leave learning off on a
laptop/smaller host. Closing a browser does not stop host recording. The former
browser-owned trace loop has been removed so the two recorders do not compete.

Priority coverage is forward Walk, backward Walk, both turning directions, and
bounding Run. Crab and Crawl remain outside this initial optimizer. Training
uses the operator's normal commands; the service never submits motion, Stop,
Home, resets, or raw joint targets. Existing P4 heading feedback, self-leveling,
fast-stroke timing and mechanical travel handling retain their owners.

The host drains the existing P4 trace and writes camera JPEGs, IMU/joint/output
records, motion commands, calibration/model metadata and measured motion windows
under `$XDG_STATE_HOME/ainekio/gait-learning` (default
`~/.local/state/ainekio/gait-learning`). These private data are not repository
assets. Recording includes acceleration and planned support information;
planned support is not a measured contact switch. Learning includes logging.
Neural walking trials use this same recorder: `commands.jsonl` retains the
accepted host reference, SI request and requested foot samples; `neural.jsonl`
attributes those requests to the model, normalized action, inference input
timestamps, fixed Walk yaw reference and any producer-failure Finish request.
`metadata.jsonl` retains available motion-speed, balance and selected-source
settings from the existing gateway state, with unknown values left explicit.
`events.jsonl` retains paired IMU/joint packets with the actually
consumed sample, command rejection/termination and body-stall/fall events.
These are different stages of evidence, not interchangeable success receipts.
The native residual optimizer does not consume host-neural tracking windows;
recording a neural trial is not an automatic model-weight update.
Logging alone does not start an optimizer. Analyze now can calculate a proposal
with learning off; it does not install that proposal.

Trace downloads reuse a per-robot HTTP connection; failed requests are reported
without replaying model-install operations. Brief missing joint observations
are counted inside the current window, not treated as a change of installed
policy. Windows report both unusable tracking observations and observations
where the learned correction was active. Missing readings never become zero
tracking error. Model, command, calibration and profile changes still identify
different observations.
Camera history comes from timestamped measurement events rather than polling
the dashboard's freshness-filtered current value. A valid archived frame does
not become a failed measurement merely because it later expires for live use.
Real camera-fit failures remain unavailable. HTTP reconnects also retain partial
windows when the device cursor confirms no lost samples.

The initial search has nine coordinated parameters: duty fraction, sweep,
front/rear lift, front/rear landing position, body height, tilt-feedback gain and
fourth-wire reference-point feedback gain. These are deltas around the reference
policy, not raw PWM angles. Radii are editable search scales, not new motor
limits. Space-filling initialization precedes BoTorch Gaussian-process Bayesian
optimization. Demonstrated improvements recenter the search and retain earlier
observations in the new coordinates. This is hardware policy optimization, not
an assertion that an end-to-end neural locomotion policy has been trained.

Evaluation rewards signed translation and commanded rotation, and measures
trajectory yaw error, lateral drift, tilt, angular motion, acceleration-norm
deviation and measured reference-point following. It uses the P4's recorded
planned twist only as a target, never as measured distance. Candidate/reference
comparisons match direction, stride and requested motion rate; resulting cadence
is an outcome, not a condition that excludes faster candidates. Walk needs repeated forward,
backward, left-turn and right-turn evidence. A single forward win cannot promote
a Walk policy. Uncertainty estimates from repeated windows are descriptive:
adjacent walking windows are not guaranteed to be statistically independent.
These observations measure neither motor current nor torque/energy consumption.
Useful motion is divided by the measured quality costs: quiet stillness cannot
beat useful progress solely by removing vibration. Turning beyond the planned
rotation earns no extra reward.

Before installation, the existing native linkage preview evaluates the proposed
profile against observed commands and current joint calibration. If it cannot
solve the proposed change, the host fits only the learned delta toward the
incumbent and reports its scale. This samples geometry with zero sensor features;
it does not establish collision-free physical operation or loaded stability.
Existing P4 residual fitting handles live additions. An unsolved incumbent is
reported for investigation, without changing the base gait or sending movement.

Candidate installation uses the existing RAM-only maintenance operation. Only
demonstrated incumbents are saved to P4 flash. A separate Run policy is stored
under the `p4_learning/run` NVS key; the existing Walk model stays under `model`.
`POST /api/gait-learning` accepts `gait: "walk" | "run"` with `read`, `install`
and `configure`. Omitting `gait` retains the Walk API. Run preserves front-pair/
rear-pair bounding. Trace policy records include actual model identity, amount,
active state, gait, cadence, profile identity and planned twist. Geometry
profiles take effect at the next locomotion start; installing a candidate does
not retarget an airborne foot. Walk-to-Run interpolation continues under the
existing motion owner; an unmatched learned profile remains reported as pending.

After the configurable number of post-bootstrap Bayesian comparisons without
the requested minimum demonstrated improvement, that bank retains its incumbent.
Learning switches off automatically only when both priority banks have reached
that condition. This is a plateau in the covered search/conditions, not a global
optimum or a cutoff on robot movement. Turning learning off restores the saved
incumbents; learned execution and live feedback remain available.

Install optional optimizer dependencies separately from the gateway:

```bash
python3 -m venv --system-site-packages build/gait-training-env
build/gait-training-env/bin/python -m pip --isolated install torch==2.8.0 \
  --index-url https://download.pytorch.org/whl/cpu
build/gait-training-env/bin/python -m pip --isolated install \
  -r Emulator/requirements-gait-training.txt
cmake -S Slave/firmware/esp32p4-wifi6/tests -B build/gait-native \
  -DPython3_EXECUTABLE="$PWD/build/gait-training-env/bin/python"
cmake --build build/gait-native --target preview_gait_learning -j4
```

The host launches that interpreter as a worker; alternatively set
`AINEKIO_GAIT_TRAINING_PYTHON`. There is no optimizer/inference elapsed-time
cutoff and no GPU requirement. Disabling learning avoids background optimization.
`AINEKIO_GAIT_PREVIEW` can select the matching native preview executable.
Rebuild it with firmware geometry changes.

**Qualification status:** this implementation consumes the existing calibrated
camera motion owner. It does not implement or claim working OpenVINS odometry.
Camera/IMU timing remains explicitly marked as approximate receipt-clock
alignment. Unavailable/ambiguous camera motion, a changed reference, lost trace
records or unavailable calibrated joint/IMU observations do not become a
tracking-only progress reward. Recording and ordinary motion remain available,
but those windows cannot demonstrate improvement. Hardware-qualified metric
motion, deployment and physical evaluation of all four priorities remain
necessary before calling the automatic learning system operational on the robot.
This separates candidate exploration from permanent deployment without adding
an elapsed-time wait or stopping the commanded gait.

The profile is selected when new locomotion begins. Updating a model mid-command
reports `profile_pending_next_walk` rather than moving already planted foot
anchors. Operator steering, heading correction and Walk/Run interpolation retain
their existing owners. Walk and Run select their separate profile banks;
a mid-command transition retains gait interpolation and reports an unmatched
learned profile until the next start. Sensor-dependent additions retain their approved fade behavior
on unavailable feedback, while the selected underlying gait keeps running.
Version 4 supports forward, backward, turning and interpolated Walk commands;
version 2/3 models retain their earlier eligibility. Old models load with zero
new parameters. No IMU signs, joint calibration, nominal servo-speed setting or
approved mechanical travel are changed by the profile implementation.

The recorder includes the four operator inputs, gait context and selected
profile hash. Evaluation checks the executed profile against the candidate.
`--policy-seed` now creates a version 4 zero-addition seed from new recordings;
search requires explicit command and 33 profile exploration scales. These scales
define the experiment, not motor travel restrictions. Mathematical profile
validity is not evidence of linkage feasibility or physical stability.

The existing offline `preview_gait_learning` executable accepts optional
`v4 direction stride` arguments after amount and heading drift, followed
optionally by a JSON command selecting Run or curved steering. Input is twelve
calibration rows, 237 model floats, 32 sensor features and optional pulse-envelope
pairs. It reports calibrated travel and linkage fitting under that specified
sensor condition; it cannot predict actual loading, slip or sensor response.

Usable metric visual progress and repeated physical evaluation during ordinary
operation remain necessary before this meets the full
learned-walking objective. Software tests and a firmware build are not evidence
that the new profile has improved walking.

Requested measurement photos use `gateway.gait_trials.capture_snapshot(client,
robot_id, output_directory)`. It issues the existing Snap command and retrieves
that request's JPEG by connection epoch and sequence, saving bracketing status
alongside it. It does not send a movement command or change a gait. HTTP clients
can retrieve the same image at `/api/camera/frame?robot_id=...&epoch=...&request_seq=...`.
The latest requested still is retained separately from preview frames. Response
headers include `X-Ainekio-Camera-Epoch`, `X-Ainekio-Camera-Origin` and
`X-Ainekio-Camera-Origin-Id`; these identify the capture but are not exposure
timestamps. Ordinary preview retrieval remains available through the same route.

### Optional host depth and camera odometry

Camera → **Depth and camera movement** selects either the existing measured
ground-plane owner or experimental **MoGe-2 + landmark tracking**. The latter runs the
installed MoGe-2 network in an isolated host process and uses OpenCV SIFT matches,
PnP RANSAC and pose refinement against retained 3-D landmarks. It supplies the existing `locomotion_measurement` contract,
including a depth preview, camera intrinsics, relative position/heading and
landmark counts and pixel reprojection error. No P4 firmware change or robot movement command is involved.
The source selection persists in private `sensing-controls.json`.
The saved mode key `moge-open3d` remains compatible with existing settings;
the measurement source is now `moge2-landmark-odometry`. The initial dense
RGB-D comparison treated inconsistent per-image learned depth as movement in
physical recordings. Matched landmarks now retain world positions; newly seen
landmarks use model depth aligned to the retained map's scale. This avoids that
direct depth-difference error without claiming a calibrated absolute scale.

This is estimated metric depth and local odometry, **not a calibrated distance
sensor, loop-closing SLAM or visual-inertial fusion**. `scaleSource` is
`learned-metric-estimate`, metric accuracy is explicitly unverified, and metric
uncertainty is unknown. Inlier counts and residual error are optimizer diagnostics,
not an accuracy certificate. The first image establishes estimated intrinsics;
those optics remain fixed for that reference instead of changing focal length
on every image. Unknown/failed focal estimation is reported rather than replaced
with a guessed field of view. Changing resolution, body epoch, source settings
or explicitly restarting depth tracking establishes a new reference.
An ordinary connection-epoch change preserves estimated intrinsics when the
image size and source configuration are unchanged; it resets only the local map.
The worker retains optics per image mode. Returning from a high-resolution
still to preview reuses the preview's estimate rather than recalibrating it
from a different scene. Restarting the worker still creates a fresh estimate.

If landmark matching cannot fit a camera pose, tracking automatically establishes a new local
reference using the current image's usable features, keeping the existing intrinsics and
calibration identity. The failed interval is unavailable, with no position;
the next successful pair resumes local tracking. No travel is inferred across
the break. Training windows spanning that break are recorded as unscored, while
valid windows on either side retain their common measurement context.

Without an entered measured camera-to-body transform, reported motion belongs
to the camera origin with forward/upright mounting assumed. Camera rotation,
mounting tilt and a body-centre lever arm therefore matter. Supplying the actual
4×4 transform accounts for the lever arm; it does not calibrate the learned depth
scale. This implementation does not claim it can infer body height, foot contact
or metric scale accuracy from these estimates alone.

The gait recorder consumes the selected source through its existing camera
measurement callback. Reward records retain distance source, scale provenance,
coordinate origin and calibration context. A changed camera context starts a new
comparison bank using the actual current gait; previous observations are
archived, not compared across measurement systems. Joint feedback, IMU scoring,
live steering and self-leveling retain their existing owners. Depth processing
has no motion authority or inference time cutoff. It uses the existing
one-pending-frame camera executor; original receipt timestamps and normal
freshness reporting are retained. The depth image is shown in Body Control, not
duplicated into every training event or text prompt. Processing is on demand:
distance/metric navigation executions register through the existing camera-read
bridge using `operation: "depthDemand"`, `consumerId` and `enabled`. The gait
recorder registers with that same camera owner only while logging or learning
an active gait reported by the gateway's existing command lifecycle. Enabling
logging or learning alone does not request depth. Command completion, rejection,
cancellation or disconnection releases the recorder's demand on its existing
trace-drain cycle; no additional polling task is created. It does not wait for a
first measurement or pending inference. Body trace collection and recording
shutdown remain independent of depth readiness; unavailable depth is retained
as unavailable evidence. Consumers share the model. Removing a recorder leaves
navigation's reference intact; removing the last consumer invalidates its samples
immediately and unloads the model after in-flight inference on the same executor.
Bridge disconnect releases its
connection's registrations; reconnect restores only still-active executions.
Completion, failure and cancellation release execution demand. Ordinary streaming,
photos and conversation do not load depth. The dashboard's **Measure depth now**
button acquires one sample and releases its demand; selecting a source only saves
configuration. First use includes model loading; reactivation starts a new local
odometry reference. Recognition and robot admission remain independent of depth
inference. The standalone trial recorder observes available status; it does not
implicitly enable depth merely because RGB frames are being recorded.

Focused recorder/depth lifecycle checks (simulated commands, no robot movement):
```sh
PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests python3 -B -m unittest \
  test_gait_learning_service test_depth_motion
```

The recorder binds each trace cursor to the device boot/session and reacquires
the stream after a session change. Live status-clock receipts align queued
sensor history with camera receipts; network latency remains approximate and
camera exposure is not synchronized. An unavailable joint observation is
excluded, counted and reported without restarting the entire cycle window.
Command/calibration changes and lost trace records still separate observations.
Tracking-error statistics describe the usable samples, not the missing ones.

Host runtime configuration (environment variables read by the gateway/worker):

- `AINEKIO_DEPTH_PYTHON`: interpreter containing Torch, NumPy, OpenCV,
  and safetensors; defaults to the gateway interpreter.
- `AINEKIO_DEPTH_COMFY_ROOT`: existing ComfyUI checkout containing
  `comfy.ldm.moge`; defaults to `~/ComfyUI`.
- `AINEKIO_DEPTH_MODEL`: existing MoGe-2 converted safetensors file; defaults to
  `models/geometry_estimation/moge_2_vitl_normal_fp16.safetensors` under that checkout.
- `AINEKIO_DEPTH_CUDA_VISIBLE_DEVICES`: optional depth-worker GPU allocation.
  Otherwise the worker preserves the launcher's original CUDA visibility,
  independently of the recognition backend's later CPU-device selection.

No automatic package installation, model download, alternate model fallback or
camera FPS change occurs. Errors appear in camera measurement status. These are
optional dependencies; ground-plane operation does not import Torch.
The October 20 workstation already contained OpenCV and the MoGe-2 weights.
Other hosts must provide that runtime or retain the ground-plane source.

Research comparison:

| System | Relevant capability | Fit and remaining work |
| --- | --- | --- |
| [MoGe-2](https://github.com/microsoft/MoGe) + [Open3D](https://www.open3d.org/docs/latest/tutorial/t_reconstruction_system/dense_slam.html) | Estimated metric geometry/intrinsics plus RGB-D tracking | Both already installed here; selected for an optional prototype. Single-frame depth inconsistency and visual drift require physical evaluation. Only odometry is integrated, not Open3D's dense mapping API. |
| [Depth Anything 3](https://github.com/ByteDance-Seed/Depth-Anything-3) | Multi-view depth and camera poses; nested model adds metric scale | Strong alternative for jointly estimated poses/depth. The metric nested 1.1 checkpoint is about 6.76 GB; not downloaded or benchmarked here. Standard relative variants must not be labelled metric. |
| [UniDepth V2](https://github.com/lpiccinelli-eth/UniDepth) | Metric depth, intrinsics and confidence | Alternative depth producer, including smaller variants; still needs a motion estimator. Confidence is not a calibrated centimetre error bound. |
| [Depth Pro](https://github.com/apple-aiml-research/ml-depth-pro) | Metric depth and focal-length estimation | Alternative depth producer; no built-in trajectory estimator. Not benchmarked here. |
| [ORB-SLAM3](https://github.com/UZ-SLAMLab/ORB_SLAM3) / [OpenVINS](https://docs.openvins.com/gs-calibration.html) | Established visual/visual-inertial motion estimation | Neither found installed/running here. Camera/IMU calibration and timestamp alignment must be addressed for VIO; monocular image-only SLAM does not by itself establish absolute scale. |

Qualification: installed APIs and offline worker operation are confirmed. The
initial saved-image benchmark used four sparse VGA images, not a surveyed path.
MoGe took about 77 ms/image after warm-up and about 1 GB peak Torch allocation.
The current worker fixes intrinsics per reference and tracks sparse landmarks;
these timings are not an end-to-end walking FPS guarantee.
Synthetic known-motion tests check transform direction, metric units and
lever-arm handling. Real travel accuracy, drift during body bobbing, and improved
physical gait selection remain unverified. The live camera was configured for
1 FPS during the audit; motion tracking needs substantially more overlapping
views than the historical multi-second snapshots. Selection of this experimental
source is explicit; it is not silently substituted for measured calibration.


## P4 inactivity rest

In **Mode and power**, supported P4 firmware exposes **Lay down after inactivity
(minutes)**. Save the desired interval on the robot; the initial default is
three minutes and `0` disables it. It survives power cycles and works without
Body Control remaining connected. Active motion and speech defer rest. The
automatic lay-down clip releases its servo outputs after successful completion
with P4 firmware `0.8.117-p4-rest-release` or later. New movement commands
re-enable outputs; explicitly requested lay-down motions retain their powered
hold. Output release removes PWM drive, not the physical servo supply voltage.
Calibration/manual joint moves do not start an automatic rest motion.
The authenticated maintenance proxy is `/api/robot/idle-rest?robot_id=…`;
GET returns `{seconds, saved}`, POST accepts
`{"op":"configure","seconds":180}`. Older firmware does not advertise the
feature, so its dashboard keeps these controls hidden.

### Environment Bridge availability

The existing `/environment` WebSocket supports an authenticated read-only watcher.
Send `{"type":"bridge.watch","version":1,"token":"<adapter token>"}`.
The adapter returns `bridge.availability` version 1 with `sessionId`,
`gatewayInstance`, `robotId` (the selected robot, or null) and `connected`.
It sends updates on robot connection changes. A watcher neither claims the active
bridge nor replays receipts, queues messages, or enables unsolicited delivery.
The existing authenticated `bridge.connect` handshake opens the control connection
separately. MetaHuman's single Environment Bridge uses availability to locate the
selected robot across configured hosts; Body Control retains its existing robot
selection and action ownership.
