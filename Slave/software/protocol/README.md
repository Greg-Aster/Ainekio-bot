# Ainekio Protocol v1

This directory owns the machine-checkable Ainekio wire contract. It is shared by
the gateway, emulator, host tests, and firmware tests.

`schemas/control-v1.schema.json` is the language-neutral JSON control contract.
It follows section 3 of `docs/Ainekio - System Specification v1.0.docx` and
allows additional fields on known messages for forward compatibility. Semantic
rules that standard JSON Schema cannot express are named with
`x-ainekio-rules` and remain mandatory in every implementation.

`control_v1.py` is the host Python validator for that contract. Protocol errors
raise `ProtocolValidationError`; they never partially execute a command.

`schemas/binary-v1.json` describes the five-byte media header, frame types,
direction, counter behavior, and payload limits without depending on a
programming language. `binary_helpers/frame_v1.py` is the host Python
encode/decode implementation. Firmware will use equivalent bounded C code, not
the Python module or a JSON Schema runtime.

Fixtures are stored as JSON so every implementation can consume the same source
data. Authentication values in fixtures use the literal `REDACTED-TOKEN`.
Contract tests verify that all fixture message types remain represented by both
the language-neutral schema and the Python validator.

## Body command subsets

`body_commands_v1` extends `body_capabilities_v1`: hello must include a bounded,
unique `capabilities.commands` array of registered semantic names. It does not
change movement envelopes, calibration formats or protocol version. For example,
the current V2 declares `walk`, `stop`, eight `turn_left_*`/`turn_right_*` names
(15/45/90/180), and `sit`, `rest`, `wave`, `dance`, `swim`, `point`, `nod`,
`pushup`, `bow`, `cute`, `freaky`, `worm`, `shake`, `shrug`, `dead`, `crab`,
`celebrate`, `stretch`, `surprised`, `sad`, `curious` with `motion=false`:
the geometric assets are installed, but powered
motion is unavailable. The gateway advertises
commands to MetaHuman only when the body's motion capability is ready; emergency
stop remains independently available to the operator.

The gateway-owned semantic catalog supplies names and descriptions. A negotiated
body selects its subset; it cannot grant itself unknown catalog entries. Legacy
V1 without the feature retains its existing catalog, excluding the new 15° turns.
A different model without
an explicit command list gets no inferred V1 motion capability. Unsupported or
unready movement is rejected before gateway dispatch, and firmware admission
independently applies model support after session, expiry and sequence checks.
No raw twelve-joint motion/calibration payload is introduced by this feature.

## P4 twelve-joint Freestyle

P4 firmware 0.8.60 advertises `motion_plan_v2`. The existing `motion_plan`
envelope uses `map:2` and frames of `[duration_ms, [twelve targets]]`. Targets
are signed model-angle centidegrees, in `joints_v2.py` order: rear-left,
rear-right, front-left, front-right; each leg has shoulder, carrier, crank.
They are not pulse widths or angles relative to the saved Home pose. Saved
joint mounting references, inversion and scaling convert them to pulses.

Map 2 supports 1–32 frames, positive uint32 millisecond frame durations, and
signed int32 targets. The P4 control decoder accepts up to 8192 bytes. Map 1
and its existing eight-servo representation and timing limits remain unchanged.
The gateway selects the map from the negotiated robot model and feature.

P4 interpolates linearly from its last commanded pose using each frame's
duration, through the existing staggered PCA9685 output owner. It adds no Home,
Stand, easing or named-motion speed multiplier before the plan. Endpoints are
written at the existing 50 Hz output cadence before advancing, so sub-tick
durations cannot imply faster physical output. These are commanded targets;
there is no shaft-position feedback. An initially unknown commanded pose uses
the first target as the initial output.

`end:"hold"` holds the final target; `end:"stand"` or `end:"neutral"`
explicitly requests that final named pose. Completion follows its actual
execution. Stop, replacement and disconnect retain existing command semantics.
Freestyle clears active balance corrections without changing the saved
self-leveling setting: arbitrary joint plans do not define foot contact or a
body pose for the balance solver. Explicit `end:"stand"` resumes normal Stand
feedback.

## Saved joint speed limit

V2 `joint_speed_limit_v1` extends the existing motion-speed command with
`joint_speed_limit_deg_s`, a saved commanded-speed setting used by named motions,
entry transitions and balance corrections. P4 0.8.56 semantic gaits use fast
coordinated angular-distance timing at the nominal 545.45 deg/s reference instead
of this setting. Speed selects stroke distance, and the gait clock follows joint
travel. This applies to Walk, Run, Crawl, Crab, directions and transitions. Run
retains its front/rear bound. These are commanded positions, not motor feedback.
Manual calibration pulses and startup Home remain direct pulse operations.

```json
{"t":"motion_speed","op":"save","joint_speed_limit_deg_s":900,"seq":74}
{"t":"motion_speed_status","seq":74,"rate":2,"saved":true,"joint_speed_limit_deg_s":900,"joint_speed_limit_saved":true}
```

Save accepts exactly one setting, either `rate` or `joint_speed_limit_deg_s`.
Get returns both. The limit is saved in its own four-byte NVS value, preserving
calibration and the named-motion multiplier. Saving follows the existing output
disarm behavior; start another motion to resume. Status includes the configured
limit and `speed_limited`, indicating slowed coordinated motion timing.
`gait_cadence` reports automatic Run mode, commanded and requested cycles/second,
and commanded and requested stride percentages. These are model command values,
not measured shaft tracking. Gate limit writes on the advertised feature; older firmware
continues to support rate-only commands and readback.

## Saved self-leveling selection

P4 `balance_control_v1` exposes an independent saved feedback switch. It defaults
On to preserve existing behavior. Changing it never issues a motion, Stop,
calibration command or output detach. Off removes the balance correction using
the existing fade toward the nominal pose while the selected motion continues.
On resumes feedback in an existing Stand hold or supported moving gait; it does
not start Stand or change a gesture into a balancing pose.

```json
{"t":"balance","op":"get","seq":75}
{"t":"balance","op":"save","enabled":false,"seq":76}
{"t":"balance_status","seq":76,"enabled":false,"saved":true,"active":false}
```

Get/Save settle on matching `balance_status` after ACK. `enabled` is the selection;
`active` reports whether feedback is currently running. `saved:false` identifies
the default before a valid value is stored. A failed NVS commit leaves the prior
selection intact. The setting record is separate from joint and IMU calibration.
Regular status includes `balance.enabled` as well as `balance.active`. Body Control
shows On/Off, explicit Save on robot and Read from robot, plus current activity.

`balance_tuning_v1` adds `strength`, `damping`, `roll_deg`, `pitch_deg`, and
`tuning_saved` to readback. Strength/damping are nonnegative multipliers with no
application-imposed maximum; defaults are 1× each. Zero strength removes the
attitude-error response, zero damping removes angular-rate damping. Turning
leveling Off remains the way to fade all correction back to nominal.
Roll/pitch targets are offsets from the nominal body attitude, in degrees:
positive roll raises the left side; positive pitch raises the nose (the firmware
converts the latter to negative Euler pitch in its x-forward/y-left/z-up frame).
Both default to zero. This changes the feedback reference, not IMU calibration.

`balance_feedback_v1` adds physical-leg diagnostics under status `balance`:
`legs_valid`, `extension_mm` (front-left, front-right, rear-left, rear-right),
and `joint_delta_deg` in model joint order. Positive extension is a downward
shift of the modeled contact relative to the chassis. Values compare the
successfully written pose against the nominal motion; they are not measured
servo positions or evidence of contact. The dashboard derives live roll/pitch
from fresh IMU quaternions even when self-leveling is Off. Its level-reference
button copies these angles into the existing target fields for explicit Save;
the displayed target error then reads zero at that orientation.

The same feature adds `{"t":"balance","op":"calibrate_gyro","seq":78}`.
ACK plus matching `balance_status` confirms the sampling request, not completion.
The IMU acquisition owner collects 256 new raw samples, saves their mean as gyro
bias in the existing IMU calibration blob, and applies it between samples without
resetting attitude or changing the mounting rotation. The operator keeps the
robot still; there is no automatic movement, Stop, leveling switch or reboot.
Status `balance.gyro_calibration` reports `phase` (0 idle, 1 collecting, 2 saved
and applied, 3 storage error), `samples`, `target`, `error`, `bias_rad_s` and
`deviation_rad_s` in sensor axes. Deviation is sample standard deviation, not an
automatic motion rejection threshold. A failed save retains the active bias.
This does not calibrate accelerometer scale/bias or establish mounting-axis signs.

```json
{"t":"balance","op":"save","seq":77,"enabled":false,"strength":1.5,"damping":1,"roll_deg":0,"pitch_deg":2}
{"t":"balance_status","seq":77,"enabled":false,"saved":true,"active":false,"strength":1.5,"damping":1,"roll_deg":0,"pitch_deg":2,"tuning_saved":true}
```

Send all four tuning values together; an enabled-only save preserves tuning.
A single versioned NVS record commits the selection and tuning together. Upgrade
loads the old On/Off setting with original gains until tuning is saved. Body
Control reads confirmed settings, preserves unsaved edits during polling, and
provides Use default response without changing On/Off or saving automatically.
The firmware applies new tuning on subsequent output frames, preserving the
accepted standing offset and the requested gait. Existing linkage and joint-speed
criteria still apply; changing gain does not increase motor torque or joint travel.

## Saved named-motion speed

V2 `motion_speed_v1` retains its existing wire format and default 2× setting.
For Sit and finite named gestures, the multiplier scales intentional holds and
entry easing. Moving portions always traverse the coordinated path at the saved
joint speed, independent of this multiplier. Stand uses its own full-speed path.
An optional `playback_rate` previews a different hold/entry rate for that command.
Omission uses the robot's current saved setting. Both rate and joint speed are
captured when a gesture starts; changing them does not retime a running gesture.

```json
{"t":"intent","name":"emote","asset":"wave","playback_rate":1.35,"seq":71}
{"t":"motion_speed","op":"get","seq":72}
{"t":"motion_speed","op":"save","rate":1.35,"seq":73}
{"t":"motion_speed_status","seq":73,"rate":1.35,"saved":true}
```

Get/Save settle on a matching `motion_speed_status` after ACK. Saving disables
outputs through the existing owner before writing a separate four-byte floating-point NVS value;
it never alters the joint-mapping record. A missing or invalid value falls back
to 2× with `saved:false`. The command and saved setting use single precision.
Body Control uses confirmed robot readback and explicit Save on robot.

The compiler supplies a joint-distance clock alongside the original cubic path.
Each moving interval is timed by its fastest joint; stationary intervals retain
their authored duration divided by the requested rate. One fast segment no
longer slows the entire gesture or its holds. Face cues and expected attitude
follow the corresponding source position, including reverse recovery. Startup
Home and Stop retain their existing timing. Ongoing gaits use fast coordinated
strokes; Neutral entry still uses the saved joint-speed setting. V1 and
older V2 firmware reject the extension at the gateway; the V1 C decoder rejects it.

## Variable forward walking

`walk_controls_v1` is an optional V2 hello feature. The existing `intent: walk`
envelope accepts `speed` (finite 0–100), or both `stride` (1–100 percent) and
`rate` (0.25–3 legacy multiplier). On P4 0.8.56, the rate field remains accepted
but no longer changes gait timing: direct stride also uses fast strokes.
Mixing modes, incomplete advanced controls, and
controls on directions other than `fwd` are rejected. A plain walk remains
valid. V1 and bodies without this feature reject extended controls.

```json
{"t":"intent","name":"walk","dir":"fwd","steps":3,"speed":25,"seq":41}
{"t":"intent","name":"walk","dir":"fwd","steps":3,"stride":100,"rate":2,"update":41,"seq":42}
{"t":"intent","name":"walk","dir":"fwd","steps":1,"speed":0,"update":41,"seq":43}
```

An optional `update` names the original active walk sequence. It requires controls,
preserves phase and cycle count, and uses the normal fresh sequence, epoch and
expiry checks. The update's ACK settles its settings request; only the original
walk emits movement completion. The gateway rejects missing/completed targets
before dispatch and exposes `active_walk_sequence` to Body Control. Speed zero
requests the model's controlled finish; independent emergency detach is unchanged.
The native accept API runs after shared admission. P4 keeps `motion=false` and
cannot physically execute this extension yet. See the
[V2 model](../models/v2-12servo/README.md) for the speed mapping and transition rules.

## Directional locomotion and automatic Run

`walk_steering_v1` separately negotiates composed steering, in addition to
`walk_controls_v2`. It uses paired finite `forward` and `turn` percentages
(-100 through 100) on a V2 walk or its update: positive forward advances,
negative forward reverses; positive turn turns left, negative turn turns right.
These are body-local movement magnitudes, not degrees, metres or a measured
velocity. Translation and yaw combine into an arc; updates keep the original
sequence, stance anchors, gait phase and existing servo-speed budgeting.

This contract was agreed with the owner on 2026-10-01 and matches MetaHuman's
existing signed-percentage action/update fields. `walk_controls_v2` alone does
**not** establish steering support: older P4 decoders can ignore these added
fields and acknowledge a straight walk. The gateway rejects either steering
field before allocating a sequence or dispatching when `walk_steering_v1` is
absent, including zero-valued fields. It advertises `forward` and `turn` only
with this feature. Older directional walking and speed-only updates remain
supported; steering is never translated into substitute motion.
Steering fields on another intent are explicitly malformed, so alias
normalization (including Run) cannot discard them and dispatch straight walking.

ACK confirms body admission, not goal achievement. An update ACK settles only
that correlated settings request; the original walk retains its action identity
and alone emits DONE or CANCELLED. Missing acknowledgement after dispatch is an
explicit unknown outcome, never completion. Session, epoch, revision, body-lease
and deadline fencing, controlled Finish and independent emergency stop retain
their existing owners.

```json
{"t":"intent","name":"walk","dir":"fwd","gait":"walk","steps":0,"speed":60,"forward":80,"turn":25,"seq":50}
{"t":"intent","name":"walk","dir":"fwd","gait":"walk","steps":0,"speed":60,"forward":80,"turn":-25,"update":50,"seq":51}
```

`walk_controls_v2` adds `dir: fwd|back|turn_l|turn_r`, `gait: walk|crawl`
and `steps:0` for ongoing operation. `run_gait_v1` additionally permits Speed
above 100 through 200 on the Walk family, and explicit `gait:run` for advanced
stride/rate tuning. Crawl Speed remains 0–100. The gateway requires both the
feature and declared `run` capability; older bodies cannot silently interpret it.

```json
{"t":"intent","name":"walk","dir":"fwd","gait":"walk","steps":0,"speed":100,"seq":51}
{"t":"intent","name":"walk","dir":"fwd","gait":"walk","steps":0,"speed":150,"update":51,"seq":52}
{"t":"intent","name":"walk","dir":"fwd","gait":"walk","steps":0,"speed":75,"update":51,"seq":53}
{"t":"intent","name":"walk","dir":"fwd","gait":"walk","steps":0,"speed":0,"update":51,"seq":54}
```

This is one command transitioning Walk → Run → Walk → Finish. The wire gait
family stays `walk`; changing Speed does not require a new sequence owner or a
stop. Only the original sequence emits completion. Changing direction or the
explicit gait family still requires finishing the active command. The schema
expresses field ranges; negotiated-feature admission is an additional runtime rule.
A bare semantic Run selects ongoing V2 Walk-family Speed 150; V1 keeps its
preprogrammed Run asset. Firmware output supervision and calibration are unchanged.

`crab_gait_v1` negotiates ongoing wide-stance `gait:crab`, with Speed 0–100,
advanced stride/rate and the same sequence-bound Finish. It adds Crab-only
`side_l` and `side_r`; forward/backward/turning reuse the existing directions.
The semantic commands `crab`, `crab_right`, `crab_forward`, `crab_backward`,
`crab_turn_left`, `crab_turn_right` require the connected V2 body's declarations.
The V1 `crab` emote is unchanged. `lay_down` is a separate declared V2 emote;
`dead` is labeled Play Dead, and `rest` retains the chassis-grounded posture.

## IMU execution context (P4)

From `0.8.85-p4-event-face`, `data.face_token` carries the active timed/manual
display selection's token, or an empty string after release/expiry. Tokens retain
the existing `[a-z0-9_]{1,32}` command format. This identifies the retained
selection even during temporary speech/listening overlays. MetaHuman's initial
body-event reaction uses `be_` followed by 29 hex characters; Body Control uses
that lifecycle to suppress repeat shake/tip notifications, independently of motion
commands. Replacement and the P4's existing expression timeout end that lifecycle.
Older firmware may omit the field. The token does not change sensor availability,
sample cadence or command admission.

The existing `event` / `name:"imu"` message optionally includes `data.motion`.
It describes the output owner's execution, not measured chassis or shaft motion:

```json
{"command":"walk","activity":"locomotion","phase":"motion","sequence":42,
 "connection":7,"started_us":1000000,"sampled_us":1020000,"expected_up":[0,0,1]}
```

`connection` is the P4-local command connection generation; the gateway envelope's
`robot_id` and `epoch` retain their existing attribution. `started_us` is the
first successful target-write time for this command. `sampled_us` timestamps the
latest target/context update, including completion/hold and output-off changes.
All times use the device monotonic clock shared with `data.timestamp_us`.
The producer supplies the most recent execution snapshot not later than that
IMU sample. Commands waiting in admission cannot supply this context.

Activities are `idle`, `pose`, `locomotion`, `clip`, `freestyle` and `manual`;
phases are `off`, `entry`, `motion` and `hold`. `expected_up` is a unit vector
for world vertical expressed in nominal body coordinates, or `null` when no
authored body-orientation reference is available. It follows recorded motion
time, including playback-rate changes and reverse recovery; a held pose keeps
its last reference. This reference is comparable with the sensor only when
`calibration_applied` identifies its calibrated body frame. It describes intent,
not evidence that the robot reached it. Consumers without this extension can
continue reading the existing IMU fields.

Body Control uses this context only for notification classification. Commanded
locomotion does not generate rapid-movement reactions; unexpected falls remain
reportable. Intended orientation is not permission to reject, stop or limit a
motion. No new message type, sensor loop, inference call or execution gate is
part of this extension.

## Existing lifecycle and media contracts

The current protocol-v1 liveness contract sends an application control ping
after one second without a control transmission. User-message timing is
irrelevant: the lightweight heartbeat continues while conversation is idle.
Four seconds without a valid control frame stops active motion but does not
destroy the authenticated session. A real WebSocket, gateway, or Wi-Fi failure
enters FAILSAFE/offline and starts reconnection. This keeps the home companion
connected while preserving an action-level actuator guard.

Bodies advertising `audio_input_v1` accept saved microphone gain and wake
threshold adjustments on the existing commands:

```json
{"t":"mic","seq":40,"on":true,"gate":"wake","gain_db":36}
{"t":"wake","seq":41,"enabled":true,"model":"ainekio","threshold":0.4}
```

`gain_db` selects ES8311 input gain from 0 through 42 dB in 6 dB steps. It is
stored on the robot; `on` and `gate` remain connection-scoped. `threshold` is
0..1 and is saved independently of the model manifest, quantized to 0..255.
Omitting either field preserves its saved value. With no saved override, P4
keeps its previous 30 dB gain and the installed model's threshold. Body Control
shows sensitivity as `100 * (1 - threshold)`: higher sensitivity triggers more
easily; threshold 1 (sensitivity 0) cannot be exceeded by the model.

These bodies include optional `audio` telemetry on their existing ping/pong:

```json
{"t":"ping","clock_ms":12000,"audio":{"on":true,"listening":true,"gate":"wake","gain_db":36,"wake_enabled":true,"wake_threshold":0.4,"rms":0.08,"peak":0.24}}
```

Levels are normalized 0..1 and measured before VAD/wake gating, with fast attack
and approximately one-second decay for display. No extra pre-wake PCM is sent.
`listening` reports active microphone monitoring (false during speaker
playback/cooldown or when off); levels are zero when not listening. Optional
`capturing` reports an open utterance and `speaker_busy` reports playback. These
are distinct: waiting for the wake word is listening but is not yet capturing. The dashboard uses a −60..0 dBFS
scale and discards stale display readings. The gateway keeps these scalar
readings separate from the existing PCM utterance/recording boundary.

Wake-word preferences use a separate persistent command from the session-only
microphone stream command:

```json
{"t":"wake","seq":42,"enabled":false,"model":"ainekio"}
```

`model` is a bounded trained-model identifier, not arbitrary text to be turned
into a wake word. The ESP32 stores the accepted setting in NVS. Status frames
may report `camera_ready`, `wake_enabled`, `wake_model`, and `wake_ready`;
`camera_ready=false` means snapshot/visual capability must not be advertised,
and `wake_ready=false`
means firmware must reject both enabling the setting and opening a microphone
with `gate="wake"`. These status additions remain optional so an older
protocol-v1 body is still accepted by the gateway validator.

Firmware-owned perception snapshots use optional correlation fields without
embedding media in JSON. VAD boundary events carry one robot-generated
`origin_id`; the following snapshot metadata repeats that identifier:

```json
{"t":"event","name":"vad_close","origin_id":73}
{"t":"cam_meta","res":"XGA","fps":0,"counter_base":18,"origin":"audio","origin_id":73}
```

The JPEG retains camera counter `18`. A body can send the complete image as
binary type `0x02`, or interleave it with audio/control using type `0x03` chunks.
Each chunk uses the existing five-byte type/counter header, followed by a
little-endian uint32 total JPEG length, uint32 byte offset, and JPEG bytes.
Offsets are contiguous from zero and all chunks of one image share its counter
and total length. The existing JPEG size and format contract is unchanged.
Body Control reassembles within the authenticated connection, then delivers one
ordinary camera frame with the original `cam_meta` correlation. An incomplete
image never becomes a camera observation and cannot cross a reconnect.
P4 uses its 4096-byte WebSocket send-buffer size for each complete chunk message;
this is a transfer granularity, not a smaller image-size limit. It drains ready
microphone packets between chunks. Other protocol-v1 bodies can continue sending
complete images. Deploy the receiving Body Control update before P4 chunk firmware.

Completed physical actions use `origin="action"` and the command sequence as
`origin_id`; firmware sends the JPEG before `{"t":"done","seq":...}`. An
explicit `snap` command uses `origin="request"`. These fields are optional for
protocol-v1 compatibility with older bodies, but when present they must occur
as a validated pair.

`camera_profiles_v1` negotiates independent stream and snapshot resolutions on
the existing `cam` command:

```json
{"t":"cam","seq":74,"on":true,"fps":5,"res":"QVGA","snapshot_res":"XGA"}
```

`res` selects QVGA (320×240) or VGA (640×480) preview; `fps` accepts 0–15.
The optional `snapshot_res` selects QVGA, VGA or XGA (1024×768) for request,
action and audio stills. Omission preserves the current still profile.
Disabling the stream does not disable requested snapshots.
The gateway rejects `snapshot_res` before dispatch when the body has not
advertised this feature. These profiles are runtime settings, not NVS records.

Bodies additionally advertising `camera_adaptive_v1` accept `snapshot_res`
values `960P` (1280×960 full-field), `FHD` (1920×1080 cropped), and `AUTO`.
Adaptive P4 firmware boots with AUTO; older firmware boots with VGA. AUTO
selects a concrete mode after metering and reports that concrete resolution
in `cam_meta` (never AUTO). It favors binned 960p in dim light and cropped FHD
in brighter light; select 960P for a consistent field of view. Stills allow
longer automatic exposures and exposure settling; preview favors shorter
exposures. The P4 README documents the selection and settling policy.

Bodies advertising `camera_controls_v1` additionally accept stream `res` values
`XGA`, `960P` and `FHD`, and this optional complete group:

```json
{"t":"cam","seq":75,"on":true,"fps":3,"res":"960P","snapshot_res":"AUTO","exposure_us":50000,"gain_x16":64,"jpeg_quality":75}
```

`exposure_us:0` selects automatic exposure; manual range is 100–1,000,000 µs.
`gain_x16:0` selects automatic gain; manual range is 16–1023 (1–63.9375×).
`jpeg_quality` is 1–100. All three fields must be supplied together; omission
preserves their previous values. This is sensor gain, not calibrated ISO.
The gateway uses existing feature negotiation before sending upgraded controls.
Automatic preview now permits the same night integration range as stills;
manual shutter extends frame timing when necessary. Delivered FPS may be lower
than requested. No change to movement ownership or stopping policy is involved.
The existing 256 KiB JPEG capacity still applies; oversize encoding reports an
error instead of silently changing resolution or quality.

Optional status `camera_capture` reports the latest emitted frame's `counter`,
`width`, `height`, measured `exposure_us`, `gain_x16` (16 = 1×; not ISO),
`settle_ms`, and `settled`. Preview has `settle_ms:0`; stills report whether
settings converged before the settling budget expired. This is diagnostic
information, not an image-quality guarantee or a robot movement condition.

The P4 uses one camera task and one JPEG encoder for both outputs, at the
existing quality 75. A queued snapshot retains the profile selected when it was
requested. Tagged still metadata reports `fps:0` regardless of preview rate;
the gateway also accepts explicit still origins from older P4 metadata that
carried preview FPS. Preview frames do not enter the remote Environment
observation path. Snapshot capture does not reset the preview's next-frame
deadline, although encoding and transport still share resources.

Run the host fixture suite from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=Slave/software \
  python3 -m unittest discover -s Slave/software/tests/protocol -v
```

## Gateway switching

`gateway_switching_v1` accompanies P4's existing `robot_settings_v1` messages.
It changes no command/result envelope: saved slots may share an SSID with
distinct `ws://` LAN or `wss://` configured remote addresses. Shared-SSID slots
have one Wi-Fi password; an omitted password for another address reuses that
network's saved credential. Readback and revision/ACK/persistence semantics stay
unchanged. Gateway admission explicitly rejects a same-SSID alternate for
firmware lacking this feature before dispatching that write. Legacy distinct
networks and other supported commands remain usable.

P4 keeps one authenticated outbound WebSocket and its existing admission
generation. Failed configured candidates can advance to another address on the
associated network, then to bounded protocol-v1 DNS-SD LAN candidates only if a
plain-WS address was explicitly configured for that network. TLS-only profiles
never downgrade to discovery. A healthy connection is sticky; an unauthenticated
attempt expires after 10 seconds. Close invalidates old work before reconnect,
even when independent hosts assign the same epoch. Switching is connection
availability, not task completion or cross-installation durable continuation.

## Twelve-joint operator calibration

`body_calibration_v2` is negotiated only by the P4 body. V1's eight-joint
`servo`, `limits`, and `cal_save` messages remain unchanged. It is an authenticated
Body Control operator service, not a MetaHuman motion or raw-angle action.

Requests use `t: "calibration"`, `seq`, the session `epoch` and `deadline_ms`.
`op` is `get`, `set`, `move`, `home`, or `save`. `get` reads all twelve records in
any mode; the other operations require `mode: calibrate`. `set` stages one
record (`id`, `channel`, `home_us`, `invert`) without moving it. The optional
`home_cd` and `us_per_degree` mapping fields must be supplied together; omitting
them preserves the saved mapping.
IDs are 0–11; channels are 0–11 or -1 to disable a joint. Assigned channels must
be unique. Home and Move pulses are positive 16-bit integers (1–65535 µs).
Those are wire-format bounds, not a declaration of servo travel; the body also
checks whether its configured PWM hardware can represent the pulse. `move`
takes `id` and `pulse_us`. There are no per-joint pulse endpoints in this
contract. `home` optionally takes `id`, otherwise homes assigned
joints. `save` commits the staged records without rebooting; outputs are disabled
before the flash write, and an explicit subsequent home/move resumes them.

Each successful operation emits ACK, then `calibration_status` carrying the same
sequence, `dirty`, `saved`, `ready`, and exactly twelve `joints` records. Records
include `pulse_us`, the last commanded pulse (0–65535, with zero when disabled),
not measured shaft position. `ready` describes calibration/output readiness, never gait
qualification. `saved` means the records match committed storage; defaults may
be neither dirty nor saved. Failed operations produce NAK. The gateway requires
correlated readback before reporting success and discards cached calibration on
reconnect. An ACK alone does not confirm a save or position.

When the PWM hardware range is available, `calibration_status` includes the
paired optional `pulse_min_us` and `pulse_max_us` fields. Both are positive
16-bit integers, with minimum <= maximum. They describe pulse widths the
configured PWM hardware can represent, not the endpoints of an attached servo.
Bodies omit both fields when hardware capacity is unavailable.

Physical order is rear-left, rear-right, front-left, front-right, with shoulder,
carrier and crank in each group. Front-left therefore uses joint IDs 6, 7, 8;
its default PCA channels match those IDs. Channel assignments are calibration
data and may be changed explicitly by the owner.

## Storage service and current capabilities

P4 advertises `storage_control_v1` and `capabilities.storage=true` when the
storage service is implemented, including when no card is mounted. Operator
requests `{t:"storage",op:"get"|"retry"|"clear",seq,epoch,deadline_ms}` receive
ACK followed by a correlated `storage_status` with `available`, `mounted`,
`busy`, `total_bytes`, `free_bytes`, `dropped_records` and a bounded `error`
string. Clear deletes Ainekio logs and captures; it does not format the card.
The dashboard requires explicit confirmation and a fresh mounted/idle readback
before clearing, and the device independently rechecks its storage state.
V1 does not decode this extension.

For bodies negotiating `body_capabilities_v1`, regular `status` may include the
same complete `capabilities` object used in hello. The gateway replaces its
capability snapshot after validating that status. Camera or audio readiness
can therefore change after asynchronous initialization without reconnecting.
This never implies that a separately deferred movement executor is ready.

## Saved speaker volume (P4 body extension)

A body reporting `audio.speaker_volume_percent` in ping/pong accepts
`{"t":"speaker","seq":1,"volume_percent":50}` with the usual negotiated epoch
and deadline. `volume_percent` is an integer from 0 (mute) to 100 (unchanged PCM).
The command completes after the body saves and applies the value. It applies to
both streamed speech and local audio assets, and remains set across power cycles.
Read back the current value from heartbeat audio telemetry. Existing V1 firmware
without that telemetry field does not implement this command.

## Timed display expressions

`face_feedback_v1` extends the existing `intent` / `face` command. `expr` remains
an identifier from the same face library used by Body Control and motion cues.
Optional `token` and `if_token` are 1–32 lowercase alphanumeric/underscore
identifiers. `timeout_ms` is an unsigned 32-bit duration measured on the robot;
zero retains an untimed selection. `background:true` yields to actual motion and
speech while preserving the expression between activities. Each set replaces
the single active selection immediately; receipt completion means applied, not
that its display timeout has elapsed.

`release:true` with `token` releases only the matching selection and needs no
`expr`. `if_token` makes a set conditional on the currently active token, so an
old request's failure indication cannot replace a newer face. Expiry/release
returns to the underlying motion/default face. Listening and connection screens
retain their existing renderer ownership. These operations never send Stop or
change body outputs. Untimed legacy `face` requests retain their existing
clear-on-next-motion behavior. Gateways reject extension fields unless the body
advertises this feature. The hello feature array now permits 32 entries.

`walk_lateral_v1` adds optional signed `lateral` percent (-100 to 100), positive
left, to the existing paired `forward`/`turn` steering fields. It requires
`walk_steering_v1` and `walk_controls_v2`; the gateway advertises the update
control only when the connected firmware reports that feature. Existing updates
retain the original action, direction, gait, revision and acknowledgement identity.
The gait owner blends all three body-frame velocity components while preserving
planted contacts; `speed: 0` still finishes the original action. This source
extension requires rebuilt firmware and has not established physical qualification.


### V2 measured-position stall event

The P4 sends `{"t":"event","name":"servo_stall","event_id":"BOOT:CLOCK",
"clock_us":1234567,"seq":0,"joint_mask":48,"outputs_released":true}` after
its output owner releases all channels for observed shaft non-progress. `seq=0`
allows startup/holding faults; bits 0–11 of `joint_mask` identify model joints,
not configurable PWM or mux channels. Body Control wraps this as the existing
`body_event` notification with `data.kind="servo_stall"`, adding physical joint
names before forwarding it through the environment bridge. The normal command
failure receipt is separate from this single notification. No current or
thermal measurement is implied.

### V2 feedback confidence and unverified completion

From `0.8.112-p4-feedback-fallback`, coordinated Stand can complete its authored
path with `{"t":"done","seq":7,"position_verified":false}` when usable
post-command observations are unavailable. Outputs stay powered and new commands
remain available. `position_verified:true` means the final measured joint targets
matched. The optional field is retained in Environment Bridge receipt data.
A retained Stand goal may resume correction when observations return, without a
second receipt for the same request. Ordinary trajectory completion omits the field.

The existing telemetry cadence also carries `event`, `name:"servo_feedback"`.
Its `data` includes `enabled`, `usable`, `scan`, `clock_us`, `calibrated_mask`,
`unavailable_mask`, `clipped_mask`, `below_calibration_mask`,
`above_calibration_mask`, `adc_error`, `supply_voltage_available:false`, and
`signal_millivolts` (twelve integers or null in model-joint order). Masks identify
joints rather than mux/PWM channels. Below/above calibration marks position
confidence, not a limit on commanded pulse widths. Diagnostic extrapolation
remains available; unusable observations cannot establish a jam or arrival.

Body Control retains current health in robot status and emits
`servo_feedback_fault`/`servo_feedback_restored` through the existing body-event
route. Fault notices share the existing event cooldown and reaction-face
suppression and do not command any motion or output release. Signal voltage is
not battery or servo-rail voltage and cannot identify the electrical cause alone.
