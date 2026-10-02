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

## Saved named-motion speed

V2 `motion_speed_v1` provides one shared speed multiplier for Stand, Sit and
finite named motions. The default is 2×; positive numeric multipliers have no
application-imposed speed cap or fixed increment.
An optional `playback_rate` on these intents previews a different speed for that
command. Omission uses the robot's current saved setting. The setting is captured
when a motion starts; changing it does not retime a running gesture.

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

The multiplier directly scales the existing entry and clip clocks; it does not
change the joint path or motion assets. Startup
Home, Neutral/Stop and ongoing gait controls retain their existing timing. V1 and
older V2 firmware reject the extension at the gateway; the V1 C decoder rejects it.

## Variable forward walking

`walk_controls_v1` is an optional V2 hello feature. The existing `intent: walk`
envelope accepts `speed` (finite 0–100), or both `stride` (1–100 percent) and
`rate` (0.25–3 multiplier). Mixing modes, incomplete advanced controls, and
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

## Existing lifecycle and media contracts

The current protocol-v1 liveness contract sends an application control ping
after one second without a control transmission. User-message timing is
irrelevant: the lightweight heartbeat continues while conversation is idle.
Four seconds without a valid control frame stops active motion but does not
destroy the authenticated session. A real WebSocket, gateway, or Wi-Fi failure
enters FAILSAFE/offline and starts reconnection. This keeps the home companion
connected while preserving an action-level actuator guard.

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

The JPEG remains the next bounded camera binary frame with counter `18`.
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
action and audio stills. Omission preserves the current still profile; its boot
default remains VGA. Disabling the stream does not disable requested snapshots.
The gateway rejects `snapshot_res` before dispatch when the body has not
advertised this feature. These profiles are runtime settings, not NVS records.

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
