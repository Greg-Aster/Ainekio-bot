# Ainekio and MetaHuman Bridge Hardening Plan

Status: source hardening implemented and host-validated on 2026-07-22; the
supervised gateway is active and the controller is flashed. Physical acceptance
is not complete because the live connection still repeats a `1011 control
timeout` after authentication.

## Purpose

Harden the full path between MetaHuman OS and the physical Ainekio controller so
that connection state, command results, and camera capabilities remain truthful.
The bridge must never report physical success merely because an adapter accepted
work, and it must never advertise a sensor or movement capability that the
current body cannot use.

The existing ownership boundaries remain unchanged:

- MetaHuman OS interprets the current instruction, queues semantic actions, and
  consumes feedback and observations.
- `Master/gateway/` authenticates the physical robot, assigns command sequence
  numbers, and owns brain-side protocol lifecycle.
- `Master/gateway/environment_adapter/` translates generic Environment Bridge
  actions into Ainekio semantic commands and returns bounded feedback.
- `Slave/` owns hardware capability, command execution, local safety, and media
  production.
- AI output must not contain raw servo angles, PWM values, or unbounded motion.

## Intended Closed Loop

```text
MetaHuman Environment Mode
  -> coordinator action queue
  -> authenticated Environment Bridge adapter
  -> Ainekio gateway
  -> authenticated physical robot
  -> ack / done / nak / cancelled, status, or bounded JPEG
  -> gateway adapter feedback or observation
  -> MetaHuman Environment Mode and operator-visible result
```

Each arrow is a distinct state boundary. An available coordinator subscriber
does not prove that the physical robot is connected, and a queued action does
not prove that it completed.

## Confirmed Findings (Pre-Hardening Snapshot)

The following findings come from the live physical-gateway and MetaHuman run on
2026-07-22. The robot had its OLED and OV3660 camera attached, with no servos,
speaker, SD card, or other body systems connected.

### B1 - Adapter connected while physical robot was offline

Priority: P0

MetaHuman reported one connected Environment Bridge session and one action
subscriber. The same live observation contained an empty
`gateway.robots` object. The physical gateway had two controller TCP sockets,
but neither was registered as an authenticated protocol-v1 robot session.

The message `Environment Bridge connected` therefore meant only that MetaHuman
was connected to the Ainekio environment adapter. It did not mean that the
physical controller was available for commands.

### B2 - Queue acceptance was presented as physical action success

Priority: P0

For `please walk forward`, MetaHuman generated:

```json
{"type":"robotCommand","command":"walk","sessionId":"ainekio-sim-1"}
```

Environment Bridge Out returned `coordinated_for_adapter`, and the visible and
spoken response said `Walking forward.` before a body terminal result existed.
The adapter then rejected the action with `requested robot is not connected`.
No gateway sequence number was assigned and no command reached the controller.

Queue acceptance, dispatch acceptance, and physical completion are currently
being collapsed into one user-facing success message.

### B3 - Terminal rejection was recorded but not presented clearly

Priority: P0

The rejection was correctly recorded in the robot buffer as inbound bridge
feedback. It did not replace or visibly correct the earlier success statement.
The automatic follow-up Environment Mode run had no user instruction and
produced a generic conversational response instead of reporting the failed
movement.

### B4 - Direct camera requests cannot produce a snapshot action

Priority: P0

For `what do you see with the camera?`, Environment Mode produced no actions and
answered that the camera was unavailable. No `captureImage` action, gateway
snapshot command, robot sequence, JPEG frame, or visual observation was created.

The Ainekio adapter can translate `captureImage` into a protocol snapshot, but
MetaHuman's direct environment action parser excludes `captureImage`, Environment
Bridge Out excludes it from its selectable actions, and the checked graph does
not allow it on that output node. The image-validation and image-to-context edge
exist, but there is no direct action path that obtains the first image.

### B5 - Camera and movement capabilities are advertised without body truth

Priority: P0

The adapter observation advertised `visual: true`, `movement: true`, the full
robot command catalog, and an active adapter session while
`gateway.robots` was empty. This tells MetaHuman that capabilities exist even
when there is no authenticated body to provide them.

The actions list also omitted `captureImage`, contradicting `visual: true`.

### B6 - Physical camera readiness is not carried through protocol status

Priority: P1

The firmware knows whether its camera service initialized, but the physical
hello and periodic status messages do not expose that readiness. The gateway and
adapter therefore cannot distinguish these states:

- controller offline;
- controller online with no working camera;
- controller online with a ready camera;
- controller online with a camera that failed after startup.

The emulator has a `camera_ready` field, but physical protocol parity is missing.

### B7 - Physical session still uses a simulator-era name

Priority: P2

The physical environment adapter is configured as `ainekio-sim-1`. This label
does not route commands to a simulator by itself, but it makes physical logs,
feedback, stored robot-buffer entries, and diagnostics ambiguous.

### B8 - Connection display and raw socket state can look healthier than the
authenticated session

Priority: P1

The OLED and operating-system TCP table can show apparent connectivity while the
gateway has no authenticated robot in its application state. Operator-visible
status must be derived from authenticated protocol state, not WiFi association
or an established-but-incomplete TCP socket.

### B9 - Motion completion cannot prove physical movement

Priority: design limitation

The installed three-wire servos provide no positional feedback. Even after the
servos are attached, `done` can prove that the accepted firmware motion timeline
finished; it cannot prove that a joint physically reached its target. With no
servos currently connected, a successfully executed command would produce only
the configured PWM signals and a software terminal result.

## Implementation Audit - 2026-07-22

The following table records what changed after the findings above were captured.
"Source complete" means the checked-in implementation and host tests pass; it
does not substitute for activating the new processes or validating the physical
controller.

| Finding | Implementation status | Audit result |
| --- | --- | --- |
| B1 | Source complete; activation pending | The adapter now publishes separate adapter and authenticated-body state and rejects body actions before gateway dispatch when the configured robot is absent. |
| B2 | Source complete; activation pending | MetaHuman now says that a body command is queued and awaiting terminal feedback. It no longer reuses `Walking forward` as a completion statement at queue time. |
| B3 | Source complete; end-to-end presentation pending | Ainekio includes correlated terminal feedback in the next observation. MetaHuman turns terminal feedback into a no-new-action reporting instruction on the existing Environment graph, Conversation output, and TTS path. |
| B4 | Source complete; physical image pending | `captureImage` is accepted by the direct parser, Bridge Out options, node schema, and checked graph. A correlated fresh image is automatically selected for multimodal context even when the continuation has no typed user message. |
| B5 | Source complete; activation pending | Offline observations advertise only `sendText`. Movement requires an authenticated body; `captureImage` and `visual=true` additionally require `camera_ready=true`. The full semantic command catalog is hidden while the body is offline. |
| B6 | Source complete; controller flash pending | Physical status now encodes optional `camera_ready`, the protocol validator accepts it, gateway telemetry preserves it, and the adapter consumes it. This currently reports camera-service initialization; detecting a later camera-task failure remains future fault-health work. |
| B7 | Source complete; activation pending | Gateway and adapter defaults, the physical launcher, and the local runtime environment now use `ainekio-01`. Existing stale MetaHuman session state is not replayable because body actions retain their two-second age limit. |
| B8 | Source complete; physical display check pending | Incomplete WebSocket openings now close after a bounded ten-second handshake, with a regression test. Firmware OLED online state remains tied to authenticated `welcome`; disconnect/close moves it offline and signals failsafe. |
| B9 | Documented hardware limitation | No software claim of positional proof was added. A commissioning gate for attached and powered three-wire servos remains an owner decision because the controller cannot detect their physical attachment. |

## Local-First Connection Audit - 2026-07-22

The primary physical path is now one body-initiated local connection. This is a
replacement for saved LAN addresses, not an additional fallback chain:

```text
saved WiFi -> last authenticated local endpoint -> _ainekio._tcp.local fallback
           -> same-subnet gateway -> /robot
```

- Local mode is the configuration default and does not use the saved endpoint
  field. An older record without a transport key migrates to local mode without
  erasing WiFi, robot identity, calibration, poses, assets, or preferences.
- The controller stores one non-secret endpoint only after an authenticated
  `welcome`. It tries that endpoint once on boot or transport reconnect, then
  resumes DNS-SD if the address is stale or unavailable. This is a bounded cache,
  not hardcoded network configuration.
- Discovery requires protocol v1, `/robot`, LAN transport, the expected gateway
  service, and an IPv4 address on the robot's current WiFi subnet. An advertised
  Docker, VPN, or other off-subnet address is rejected; there is no first-address
  fallback. The earlier fixed `gateway_id` TXT value was removed because it was
  duplicated configuration and provided no authentication.
- If more than one distinct matching LAN service is visible, the controller
  refuses to choose and displays `MULTIPLE GATEWAYS`; it never connects to the
  first reply nondeterministically.
- Remote relay mode is explicit and requires a `wss://` endpoint. Local mode
  never silently falls back through Cloudflare.
- Owner decision: this one-off home companion uses authenticated `ws://` as its
  local transport. The trusted private WPA2 LAN is part of the security
  boundary. Pinned local WSS is not another pending connection path and should
  be reconsidered only if the robot moves to a shared or untrusted network.
- `/robot` remains LAN-facing on the one gateway listener. `/environment` now
  rejects every non-loopback peer, preserving MetaHuman's existing
  `ws://127.0.0.1:8790/environment` configuration without adding a second
  listener or service. Requests carrying Cloudflare relay headers are also
  rejected even though the local tunnel connector itself reaches loopback.
- OLED states distinguish searching, not found, verifying, authentication
  rejection, cached-address connection, and local/remote connection. Retry
  backoff resets after authenticated `welcome` and is capped at 15 seconds.
  Only a real socket, gateway, or Wi-Fi failure moves an authenticated session
  offline; conversational idle and a late application heartbeat do not.
- For bring-up testing, microphone transport starts enabled behind VAD while
  wake-word gating remains separate and off by default. Every completed action
  requests a correlated still when the camera is ready, and `captureImage`
  remains directly available to the LLM. Continuous camera transport stays off
  until enabled in Body Control; its frames feed only the local dashboard, not
  the Environment/LLM observation path. The dashboard also exposes the live
  microphone level and can enable or disable both devices.
- `Master/ainekio-gateway.service` is a single systemd user-service wrapper
  around the existing launcher. It is linked, enabled, and running on the owner
  computer; the old terminal-owned gateway was stopped after confirming it had
  no active body or Environment Bridge sockets.

The mDNS component is configured for the smallest supported interface count,
one advertised service, an eight-entry action queue, WiFi station only, and no
console CLI or multiple-instance support. Setting its interface count below two
does not compile because the upstream component internally compares two
interface slots; two is therefore the minimum supported build value even
though Ainekio enables only the station interface.

### Still open before production-ready local operation

- The chosen local `ws://` design does not cryptographically identify the
  discovered gateway or encrypt LAN traffic. Keep the robot on the owner's
  private WPA2 network, do not reuse its robot token, and rotate that token if
  an untrusted device joins the LAN or compromise is suspected.
- The maintained liveness contract is now one-second diagnostic heartbeats and
  a four-second action-level stale guard. A stale heartbeat stops active motion
  but does not close the WebSocket. The v1.0 DOCX contains older connection-
  timeout wording and requires a numbered erratum.
- The prepared firmware and LittleFS image were flashed on 2026-07-22. Separate
  digest verification passed for the bootloader, application, partition table,
  and LittleFS regions. NVS was not written, preserving provisioning and robot
  configuration. The mutable OTA-data digest changed after boot as expected.
- The controller boots, passes the 8 MB PSRAM test, initializes all eight
  remapped servo outputs, discovers the gateway, and authenticates. The first
  physical A/B correction enabled Espressif's separate WebSocket TX lock and
  increased the authenticated exchange from roughly 6-10 seconds to about 31
  seconds, with 36 valid control frames observed, but the gateway still closed
  the session as `1011 control timeout`. On 2026-07-22 the owner rejected idle
  heartbeat expiry as a session teardown condition. The prepared replacement
  keeps the short motion stop guard, removes timer-driven gateway/body session
  closure, and reserves reconnect for real transport failure. Physical flash
  and the 15-minute soak remain required before this finding closes.

### Local media testing policy - 2026-07-22

The owner selected the following bring-up behavior while wake-word support is
deferred:

- The controller microphone starts enabled with the VAD gate. Wake-word gating
  remains a separate persisted setting and is off by default.
- Every completed robot action requests one fresh JPEG when camera health is
  available. That image and the terminal feedback share the correlated
  Environment observation used for the LLM's next decision.
- The LLM can request a still directly through the existing `captureImage`
  action.
- Continuous camera frames are consumed by the local Body Control dashboard
  only. The Environment adapter now admits a JPEG only when the snapshot
  command's `cam_meta` counter identifies it as the requested still. This
  prevents dashboard live view from becoming continuous LLM image traffic.
- Body Control retains live JPEG viewing, camera enable/disable, microphone
  enable/disable and gating, and the live microphone-level meter. Audio sent to
  MetaHuman remains VAD-bounded utterances rather than a continuous raw stream.

Source and host tests are complete, the supervised host gateway was reloaded,
and the controller now contains the new microphone startup default and image
routing counterpart. Physical camera/audio acceptance remains pending behind
the recurring control-timeout failure.

Host activation evidence: systemd reports the user unit enabled and active;
one Python gateway owns `0.0.0.0:8790` and `127.0.0.1:8791`; Avahi resolves the
service on WiFi as `192.168.0.44:8790` with `protocol=1`, `path=/robot`,
`transport=lan`, and `tls=0`. User lingering is disabled, so automatic startup
currently occurs at owner login rather than before login.

### Ainekio source changes

- `Master/gateway/environment_adapter/server.py` now derives actions from one
  selected authenticated body, publishes bounded body readiness, blocks offline
  dispatch, gates snapshots on physical camera status, carries terminal feedback
  into observations, and includes robot ID, epoch, and sequence in terminal data
  when available.
- `Master/gateway/server/__main__.py` now uses the physical session name and a
  runtime-compatible bounded handshake protocol. The previously prepared close
  code/reason audit fields remain in place.
- `Master/start-physical-gateway.sh` now defaults the Environment session to the
  physical robot ID.
- Physical status encoding and runtime production now include
  `camera_ready`; the Python protocol contract keeps it optional so an older
  protocol-v1 controller is rejected by capability gating rather than by schema.
- Emulator and gateway regressions cover offline capability suppression,
  pre-dispatch rejection, camera-unavailable rejection, camera telemetry parity,
  and incomplete handshake cleanup.

### MetaHuman source changes

- Environment Action Parser now accepts direct camera requests only when the
  active observation advertises `captureImage`, and it capability-gates all
  other parsed actions against the same current observation.
- Environment Bridge Out distinguishes adapter readiness from Ainekio body
  authentication, rejects unavailable physical actions before queueing, and
  uses pending language until terminal feedback exists. The physical-body rule
  is scoped to the `ainekio-gateway` adapter so other Environment adapters are
  unchanged.
- Terminal feedback remains persisted through the canonical Robot Buffer and is
  also returned through the existing Environment graph for visible/TTS result
  reporting; no parallel conversation-memory system was added.
- Direct `captureImage` is enabled in the maintained node definition, schema,
  and graph. A fresh correlated still is selected for model context, while an
  unrelated or stale image remains excluded.
- Safe telemetry filtering now admits `camera_ready` without admitting secrets
  or unrestricted robot payloads.

### Validation evidence

- Ainekio emulator/gateway suite: all 138 tests passed, including dedicated
  incomplete-handshake, loopback-only Environment-route, correlated snapshot,
  and continuous-camera isolation regressions.
- Portable C core: all 11 tests passed.
- Python protocol contract: all 13 tests passed.
- ESP-IDF 5.5.4 firmware build: passed; local-discovery application image size
  `0x158250`, with 55 percent of the smallest application partition free.
- MetaHuman focused Robot Operator/Environment parser suite: 7 tests passed.
- MetaHuman Environment Bridge coordinator compatibility suite: passed,
  including adapter-only rejection, pending lifecycle wording, terminal feedback
  interpretation, and correlated image selection.
- All 25 MetaHuman cognitive graphs validated.
- The full MetaHuman core typecheck still reports existing errors in unrelated
  maintained areas. After correcting two initially exposed compatibility issues,
  it reports no error in the bridge-hardening files changed here.

### Activation and physical evidence still required

1. Restart MetaHuman OS and the physical gateway in an owner-approved window so
   the new graph, adapter, session identity, and handshake behavior load.
2. Include the firmware-side heartbeat and `camera_ready` status changes in the
   next owner-approved firmware flash; do not perform a separate flash only for
   this audit.
3. Run the 15-minute authenticated body soak and forced gateway-stop/OLED checks.
4. Obtain one physical OV3660 still through the complete correlated MetaHuman
   multimodal path.
5. Decide whether motion advertisement requires an explicit commissioning flag
   after servo wiring, neutral pose, power, and stop behavior pass bring-up.
6. Verify separate acknowledged-state presentation if operator UX needs an
   intermediate robot `ack`; this pass fixes queued-versus-terminal truth but
   does not add a new acknowledgement notification channel.

## Work Prepared but Not Active on the Controller

The source tree contains the following unflashed owner-approved liveness
correction:

- one-second control heartbeats;
- four-second stale-control motion stop without WebSocket teardown;
- no gateway or controller disconnect caused only by an idle timer;
- reconnect only after a real WebSocket, gateway, or Wi-Fi failure;
- duplicate native WebSocket pings disabled in the pinned client; protocol-v1
  remains the only application heartbeat;
- a separate upstream WebSocket TX lock for the existing dedicated TX task;
- gateway heartbeat counters for JSON pings sent, valid control frames received,
  and last control type;
- firmware counters and failure-only logs for frame metadata, decode rejection,
  heartbeat enqueue, and control send result;
- emulator parity and a regression proving that a silent authenticated body is
  not disconnected by a timer.

The controller currently runs the verified transient-write diagnostic A/B image.
It includes temporary cumulative status fields and still has the aggressive TCP
keepalive values. Those temporary wire fields have been removed from prepared
source; the clean keepalive-free policy still requires one application-only
flash after rebuild and host tests pass.
The first replacement-image soak stayed authenticated past the former 31-second
cutoff but ended with abnormal socket close `1006` at about 68 seconds,
immediately after the remaining 60-second native client ping. That native ping
is now removed from the prepared image rather than allowed to compete with the
protocol heartbeat.
The next physical session still ended as `1006` after about 93 seconds, proving
the native ping was not the sole cause. Status delivery paused and later
recovered in bursts before the close. The next prepared A/B change therefore
treats a bounded single-frame control or microphone write failure as transient:
it drops that frame, stops motion when control becomes stale, and keeps the
authenticated socket. The physical A/B image also exposed temporary cumulative
status counters, which supplied the evidence below and were then removed from
prepared source. A failed fragmented camera frame still rebuilds the socket
because continuing after a partial WebSocket message would corrupt the stream.
That image extended the next session to about 171 seconds. Live TCP inspection
then showed the controller link at roughly 444 ms RTT, congestion window one,
retransmissions, and a 6.2-second retransmission timeout. Firmware still had
TCP keepalive configured to declare failure after an approximately 20-second
idle/retry window, matching the observed recoverable 20-30 second pauses. The
next prepared image removes that duplicate transport timer. Protocol heartbeat
age still stops motion, while real Wi-Fi and WebSocket error events retain the
normal reconnect/failsafe path.

## Hardening Plan

### Phase 1 - Restore and prove authenticated body connectivity

Owners: Ainekio gateway and physical firmware

1. Restart the physical gateway so timer-driven session closure is removed.
2. Flash the application-only controller change, preserving NVS, LittleFS,
   pairing, and Wi-Fi configuration.
3. Add or verify a bounded WebSocket opening/handshake timeout so incomplete TCP
   clients cannot remain indefinitely as misleading established sockets.
4. Confirm every disconnect records a bounded code and reason without secrets.
5. Make OLED gateway state follow authenticated welcome/disconnect events and
   ensure it cannot remain `online` after the application session is gone.

Acceptance:

- `gateway.status().robots` contains `ainekio-01` continuously for at least
  15 minutes on the home LAN.
- Status frames arrive at the configured five-second interval.
- A forced gateway stop moves the OLED to offline and detaches motion through
  the existing failsafe.
- Restarting the gateway creates one new authenticated epoch without duplicate
  active robot sessions or replayed commands.
- The audit records the close cause for malformed input, replacement, and
  gateway-stop cases; it records no idle-timer disconnect.

### Phase 2 - Separate adapter, body, and capability state

Owners: Ainekio environment adapter and MetaHuman environment interface

1. Publish separate bounded state for:
   - adapter connected;
   - physical body authenticated;
   - latest body heartbeat age;
   - motion available;
   - camera ready;
   - microphone ready;
   - speaker ready.
2. Derive advertised actions from the authenticated body's current capabilities.
   An offline robot must not advertise executable movement or camera actions.
3. Change Environment Bridge Out readiness so it checks both the adapter
   subscriber and body availability for body-dependent actions.
4. Present the three states distinctly in operator diagnostics:
   `adapter offline`, `adapter online / robot offline`, and `robot online`.
5. Rename the physical session from `ainekio-sim-1` to an owner-selected
   physical name, preferably `ainekio-01`, and migrate or expire stale session
   state without replaying pending work.

Owner decision before implementation:

- Decide whether motion should require an explicit commissioning flag after
  servo power, wiring, neutral pose, calibration, and stop behavior pass physical
  bring-up. Firmware cannot automatically detect whether three-wire servos are
  physically attached.

Acceptance:

- An adapter-only connection cannot produce a success status for a body action.
- Offline observations advertise no executable body movement or snapshot action.
- Reconnecting the physical controller updates capabilities without restarting
  MetaHuman OS.
- No raw servo or PWM surface is exposed through the bridge.

### Phase 3 - Make action lifecycle truthful to the operator

Owners: MetaHuman coordinator, Environment Bridge Out, and Ainekio adapter

1. Preserve distinct lifecycle states:
   `queued`, `dispatched`, `acknowledged`, and terminal
   `completed`, `rejected`, `cancelled`, `expired`, or `timed_out`.
2. Do not speak or display `Walking forward` as a completed fact when only queue
   acceptance exists. Use a pending phrase or wait for terminal feedback.
3. Correlate every visible response with the coordinator action ID, gateway
   epoch, and robot sequence when one exists.
4. Surface terminal failure once in the normal conversation output and TTS path.
   Preserve feedback ID idempotency so retries cannot create duplicate messages.
5. Ensure a late terminal result cannot be attached to a newer action or session.
6. Keep stop preemption on the existing high-priority semantic path.

Acceptance:

- Body-offline `walk` produces one visible rejection and no success statement.
- Successful `walk` reports pending/accepted before terminal completion and
  reports completion only after the robot returns `done`.
- `nak`, cancellation, expiry, timeout, reconnect, and duplicate feedback each
  have focused tests.
- Robot-buffer history and the visible response agree about the final result.

### Phase 4 - Complete truthful snapshot and vision flow

Owners: physical firmware, Ainekio adapter, and MetaHuman Environment Mode

1. Add bounded physical camera readiness to the protocol contract. Prefer one
   explicit feature/readiness field that the gateway can validate and expose.
2. Advertise `visual: true` and `captureImage` only while an authenticated body
   reports a ready camera.
3. Add `captureImage` to MetaHuman's validated environment action parser,
   Environment Bridge Out action options, graph configuration, and capability
   tests.
4. Add a deterministic narrow fallback for direct requests such as
   `what do you see?`, `take a picture`, and `use the camera`, gated by the
   current adapter capability and routing authorization.
5. Preserve the existing bounded snapshot path:
   semantic snapshot -> protocol sequence -> bounded JPEG -> validated data URL
   observation -> image-capable model context.
6. Wait for the correlated JPEG observation before asking the model to describe
   what the robot sees. Do not answer from a stale image or from capability
   metadata alone.
7. Keep continuous video out of the model path. One bounded still is the current
   contract.

Acceptance:

- Camera absent or failed: `captureImage` is unavailable and the user receives
  one truthful explanation.
- Camera ready: one direct camera request creates one snapshot sequence and one
  correlated visual observation.
- Malformed, oversized, stale, and uncorrelated JPEGs are rejected.
- The accepted physical OV3660 frame reaches the selected multimodal provider
  and produces a response grounded in that frame.
- The physical result is recorded in the H-series hardware checklist; emulator
  fixtures do not substitute for this evidence.

### Phase 5 - End-to-end bench and assembled-body acceptance

Owners: project owner with Ainekio and MetaHuman test support

Run the first closed-loop checks without a powered servo rail:

1. Authenticate the body and hold the connection for the Phase 1 duration.
2. Request status and one camera snapshot.
3. Verify that a movement request follows the expected semantic and terminal
   lifecycle while acknowledging that no joint can move without attached and
   powered servos.
4. Verify stop and disconnect failsafe behavior at the signal/software level.

After the servo rail, neutral calibration, battery monitoring, and physical stop
gates pass their hardware checklist sections:

5. Repeat stand, one-step walk, stop, disconnect, reconnect, and snapshot tests.
6. Observe power stability, joint direction, range, heating, and mechanical
   interference. Stop immediately on any hardware-checklist stop condition.
7. Record software terminal results separately from observed physical motion.

Final acceptance requires one recorded chain for each supported result:

```text
user instruction
  -> parsed semantic action
  -> coordinator action ID
  -> gateway epoch and sequence
  -> robot ack
  -> robot terminal result
  -> operator-visible result
```

Camera acceptance additionally requires:

```text
capture request
  -> snapshot sequence
  -> physical JPEG frame
  -> correlated visual observation
  -> validated multimodal model input
  -> grounded response
```

## Required Test Coverage

### Ainekio repository

- Gateway liveness with delayed heartbeat and real close-cause audit fields.
- Incomplete WebSocket handshake cleanup.
- Adapter-connected/body-offline capability observation.
- Body reconnect capability refresh.
- Every semantic command terminal outcome.
- Physical and emulator camera-ready parity.
- Snapshot success, camera unavailable, busy, timeout, malformed frame, and
  correlation behavior.

### MetaHuman repository

- Adapter online/body offline is not reported as robot ready.
- Queue acceptance cannot produce a completed-action response.
- Terminal rejection is visible once and is safe for TTS.
- `captureImage` parsing and capability gating.
- Camera question waits for a correlated visual observation.
- Existing JPEG size and structure validation remains enforced.
- Environment graph validation and maintained-surface architecture guardrails.

### Physical evidence

- Fifteen-minute authenticated WiFi/gateway soak.
- Gateway restart, router interruption, and controller reconnect.
- OLED agreement with gateway application state.
- One OV3660 still through the complete MetaHuman image path.
- Servo-signal and later powered-joint results recorded under the hardware
  checklist rather than inferred from `done`.

## Completion Criteria

Bridge hardening is complete only when all of the following are true:

- The operator can distinguish adapter connectivity from physical robot
  connectivity.
- MetaHuman never claims that a physical action happened before terminal robot
  feedback.
- Offline, failed, and unavailable results are visible once and remain
  correlated to their initiating action.
- Movement and media capabilities reflect the authenticated body's current
  state.
- A direct camera request can obtain and consume one physical OV3660 still.
- Reconnects cannot replay stale movement or attach feedback to the wrong epoch.
- Emulator, gateway, MetaHuman, and physical acceptance evidence all pass within
  their own boundaries.

## Related Authority

- [AINEKIO_METAHUMAN_CLOSED_LOOP_STATUS.md](AINEKIO_METAHUMAN_CLOSED_LOOP_STATUS.md)
  describes the intended closed-loop architecture and previously validated
  software behavior.
- [HARDWARE_BRINGUP_CHECKLIST.md](HARDWARE_BRINGUP_CHECKLIST.md) owns physical
  camera, audio, motion, power, and assembled-system evidence.
- [SLAVE_BRAIN_PROGRESS.md](SLAVE_BRAIN_PROGRESS.md) owns the current robot-body
  implementation record.
- [REPOSITORY_MAP.md](REPOSITORY_MAP.md) owns code and documentation boundaries.
