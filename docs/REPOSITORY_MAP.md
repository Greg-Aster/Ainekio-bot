# Ainekio Repository Map

**V2 is active; V1 work is paused.** This map describes the current source owners.
Start with the cross-repository [software architecture](../../metahuman/docs/robot/SYSTEM_ARCHITECTURE.md)
for processes, interfaces and complete request/result paths. [Robot Models](ROBOT_MODELS.md)
defines V1/V2 boundaries; [V2 specifications](v2-12servo/SPECIFICATIONS.md) defines
the physical assembly. Source support and installed qualification are separate.

## Robot Code

| Path | Responsibility |
| --- | --- |
| `Slave/hardware/v2-12servo/` | Current V2 Blender, STEP, GLB and printable geometry |
| `Slave/firmware/esp32p4-wifi6/main/app_main.c` | Physical V2 firmware entrypoint; initializes board, controller, feedback, media, IMU, display and network |
| `Slave/firmware/esp32p4-wifi6/main/controller.c` | Robot WebSocket session, command admission, observations and receipts |
| `Slave/firmware/esp32p4-wifi6/main/body.c` | V2 device motion lifecycle, target tracking, calibration-to-output handoff |
| `Slave/firmware/esp32p4-wifi6/components/` | PCA9685 driver, media and assets |
| `Slave/software/models/v2-12servo/` | V2 geometry, kinematics, postures, native motion and tests |
| `Slave/software/imu/` | Shared attitude mathematics; P4 acquisition lives in `components/ainekio_p4_media/imu.c` |
| `Slave/software/protocol/` | Wire schemas, helpers, validators and model-specific joint contracts |
| `Slave/software/core/` | Portable command/core functions, including retained V1 body assumptions; not a universal V2 motion executor |
| `Slave/firmware/esp32s3/`, `Slave/hardware/v1-8servo/` | Retained V1 firmware and physical assets |
| `Slave/software/assets/`, `Slave/software/tests/`, `Slave/software/tools/` | Seed assets, portable tests and deterministic asset tooling |

Only the selected firmware image runs on the microcontroller. MetaHuman, the
gateway and the host emulator are not flashed into it.

## Master

[`Master/gateway/server/__main__.py`](../Master/gateway/server/__main__.py) composes
the Python Body Control application:

| Path | Responsibility |
| --- | --- |
| `Master/gateway/server/service.py` | Robot sessions, epochs, command sequences, capabilities and receipts |
| `Master/gateway/environment_adapter/` | Semantic `/environment` protocol, translation and persistent action-result correlation |
| `Master/gateway/dashboard/` | Operator HTTP API/browser UI; wires the existing Freestyle executor into GatewayService |
| `Master/gateway/plugins.py`, `perception.py` | Camera processing and configured perception |
| `Master/start-physical-gateway.sh` | Physical Body Control launcher with saved configuration |

Both bodies use this gateway. `body_capabilities.py` derives the selected body's
capabilities; twelve-joint commands, feedback/calibration controls and P4 media
are implemented. Their per-device qualification belongs to dated evidence.

## Freestyle

[`experiments/freestyle/`](../experiments/freestyle/README.md) is an **active runtime
dependency**, not an orphaned experiment. `dashboard/server.py` imports its
`bridge.py`; `GatewayService.request_motion` calls that executor. `generator.py`
serves the model-backed generation API. Program compilation, observation-driven
continuation, datasets and recording belong to this owner. Execution uses the
existing gateway/P4 path. MetaHuman supplies semantic requests, not joint frames.

## Emulator

`Emulator/emulator/body/` implements the host protocol body, `backends/` supplies
the Sesame adapter, and `sesame-robot-sim/` supplies its browser renderer.
`Emulator/tests/` also contains gateway and V2 integration tests; its directory
name does not mean all those tests concern the V1 renderer. The Sesame visual
body is V1; native V2 tests and Freestyle simulation are separate test surfaces.

## Documentation

`docs/README.md` names document authority. Model-specific specifications and
wiring live in `docs/v1-8servo/` and `docs/v2-12servo/`. Firmware/model READMEs
describe their owners. Dated research and bring-up records retain their original
conditions; old pending-work statements are not the current implementation map.
`docs/sesame-robot/` and the Freenove reference bundle supply reference material,
not Ainekio runtime behavior. [Startup](STARTUP.md) describes an existing physical
installation; the root `start.sh` starts the simulator inspection stack.

## Runtime Paths

```text
MetaHuman graph / Core action
  <-> MetaHuman Environment Bridge
  <-> gateway environment adapter
  <-> GatewayService / Freestyle executor when movement is requested
  <-> P4 controller -> body executor -> PCA9685/peripherals
  <-> correlated receipts and observations back to the same Core execution
```

Manual Body Control enters at the gateway. V1 instead uses ESP32-S3 `app_main.c`
and its platform/core path; its eight-joint conventions are retained. Host
simulation substitutes the emulator for the physical body connection.

## Non-Source Root Paths

| Path | Purpose |
| --- | --- |
| `AGENTS.md`, `.agents/`, `.codex/` | Local contributor instructions/tooling; Ainekio `AGENTS.md` remains ignored |
| `.git/` | Repository metadata |
| `build/` | Runtime stores, credentials, recordings, generated builds and reports; not disposable merely because ignored |

Determine readers, lifecycle and retention before removing data. Active receipts,
recovery state, training evidence and other tasks' artifacts are not orphaned
merely because they are absent from the source import graph.
