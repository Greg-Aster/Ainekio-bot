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
| Servo signal driver | HUAREW PCA9685 16-channel PWM breakout, [Amazon B0CRV3MK14](https://www.amazon.com/dp/B0CRV3MK14), supplied by the owner. The listing advertises an output-enable pin; delivered wiring is unverified. Chip reference: [NXP datasheet](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf). |

The robot has twelve joints even though the driver provides sixteen channels.
The actual P4 is revision 1.3 with 32 MiB flash and 32 MiB PSRAM. The native target
assigns a dedicated PCA bus to GPIO2/3 and OE to GPIO4; delivered wiring is not
verified. The exact PCA9685 breakout revision and OE/pull-up wiring, joint-to-channel
assignments, MG90 variant/specifications, calibration, and V2 power wiring remain
pending. V1's GPIO map, poses, and power records do
not supply those values.

## Wiring Guides

- [P4 pinout image](ESP32P4_Pinout.png)
- [PCA9685 connection image](PCA9685_Wiring.png)
- [Wiring table, sources and first multimeter checks](PCA9685_WIRING.md)

The guides match the native firmware's GPIO2/3/4 assignments. Keep servo V+
and all servo plugs disconnected; OE reset bias remains unverified.

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
the initial real PCA9685 driver, disabled startup, diagnostic entry points,
matched C6 networking and shared command admission. It has been built and flashed;
read the [Step 1 evidence](STEP1_EVIDENCE.md) before treating any hardware behavior
as verified. **Step 1 is not accepted; PWM/OE electrical evidence is missing.**

The optional Q6A deployment, controller-selection boundary and future native USB
reservation are documented in the firmware design. No Q6A services are implemented.
The [V2 model](../../Slave/software/models/v2-12servo/README.md) contains the
compiled twelve-joint walk, turn and gesture samplers. The
[2026-09-17 integration record](MOTION_INTEGRATION_20260917.md) covers all 30 motions,
the successful software checks, and the pending `0.4.0-p4-motions` flash with its
larger application partition. Calibrated physical execution,
joint calibration and the V2 simulator remain pending. The shared gateway
negotiates model/readiness and does not advertise unimplemented P4 motion/media.
