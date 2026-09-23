# V2: Twelve-Servo Robot

V2 is a second Ainekio body developed alongside the existing eight-servo V1.
The owner confirmed the following hardware selection on 2026-09-15.

## Selected Hardware

| Item | Selection and source |
| --- | --- |
| Body | Twelve servos in the new frame; owner-confirmed |
| Controller | ESP32-P4-WIFI6 development board, based on ESP32-P4 with an ESP32-C6 for wireless connectivity; [manufacturer documentation](https://docs.waveshare.com/ESP32-P4-WIFI6) |
| Purchased listing / kit selection | [Amazon B0FLXX1BZ6](https://www.amazon.com/dp/B0FLXX1BZ6), listed with an OV5647 camera and speaker; this records the listing, not installed peripheral evidence |
| Servos | Twelve MG90 servos; owner-confirmed designation. Exact variant and supplier, pulse limits, and measured calibration remain pending. |
| Servo signal driver | HUAREW PCA9685 16-channel PWM breakout, [Amazon B0CRV3MK14](https://www.amazon.com/dp/B0CRV3MK14), supplied by the owner. Used as a standard PCA9685 breakout; the owner confirmed channel-0 servo movement on 2026-09-22. Chip reference: [NXP datasheet](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf). |

The robot has twelve joints even though the driver provides sixteen channels.
The actual P4 is revision 1.3 with 32 MiB flash and 32 MiB PSRAM. The native target
assigns a dedicated PCA bus to GPIO2/3 and OE to GPIO4. Channel-0 movement is
confirmed; physical joint assignments, horn indexing, travel calibration and
multi-servo power capacity remain to be established. V1 poses and calibration
do not supply those values.

## Wiring Guides

- [P4 pinout image](ESP32P4_Pinout.png)
- [PCA9685 connection image](PCA9685_Wiring.png)
- [Wiring table, sources and servo power](PCA9685_WIRING.md)

The guides match the native firmware's GPIO2/3/4 assignments. Remove power
before adding or moving connectors. See the normal firmware's startup procedure
for connecting servos one at a time.

## Design Assets

[Slave/hardware/v2-12servo/](../../Slave/hardware/v2-12servo/) contains the
existing STEP sources, Blender assemblies and backups, GLB conversions, STL
exports, and source archive. Original filenames and the internal directory
structure are preserved. Use this model directory for all opens, saves, and
exports.

## Software Status

The [firmware review and implementation design](FIRMWARE_DESIGN.md) records the
V1 source findings, P4 platform research, and recommended implementation stages.
It specifies proposed timing/fault contracts and starts with P4/C6/output-disable
hardware checks, followed by supported motion before complete media integration.
It develops the [approved code boundaries](../ROBOT_MODELS.md).
The [native P4 target](../../Slave/firmware/esp32p4-wifi6/README.md) now contains
the PCA9685 driver, automatic startup home, matched C6 networking and shared
command admission. Normal power-on starts channels 0–11 at saved pulses,
200 ms apart; the current source default is the 1300 µs selected assembly reference. The laying pose is
updated in both Blender and the exported rest source: the chassis base
plate and all four lower legs rest on the floor. Midpoint and a calibrated body rest pose are
separate until horn indexing and joint calibration are established. Temporary
bench commands and fault injection have been removed. See the firmware README
for normal operation and the historical [Step 1 evidence](STEP1_EVIDENCE.md) for
earlier measurements and unmeasured electrical behavior.

The optional Q6A deployment, controller-selection boundary and future native USB
reservation are documented in the firmware design. No Q6A services are implemented.
The [V2 model](../../Slave/software/models/v2-12servo/README.md) contains the
variable forward gait with automatic Speed and advanced stride/cadence controls,
plus 29 finite motions regenerated for the same current leg and sole geometry.
The Blender project includes a separate **Motions - Current Geometry** scene
with all 30 motions and a selector for individual commands. The gait is integrated through
`walk_controls_v1`; walking and gesture execution remain disabled. The
[2026-09-17 integration record](MOTION_INTEGRATION_20260917.md) covers all 30 motions,
the successful software checks, and the migration to the larger application partition. Calibrated physical execution,
joint calibration and the V2 simulator remain pending. The shared gateway
negotiates model/readiness and does not advertise unimplemented P4 motion/media.

## Servo range and assembly update

The current servo profile uses the observed 300–2900 µs span, a selected1300µs reference, and geometry-derived mounting offsets. Actual angular travel is still unmeasured. Follow the [twelve-joint assembly guide](../../Slave/software/models/v2-12servo/SERVO_ASSEMBLY.md). Original gait and motion sources are restored unchanged. The separate internal-leg clearance audit flags unresolved conflicts; these need owner review before assembly. Existing deployed firmware evidence below the current design tracker refers to the previous application.
