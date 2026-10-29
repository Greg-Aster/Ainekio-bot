# V1 robot specifications

Scope: `v1-8servo`, the eight-servo Sesame-based Ainekio body. For the companion's
purpose and maintenance method, start with the [robot design core](../../../metahuman/docs/robot/ROBOT_BIBLE.md).
For the other body, use the [V2 specifications](../v2-12servo/SPECIFICATIONS.md).

**Work status (owner-confirmed 2026-10-26): V1 work is paused; V2 is active.**

Source reconciliation: **2026-10-26**. This is the concise V1 hardware and
integration reference. **Source** means inspected code/configuration; **recorded**
means an existing owner or hardware-evidence record; **unknown** means that the
reviewed records do not establish the value. No hardware was measured or operated
for this document. Recorded installed facts retain their original evidence dates.

## Hardware

| Component | V1 specification | Basis and remaining uncertainty |
| --- | --- | --- |
| Body | Four-legged Sesame-based frame; eight servo outputs | V1 body/assets and [model boundaries](../ROBOT_MODELS.md); V2 geometry is not interchangeable |
| Controller | Freenove ESP32-S3-WROOM CAM, ESP32-S3-WROOM-1 N16R8 | Delivered-board record; exact PCB revision remains unrecorded |
| Memory | 16 MiB flash; 8 MiB octal PSRAM | Board profile and boot evidence; [pin-map owner](../../Slave/firmware/esp32s3/components/ainekio_platform/include/ainekio/platform/pin_map.h) |
| Servo output | Eight direct ESP32-S3 MCPWM outputs | Firmware source; no PCA9685 in the V1 output path |
| Servos | Eight MG90S listed in the parts record | Delivered variant, actual travel, torque/current and loaded tracking are not established by that list |
| Camera | Built-in OV3660 | Delivered marking and firmware identification in [V1 hardware evidence](HARDWARE_BRINGUP_CHECKLIST.md); older OV2640 planning text is superseded for this recorded board |
| Microphone | INMP441 I2S module | Listed part; firmware uses GPIO19 data-in, shared GPIO41/42 clocks; physical module/strap verification is separate |
| Audio output | MAX98357A amplifier; owner-confirmed 8 Ω, 2 W speaker | Recorded design; amplifier supplied from the electronics 5 V branch; physical audio quality and load remain separate evidence |
| Display | 0.96-inch SSD1306 I2C OLED; configured address `0x3C` | Parts record and board configuration; see [pinout diagnostics](PINOUT_DIAGNOSTICS.md) for the BOOT/UART pin handoff |
| Storage | Board microSD slot, SD_MMC one-bit bus; internal LittleFS and NVS | Firmware source; installed card capacity is device-specific |
| Battery sensing | GPIO3 ADC input through a recorded 100 kΩ / 47 kΩ divider and 0.1 µF filter | Nominal divider factor 3.12766; installed resistor values and voltage calibration require their own evidence |
| IMU / joint feedback | No installed V1 IMU or shaft-feedback system established in the reviewed V1 records | Do not inherit the V2 LSM6DS3 or feedback-multiplexer specification |

Detailed parts provenance and unresolved electrical measurements belong in
[HARDWARE_BRINGUP_CHECKLIST.md](HARDWARE_BRINGUP_CHECKLIST.md). The current firmware
entry point is [ESP32-S3 app_main.c](../../Slave/firmware/esp32s3/main/app_main.c);
its [firmware reference](../../Slave/firmware/esp32s3/README.md) owns implementation details.

## Geometry and dimensions

| Quantity | Established value / source |
| --- | --- |
| Overall length × width × height | Unknown in the reviewed maintained V1 specification and hardware records; a measured value must name the pose and included attachments |
| Leg/link dimensions and coordinate frames | No reconciled numeric V1 geometry table established here; [V1 CAD/print assets](../../Slave/hardware/v1-8servo/) and existing V1 motion assets are the source material |
| Assembled mass and center of mass | Unknown; do not substitute V2 or simulator values |
| Joint count/order | Eight, frozen order: `R1, R2, L1, L2, R4, R3, L3, L4` |
| Calibration and usable travel | Device-owned values; neither generic MG90S travel nor V2 calibration proves V1's installed range |

The [V1 joint contract](../../Slave/software/protocol/joints_v1.py) owns IDs and
ordering. The body model has not been extracted into a V2-style geometry package:
V1 assumptions still reside in the portable core, seed assets and S3 platform.
Use the [ownership map](../ROBOT_MODELS.md#existing-v1-code-to-separate) to locate
them. A simulator's coordinate scale is not an assembled-robot measurement.

## Joint and peripheral connections

Source: the [board pin map](../../Slave/firmware/esp32s3/components/ainekio_platform/include/ainekio/platform/pin_map.h),
cross-checked against [pinout diagnostics](PINOUT_DIAGNOSTICS.md).

| Joint ID | Label | Signal GPIO |
| --- | --- | --- |
| 0 | R1 | 1 |
| 1 | R2 | 2 |
| 2 | L1 | 14 |
| 3 | L2 | 21 |
| 4 | R4 | 47 |
| 5 | R3 | 48 |
| 6 | L3 | 45 |
| 7 | L4 | 46 |

- Audio: microphone DIN19, amplifier DOUT20, BCLK41 and WS42. GPIO19/20 are used
  for audio in this profile, so native USB data is unavailable through those pins.
- OLED: SDA0 after BOOT sampling; SCL43 after boot UART use. The existing display
  owner manages that handoff.
- SD: CMD38, CLK39, DAT0=40. Camera pins and octal-PSRAM pins remain allocated
  by the board owner; the old GPIO33/34 servo plan is invalid for this N16R8 board.
- Connector positions, camera pins, reset straps and electrical procedures remain
  in the pinout guide. GPIO numbers are not physical header-row numbers.

## Power

The [owner-recorded topology](HARDWARE_BRINGUP_CHECKLIST.md#owner-confirmed-power-topology)
uses a Sea Jump 2S 7.4 V nominal, 1000 mAh Li-ion battery, with separate MusRock
MINI560 PRO buck converters for the 5 V servo rail and 5 V electronics/amplifier
rail. The board's regulated 3.3 V feeds the microphone, OLED and other 3.3 V
devices; grounds are common. Servo load current uses its dedicated rail.

The converters' advertised 5 A rating is not measured continuous assembled-system
capacity. Battery protection/cutoff, loaded voltage drop, current, heating and
backfeed evidence remain in the hardware record. These are specification limits
and unknowns, not new firmware policies.

## Body Control and remote MetaHuman connections

```text
V1 ESP32-S3 -- Wi-Fi / authenticated robot WebSocket --> Body Control host
MetaHuman Environment Bridge -- local or tunneled WebSocket --> same Body Control
```

Both sessions are bidirectional. The robot initiates its connection to the
gateway's `/robot` route. MetaHuman initiates its connection to `/environment`;
that endpoint accepts loopback access at the gateway, including a tunnel ending
on that host. Body Control can run on a supported desktop or Q6A host; the V1 body
does not require the brain to be physically onboard.

| Interface | Default / ownership |
| --- | --- |
| Robot and Environment WebSockets | Gateway port `8790`; distinct `/robot` and `/environment` routes and authentication |
| Body Control dashboard | `127.0.0.1:8791` on the gateway host; browser access is not proof of a robot session |
| MetaHuman on the same host | Bridge connects to `ws://127.0.0.1:8790/environment` |
| MetaHuman on another host | Its existing forwarder uses the configured SSH or Cloudflare TCP route to gateway loopback; SSH can run over the configured WireGuard network |
| Pairing, tokens, addresses and calibration | Existing per-device/private configuration owners; credentials and installation-specific values are not copied into this specification |

The [gateway reference](../../Master/gateway/README.md#physical-robot-gateway-operation)
owns transport and pairing; MetaHuman's [connection owner](../../../metahuman/brain/agents/environment-bridge/connections.ts)
and [forwarder](../../../metahuman/brain/agents/environment-bridge/forwarder.ts)
own host selection and tunnel lifetime. Current source uses one Environment Bridge
with configured local/remote endpoints, not separate Local/Remote agents. A public
web portal and a remote model provider are separate connections from the body bridge.

The [protocol](../../Slave/software/protocol/README.md) and advertised body
capabilities own supported requests and receipts. Protocol-v1 does not mean every
body has eight joints. Preserve V1's joint/asset format when changing shared code.

## Maintaining this specification

Update the affected entry when hardware, geometry, wiring or a connection contract
changes; link its source and label design values versus physical evidence. Keep
firmware versions, installation status, benchmarks and repair narratives in their
existing dated records. The [documentation authority](../README.md) retains the
normative specification and hardware-evidence process; this file does not silently
amend their behavior policies. It introduces no new runtime restrictions.
