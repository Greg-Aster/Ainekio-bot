# Simulator Bridge Progress Scratchpad

## Current Direction

- MetaHuman OS remains the remote brain.
- Ainekio owns the robot-side adapter / slave brain.
- The adapter connects over WiFi to the MetaHuman web address, currently `http://192.168.0.44:4321`.
- The adapter should use MetaHuman's environment bridge endpoints under that base address.
- The Sesame simulator in `Emulator/sesame-robot-sim` is the first testing ground.
- The ESP32-S3 hardware target comes later, after the adapter can listen, translate commands, apply safety, and drive the simulator.
- Current first priority is complete: MetaHuman Environment Mode can send typed movement instructions to the Ainekio adapter over the persistent bridge stream.
- Current next priority: connect the Ainekio virtual backend to visible Sesame simulator movement.

## Working Architecture

```text
MetaHuman OS environment bridge
        |
        v
Ainekio robot-side adapter
        |
        v
Ainekio motion safety + sequence module
        |
        v
Sesame simulator backend now
ESP32-S3 firmware/backend later
```

## Decisions So Far

- Use the ESP32-S3 body plan as the hardware target.
- Do not resurrect the obsolete hardware path.
- Use existing MetaHuman HTTP environment bridge endpoints for v1.
- First network target is same-LAN WiFi.
- Treat `http://192.168.0.44:4321` as the MetaHuman base URL for the robot client.
- V1 should prove both the bridge loop and visible simulator motion.
- Do not rewrite Environment Mode from scratch. Replace the Megameal-only interpreter step with a generic environment instruction surface that can support Ainekio.
- The current Sesame simulator does not implement WiFi/API behavior. It will be driven as a visual simulator backend, not as a networked robot.
- Action delivery is now event-driven over a persistent server-sent event stream at `/api/environment-bridge/stream`.
- The old action polling endpoint `/api/environment-bridge/actions` has been removed from the source route and adapter code.
- Environment Mode should surface bridge delivery problems to the chat user. Silent queueing is not acceptable for robot commands.
- The Ainekio adapter can be started from the repo root with
  `./Emulator/start-ainekio-adapter.sh`.

## Current Finding

- Original failure: sending `hello!` or `walk forward 5 units` in MetaHuman Environment Mode ran the graph but reached vLLM with `messages=0`.
- The empty model request fails with `vLLM request failed (400): list index out of range`.
- Root cause: normal typed chat is not being converted into an environment instruction before the context builder/model router.
- Current source-graph wiring is connected: the new interpreter still feeds observation/instruction/sessionId into the existing context builder, parser, and send-action nodes.
- Focused core smoke test confirms `walk forward 5 units` now produces one model message and parses into a semantic `move forward` action.
- Runtime check from the UI showed `[Node:environment_instruction_interpreter] No executor found`, which means the server was still running an old built bundle.
- `pnpm --dir apps/site build` has now completed, and the rebuilt `apps/site/dist` contains `environment_instruction_interpreter`.
- Environment bridge transport has been changed from action polling to a persistent SSE stream.
- Focused stream smoke test confirms the stream first sends a `connected` handshake event.
- The Environment Bridge Out node now reports delivery readiness. If no adapter stream/session is connected, it returns a chat-visible warning instead of silently leaving the LLM response as the only output, and it does not queue stale movement commands.
- Typed Environment Mode fallback commands now target `ainekio-sim-1` instead of a MetaHuman chat session ID, unless a real adapter observation supplies another session.
- Focused node smoke test result for `walk forward 5 units`: `sessionId=ainekio-sim-1`, `status=waiting_for_adapter`, `reason=no_connected_environment_adapter`, `count=0`, `success=false`, `response="I understood the environment command, but no robot adapter is connected for session ainekio-sim-1. Start the Ainekio adapter and try again."`
- UI test after restart confirmed the graph output selects `Environment Bridge Out` for bridge errors and falls back to the normal LLM response when the adapter is connected.
- Successful connected-adapter MetaHuman log for `please walk forward 5 units`: `status=queued_for_adapter`, `targetSessionId=ainekio-sim-1`, `streamSubscriberCount=1`, `queuedCount=2`.
- Successful Ainekio adapter output: `completed action=env-action-202607080327132-6ksdd0 command=walk frames=16 message=completed` and `completed action=env-action-202607080327132-xb5dfq command=sendText frames=0 message=text_received`.

## Current Implementation Step

- Added a generic MetaHuman environment instruction interpreter node.
- Updated `environment-mode.json` to use that generic interpreter instead of `megameal_interpreter`.
- Kept downstream graph behavior the same: context builder, optional LLM, action parser, queue action.
- Added an Ainekio robot-side adapter CLI that posts an observation, opens the persistent stream, handles pushed actions, applies safety, runs the virtual backend, and reports results.
- `sendText` actions are acknowledged by the adapter as received text instead of being treated as unsupported motion.
- Added bridge-output error/status fields to the MetaHuman `environment_send_action` node and renamed its graph label to `Environment Bridge Out`.
- Added an action-stream subscriber count check so the send node only queues commands when a persistent adapter stream is actually connected.
- Added the adapter launcher, now at `Emulator/start-ainekio-adapter.sh`. It
  starts the adapter with default URL `http://192.168.0.44:4321` and session
  `ainekio-sim-1`, with environment-variable overrides.
- Updated the legacy MetaHuman Megameal bridge adapter so it no longer imports the removed polling function `claimEnvironmentActions`; it now uses event-driven dispatch/subscription.
- Next implementation step: connect the Ainekio virtual backend result to the Sesame simulator so completed `walk` frames move something visible.

## Verification

- `pnpm validate:graphs` in `/home/greggles/metahuman`: passed, 20 graphs valid.
- Focused `tsx` node smoke test: passed for stopped-adapter warning path; no action was queued when no adapter stream was connected.
- `pnpm --dir apps/site build` in `/home/greggles/metahuman`: passed. Existing Svelte/Vite warnings remain unrelated to this bridge work.
- A previous Ainekio motion test run passed before the package moved to
  `Emulator/legacy/motion/`; the current command is
  `PYTHONPATH=Emulator:Emulator/legacy/motion/src python3 -m unittest discover -s Emulator/legacy/motion/tests`.
- Runtime stopped-adapter UI test: passed. MetaHuman returned the clear no-adapter message and queued no stale movement.
- Runtime connected-adapter UI test: passed. MetaHuman queued two actions to `ainekio-sim-1`; Ainekio completed the `walk` command with 16 virtual frames and acknowledged `sendText`.
- Megameal bridge adapter import check: passed after replacing the stale polling import.

## Open Work

- Decide how the Sesame simulator should receive visible movement commands from the Ainekio adapter.
- Add a simulator-control path for visible Sesame simulator movement.
- Decide whether to keep the default MetaHuman environment-bridge agent on Megameal while Ainekio uses its own adapter process, or add a first-class Ainekio bridge agent entry later.
- Keep simulator and future hardware behind backend interfaces.

## Notes

- `localhost:4321` only works from the MetaHuman machine itself.
- A robot on WiFi must use the host LAN address or hostname.
- The simulator is a prebuilt browser app; direct control may need a small shim.
- AI should never send raw servo angles. Ainekio motion code owns servo safety and sequence rendering.

## Update - 2026-07-07 21:00 PDT

- Added a local Ainekio simulator shim process and startup scripts so the dev stack can run as one workflow.
- Current stack command: `./Emulator/start-ainekio-sim-stack.sh`.
- Stack starts:
  - Sesame simulator at `http://127.0.0.1:8765/`
  - Ainekio simulator shim at `http://127.0.0.1:8788/`
  - Shim monitor at `http://127.0.0.1:8788/monitor`
  - Ainekio adapter pointed at MetaHuman `http://192.168.0.44:4321`
- Confirmed end-to-end bridge path:
  - MetaHuman Environment Mode sends `walk` / `sendText` actions.
  - Ainekio adapter receives the SSE action stream.
  - Adapter translates command, applies safety, renders virtual servo frames, publishes to the simulator shim, and reports results back to MetaHuman.
  - Adapter output example: `completed action=... command=walk frames=16 message=completed`.
- Confirmed browser-side shim connection:
  - Sesame simulator page loads `ainekio-shim.js`.
  - Browser subscribes to shim `/events`.
  - Shim logs `subscribers=1` when a motion command arrives.
- Current limitation:
  - The shim monitor / overlay registers movement, but the actual Sesame robot model does not move yet.
  - This is not a MetaHuman or adapter failure. The remaining gap is simulator visual control.
- Current simulator finding:
  - The Sesame simulator is a prebuilt Rspack/WASM browser app, not a local source checkout.
  - The compiled app has an internal runtime with `hybrid.set_joint_q(...)`, `hybrid.reset()`, `updateHybrid()`, and `run(...)`.
  - The simulator reset button already uses `hybrid.set_joint_q(...)` to set the 8 servo joints.
  - The runtime is held in a local module variable, so the next practical step is exposing it to the Ainekio shim as a controlled bridge hook.
- Motion architecture decision:
  - The robot should use named pre-programmed settings / sequences in the simulator and later on the ESP32-S3 firmware.
  - MetaHuman should keep sending semantic commands like `walk`, `stop`, `wave`, not raw servo angles.
  - Ainekio owns the preset-to-servo-frame translation for the simulator and later ESP32-S3 firmware.
- Existing Ainekio preset coverage:
  - Implemented sequences: `rest`, `stand`, `idle`, `stop`, `walk`, `backward`, `left`, `right`, `wave`.
  - Additional command names exist in `RobotCommand` but need actual sequences before they are meaningful.
- Next implementation step:
  - Expose the Sesame simulator runtime to the injected Ainekio shim.
  - Have `ainekio-shim.js` play received Ainekio servo frames through `hybrid.set_joint_q(...)` and `updateHybrid()`.
  - Keep the shim monitor as debug feedback, but make the actual simulator robot model the primary visual target.
