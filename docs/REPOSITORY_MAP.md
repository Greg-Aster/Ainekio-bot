# Ainekio Repository Map

All project code belongs to one of three runtime owners: `Master/`, `Slave/`, or
`Emulator/`. Project documentation and external reference material belong in
`docs/`.

The repository supports ongoing V1 development alongside the new V2 frame.
[Robot Models](ROBOT_MODELS.md) records the approved model/board/output boundaries
and identifies the code extraction still needed for V2. The trees below show
existing directories, not future firmware scaffolding.

## Robot Code

The physical robot's code is under `Slave/`.

```text
Slave/
  hardware/
    README.md                 Model-specific asset guide
    v1-8servo/
      3d-print/               Existing V1 Blender and STL assets
      Parts/                  Existing V1 OBJ and material assets
    v2-12servo/               V2 STEP, Blender, GLB, STL, and source archive
  software/
    assets/                   Current V1 motion, face, and PCM assets
    core/                     Portable C lifecycle/safety with V1 body assumptions
    imu/                      Portable six-axis attitude estimator and native tests; acquisition not integrated
    models/v2-12servo/        Twelve-joint geometry, first walk source, compiler and sampler
    protocol/                 Protocol-v1 schemas, validator, helpers, fixtures
    tests/                    Portable slave-software protocol tests
    tools/                    Deterministic asset conversion and validation
  firmware/
    esp32s3/                  Existing V1 ESP-IDF project
      components/             ESP32-S3 platform services and hardware ports
      main/app_main.c         Physical robot firmware entry point
    esp32p4-wifi6/            Native V2 board/network/output-disable bring-up
      components/ainekio_pca9685/  Real register driver, output gate and tests
      main/                   P4 startup, resources, configuration, network and admission adapter
```

`Slave/firmware/esp32s3/main/app_main.c` is where the ESP32-S3 robot starts.
`Slave/software/core/` is linked into that firmware. Neither `Master/` nor
`Emulator/` is flashed to the robot.

The firmware, protocol, core, and runtime asset paths retain their existing
build/import behavior. `Slave/software/models/v2-12servo/` owns the first V2 gait;
V1 model extraction remains pending.
The native P4 target exists; its [Step 1 record](v2-12servo/STEP1_EVIDENCE.md)
separates software/network checks from outstanding electrical acceptance.

## Master

```text
Master/
  gateway/                    Brain-side protocol-v1 WebSocket owner
    server/                   Production gateway service and focused test stub
    dashboard/                Authenticated operator dashboard
    environment_adapter/      Authenticated environment WebSocket and semantic translation
```

The production gateway, dashboard, plugins, security stores, and generic
environment adapter stay under `Master/`.

Both robot models use this owner. Legacy V1 retains its motion catalog; negotiated
P4 readiness suppresses unimplemented motion/media. The first V2 walk sampler
has twelve geometric joints; measured calibration, its operator controls and
powered execution remain subsequent work. `body_capabilities.py` selects the
connected body's subset of the existing gateway semantic catalog.

## Emulator

```text
Emulator/
  emulator/                   Protocol-v1 host body emulator
    body/                     Host session, client, and portable-core bridge
    backends/                 Optional Sesame renderer backend and HTTP/SSE shim
  tests/                      Host emulator and gateway integration tests
  sesame-robot-sim/           Runnable browser/WASM visual simulator
  requirements-host.txt       Host-only Python dependency pin
  start-protocol-v1-stack.sh  Complete local inspection stack
  start-protocol-v1-emulator.sh
  start-simulator-shim.sh
```

The host emulator uses the portable core from `Slave/software/core/`. The Sesame
browser renders accepted commands but does not own protocol or safety decisions.
The current body and Sesame backend implement V1; a V2 visual backend is pending.

## Documentation

```text
docs/
  README.md                   Normative-document authority
  ROBOT_MODELS.md             Approved model/board/output separation
  Ainekio - System Specification v1.0.docx
  v1-8servo/
    HARDWARE_BRINGUP_CHECKLIST.md
    PINOUT_DIAGNOSTICS.md
  v2-12servo/
    README.md                 Selected hardware and current design status
    FIRMWARE_DESIGN.md         V1 review, P4 design and optional Q6A boundaries
    STEP1_EVIDENCE.md          Board bring-up evidence and open electrical checks
  AINEKIO_METAHUMAN_CLOSED_LOOP_STATUS.md
  BODY_CONTROL_INTEGRATION.md  ROS 2 role, transport and operating targets
  LOCAL_WAKE_WORD.md
  freestyle-movement.md
  SLAVE_BRAIN_PROGRESS.md
  REPOSITORY_MAP.md
  Freenove_ESP32_S3_WROOM_Board-main/
                              Current vendor board reference bundle
  archive/                    Superseded specifications and historical notes
  sesame-robot/               Ignored upstream Sesame reference clone
```

`docs/sesame-robot/` supplies upstream seed material to the deterministic asset
conversion tools, but it is not imported, linked, or built into Ainekio. The
Freenove bundle identifies the delivered board's physical headers and onboard
buses; neither reference directory owns Ainekio behavior or safety decisions.

## Runtime Paths

Current V1 physical robot:

```text
Slave/software/protocol
  -> Slave/software/core
  -> Slave/firmware/esp32s3/main/app_main.c
  -> ESP-IDF hardware services
```

Host test path:

```text
Master/gateway
  -> WebSocket protocol v1
  -> Emulator/emulator/body
  -> Slave/software/core
  -> Emulator/emulator/backends
  -> Emulator/sesame-robot-sim
```

## Non-Source Root Paths

| Path | Purpose |
| --- | --- |
| `README.md` | Project introduction and short folder guide. |
| `AGENTS.md`, `.agents/`, `.codex/` | Local collaboration instructions and agent tooling. |
| `.git/` | Git metadata. |
| `build/` | Generated acceptance reports, host builds, credentials, and runtime data. |
| `node_modules/` | Generated JavaScript dependencies. |
| `packages/` | Existing generated dependency links; no current Ainekio source owner. |

Generated output is not a fifth code owner and should not contain authoritative
robot implementation.
