# Robot Models and Code Separation

The owner approved maintaining V1 and V2 as two supported robot styles on
2026-09-15. They share the gateway and Body Control interface, with separate
body definitions and board implementations.

## Current Models

| Model | Body | Board | Servo output | Current implementation |
| --- | --- | --- | --- | --- |
| `v1-8servo` | Existing eight-servo Sesame-based frame | Freenove ESP32-S3-WROOM CAM N16R8 | Direct ESP32 MCPWM outputs | Existing firmware, portable core, motion assets, and Sesame emulator |
| `v2-12servo` | Twelve-servo frame under development | ESP32-P4-WIFI6 | PCA9685 over I2C | Native bring-up, output driver, twelve-joint geometric model, walk and eight finite turn samplers; calibrated execution and electrical acceptance pending |

[V1 hardware evidence](v1-8servo/HARDWARE_BRINGUP_CHECKLIST.md) and the
[V2 hardware record](v2-12servo/README.md) have separate scopes. V1 results do
not establish V2 wiring, motion, or physical readiness.

The [V2 firmware design](v2-12servo/FIRMWARE_DESIGN.md) records the V1 source
review, ESP32-P4-WIFI6/PCA9685 research, and proposed implementation details.

## Ownership Boundaries

| Concern | Owner |
| --- | --- |
| Robot geometry and printable parts | `Slave/hardware/<model>/` |
| Joint names/order, joint-to-output mapping, default poses, and motion assets | `Slave/software/models/<model>/`; V2 exists, V1 extraction remains pending |
| Command lifecycle, state, and reusable safety logic | `Slave/software/core/`, using the selected model's data |
| Wire formats, compatibility, and validation | `Slave/software/protocol/` |
| Board GPIOs, buses, peripherals, and firmware composition | `Slave/firmware/<board>/` |
| Servo signal generation | The board's output implementation: MCPWM for V1, PCA9685 for V2 |
| Connections, authentication, command transport, and Body Control UI | `Master/gateway/` |
| Semantic capabilities presented to MetaHuman OS | `Master/gateway/environment_adapter/`, scoped to the selected body's supported commands |
| Host execution and visual simulation | `Emulator/`, with model-specific renderer backends |
| Device identity, measured calibration, credentials, and runtime records | Per-device storage; private runtime data stays outside tracked source |

Motion logic and servo signal generation meet at a small output interface. The
shared logic applies lifecycle and safety rules before the board implementation
updates or disables outputs. The V2 PCA9685 implementation belongs with its
firmware target; there is no need to duplicate the gateway for it.

The native V2 target and portable command-admission boundary now exist.
[Step 1 evidence](v2-12servo/STEP1_EVIDENCE.md) records their tested limits.
The [V2 model](../Slave/software/models/v2-12servo/README.md) owns its walk trajectory,
eight finite turn trajectories and geometric joint definition. Per-body command
subsets use the same public names; the additional 15° turns require an explicit
body declaration. A shared V1/V2 actuator runtime and calibrated twelve-joint
execution remain later work, after output-disable hardware proof.

## Existing V1 Code to Separate

The existing code stays at its current build/import paths during this first
pass. The following owners identify the actual V1 assumptions for the next
code change:

| Current owner | V1-specific content |
| --- | --- |
| [protocol.h](../Slave/software/core/include/ainekio/protocol.h) | Eight-servo count, joint enum, and fixed-size motion/pose structures |
| [joints_v1.py](../Slave/software/protocol/joints_v1.py), [control_v1.py](../Slave/software/protocol/control_v1.py), and [schemas/](../Slave/software/protocol/schemas/) | Frozen joint order and eight-joint validation |
| [assets.c](../Slave/software/core/src/assets.c) and [seed assets](../Slave/software/assets/seed/) | Body-specific fallback poses and motion frames; faces/audio also currently reside in the seed tree |
| [ESP32-S3 platform](../Slave/firmware/esp32s3/components/ainekio_platform/) | V1 board pin map, motion service, and MCPWM driver |
| [translation.py](../Master/gateway/environment_adapter/translation.py) and [adapter server](../Master/gateway/environment_adapter/server.py) | One fixed semantic motion catalog and V1 joint translation |
| [dashboard server](../Master/gateway/dashboard/server.py) | Eight-servo calibration-neutral operation |
| [emulator body](../Emulator/emulator/body/) and [Sesame backend](../Emulator/emulator/backends/sesame.py) | V1 asset validation, portable-core integration, and visual motion mapping |

The [V2 firmware design](v2-12servo/FIRMWARE_DESIGN.md#recommended-implementation-order-and-acceptance)
places a small P4/C6/PCA9685 hardware proof before broad shared-code extraction.
Extract V1's model data and needed services in working steps that preserve its
behavior and protocol/core/firmware checks. Model-aware gateway capabilities and
the V2 motion implementation then use those owners. Reusable face and audio
assets can remain shared where their format and playback requirements match.

## Compatibility Rules

- Robot model, board target, firmware version, wire-protocol version, and joint-map
  version are separate identifiers. A V2 body does not automatically require
  protocol v2.
- Preserve V1's existing joint order and eight-joint wire/asset semantics. Do not
  change the global servo count to twelve or reinterpret V1 motion files for V2.
- Resolve model data and advertised capabilities for the selected robot. The
  gateway already identifies devices by robot ID; a device ID is not a model ID.
  Step 1 negotiates model/readiness. V2 now has geometric joint identities;
  electrical channel assignments and measured device calibration remain pending.
- V2 commands must reflect its implemented motions and available hardware. It
  must not inherit the complete V1 catalog just by authenticating.
- Keep each device's measured calibration associated with its model and joint
  map. The existing `home`/`tether` operating profiles are not robot models.

The [repository map](REPOSITORY_MAP.md) describes directories that exist now.
