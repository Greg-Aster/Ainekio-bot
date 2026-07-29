# Camera Hardening

Status: freestyle completion and gateway lifecycle revision flashed, verified,
and connected; physical motion proof awaits owner-supervised validation and
physical audio proof awaits a microphone
Owner decision recorded: 2026-07-23
Applies to: Ainekio physical controller, Ainekio gateway Environment adapter,
and the maintained MetaHuman Environment Mode path

## Purpose

Harden the robot perception cycle so that sight, speech, action completion, and
future important sensor events reach MetaHuman as truthful, correlated,
event-driven observations.

The target is one bounded still image for each meaningful perception event.
Continuous video is not sent to the LLM, images are not added to routine
network packets, and English phrases are not hard-coded as robot commands.

## Owner Decisions

- The camera represents the robot's eyes. The local LLM must infer when a
  request requires current visual perception.
- Phrases such as `tell me what you see` must not be encoded as exact matches
  in a node or workflow.
- The LLM receives semantic capability descriptions and returns semantic
  actions. Existing capability, safety, freshness, and raw-servo rejection
  gates remain authoritative.
- One still should accompany each meaningful robot-originated perception
  event, including a completed microphone utterance, a completed physical
  action, and selected future safety or sensor alerts.
- Audio and snapshot capture should proceed concurrently and be joined by a
  bounded correlation identifier before cognition runs.
- Camera or snapshot failure must not discard audio, action completion, or
  sensor state.
- Continuous video remains off for the model path. The local Body Control
  dashboard may continue to use an explicitly enabled preview stream.
- A robot speech-completion event does not automatically request another
  cognitive snapshot. Doing so could create a speech, image, response, speech
  loop without new user or world input.

## Boundary and Ownership

```text
ESP32-S3 body
  -> local event boundary queues one existing snapshot operation
  -> bounded media frames plus typed origin and correlation metadata
  -> Ainekio gateway validation, utterance assembly, and correlation forwarding
  -> MetaHuman Environment Bridge transcription and bounded media join
  -> one Environment observation containing the available event data
  -> Environment Mode multimodal reasoning
  -> zero or more validated semantic actions
  -> Ainekio gateway safety and protocol translation
  -> body execution
  -> terminal result plus one correlated post-action still
```

- Firmware owns camera and audio device operation, bounded queues, VAD events,
  automatic event-boundary snapshot triggers, protocol frames, local safety,
  and command execution.
- The Ainekio gateway owns protocol validation, utterance assembly, correlation
  forwarding, media bounds, terminal feedback, and truthful body capabilities.
  It does not issue a second automatic snapshot command for a completed
  utterance or motion action.
- MetaHuman owns speech-to-text, multimodal joining at its Environment Bridge
  boundary, cognition, bounded continuation, and semantic action selection.
- Ainekio does not call MetaHuman APIs or contain a MetaHuman URL.
- MetaHuman does not produce raw servo angles or bypass the Ainekio safety
  boundary.

## Current Status

### Working

- The physical controller reports camera readiness and can return a bounded
  OV3660 JPEG snapshot.
- A direct snapshot uses the camera's full 1024x768 XGA sensor mode and returns
  the camera to its previous preview or off state afterward.
- Continuous dashboard camera frames are excluded from Environment Mode.
- Firmware sends 20 ms microphone PCM frames. The Ainekio gateway assembles
  one VAD-bounded utterance, and MetaHuman transcribes it through the existing
  STT service.
- Completed semantic motion actions originate a post-action still from the
  controller when the camera is ready.
- The action feedback and accepted JPEG can share one correlated Environment
  observation.
- The maintained Environment graph wires validated images into the normal
  model context.
- Semantic capability and safety gates reject unavailable actions and raw
  servo-like output.

### Baseline Findings Before This Pass

1. **Stale camera capability**

   Robot status refreshes diagnostic telemetry but not the Environment
   observation. If the initial connection observation has no body status,
   MetaHuman can continue reporting `cameraReady: false` after the physical
   controller reports `camera_ready: true`.

2. **Hard-coded natural-language action matching**

   MetaHuman currently contains exact phrase matching that converts selected
   camera, movement, and stop phrases into actions. This conflicts with the
   owner decision that the local LLM should infer intent from embodiment and
   semantic capabilities.

3. **Audio observations deliberately omit vision**

   A completed robot utterance becomes a text observation after STT, but the
   current implementation explicitly removes `visual` and `visuals` to prevent
   an unrelated stale image from being reused. That stale-image protection is
   correct, but no fresh utterance-correlated image replaces it.

4. **VAD and general body events do not receive snapshots**

   VAD events and other typed body events can create observations, but they do
   not currently request or correlate a still.

5. **Continuation ownership is inconsistent**

   Robot Observer has a three-step default cycle bound and Environment work has
   a broader automatic-run guard. Ordinary user interactions and
   robot-originated audio do not consistently carry the dedicated cycle
   metadata through each action and returned observation.

6. **Image-size contract drift**

   The robot transport now supports a bounded 256 KiB JPEG, while the MetaHuman
   image-input node accepts at most 120 KiB. Current XGA test images are below
   the smaller limit, but a more detailed scene could be rejected despite being
   valid at the Ainekio boundary.

7. **Physical multimodal acceptance is incomplete**

   Physical XGA snapshots have reached the gateway, but an utterance plus its
   fresh correlated image has not yet been proven through STT and the selected
   multimodal model in one Environment observation.

## Event Snapshot Policy

| Event | Request one still | Cognition behavior |
| --- | --- | --- |
| Completed VAD-bounded user utterance | Yes, controller-triggered when camera ready | Join transcript, still, and body state; run Environment Mode once |
| Completed semantic motion action | Yes, controller-triggered when camera ready | Join terminal feedback and still; continue the bounded action cycle |
| Rejected, cancelled, or expired action | No by default | Return truthful feedback and current state |
| Important future sensor alert | Configurable by typed event | Join alert state and still; run Environment Mode once |
| Periodic status or heartbeat | No | Refresh liveness/capability state without starting cognition |
| TTS or speaker completion | No by default | End the response turn without creating a self-triggering loop |
| Dashboard preview frame | No | Keep it local to Body Control |

This is an event policy, not a list of English commands. Future sensors opt in
through typed event definitions rather than through text matching.

## Intended Audio and Image Turn

```text
vad_open
  -> controller assigns a compact origin_id
  -> bounded 20 ms PCM transmission
vad_close
  -> controller queues the close boundary behind the final PCM frame
  -> controller queues one existing snapshot operation when camera_ready
  -> gateway derives one stable utteranceId from robot, epoch, and origin_id
  -> gateway sends bounded audio toward STT without a return camera command
  -> returned cam_meta and JPEG repeat origin_id
STT result + JPEG, or bounded timeout
  -> one Environment observation
  -> transcript + fresh image + robot state + utterance metadata
  -> one Environment Mode execution
```

The join must be bounded:

- no more than the existing bounded number of pending utterances;
- snapshots remain serialized by the controller's existing camera command
  queue and single framebuffer;
- a short timeout after which audio proceeds without an image;
- late images cannot attach to a newer utterance;
- duplicate or retried events remain idempotent;
- camera failure cannot block transcription.

## LLM Embodiment and Action Contract

MetaHuman should describe capabilities semantically rather than enumerate user
phrases:

- `captureImage` obtains the robot's current visual perception through its
  camera.
- If the current task depends on the present physical scene and no fresh
  correlated image is available, the model may request `captureImage`.
- The model must not claim to see or hear based only on capability metadata.
- The model waits for a fresh correlated observation before describing a
  scene.
- The model may return only currently advertised semantic actions.
- The Ainekio gateway remains responsible for translation and safety.

The deterministic phrase parser should not manufacture camera or movement
actions from natural-language regular expressions. Schema validation,
capability gating, freshness checks, semantic command catalogs, owner autonomy
mode, bounded continuation, and raw-servo rejection remain deterministic.

## Hardening Work

### CH-1 - Refresh truthful camera capability

- Publish an updated Environment observation when body connectivity or
  capability readiness changes.
- Do not enqueue cognition for every five-second status packet.
- Add regression coverage for initial `status: null` followed by
  `camera_ready: true`, later camera loss, and body reconnect.

### CH-2 - Remove exact-language command manufacturing

- Remove the direct natural-language phrase matcher from Environment action
  parsing.
- Preserve parsing of the model's structured semantic response.
- Preserve capability and safety validation after model output.
- Replace exact-command tests with structured inference-contract and
  capability-gating tests.

### CH-3 - Describe robot embodiment to the local LLM

- Describe the camera as current robot vision in the capability/tool contract.
- Update the context router so tasks requiring present physical perception are
  eligible environment actions without listing phrases.
- Prevent unsupported claims about camera, microphone, and speaker readiness.

### CH-4 - Correlate one utterance with one fresh still

- Use the completed VAD utterance as the event boundary.
- Assign a compact controller `origin_id` and derive the stable gateway
  `utteranceId` from the robot, epoch, and that identifier.
- Queue the still locally after the final audio frame and VAD close boundary;
  the gateway receives audio and image without sending a camera request back.
- Join transcript and matching JPEG at the MetaHuman Environment Bridge with a
  bounded timeout.
- Emit one Environment observation rather than separate text and image
  cognition runs.
- Fall back to a text-only observation when the camera is unavailable or the
  snapshot times out.

### CH-5 - Generalize selected event snapshots

- Reuse the controller's existing snapshot queue and camera task for completed
  semantic motion.
- Require future important sensor alerts to opt in at a typed controller event
  boundary rather than through gateway text or environment-variable matching.
- Do not snapshot routine status, heartbeat, every packet, or continuous media
  frames.

### CH-6 - Make continuation correlation consistent

- Carry one cycle ID and step counter from an initiating user/perception event
  through semantic actions, terminal feedback, and returned stills.
- Use the existing configured Robot Observer step bound where possible instead
  of adding an unrelated autonomous loop.
- Stop cleanly when the model produces no action, the owner mode disallows a
  continuation, a capability disappears, or the step limit is reached.

### CH-7 - Reconcile JPEG bounds

- Keep the Ainekio 256 KiB transport ceiling.
- Raise the MetaHuman validation limit only to the same explicit ceiling, while
  retaining JPEG structure validation and the one-image-per-observation limit.
- Verify typical and worst-case XGA stills without introducing resampling or
  aspect-ratio processing.

### CH-8 - Validate and activate

- Run focused Ainekio adapter, protocol, emulator, and firmware tests.
- Run focused MetaHuman Environment Bridge, graph, image, action, and Robot
  Observer tests.
- Validate both dirty worktrees without overwriting unrelated owner or agent
  changes.
- Restart only the services required to activate the tested source.
- Prove one physical utterance plus XGA still through STT and multimodal
  Environment Mode.
- Prove one completed physical action plus correlated still.
- Record timing, JPEG size, failures, and final runtime state below.

## Implementation Status

| Work item | Status | Result |
| --- | --- | --- |
| CH-1 truthful capability | Source complete | Camera readiness refreshes the cached selected observation without scheduling cognition |
| CH-2 remove phrase matching | Source complete | Only structured model actions reach deterministic capability and safety validation |
| CH-3 semantic embodiment | Source complete | Camera is described as the robot's visual sense; sensor truth is explicit |
| CH-4 utterance plus still | Source complete | One bounded correlation join accepts transcript and matching JPEG in either order |
| CH-5 selected event stills | Firmware-owned revision plus freestyle candidate implemented | VAD close, named semantic motion, and bounded freestyle-plan completion queue the existing controller snapshot path; the gateway receives rather than requests |
| CH-6 bounded continuation | Source complete | Audio, typed user perception, and returned action observations reuse the finite Robot Observer counter and recover prior intent by action ID |
| CH-7 JPEG ceiling | Source complete | Both maintained boundaries now accept one validated JPEG up to 256 KiB |
| CH-8 automated validation | Complete for firmware-owned revision | Portable C, protocol, focused adapter/media, gateway integration, final firmware build, and full A-series acceptance pass |
| CH-8 activation | Complete for firmware-owned revision | The old gateway process was stopped, the validated controller artifacts were flashed, and the gateway restarted from the matching receiver-only source |
| CH-8 physical acceptance | Pending for firmware-owned automatic triggers | Earlier explicit typed capture passed on installed hardware; automatic action proof requires a safe owner-issued motion and audio proof requires a microphone |

## Acceptance Criteria

- `what do you see`, `tell me what is in front of you`, and novel equivalent
  requests are not encoded as regular expressions or exact workflow phrases.
- With a ready camera, the local LLM can infer that current visual perception
  requires `captureImage`.
- Without a ready camera, the model receives truthful state and no camera
  action reaches the body.
- One robot utterance produces at most one fresh correlated still and one
  Environment cognition run.
- A camera timeout does not discard or indefinitely delay a valid utterance.
- One completed physical action produces one feedback observation containing
  its matching still when available.
- A returned image cannot attach to the wrong utterance, action, epoch, robot,
  or cycle.
- Periodic status, heartbeat, dashboard video, and speaker completion do not
  create uncontrolled image traffic or cognition loops.
- Automatic continuation is bounded and stops when there is no useful next
  semantic action.
- Continuous camera streaming remains off unless the owner explicitly enables
  the local dashboard preview.
- Firmware remains within its existing constrained-device queue and memory
  budgets; no JPEG is duplicated into routine control packets.
- The physical controller, gateway, Environment Bridge, and selected
  multimodal model pass the recorded installed-hardware end-to-end checks.
- The STT/image join passes bounded automated coverage; its physical
  microphone check remains explicitly deferred until that device is installed.

## Out of Scope

- Continuous video analysis.
- A snapshot attached to every WebSocket, heartbeat, status, PCM, or command
  packet.
- Raw servo output from an LLM.
- Cloud transport.
- Automatic TTS-completion snapshots.
- New sensor drivers; this pass provides the typed event policy they can use
  later.

## Progress Log

### 2026-07-23 - Architecture approved and hardening record opened

- Confirmed that the existing action-completion path already requests a
  correlated still.
- Confirmed that the current robot-audio path is VAD bounded but creates a
  text-only observation after STT.
- Confirmed that the current MetaHuman action parser contains exact
  natural-language phrase matching that conflicts with the owner decision.
- Confirmed that periodic robot status updates diagnostics without refreshing
  the cached Environment camera capability.
- Selected the gateway-owned, event-driven snapshot policy described above.
- Selected concurrent STT and image capture with a bounded correlation join.
- Rejected adding images to routine packets or enabling continuous LLM video.
- No implementation source was changed while establishing this document.

### 2026-07-23 - CH-1, CH-2, and CH-3 source milestone

- Added a bounded MetaHuman environment-state refresh that consumes the
  existing allowlisted `robot.status` telemetry and updates only the selected
  session's cached `cameraReady`, `visual`, and `captureImage` capability.
- The refresh does not publish an Environment observation and therefore does
  not enqueue an LLM run for periodic status.
- The Environment Bridge process also updates its in-memory source observation
  from the same status message, so a following robot utterance cannot reuse the
  initial stale `cameraReady: false` value.
- Removed deterministic natural-language command manufacturing from the
  Environment Action Parser. It now accepts only structured model actions,
  then applies current-turn authorization, advertised capability checks,
  semantic command-catalog checks, movement generation boundaries, and the
  existing physical-body safety gate.
- Removed English-keyword image selection from Environment Context Builder.
  Only a fresh event-correlated image is attached to model input; an
  uncorrelated image remains excluded even when the text appears visually
  phrased.
- Updated the Environment Context Router and model capability contract to
  describe the camera as the robot's visual sense and new sensor acquisition
  as an environment action, without enumerating example user phrases.
- Added a sensor-truth contract preventing claims of current sight or hearing
  from readiness metadata alone.
- Updated focused tests so selected robot commands come from structured model
  output and remain capability-gated rather than being manufactured from
  instruction text.
- Focused MetaHuman result: 12 tests passed across Environment compatibility,
  Robot Operator, bridge diagnostics, and audio transport.
- Graph result: all 25 cognitive graphs validated.
- Scoped `git diff --check` passed.
- No services were restarted in this milestone; the running MetaHuman process
  still uses the previously built source until the complete coherent batch is
  validated.

### 2026-07-23 - CH-4 and CH-5 correlated event milestone

- Reused the gateway's existing snapshot lock and camera command. No new
  firmware camera task, frame queue, continuous stream, or routine-packet image
  field was added.
- A completed VAD-bounded utterance is sent toward STT immediately. When the
  current body status reports `camera_ready: true`, the gateway concurrently
  requests one still and gives both media results the same `utteranceId`.
- Added a bounded MetaHuman audio/visual join with no more than two pending
  utterances and a five-second visual deadline. Transcript and JPEG may arrive
  in either order.
- A matching transcript and JPEG publish exactly one Environment observation.
  A timeout publishes text only, and a late correlated image is consumed
  without starting a second cognition run.
- The join rejects a mismatched session, robot, or epoch. It clears timers on
  disconnect and discards entries when STT returns no speech or fails.
- If the cached capability says the camera is unavailable, the transcript is
  marked ready to publish immediately rather than waiting through the visual
  deadline.
- VAD open, VAD close, and wake-word lifecycle messages no longer create
  separate cognition observations. VAD close still clears the diagnostic
  microphone meter.
- Added the optional `AINEKIO_SNAPSHOT_EVENT_NAMES` typed-event policy. It is
  empty by default. An explicitly selected future safety or sensor event
  receives one correlated still; routine events continue without a snapshot.
- Renamed the gateway helper from an action-specific name to
  `_request_correlated_snapshot` because actions, utterances, and selected
  typed events now share the same bounded mechanism.

### 2026-07-23 - CH-6 and CH-7 continuation and media-bound milestone

- Robot audio observations now start a user-originated
  `environment-perception` cycle using the existing Robot Operator graph and
  configured maximum-step bound instead of adding a second loop controller.
- A validated next step is attached to each queued semantic action. The
  gateway returns that metadata with terminal feedback and the post-action
  still so the next Environment execution can continue the same finite cycle.
- Corrected an existing instruction conflict that told every terminal result
  not to issue another action. Completed actions inside a validated perception
  cycle may now choose at most one useful next semantic action. Rejected,
  cancelled, expired, failed, non-cycle, and stop results remain terminal.
- The standalone Robot Observer enable switch gates only autonomous
  Robot-Observer work. It does not accidentally disable a user-triggered audio
  perception cycle. Owner autonomy policy, action capabilities, body
  authentication, action freshness, and the step ceiling still gate every
  continuation.
- Raised the MetaHuman image-input ceiling from 120 KiB to the Ainekio
  transport ceiling of 256 KiB. JPEG prefix, structure, and single-image
  validation remain in place; no resampling or aspect-ratio conversion was
  introduced.

### 2026-07-23 - Automated validation and firmware resource evidence

- Focused Ainekio Environment adapter result: 27 tests passed, including one
  utterance/one correlated still, VAD lifecycle suppression, and selected typed
  event correlation.
- Full Ainekio A-series acceptance result: 30/30 cases passed. Emulator,
  protocol, portable C, and dashboard browser gates all passed. The generated
  report is `build/acceptance/a-series.json`.
- ESP-IDF 5.5 firmware build completed. The application remains
  `0x158d00` bytes (1,412,352 bytes), matching the previously recorded flashed
  image, with `0x1a7300` bytes (55 percent) of the smallest app partition free.
- Camera hardening added no controller code and therefore no controller task,
  queue, stack, recurring diagnostic process, or flash growth. The current
  firmware image remains flash-ready; these host-side changes do not require a
  reflash.
- Focused MetaHuman result: 16 tests passed across audio transport, the new
  audio/visual join, Environment compatibility, bridge diagnostics, and Robot
  Operator continuation.
- MetaHuman architecture guardrail passed with zero current violations. All 25
  cognitive graphs validated.
- The MetaHuman production site bundle built successfully. Existing Svelte
  accessibility and bundle warnings remain outside this camera-hardening
  scope.
- A broad core typecheck still reports 56 pre-existing errors elsewhere in
  the dirty MetaHuman worktree; after correcting one inferred-array type in the
  readiness refresh, it reports zero errors in the camera-hardening files.
- The umbrella `pnpm build` reaches and passes architecture and graph
  validation, then stops in the unrelated TTS ownership guard because the
  current dirty `ChatInterface.svelte` contains three
  `playAdmittedTTSItem` occurrences while that guard expects two. Camera
  hardening does not alter the TTS subsystem.
- Scoped whitespace/diff checks pass in both repositories.

### 2026-07-23 - Live typed-camera test and context-preservation correction

- The owner tested the maintained physical path through MetaHuman OS because no
  microphone is currently installed on the robot. The local `qwen3.5:9b`
  model inferred a structured `captureImage` action from ordinary
  conversational language without an exact phrase rule.
- The controller returned real camera frames. MetaHuman correctly identified
  the blue furry subject, its eyes and red cheeks, the inverted orientation,
  and later the teal, pink, brown, red, white, and yellow regions in the wider
  scene. This proves semantic camera selection, physical capture transport, and
  multimodal model input on the typed path.
- The same live test exposed a remaining sequencing defect: a later capture
  presented the generic terminal instruction as a user turn and answered
  `Action completed` before the owner asked again for the image contents.
- A proposed command-specific replacement telling the model to describe an
  attached image was rejected because it would recreate the hard-coded
  language behavior this hardening pass removes.
- The correction keeps conversational context entirely inside MetaHuman. Each
  queued semantic action stores a bounded copy of the originating task in its
  existing coordinator work metadata. The robot and gateway receive no
  conversational memory; they continue to return only action identity,
  completion data, and one correlated still.
- When the correlated result returns, MetaHuman uses the action ID to recover
  the originating task from its own work record. Adapter-supplied instruction
  text is explicitly discarded, so an adapter cannot inject or replace the
  current task.
- A direct user-originated asynchronous action now reuses the existing finite
  Environment perception cycle. The configured three-step ceiling, semantic
  action allowlist, advertised capabilities, body-authentication gate, Active
  Operator policy, and stop behavior remain authoritative.
- Environment Instruction Interpreter now keeps completion feedback as result
  context while using the recovered originating request as the task. The
  command-specific Context Builder fallback `Describe what the robot sees...`
  was removed. The model therefore receives prior intent, structured
  completion, current state, and the correlated JPEG and must infer the
  appropriate response or next allowed semantic action.
- Direct capture feedback and its JPEG are coalesced into one gateway
  observation. MetaHuman suppresses duplicate feedback and retains a separately
  delivered result until an observation with the matching action ID arrives.
- Focused MetaHuman result after this correction: 20/20 tests passed across
  audio transport, the audio/visual join, feedback correlation, Environment
  compatibility, conversation ownership, diagnostics, and finite Robot
  Operator behavior.
- Focused gateway Environment adapter result: 27/27 tests passed, including a
  single observation carrying matching action feedback and visual metadata.
- MetaHuman architecture guardrail remains at zero violations; all 25
  cognitive graphs validate; scoped whitespace checks pass; and the production
  Astro server bundle rebuilt successfully. Existing unrelated Svelte
  accessibility and bundle warnings remain outside this subsystem.
- The typed camera path is the available hardware acceptance path today. The
  audio-plus-image acceptance case remains hardware-unavailable until a
  microphone is attached; absence of that device is not treated as a software
  failure.

### 2026-07-23 - Coordinated activation and final typed-camera acceptance

- MetaHuman OS and the physical gateway were stopped together. The gateway was
  started from the validated Ainekio source, then MetaHuman OS was started from
  the rebuilt production bundle so the server, Environment Bridge, and adapter
  used one coherent protocol version.
- A first post-restart request, `What do you see?`, caused the local model to
  produce one structured `captureImage` action. The gateway returned one
  correlated still and completion result, and the result execution immediately
  described the blue furry subject and its large eyes and pink cheeks. It did
  not emit the former generic `Action completed` response and did not request a
  second image.
- That first activation check exposed one presentation-only duplicate: the
  recovered originating request was correctly used as internal task context
  but was also appended to Conversation Buffer a second time. Environment
  observation execution now marks an instruction-only returned result as an
  already-admitted user request. This uses the existing Conversation Buffer
  ownership flag and adds no new persistence path.
- The focused MetaHuman suite was rerun after that correction and passed 20/20.
  The production bundle was rebuilt again and MetaHuman OS was restarted while
  the validated gateway remained running.
- The owner then issued `What do you see now?` against the final running
  bundle. The model inferred one `captureImage` action, the controller returned
  JPEG `ainekio-camera-13`, and MetaHuman described the fuzzy teal subject,
  large eyes, and pink cheeks without a generic terminal detour.
- The final result pass appended only the assistant response; it did not append
  another user entry. This verifies that prior intent remained internal task
  context rather than leaking into the visible conversation.
- The final JPEG was 30,249 bytes and carried the same action ID and
  correlation ID as its bounded three-step Environment perception cycle.
  Request receipt to final visual answer was about 9.1 seconds, including two
  local `qwen3.5:9b` inference passes; the physical snap command and camera
  frame arrived within the same logged second.
- Final live state records `ainekio-01` connected and authenticated, camera
  ready, `captureImage` advertised, motion available, and heartbeat age
  842 ms. Five-second status messages continued after the captures.
- Media logging shows discrete `snap`, `cam_meta`, and one JPEG media-frame
  event per requested capture, followed only by status messages. This is
  evidence that continuous preview streaming was not activated by the
  cognition path.
- No controller source changed in this hardening batch, the previously built
  firmware image remains flash-ready, and no controller reflash was required.
- The completion audit reran the current full A-series suite and restored an
  authoritative 30/30 pass across emulator, protocol, portable C, and dashboard
  browser gates. An immediately preceding sandboxed invocation was invalid
  because local socket creation was denied with `EPERM`; its failed report was
  replaced by the successful host run.
- No firmware source, header, build file, `sdkconfig`, or defaults file is newer
  than `build/ainekio_slave_brain.bin`. The current 1,412,352-byte controller
  image therefore still corresponds to the validated source and remains the
  flash-ready artifact.

### 2026-07-23 - Firmware-owned snapshot-trigger revision

- The owner revised automatic snapshot ownership after reviewing the live
  gateway round trip. The controller now originates the still at the local
  event boundary; the gateway receives, validates, correlates, and forwards it.
  This supersedes the earlier gateway-owned automatic snapshot mechanism
  recorded above without erasing that historical implementation trail.
- Reused `ainekio_camera_snapshot`, the existing four-entry camera command
  queue, camera task, single PSRAM framebuffer, and bounded outgoing JPEG copy.
  No second camera service, periodic process, continuous capture mode, or
  additional image buffer was added.
- Added compact protocol-v1-compatible `origin` and `origin_id` fields to
  snapshot `cam_meta`. Explicit requests use `request` plus their command
  sequence, completed semantic motion uses `action` plus its command sequence,
  and a completed VAD utterance uses `audio` plus a controller-generated
  microphone counter.
- VAD open and close repeat the same `origin_id`. Both boundaries use the
  existing microphone transmit queue, so VAD close cannot overtake the final
  queued PCM frames. Once the close boundary is queued, the controller starts
  the snapshot asynchronously; camera transfer remains lower priority than
  queued microphone frames.
- A completed motion queues the snapshot instead of immediately queuing
  `done`. The existing camera transmitter sends `cam_meta`, then JPEG, then
  `done`. If the camera is absent, busy, or cannot allocate its existing
  outgoing copy, the motion still reports `done`; visual failure cannot turn
  already completed motion into failure. Explicit `captureImage` retains its
  existing failure behavior.
- Speaker/TTS completion remains terminal without an automatic perception
  image. This preserves the existing protection against response, image,
  response loops.
- Removed gateway-generated post-action, post-utterance, and configurable
  typed-event snapshot commands. The adapter now keeps only bounded numeric
  action/frame correlation maps and accepts the controller-originated metadata.
  Future sensor snapshots must originate from a typed controller event rather
  than an English phrase or gateway environment variable.
- Updated the emulator to reproduce JPEG-before-`done` motion completion and
  VAD-close snapshots. Updated the shared C encoder, Python validator, JSON
  schema, fixtures, protocol documentation, firmware documentation, gateway
  documentation, and focused tests as one coordinated wire-contract change.
- Initial focused evidence: the portable C control encoder passes, the nine
  protocol contract tests pass, and 39 gateway adapter plus body-media tests
  pass.
- Final host-side evidence: 24 gateway service and WebSocket integration tests
  pass, and the full A-series acceptance report passes 30/30 across emulator,
  protocol, portable C, and dashboard browser gates. The authoritative report
  is `build/acceptance/a-series.json`, generated
  `2026-07-23T23:22:48.591359+00:00`.
- The final controller application is 1,413,024 bytes (`0x158fa0`), an increase
  of 672 bytes over the previously flashed 1,412,352-byte image. The smallest
  application partition retains 1,732,704 bytes (`0x1a7060`), or 55 percent,
  free.
- ESP-IDF size evidence reports 171,707 bytes of DIRAM use, only 8 bytes more
  than the previously recorded build, with 170,053 bytes remaining. The
  utterance state is fixed-size; the slightly wider existing microphone queue
  items remain in PSRAM.
- Source and build checks confirm no new task, queue, stack, framebuffer,
  image-copy path, camera service, timer, or recurring polling process.
  Activation, controller flash, and physical verification are recorded below.

### 2026-07-23 - Firmware-owned revision flash and activation

- Stopped the previously running physical gateway before flashing so the new
  controller could not interact with the superseded gateway-owned automatic
  snapshot behavior.
- Flashed the bootloader, partition table, initial OTA selection, application,
  and LittleFS artifacts to the connected ESP32-S3 on `/dev/ttyACM0`. Esptool
  verified every region during the write and hard-reset the controller.
- A post-boot verification matched the bootloader, 1,413,024-byte application,
  partition table, and 10,354,688-byte LittleFS images byte for byte. The
  bootloader-managed OTA metadata no longer matched its initial image after
  first boot because slot selection updates that writable sector; its original
  write had already passed digest verification.
- Restarted the gateway from the revised receiver-only source. The controller
  connected as `ainekio-01`, emitted `boot`, and continued five-second status
  traffic. It also emitted the existing `sd_fail` hardware event because no
  usable SD card is present; this is unrelated to camera correlation.
- A live socket check confirms both required gateway peers: the robot has an
  established LAN connection to port 8790 and the MetaHuman Environment Bridge
  has an established local connection to the same gateway.
- No physical movement was issued during activation. A real automatic
  motion-completion still should be verified only with the owner supervising a
  safe motion. A real VAD-close still remains hardware-blocked until a
  microphone is attached.

### 2026-07-23 - Freestyle completion and gateway lifecycle follow-up

- Reviewed the supplied independent audit against current source. The blocking
  camera delivery, epoch-insufficient correlation, unbounded deferred visuals,
  PSRAM peak uncertainty, incomplete physical acceptance, and missing clean
  commit boundary were all accurately described.
- Implemented physical `motion_plan_v1` execution in the current candidate
  source. The body advertises the feature only in a physical-motion build,
  validates the existing 1..32 frame and 10-second contract, copies it into the
  motion service's existing prepared asset buffer, and executes it on the
  existing motion task with current calibration, range, stop, and failsafe
  gates. No raw PWM, GPIO, calibration write, new motion task, queue, or plan
  buffer was added.
- A successful freestyle plan reaches the existing `motion_done` callback.
  The controller therefore emits action-correlated `cam_meta`, one XGA JPEG,
  and only then `done`, exactly like a completed walk. Cancellation, rejection,
  stop, or execution failure produces no completion still.
- Removed camera encoding and Environment WebSocket delivery from the robot
  receive callback. Correlated JPEGs now enter one bounded host-side delivery
  slot, and bridge sends have a two-second ceiling. Action completion waits only
  when its frame has actually arrived; camera failure does not introduce a
  blind two-second delay.
- Changed action and camera correlation keys from bare sequence/counter values
  to `(robot_id, epoch, sequence)` and `(robot_id, epoch, counter)`. Connection
  changes remove stale correlations, so a rebooted counter cannot inherit an
  image context from the previous body epoch.
- Replaced the unrestricted deferred-image dictionary with at most 32 pending
  action futures. Each action removes its future on completion, rejection,
  timeout, or cancellation, and a late image is discarded rather than retained
  or attached to newer work.
- The outgoing controller queue remains two entries, but a full queue now
  evicts and frees its oldest JPEG before allocating the incoming copy. The
  theoretical transient copy ceiling falls from three 256-KiB copies
  (approximately 768 KiB) to two (approximately 512 KiB), plus the existing
  camera driver framebuffer. Actual physical fragmentation/minimum-free-PSRAM
  evidence remains an activation measurement rather than a proven result.
- Focused validation currently passes: 13/13 protocol tests, all 11 portable C
  targets, 43/43 adapter/media tests including freestyle JPEG-before-`done`,
  epoch-reconnect rejection, bounded queueing, and late-image discard, plus
  24/24 gateway/WebSocket integration tests. The final full A-series runner
  passes 30/30 across emulator, protocol, portable C, and dashboard-browser
  gates. A preceding sandbox-denied run was invalid and its overwritten report
  was immediately replaced by this successful host-capable run.
- The application is 1,413,536 bytes (`0x1591a0`), 512 bytes larger than the
  preceding firmware-owned snapshot image. DIRAM remains unchanged at 171,707
  bytes with 170,053 bytes free, and the 3-MiB application partition retains 55
  percent headroom.
- At the close of this implementation pass the matching gateway and firmware
  image had not yet been activated. The subsequent owner-approved activation is
  recorded below. The worktree remains uncommitted because no commit or push
  was requested.

### 2026-07-23 - Freestyle/lifecycle revision flash and activation

- Reconfirmed the connected serial device, exact candidate artifact hashes,
  clean `git diff --check`, and the passing A-series 30/30 acceptance report
  before touching the controller.
- Stopped the older in-memory physical gateway before flashing. The first
  unprivileged serial-open attempt was denied before erase or write because the
  login session did not have `dialout` access; the exact validated command was
  then run with owner-authorized device privileges.
- Flashed the bootloader, 1,413,536-byte application, partition table, initial
  OTA selector, and 10,354,688-byte LittleFS image. Esptool verified the digest
  of every region during the write and hard-reset the ESP32-S3.
- Independent post-boot readback matched the bootloader, application, partition
  table, and LittleFS digests exactly. The initial OTA-selector image is not a
  post-boot immutable region because the bootloader updates slot state there;
  its write-time digest check passed.
- The serial boot record confirmed the expected application build, successful
  8-MiB PSRAM test, and eight servo-channel initialization. UART output becomes
  unreadable when the display takes ownership of shared GPIO43; this is the
  documented MAP_B OLED/UART handoff rather than evidence of a runtime crash.
- Restarted the physical gateway from the matching revised source. The local
  MetaHuman Environment Bridge reconnected, then `ainekio-01` connected from
  `192.168.0.84`, emitted a fresh `boot` event, reported the expected existing
  `sd_fail` condition, and resumed five-second status traffic.
- No servo movement or freestyle plan was issued during activation. Physical
  transition behavior, stop preemption, completion JPEG delivery, and
  minimum-free/fragmentation PSRAM evidence remain owner-supervised acceptance
  work. Microphone/VAD acceptance remains hardware-blocked.

### 2026-07-23 - Duplicate same-cycle capture root fix

- Reproduced the owner-reported three-message sequence from persisted runtime
  evidence. One typed request produced two physical `snap` commands and then a
  third camera proposal was stopped by the existing three-step interaction
  ceiling.
- The controller and gateway each handled the commands correctly. The duplicate
  originated in MetaHuman: after the first correlated JPEG returned, the
  automatic continuation reused the original capture imperative and continued
  advertising `captureImage`, causing the local model to request the same
  acquisition again.
- Added one shared bounded-JPEG and cycle-correlation check at the MetaHuman
  environment boundary. A continuation with a valid image correlated to its
  active cycle now treats visual acquisition as complete, presents the original
  user goal as context, and removes `captureImage` from that continuation's
  available actions.
- Added a final same-cycle dispatch invariant. If a model nevertheless emits
  another `captureImage` after the correlated frame has arrived, no command is
  sent and the bridge record explicitly reports
  `capture_already_satisfied` with the suppressed action. The conversational
  image analysis is preserved rather than replaced with another fixed
  "Camera request queued" response.
- The rule is correlation-based, not phrase-based. A later explicit user
  request for another photograph starts a new interaction and remains allowed.
  The three-step safety ceiling remains unchanged as a last-resort guard.
- Focused regression evidence passes: the returned correlated image produces
  zero additional camera tasks, an explicit retake produces exactly one task,
  the Environment Bridge coordinator suite passes, the provider multimodal
  suite passes, and adjacent Robot Operator and environment diagnostics suites
  pass. `git diff --check` also passes for the affected MetaHuman files.
- The repository-wide MetaHuman core typecheck remains blocked by existing
  errors in unrelated agent, cognitive-layer, connector, encryption, and other
  modules; none of its reported errors reference the changed environment or
  camera files.
- This revision changes MetaHuman orchestration only. It adds no firmware task,
  buffer, timer, camera operation, or gateway round trip, and it requires no
  controller flash.
- Rebuilt the MetaHuman production bundle and restarted it through the
  repository stop/start scripts. The installed server bundle contains both the
  completion instruction and `capture_already_satisfied` dispatch result,
  returned HTTP 200 on the local interface, and re-established one active
  Environment Bridge subscriber/session without issuing a robot action.

### 2026-07-23 - XGA WebSocket transport stability investigation

- Reproduced the physical disconnect at the controller/gateway boundary. A
  failed capture consistently emitted `cam_meta`, then closed the body
  WebSocket with code 1006 before a JPEG media frame or `done` reached the
  gateway. This proves the later MetaHuman offline responses were consequences
  of the body transport loss, not duplicate camera inference or a text/image
  collision.
- Removed the controller's outer manual partial/continuation loop. The pinned
  ESP WebSocket client already fragments a binary message across its configured
  4-KiB transmit buffer while retaining its own transmit lock and message
  state. The controller now gives one complete bounded JPEG to that existing
  API instead of repeatedly releasing and reacquiring the client around each
  fragment.
- Physical acceptance showed that framing correction alone was insufficient.
  A 1,000-ms camera write window was shorter than the physical build's
  1,500-ms TCP retransmission interval. A 3,000-ms candidate improved delivery
  and later completed five consecutive XGA frames in epoch 4, counters 7
  through 11, but one earlier capture on that same candidate still timed out.
  That failure is retained here rather than being hidden by the later passing
  sequence.
- Host socket evidence showed the robot link operating with a two-packet
  congestion window, repeated retransmissions, and roughly 100-200-ms TCP RTT
  despite controller telemetry reporting `-50` to `-51 dBm`. A direct ICMP
  check after an intermediate flash returned only one of two robot packets and that
  reply took 1,111 ms. In the same interval the gateway computer reached the
  local router six of six times in 3-6 ms. The impaired link is therefore
  specific to the robot side; plain PLA is not an RF shield, but antenna
  clearance, orientation, nearby battery/wiring/metal, or local 2.4-GHz
  interference remains a physical variable.
- The final bounded camera-write window is 6,000 ms, covering the initial
  1,500-ms TCP retry and its first backoff interval. This does not keep the
  camera active, add a retry task, enlarge a queue or framebuffer, or allocate
  RAM. Stop and receive processing retain their existing tasks; only an
  already-started still-image write is allowed more time to recover.
- A rapid one-second-spacing stress run then delivered all five JPEGs before
  the session closed. That moved the remaining fault beyond the binary
  payload: the small post-image `done` frame still used a 250-ms control-write
  budget, six times shorter than the configured TCP retransmission interval.
  The ESP client aborts its socket when that transport write expires even
  though the application correctly records the failed control send.
- Increased the existing control header/payload write budget to 1,900 ms. This
  permits one TCP retransmission while the compile-time bound proves the
  external ownership lock plus both WebSocket writes still fit below the
  unchanged four-second motion-stale safety cutoff. No control retry loop,
  delayed-work item, task, queue, or timer was added.
- The final application is 1,413,360 bytes, 176 bytes smaller than the
  previously installed freestyle/lifecycle image. The 3-MiB application
  partition retains 1,732,368 bytes (`0x1a6f10`), or 55 percent, free. The
  latest ESP-IDF size report remains 171,707 bytes of DIRAM use with 170,053
  bytes available.
- Full A-series acceptance passes 30/30 for the final source across emulator,
  protocol, portable C, and dashboard-browser gates. `git diff --check` also
  passes.
- Flashed only the final application partition at `0x020000`; esptool verified
  all 1,413,360 bytes against SHA-256
  `a742f3cef78396c24b7baa8ddb763221b9f010a510a29bd837b988e731927790`
  and hard-reset the controller. Bootloader, partition table, OTA selector,
  NVS, and LittleFS were not rewritten in this pass.
- Final post-flash acceptance passed. Five XGA snapshots spaced five seconds
  apart produced counters 0 through 4, each 32,510 to 32,654 bytes, in epoch 1.
  Status traffic continued after the fifth frame with no disconnect or epoch
  change. Final live state reports RSSI `-42 dBm`, 8,172,264 bytes free heap,
  camera ready, zero camera drops, and heartbeat age 694 ms. The case-open
  check remains a useful physical diagnostic if the previously measured
  robot-specific packet loss returns, but it did not block this final soak.

### Remaining hardware-dependent acceptance

- No microphone is attached to the body. A real VAD-bounded utterance, STT
  transcript, and matching XGA JPEG cannot be physically exercised until that
  hardware exists.
- When a microphone is installed, record utterance-to-observation latency,
  transcript result, JPEG bytes, timeout behavior, and final connection state.
  The bounded join, no-camera timeout, mismatch rejection, and no-speech paths
  are covered by the automated MetaHuman suite meanwhile.

### Completion audit

| Requirement | Final evidence |
| --- | --- |
| CH-1 truthful capability | Final live state reports the authenticated body, `cameraReady: true`, `captureImage`, and heartbeat age 694 ms; periodic five-second status remains telemetry-only |
| CH-2 no phrase manufacturing | Maintained Environment action sources contain no `what do you see`, `tell me what`, photo, snapshot, or camera-request matcher; final novel typed requests produced structured model actions |
| CH-3 semantic embodiment | The local model inferred `captureImage` and waited for a correlated frame before describing the physical scene |
| CH-4 utterance/still join | Audio/visual tests prove either arrival order, text-only timeout, wrong-robot rejection, bounded pending work, and one observation; physical microphone check is the one recorded hardware deferral |
| CH-5 selected event stills | Firmware and emulator queue one still on VAD close, completed named motion, and completed bounded freestyle plans; current focused adapter/media result is 43/43 and gateway integration is 24/24 |
| CH-6 bounded continuation | Returned state carried the same cycle/action correlation, step 2 of the configured 3-step ceiling, and the originating request recovered locally by action ID; the model stopped after its useful visual response |
| CH-7 JPEG ceiling | MetaHuman validates one structured JPEG through 256 KiB and rejects an oversized payload; controlled physical XGA stills were 28,101 to 37,650 bytes |
| CH-8 validation | Current candidate passes A-series 30/30, portable C 11/11, protocol 13/13, adapter/media 43/43, and gateway integration 24/24 |
| CH-8 activation | The final 1,413,360-byte application is flashed and verifies exactly; the matching receiver-only gateway is running; five post-flash XGA captures passed in one epoch with continued status traffic |
| Constrained-device efficiency | Freestyle and the transport correction reuse the existing motion task, camera path, WebSocket client, and buffers; no firmware task, queue, stack, plan buffer, or framebuffer was added; installed application size is 1,413,360 bytes (-176 versus the preceding image), DIRAM remains 171,707 bytes, and the app partition retains 55 percent headroom |
| Safety boundary | Semantic capability checks, body authentication, action freshness, Active Operator policy, stop handling, finite continuation, and raw-servo rejection remain in force |

### Installed artifact identity

The controller's application partition now contains the 1,413,360-byte image
with SHA-256
`a742f3cef78396c24b7baa8ddb763221b9f010a510a29bd837b988e731927790`.
That application passed both write-time verification and a separate
`verify_flash` comparison. The other four artifacts below are unchanged from
the preceding full flash and its recorded verification.

| Address | Artifact | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `0x000000` | `build/bootloader/bootloader.bin` | 20,912 | `5b21be18c46ade9cc6557d8201031bf8189161fc1cc0c8ef0a1699157b9774ad` |
| `0x008000` | `build/partition_table/partition-table.bin` | 3,072 | `91b86c339a5e1f2410e4a62f5b8f44f200eafccd2286288ac42e49cff06c7aad` |
| `0x01a000` | `build/ota_data_initial.bin` | 8,192 | `7d2c7ac4888bfd75cd5f56e8d61f69595121183afc81556c876732fd3782c62f` |
| `0x020000` | `build/ainekio_slave_brain.bin` | 1,413,360 | `a742f3cef78396c24b7baa8ddb763221b9f010a510a29bd837b988e731927790` |
| `0x620000` | `build/littlefs.bin` | 10,354,688 | `cc48c77e3bfaedb49ca3c2629791fa1ef85cf82f9666d3f34ec37ef3966d1965` |
