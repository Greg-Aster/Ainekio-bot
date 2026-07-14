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
    core/                     Portable C commands, state, lifecycle, and safety
    protocol/                 Protocol-v1 schemas, validator, helpers, fixtures
    tests/                    Portable slave-software protocol tests
  firmware/
    esp32s3/                  ESP-IDF project for the physical robot
      main/app_main.c         Physical robot firmware entry point
```

`Slave/firmware/esp32s3/main/app_main.c` is where the ESP32-S3 robot starts.
`Slave/software/core/` is linked into that firmware. Neither `Master/` nor
`Emulator/` is flashed to the robot.

## Master

```text
Master/
  gateway/                    Brain-side protocol-v1 WebSocket owner
    server/                   Current local gateway test stub
```

The future production MetaHuman bridge and gateway stay under `Master/`.

## Emulator

```text
Emulator/
  emulator/                   Protocol-v1 host body emulator
    body/                     Host session, client, and portable-core bridge
    backends/                 Optional Sesame renderer backend and HTTP/SSE shim
  tests/                      Host emulator and gateway integration tests
  sesame-robot-sim/           Runnable browser/WASM visual simulator
  legacy/motion/              Superseded Python MetaHuman SSE motion adapter
  requirements-host.txt       Host-only Python dependency pin
  start-protocol-v1-emulator.sh
  start-simulator-shim.sh
  start-ainekio-adapter.sh    Legacy adapter launcher
  start-ainekio-sim-stack.sh  Legacy combined-stack launcher
```

The host emulator uses the portable core from `Slave/software/core/`. The Sesame
browser renders accepted commands but does not own protocol or safety decisions.

## Documentation

```text
docs/
  Ainekio - System Specification v1.0.docx
  SLAVE_BRAIN_PROGRESS.md
  REPOSITORY_MAP.md
  archive/                    Historical notes
  sesame-robot/               Ignored upstream Sesame reference clone
```

`docs/sesame-robot/` is inspection material only. It is not imported, linked, or
built by Ainekio.

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

Legacy development path:

```text
Emulator/start-ainekio-sim-stack.sh
  -> Emulator/legacy/motion
  -> Emulator/emulator/backends/sesame_shim.py
  -> Emulator/sesame-robot-sim
```

## Non-Source Root Paths

| Path | Purpose |
| --- | --- |
| `README.md` | Project introduction and short folder guide. |
| `AGENTS.md`, `.agents/`, `.codex/` | Local collaboration instructions and agent tooling. |
| `.git/` | Git metadata. |
| `build/` | Generated host CMake output. |
| `node_modules/` | Generated JavaScript dependencies. |
| `packages/` | Existing generated dependency links; no current Ainekio source owner. |

Generated output is not a fifth code owner and should not contain authoritative
robot implementation.
