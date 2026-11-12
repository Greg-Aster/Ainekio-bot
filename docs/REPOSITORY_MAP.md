# Ainekio Repository Map

**Active target: V2 (`v2-12servo`). Retained target: V1 (`v1-8servo`, paused).**

For cross-repository processes, state lifetimes, and end-to-end execution paths with [Ainekio OS](https://github.com/Greg-Aster/ainekio-os), start with [Robot Software Architecture](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/SYSTEM_ARCHITECTURE.md). See [Robot Models](ROBOT_MODELS.md) for V1/V2 boundaries and [V2 Specifications](v2-12servo/SPECIFICATIONS.md) for physical hardware and wiring.

## Slave (Embedded Firmware, Models, CAD, and Wire Protocol)

| Path | Responsibility |
| --- | --- |
| `Slave/hardware/v2-12servo/` | Active V2 Blender assembly (`Ainekio-Motion-Working.blend`), STEP sources, GLB exports, and printable STLs |
| `Slave/firmware/esp32p4-wifi6/main/` | V2 ESP-IDF firmware (`app_main.c`, `board.c`, `controller.c`, `body.c`, `servo_feedback.c`) |
| `Slave/firmware/esp32p4-wifi6/components/` | PCA9685 PWM driver, P4 media (OV5647 camera, ES8311/NS4150B audio, ST7789 LCD face, LSM6DS3 IMU), and asset store |
| `Slave/software/models/v2-12servo/` | V2 4-bar linkage geometry, kinematics, 23 finite postures/gestures, analytic gaits, compiled Microduck neural policy (`motions/microduck/`), and authoring tools |
| `Slave/software/imu/` | Shared attitude estimation mathematics consumed by P4 IMU acquisition and host tests |
| `Slave/software/protocol/` | Language-neutral JSON/binary `protocol-v1` schemas, Python validators, and V1/V2 joint definitions (`joints_v1.py`, `joints_v2.py`) |
| `Slave/software/core/` | Portable C command/protocol helpers (retains V1 8-joint structures alongside shared framing) |
| `Slave/firmware/esp32s3/`, `Slave/hardware/v1-8servo/` | Paused V1 ESP32-S3 firmware and 8-servo mechanical assets |
| `Slave/software/assets/`, `Slave/software/tests/` | Shared face/audio seed assets and portable C/Python protocol and model test suites |
| `tools/leg-geometry-calculator/` | Mechanical design utilities, including the 4-bar leg geometry calculator |

Only the selected board's firmware image runs on the microcontroller; Body Control, Freestyle generation, and Ainekio OS run on host computers.

## Master (Body Control Gateway, Perception, and Neural Gait)

[`Master/gateway/server/__main__.py`](../Master/gateway/server/__main__.py) composes the Python Body Control stack:

| Path | Responsibility |
| --- | --- |
| `Master/gateway/server/` | `protocol-v1` `/robot` WebSocket server, session epochs, sequence fencing, capability negotiation, and command receipts |
| `Master/gateway/environment_adapter/` | Loopback `/environment` WebSocket bridge, semantic translation, speech routing, body-event forwarding, and durable receipt replay |
| `Master/gateway/dashboard/` | Operator HTTP API and browser UI (`127.0.0.1:8791`), optional `AINEKIO_DASHBOARD_NO_LOGIN=1` local mode, and Freestyle runtime wiring |
| `Master/gateway/neural_gait/` | Neural locomotion service (`8796`), Microduck PPO/mjlab GPU training & ONNX export, Pupper MJX / physical REDQ policies, and sensor/body tensor engines |
| `Master/gateway/plugins.py`, `perception.py`, `depth_motion*.py` | Non-blocking camera frame worker, YOLO/YOLOE detection, YuNet/SFace person recognition, and depth/visual motion helpers |
| `Master/gateway/hotspot.py` | Robot Wi-Fi hotspot management and service fallback |
| `Master/start-physical-gateway.sh`, `stop-physical-gateway.sh` | Physical Body Control lifecycle launchers and pairing import/export utilities |

## Freestyle (`experiments/freestyle/`)

[`experiments/freestyle/`](../experiments/freestyle/README.md) is an **active production runtime module** imported by `Master/gateway/dashboard/server.py`:

- `generator.py` & `big_brother.py` — HTTP generation server backed by native `llama-cpp.service` (`environment-0.8b-base` + Freestyle LoRA) or remote Big Brother over SSH.
- `bridge.py`, `runtime.py`, `program.py`, `compact_wire.py` — Request admission, compact-operation compilation, P4 target dispatch, and observation-driven stall/slip/tip recovery.
- `motion_library.py` / `motion_library.js`, `body_control.js` — Editable motion library backend and Body Control UI panels.
- `freestyle_curriculum.py`, `semantic_teachers.py`, `stand_curriculum.py`, `continue_training.py`, `train_full.py` — Dataset construction, curriculum splits, and model training/evaluation.

## Emulator and Integration Tests (`Emulator/`)

- `Emulator/emulator/body/` & `backends/sesame.py` — Host `protocol-v1` robot emulator and browser-rendered V1 visual simulator.
- `Emulator/tests/` — Gateway, dashboard, `/environment` adapter, V2 P4 transport/commands, Microduck neural gait, depth motion, and acceptance tests (`Emulator/tools/run_acceptance.py`).

## End-to-End Runtime Flow

```text
Ainekio OS cognitive graph (Environment Mode)
  <-> Ainekio OS Environment Bridge
  <-> Master/gateway/environment_adapter (/environment loopback WebSocket)
  <-> GatewayService + Freestyle / Neural Gait executors
  <-> ESP32-P4 controller (/robot WebSocket) -> body.c -> PCA9685 / Microduck / peripherals
  <-> Correlated 4th-wire feedback, IMU, audio, camera, and terminal receipts back to Ainekio OS
```

## Ignored Local Paths

| Path | Role |
| --- | --- |
| `build/` | Pairing credentials, dashboard sessions, receipt databases, compiled firmware/native test outputs, and neural-gait environments |
| `.env`, `~/.config/ainekio/` | Local environment tokens and service configuration |
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` | Local-only contributor instruction files (untracked) |
