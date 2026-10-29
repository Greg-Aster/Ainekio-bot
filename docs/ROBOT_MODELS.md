# Robot Models and Code Separation

The owner approved maintaining V1 and V2 as two supported robot styles on
2026-09-15. They share the gateway and Body Control interface, with separate
body definitions and board implementations.

**Current work (owner-confirmed 2026-10-26): V2 is active; V1 work is paused.**
The separate V1 implementation and records are retained.

## Current Models

| Model | Body | Board | Servo output | Current implementation |
| --- | --- | --- | --- | --- |
| `v1-8servo` | Existing eight-servo Sesame-based frame | Freenove ESP32-S3-WROOM CAM N16R8 | Direct ESP32 MCPWM outputs | Existing firmware, portable core, motion assets, and Sesame emulator |
| `v2-12servo` | Twelve-servo frame under development | ESP32-P4-WIFI6 | PCA9685 over I2C | P4 command/peripheral runtime, twelve-joint target and native motion execution, feedback/calibration, and host Freestyle integration; physical qualification is per capability |

Start physical design and integration work with the dedicated
[V1 specifications](v1-8servo/SPECIFICATIONS.md) or
[V2 specifications](v2-12servo/SPECIFICATIONS.md). They reconcile hardware,
geometry and connection facts with their existing owners and identify unknowns.
[V1 hardware evidence](v1-8servo/HARDWARE_BRINGUP_CHECKLIST.md) and the
[V2 hardware record](v2-12servo/README.md) retain their original evidence scope.
V1 results do not establish V2 wiring, motion, or physical readiness.

The [V2 firmware design](v2-12servo/FIRMWARE_DESIGN.md) records the V1 source
review, ESP32-P4-WIFI6/PCA9685 research, and proposed implementation details.

## Ownership Boundaries

| Concern | Owner |
| --- | --- |
| Robot geometry and printable parts | `Slave/hardware/<model>/` |
| Geometry, default poses and native motion assets | `Slave/software/models/<model>/`; V2 exists, V1 extraction is paused |
| Joint IDs and installed output mapping | `Slave/software/protocol/joints_v1.py` / `joints_v2.py` define order; installed output/feedback mapping belongs to per-device configuration |
| Device command lifecycle and execution | V1 portable/platform owners; V2 `Slave/firmware/esp32p4-wifi6/main/controller.c` and `body.c`, using V2 model mathematics |
| Wire formats, compatibility, and validation | `Slave/software/protocol/` |
| Board GPIOs, buses, peripherals, and firmware composition | `Slave/firmware/<board>/` |
| Servo signal generation | The board's output implementation: MCPWM for V1, PCA9685 for V2 |
| Connections, authentication, command transport, and Body Control UI | `Master/gateway/` |
| Learned V2 movement generation and host execution | `experiments/freestyle/`, loaded by the existing gateway/dashboard; submits through the existing P4 target executor |
| Semantic capabilities presented to MetaHuman OS | `Master/gateway/environment_adapter/`, scoped to the selected body's supported commands |
| Host execution and visual simulation | `Emulator/`, with model-specific renderer backends |
| Device identity, measured calibration, credentials, and runtime records | Per-device storage; private runtime data stays outside tracked source |

Motion logic and servo signal generation meet at a small output interface. The
shared logic applies lifecycle and safety rules before the board implementation
updates or disables outputs. The V2 PCA9685 implementation belongs with its
firmware target; there is no need to duplicate the gateway for it.

The [V2 model](../Slave/software/models/v2-12servo/README.md) owns geometry,
kinematics and native motion mathematics. P4 owns physical execution and feedback;
the [Freestyle owner](../experiments/freestyle/README.md) generates requested motion
and coordinates it through that existing target executor. The
[socket/feedback record](v2-12servo/SERVO_SOCKET_MAP.md) documents saved twelve-servo
mapping and calibration. [Step 1](v2-12servo/STEP1_EVIDENCE.md) is historical bring-up
evidence, not today's implementation inventory.

## Existing V1 Code to Separate

V1 extraction is paused. These retained owners identify V1-specific data; this
section is a location reference, not a standing work order to resume migration:

| Current owner | V1-specific content |
| --- | --- |
| [protocol.h](../Slave/software/core/include/ainekio/protocol.h) | Retained eight-servo joint enum and motion/pose structures alongside V2 wire structures |
| [joints_v1.py](../Slave/software/protocol/joints_v1.py) | Frozen eight-joint order; shared `control_v1.py` and schemas also support V2 map 2 |
| [assets.c](../Slave/software/core/src/assets.c) and [seed assets](../Slave/software/assets/seed/) | Body-specific fallback poses and motion frames; faces/audio also currently reside in the seed tree |
| [ESP32-S3 platform](../Slave/firmware/esp32s3/components/ainekio_platform/) | V1 board pin map, motion service, and MCPWM driver |
| [emulator body](../Emulator/emulator/body/) and [Sesame backend](../Emulator/emulator/backends/sesame.py) | V1 asset validation, portable-core integration, and visual motion mapping |

The shared gateway adapter and dashboard already handle V2 capability negotiation,
twelve-joint motion and calibration; they are not V1-only extraction targets.
Keep V1's existing contracts intact when changing those shared consumers.

## Compatibility Rules

- Robot model, board target, firmware version, wire-protocol version, and joint-map
  version are separate identifiers. A V2 body does not automatically require
  protocol v2.
- Preserve V1's existing joint order and eight-joint wire/asset semantics. Do not
  change the global servo count to twelve or reinterpret V1 motion files for V2.
- Resolve model data and advertised capabilities for the selected robot. The
  gateway already identifies devices by robot ID; a device ID is not a model ID.
  Current capability negotiation and saved per-device mapping determine the
  selected body's commands; use the socket/feedback record and device configuration
  rather than older bring-up claims that mapping/calibration has not occurred.
- V2 commands must reflect its implemented motions and available hardware. It
  must not inherit the complete V1 catalog just by authenticating.
- Keep each device's measured calibration associated with its model and joint
  map. The existing `home`/`tether` operating profiles are not robot models.

The [repository map](REPOSITORY_MAP.md) describes directories that exist now.
