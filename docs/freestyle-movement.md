# Freestyle Movement

Status: emulator milestone complete; ESP32-S3 execution not advertised
Owner decision: approved direction
Specification status: post-v1.0 extension pending numbered consolidation before
physical enablement
Updated: 2026-07-21

This file is the implementation plan and progress ledger for bounded, AI-generated
movement on Ainekio. Update the progress section after every implementation or
validation pass. Do not mark physical behavior complete from emulator evidence.

## Decision

Ainekio will support AI-generated movement through a new normal-mode motion-plan
command. It will not keep calibration mode enabled, expose calibration writes to
MetaHuman, or allow an LLM to stream individual servo commands.

The LLM may propose a complete, time-indexed eight-joint trajectory. Ainekio owns
conversion, validation, scheduling, stop behavior, and the final decision to
execute. The complete plan must be accepted or rejected before any servo moves.

## Goals

- Let MetaHuman generate useful movements that are not limited to installed
  `walk`, `wave`, and other named motion assets.
- Keep the existing semantic-command path intact for ordinary movement.
- Use logical joint angles; never expose GPIO numbers, PWM pulse widths, servo
  centers, inversion, or physical calibration to the model.
- Validate the complete trajectory at the body boundary before execution.
- Make `stop` immediately preempt generated movement.
- Return correlated `ack`, `done`, `cancelled`, or `nak` lifecycle messages.
- Exercise the same contract in fixtures, the portable core, emulator, gateway,
  ESP32-S3 firmware, MetaHuman, and diagnostics.
- Let an owner send an off-script movement request through the MetaHuman
  Environment Mode interface and see the generated movement execute in the
  Ainekio emulator with correlated lifecycle feedback.
- Allow successful generated movements to be reviewed for later promotion into
  named `.amot` assets without automatically persisting model output.

## Non-Goals

- Permanently enabling calibration mode.
- Giving the LLM access to `servo`, `limits`, `pose_save`, or `cal_save`.
- Sending eight unrelated servo messages as one movement.
- Letting the model assign command sequence numbers.
- Writing learned movement directly to firmware, NVS, LittleFS, or the repository.
- Claiming physical joint-position feedback from the current three-wire MG90S
  servos. The body can report commanded progress, not measured joint position.
- Replacing the existing named motion assets or semantic safety path.

## Confirmed Baseline

- Control commands are one JSON object per WebSocket text frame and are bounded
  by `AINEKIO_CONTROL_MAX_BYTES` at 4096 bytes.
- The body owns eight logical joints: `0=R1`, `1=R2`, `2=L1`, `3=L2`, `4=R4`,
  `5=R3`, `6=L3`, and `7=L4`.
- Stored `.amot` assets already contain bounded timed frames, logical targets,
  repeat counts, return poses, checksums, and calibration-limit validation.
- Stored assets support at most 256 frames, but that limit is too large for a
  live model-generated control message.
- The firmware motion service already interpolates logical targets, applies the
  calibrated mapping, and owns stop/failsafe behavior.
- The existing `servo` command is calibration-only. The portable core rejects it
  in normal mode, and MetaHuman does not advertise it.
- The Environment Bridge advertises and accepts only body-owned semantic robot
  commands today.
- The gateway assigns monotonic session sequence numbers and rejects stale work.

## Ownership Boundary

```text
MetaHuman model
  proposes one robotMotionPlan action
        |
MetaHuman coordinator
  validates model-facing structure, session, capability, and policy
        |
Environment Bridge
  relays one bounded action; never emits raw calibration commands
        |
Ainekio environment adapter
  converts degrees to compact centidegrees and rejects unsupported plans
        |
Ainekio gateway
  assigns seq, validates protocol-v1, tracks ack/done/cancelled/nak
        |
Portable body core and motion service
  validate the complete plan, then schedule it atomically
        |
Calibrated logical joint map
  converts approved targets to physical servo output
```

MetaHuman owns intent generation. Ainekio owns motion authority. Firmware remains
the final authority even when every upstream validator accepted a plan.

## Environment Mode Workflow

The maintained MetaHuman workflow is
`/home/greggles/metahuman/etc/cognitive-graphs/environment-mode.json`. Its current
movement path is:

```text
Environment Observation
  -> Environment Instruction Interpreter
  -> Environment Context Builder
  -> Environment LLM
  -> Thinking Stripper
  -> Environment Action Parser
  -> Environment Bridge Out
```

Freestyle movement uses one explicit generation branch without replacing the
existing semantic-action branch:

```text
Environment LLM
  -> Environment Action Parser / movement request routing
       | known body command such as walk, bow, wave, or stop
       |   -> Environment Bridge Out
       |
       | off-script movement request and robotMotionPlan is available
       |   -> Movement Generator
       |   -> typed robotMotionPlan action
       |   -> Environment Bridge Out
       |
       | off-script request but capability disabled or unavailable
           -> visible rejection; no movement action
```

The graph node is named **Movement Generator** and uses the node type
`movement_generator`. It receives the interpreted movement request, original
instruction, relevant observation state, connected-body capabilities, logical
joint catalog, current commanded pose when available, and the frozen motion-plan
limits. It returns either:

- one typed `robotMotionPlan` candidate and a short user-facing summary; or
- a structured rejection with no executable action.

The node's instructions require JSON matching the bounded action contract. It
cannot output calibration changes, GPIO numbers, PWM values, raw Ainekio protocol
messages, persistence instructions, or individual direct-servo commands.

Routing must be deliberate and structured. The primary Environment LLM marks an
off-script request as a movement-generation request when no advertised semantic
command represents the requested behavior. Phrase matching or a hard-coded list
of user sentences must not decide the route. Known semantic commands continue to
bypass Movement Generator, and a body that does not advertise
`robotMotionPlan` cannot enter the generation branch.

Movement Generator proposes motion; it does not authorize execution. MetaHuman
normalizes the generated action, and Ainekio performs the final complete-plan
validation, sequence assignment, queueing, stop handling, and lifecycle reporting.

## Capability Negotiation

Older bodies must never receive a command type they cannot decode.

1. Extend the body `hello` message with an optional bounded feature list such as
   `"features":["motion_plan_v1"]`.
2. Preserve the connected body's features in `GatewayConnection` state.
3. Advertise `robotMotionPlan` in the environment observation only when:
   - the connected body reports `motion_plan_v1`;
   - the gateway and adapter support the same version; and
   - the owner-controlled freestyle policy is enabled.
4. Keep physical execution unavailable until the physical body explicitly
   advertises `motion_plan_v1` after bring-up.
5. Keep the adapter policy enabled by default. A maintenance launch may
   explicitly set `AINEKIO_FREESTYLE_ENABLED=0` without changing body support.

Capability absence must produce an explicit unsupported/rejected result. It must
not fall back to calibration or decompose the request into servo commands.

## Implemented MetaHuman Action

The model-facing action favors readable logical degrees and named fields:

```json
{
  "type": "robotMotionPlan",
  "sessionId": "ainekio-sim-1",
  "frames": [
    {
      "durationMs": 300,
      "targets": [
        {"joint": "R1", "degrees": 95.0},
        {"joint": "R2", "degrees": 85.0},
        {"joint": "L1", "degrees": 90.0},
        {"joint": "L2", "degrees": 90.0},
        {"joint": "R4", "degrees": 80.0},
        {"joint": "R3", "degrees": 100.0},
        {"joint": "L3", "degrees": 90.0},
        {"joint": "L4", "degrees": 90.0}
      ]
    }
  ],
  "endPose": "hold"
}
```

The model does not provide `seq`, calibration, GPIO, pulse width, or a persistence
flag. Unknown fields are removed before the plan crosses into Ainekio.

## Implemented Body Command

The adapter converts the readable action into a compact protocol message. Angles
are unsigned integer centidegrees from 0 to 180 degrees to match the existing
logical joint model and avoid floating-point ambiguity on the wire. Because every
frame contains all eight joints, `map: 1` fixes their positional order as
`R1, R2, L1, L2, R4, R3, L3, L4`:

```json
{
  "t": "motion_plan",
  "seq": 42,
  "map": 1,
  "frames": [
    [300, [9500, 8500, 9000, 9000, 8000, 10000, 9000, 9000]]
  ],
  "end": "hold"
}
```

A 32-frame command with all eight integer targets per frame is approximately
2.1 KiB before WebSocket framing, within the existing 4096-byte control limit.
The schema, bounds, and maximum encoded size are locked by the shared fixtures.
The portable core can decode and safety-gate the command, but the ESP32-S3
runtime does not advertise `motion_plan_v1` or dispatch the plan to physical
motion.

## Initial Motion-Plan Limits

These are the initial contract bounds. Physical limits remain authoritative and
may tighten them after hardware measurements.

- 1 to 32 frames.
- Exactly eight unique known joints in every frame.
- Integer centidegree targets from 0 to 18000 after adapter conversion.
- 100 to 5000 ms per frame for initial physical use.
- Maximum 10 seconds total planned duration.
- One execution only; generated plans cannot repeat in the first release.
- End behavior is one of `hold`, `stand`, or `neutral`.
- One active plan and no pending replacement plan.
- Existing gateway freshness limit applies before sequence assignment.
- Existing calibration ranges apply to every target.
- A separately configured maximum delta, velocity, and acceleration applies to
  every joint transition. These values require physical bring-up evidence and
  must not be invented from the model output.
- The first frame must be reachable from the body's last commanded pose under
  the same transition limits.

The complete plan is rejected if any frame, target, transition, duration, end
behavior, state, or power check fails. Validation never clamps model targets into
something different and then proceeds silently.

## Runtime Safety Rules

- `motion_plan` is a normal-mode command. Calibration mode remains maintenance
  only and is never a prerequisite for freestyle movement.
- `stop` cancels the active plan, detaches or holds servos according to the
  existing stop policy, and prevents remaining frames from executing.
- Boot readiness, power guard, body state, profile, motion-busy state, calibrated
  ranges, and queue capacity are checked before acceptance.
- The body sends `ack` only after the entire trajectory is decoded and validated.
- Any execution-time failure produces a terminal result and safe stop behavior.
- Disconnect, stale session, sequence exhaustion, low voltage, or failsafe state
  prevents new execution.
- Generated movement cannot modify calibration, saved poses, or named assets.
- Logs and diagnostics store metadata and bounded plan summaries, not an
  unbounded history of model-generated movement.

## Learning and Promotion

Freestyle execution and durable learning are separate operations.

1. Generate a one-shot plan.
2. Validate it without moving.
3. Execute it in the emulator.
4. Return terminal feedback and diagnostic evidence to MetaHuman.
5. When physical freestyle is enabled, begin with the existing reduced-range,
   conservative-speed hardware profile and a supported robot.
6. Let the owner review successful plans.
7. Promote an approved plan through the existing motion-asset compiler into a
   named, checksummed `.amot` asset.
8. Install that asset through the normal firmware/asset process.

Automatic promotion is deferred. The LLM may recommend that a plan be saved, but
only an owner-approved tool may create or install a durable asset.

## Implementation Phases

### Phase 0: Contract and ownership freeze

- Confirm the architecture and limits in this file.
- Confirm names: MetaHuman `robotMotionPlan`, protocol `motion_plan`, feature
  `motion_plan_v1`.
- Decide the owner-facing enable policy and physical default.
- Confirm initial transition limits after hardware bring-up evidence exists.

Acceptance: the owner approves the frozen contract before runtime code changes.

### Phase 1: Language-neutral protocol and fixtures

Files:

- `Slave/software/protocol/schemas/control-v1.schema.json`
- `Slave/software/protocol/fixtures/control-valid-v1.json`
- `Slave/software/protocol/fixtures/control-invalid-v1.json`
- `Slave/software/protocol/control_v1.py`
- `Slave/software/tests/protocol/`

Work:

- Add optional feature negotiation to `hello`.
- Add `motion_plan` and its exact bounds.
- Add valid boundary fixtures and invalid cases for size, count, duplicate/missing
  joints, range, duration, total duration, end behavior, and malformed nesting.
- Prove maximum valid encoding remains at or below 4096 bytes.

Acceptance: host protocol tests pass and every invalid fixture is rejected before
any runtime layer sees it.

### Phase 2: Portable core and codec

Files:

- `Slave/software/core/include/ainekio/protocol.h`
- `Slave/software/core/include/ainekio/control_codec.h`
- `Slave/software/core/src/control_codec.c`
- `Slave/software/core/src/core.c`
- `Slave/software/core/tests/`

Work:

- Add fixed-size plan/frame structures with no safety-path heap allocation.
- Decode the complete command into bounded storage.
- Add normal-mode acceptance, power and busy gates, lifecycle behavior, and stop
  preemption.
- Reject calibration-only reuse.

Acceptance: native portable-core tests cover acceptance, every rejection reason,
stale sequences, stop, disconnect/failsafe, and no partial state mutation.

### Phase 3: Motion service and emulator

Files:

- `Slave/firmware/esp32s3/components/ainekio_platform/src/motion_service.c`
- `Emulator/emulator/body/session.py`
- `Emulator/emulator/body/core.py`
- `Emulator/emulator/backends/sesame.py`
- `Emulator/tests/`

Work:

- Convert an accepted plan to the existing interpolation/scheduling model.
- Validate all transitions before scheduling the first frame.
- Keep one active plan and deterministic end behavior.
- Add headless completion and renderer-correlated emulator coverage.

Acceptance: emulator and portable firmware logic produce matching commanded joint
frames and terminal lifecycle for the same fixtures.

### Phase 4: Gateway and Ainekio environment adapter

Files:

- `Master/gateway/server/service.py`
- `Master/gateway/environment_adapter/translation.py`
- `Master/gateway/environment_adapter/server.py`
- `Emulator/tests/test_gateway_service.py`
- `Emulator/tests/test_environment_adapter.py`

Work:

- Preserve connected-body feature negotiation.
- Add a bounded `queue_motion_plan` gateway method.
- Translate only the approved `robotMotionPlan` shape.
- Convert joint labels/degrees to ids/centidegrees.
- Advertise the capability only when body support and owner policy are both true.
- Return explicit rejection and terminal feedback.

Acceptance: no unsupported body receives the new command, and no raw servo or
calibration action becomes reachable from the environment bridge.

### Phase 5: MetaHuman contract and Environment Mode

Files in `/home/greggles/metahuman`:

- `etc/cognitive-graphs/environment-mode.json`
- `packages/core/src/environment-interface/types.ts`
- `packages/core/src/environment-interface/store.ts`
- `packages/core/src/nodes/environment/helpers.ts`
- `packages/core/src/nodes/environment/action-parser.node.ts`
- `packages/core/src/nodes/environment/movement-generator.node.ts`
- `packages/core/src/nodes/environment/send-action.node.ts`
- `packages/core/src/nodes/environment/index.ts`
- `packages/core/src/nodes/schemas.ts`
- `brain/agents/environment-bridge/core.ts`
- focused environment-interface and bridge tests

Work:

- Add the typed action and bounded normalization.
- Expose the action to the model only when the observation advertises it.
- Add the `movement_generator` node with dedicated instructions and structured
  inputs and outputs; do not reuse the general Environment LLM prompt as the
  motion contract.
- Extend the Environment Action Parser contract so it distinguishes an existing
  semantic action from a structured off-script movement request.
- Wire `environment-mode.json` so known actions keep the existing direct path,
  while eligible off-script requests pass through Movement Generator and then
  rejoin the existing Environment Bridge Out path.
- Require structured frames; reject prose, raw servo fields, simulator commands,
  and unknown metadata.
- Keep ordinary semantic commands as the preferred path for known behaviors.
- Preserve task correlation through the action stream.

Acceptance: malformed model output cannot reach Ainekio, capability absence hides
the generation route, known semantic commands bypass Movement Generator, an
off-script request produces one bounded `robotMotionPlan`, and existing semantic
action tests remain unchanged.

### Phase 6: ESP32-S3 integration

Files:

- `Slave/firmware/esp32s3/components/ainekio_platform/src/runtime_service.c`
- `Slave/firmware/esp32s3/components/ainekio_platform/src/motion_service.c`
- associated platform headers and firmware tests

Work:

- Integrate fixed-size decoded plans into the existing motion task.
- Validate calibrated targets and transitions before `ack`.
- Preserve stop, brownout, disconnect, failsafe, and idle behavior.
- Avoid unbounded allocation and unbounded queues.

Acceptance: ESP32-S3 cross-build passes and firmware tests prove rejection causes
zero movement while stop prevents every remaining frame.

### Phase 7: Diagnostics and operator policy

Files in Ainekio and MetaHuman diagnostics/monitor surfaces.

Work:

- Add an owner-controlled freestyle enable state.
- Show supported/enabled status, plan id, frame count, duration, active frame,
  terminal result, rejection reason, and stop event.
- Do not display or persist secrets, calibration internals, or an unbounded plan
  history.

Acceptance: the owner can distinguish unsupported, disabled, validating, active,
completed, cancelled, and rejected states without inspecting raw logs.

### Phase 8: Hardware rollout

- Keep physical freestyle disabled until the servo rail, centers, directions,
  ranges, stop behavior, and combined-load checklist pass.
- Support the robot so it cannot fall or strike anything.
- Start with one conservative pose, reduced logical range, and slow transitions.
- Increase complexity only from measured evidence.
- Record hardware-dependent results in this file without claiming completion from
  emulator results.

Acceptance: all eight joints remain inside calibrated limits, the controller does
not reset, rail voltage remains valid, stop works during every test, and no wiring
or actuator overheats.

## Required Test Gates

- Protocol schema/fixture suite.
- Portable C core and codec tests.
- Emulator body, gateway, environment adapter, and WebSocket integration tests.
- Golden parity fixtures for every accepted plan.
- Maximum-size and one-byte-oversize tests.
- Fuzz/malformed nesting tests at the JSON decoder boundary.
- Stop on every frame index.
- Disconnect, stale sequence, busy motion, low-power, and failsafe tests.
- MetaHuman environment-interface and bridge tests.
- Environment Mode graph test proving that named semantic commands bypass
  Movement Generator and an eligible off-script request enters it exactly once.
- Environment Mode rejection test proving that a missing capability or invalid
  generated plan sends no movement to the bridge.
- MetaHuman production site build when diagnostics UI changes.
- ESP32-S3 cross-build.
- Physical checklist gates before physical enablement.

## Emulator Completion Criteria

The emulator milestone is complete only when all of the following are observed
in one end-to-end run:

1. Start the Ainekio emulator, gateway, environment adapter, MetaHuman
   Environment Bridge, and the Environment Mode workflow.
2. In the MetaHuman user interface, send a request that has no matching installed
   named movement, for example: "Crouch low, lift the front-right leg, pause,
   then return to standing."
3. Environment Mode identifies the request as off-script and routes it to the
   `movement_generator` node. It must not pretend that a named `walk`, `bow`, or
   other motion asset matched the request.
4. Movement Generator emits one bounded, typed `robotMotionPlan`; MetaHuman
   normalization and Ainekio validation both accept it.
5. The plan travels through Environment Bridge Out, the MetaHuman Environment
   Bridge, the Ainekio environment adapter, and the Ainekio gateway to the
   emulator.
6. The emulator visibly performs the generated sequence and returns correlated
   `ack` and `done` results. The diagnostics interface shows the plan identity,
   frame progress, data flow, and terminal state, and the MetaHuman conversation
   reports the result.
7. Evidence confirms that the run did not invoke a matching precompiled `.amot`
   movement asset.
8. A known command such as `walk` still uses the existing semantic route and does
   not invoke Movement Generator.
9. An invalid generated plan produces a visible `nak` or rejected result and
   causes zero emulator movement.
10. Sending `stop` during a valid generated plan cancels the remaining frames and
    returns a correlated `cancelled` result.

This milestone proves the user-visible software path and emulator behavior. It
does not enable or certify freestyle movement on physical hardware; Phase 8
remains separately gated.

## Progress

Overall: the owner-visible MetaHuman-to-Ainekio emulator milestone is complete.
Environment Mode routes off-script requests through Movement Generator, both
bridges carry one validated plan, Sesame visibly executes it, diagnostics report
progress and terminal lifecycle, known commands retain their semantic path, and
live `stop` cancels remaining frames. Physical firmware execution remains
disabled and is not claimed complete.

The initial baseline review covered the checked-in language-neutral protocol,
portable C core, motion asset format, ESP32-S3 motion service, emulator, gateway,
Ainekio environment adapter, and MetaHuman bridge contract. No existing
`motion_plan` or equivalent generated-trajectory command was found at that time.
The calibration-only `servo` boundary remains unchanged.

| Phase | Status | Evidence / next action |
| --- | --- | --- |
| 0. Contract and ownership freeze | Complete for emulator | Architecture, names, bounded `map:1` wire shape, owner policy, and emulator completion criteria are frozen. Hardware-derived transition limits remain a Phase 6/8 prerequisite; physical use stays disabled. |
| 1. Protocol and fixtures | Complete | `motion_plan`, optional bounded hello features, compact 8-joint frames, duration/end bounds, valid/invalid fixtures, schema parity, and the 32-frame encoded-size proof pass 13 Python contract tests. |
| 2. Portable core and codec | Complete for emulator contract | Fixed-size 32-frame storage, complete decode/validation before mutation, normal movement gates, stale-sequence handling, lifecycle, and stop/failsafe behavior pass all 11 native CTest targets. Hardware-derived transition values remain deferred to physical bring-up. |
| 3. Motion service and emulator | Complete | The emulator validates before ack, executes atomically, interpolates the eight Sesame servo joints using Sesame's verified 1..8 setter contract, reports done/rejected, and supports stop cancellation. Live UI requests visibly execute without renderer errors. |
| 4. Gateway and adapter | Complete | Gateway feature negotiation, bounded queueing, lifecycle tracking, strict readable-to-centidegree translation, owner policy, and concurrent stop preemption are implemented. The full 127-test Ainekio emulator/gateway/adapter suite passes. |
| 5. MetaHuman contract | Complete | Added typed normalization, the `movement_generator` node, explicit graph branch/rejoin, exact-instruction ownership, upstream-refusal recovery, compact private generator output with one bounded correction retry, semantic bypass, and production build coverage. Seven focused tests and all 21 graph validations pass. |
| 6. ESP32-S3 integration | Not started; disabled | The physical body does not advertise/enable freestyle. Implement fixed-size firmware execution and hardware-derived transition gates before changing that policy. |
| 7. Diagnostics and policy | Complete for emulator | The owner interface reports transport/media flow plus freestyle supported/enabled/available state, plan id, sequence, frames, duration, active frame, terminal result, rejection detail, and stop events. |
| 8. Hardware rollout | Blocked on hardware validation | Keep physical freestyle disabled. |

## Progress Log

Add newest entries first. Separate implemented software, emulator validation, and
physical validation.

- 2026-07-18: Made the environment adapter's freestyle policy enabled by default
  in both its configuration and production gateway startup. Future launches no
  longer depend on remembering `AINEKIO_FREESTYLE_ENABLED=1`; an explicit `0`
  remains available for maintenance. Physical bodies still cannot receive plans
  unless they advertise `motion_plan_v1`. The focused 22-test adapter suite
  passes, and the live emulator observation reports `supported=true`,
  `enabled=true`, `available=true` with `robotMotionPlan` advertised.
- 2026-07-17: Completed the owner-visible emulator milestone. From the MetaHuman
  Environment Mode UI, the approved off-script crouch/front-right-leg request
  produced one bounded plan and reached Sesame as `freestyle` with no browser or
  WebAssembly errors. The owner's exact previously rejected request, "can you put
  your hands in the air like you just dont care?", then produced six generated
  frames and visibly executed. A live `Walk forward.` request retained the named
  semantic route and reached Sesame as `run walk`. A live nine-second plan was
  stopped at frame 4/9; diagnostics recorded sequence 43, `movement.stop`, and a
  terminal correlated `cancelled` result. Invalid generated structures are
  rejected before dispatch and the emulator rejection tests prove zero movement.
  The full Ainekio suite passes 127 tests; MetaHuman passes seven focused motion
  tests, validates all 21 graphs, and completes the production site build.
- 2026-07-17: Hardened Environment Mode against upstream prompt poisoning and
  brittle generator output. The current typed UI instruction now wins over stale
  adapter transcript text. Exact known commands always win, while unsupported or
  lossy model substitutions and explicit upstream "unsupported movement"
  refusals route the owner's exact request to Movement Generator. Supported
  commands explicitly named in polite requests also stay semantic; the live
  `please shrug for me` check reached Sesame as `shrug` / `rn sg`, not freestyle.
  The generator
  now asks its model for compact fixed-order frame arrays, expands them into the
  unchanged strict public `robotMotionPlan`, derives a bounded display summary
  from the request when needed, and performs one node-local JSON correction retry.
  Its 1536-token limit remains local to Movement Generator and does not alter any
  global model/provider/router setting.
- 2026-07-17: Implemented the Ainekio path from environment action through visible
  emulator payload. The emulator now advertises `motion_plan_v1`, rejects an
  entire plan when any logical target violates calibration, executes accepted
  plans with ack/done lifecycle, and allows `stop` to cancel the active plan.
  The gateway preserves body features, refuses unsupported bodies, queues the
  bounded command, and tracks terminal results. The environment adapter converts
  eight named logical targets per frame to joint-map-v1 centidegrees and exposes
  `robotMotionPlan` only when the body feature is present and the adapter policy
  is enabled. The Sesame browser shim
  validates and interpolates generated frames through its eight-joint runtime API
  while named commands retain their existing UART route. Thirty-eight focused
  tests, JavaScript syntax validation, and the then-current emulator/gateway suite
  passed. Live renderer evidence and MetaHuman Movement Generator routing were
  completed in the later entries above.
- 2026-07-17: Implementation started. Added optional bounded `hello.features`,
  the `motion_plan_v1` feature name, and the `motion_plan` JSON schema using
  joint map version 1 and compact eight-target frames. Added 1..32 frame,
  100..5000 ms frame, 10000 ms total, 0..18000 centidegree, and end-behavior
  validation plus valid/invalid golden fixtures and a maximum-frame-count size
  proof. Added fixed-size portable C plan storage/decoding and normal movement
  safety/lifecycle handling. Thirteen Python protocol tests and all eleven native
  CTest targets pass. Emulator execution and MetaHuman routing are not yet wired.
- 2026-07-17: Added the owner-approved Environment Mode design. The maintained
  workflow will route eligible off-script requests through a new
  `movement_generator` node, rejoin the existing Environment Bridge output, and
  retain the current direct route for named semantic movements. Added the
  decisive UI-to-emulator completion scenario plus rejection, bypass, and stop
  criteria. No runtime or graph code changed in this pass.
- 2026-07-17: Repository baseline audit completed. Confirmed the 4096-byte JSON
  control limit, fixed eight-joint map, existing bounded `.amot` frame model,
  normal-mode rejection of direct servo commands, gateway-assigned sequences,
  and semantic-only MetaHuman adapter. Confirmed generated trajectory transport
  is not implemented. No runtime code changed in this pass.
- 2026-07-17: Initial plan created from the owner-approved atomic motion-plan
  direction. Physical freestyle remains disabled pending implementation and
  hardware validation.
