# Ainekio Repository Map

All project code belongs to one of three runtime owners: `Master/`, `Slave/`, or
`Emulator/`. Project documentation and external reference material belong in
`docs/`.

## Robot Code

The physical robot's code is under `Slave/`.

```text
Slave/
  hardware/
    3d-print/                 CAD, Blender, and STL body assets
  software/
    assets/                   Versioned LittleFS motion, face, and PCM assets
    core/                     Portable C commands, state, lifecycle, and safety
    protocol/                 Protocol-v1 schemas, validator, helpers, fixtures
    tests/                    Portable slave-software protocol tests
    tools/                    Deterministic asset conversion and validation
  firmware/
    esp32s3/                  ESP-IDF project for the physical robot
      components/             ESP32-S3 platform services and hardware ports
      main/app_main.c         Physical robot firmware entry point
```

`Slave/firmware/esp32s3/main/app_main.c` is where the ESP32-S3 robot starts.
`Slave/software/core/` is linked into that firmware. Neither `Master/` nor
`Emulator/` is flashed to the robot.

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

## Documentation

```text
docs/
  README.md                   Normative-document authority
  Ainekio - System Specification v1.0.docx
  HARDWARE_BRINGUP_CHECKLIST.md
  PINOUT_DIAGNOSTICS.md
  AINEKIO_METAHUMAN_CLOSED_LOOP_STATUS.md
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

Physical robot:

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
