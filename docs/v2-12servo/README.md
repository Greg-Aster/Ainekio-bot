# V2: Twelve-Servo Robot

Start with [V2 Specifications](SPECIFICATIONS.md) for authoritative hardware, CAD geometry, pin assignments, power topology, and Body Control / Ainekio OS connection boundaries. **V2 (`v2-12servo`) is the active robot platform; V1 (`v1-8servo`) work is paused.**

## Hardware Summary

| Subsystem | V2 Component | Details & Owner |
| --- | --- | --- |
| Controller | Waveshare ESP32-P4-WIFI6 (P4 rev 1.3, 32 MiB flash, 32 MiB PSRAM, onboard ESP32-C6 Wi-Fi 6 over SDIO) | [Manufacturer docs](https://docs.waveshare.com/ESP32-P4-WIFI6) · [ESP32-P4 firmware README](../../Slave/firmware/esp32p4-wifi6/README.md) |
| Servo PWM | PCA9685 16-channel PWM breakout (`0x40` on I2C1 GPIO2/3, active-low `OE` on GPIO4; channels 0–11 used) | [PCA9685 wiring](PCA9685_WIRING.md) · [NXP datasheet](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf) |
| Actuators & Feedback | Twelve Miuzei MG90S servos modified with 4th-wire wiper leads into a CD74HC4067 16-channel multiplexer (select GPIO27–30, ADC2 ch 0) | [Socket & feedback map](SERVO_SOCKET_MAP.md) · [Servo assembly](../../Slave/software/models/v2-12servo/SERVO_ASSEMBLY.md) |
| Attitude IMU | Two-hole GY-LSM6DS3 6-axis IMU (`0x6A` on shared I2C0 GPIO7/8) | [LSM6DS3 wiring & calibration](LSM6DS3_IMU.md) |
| Vision & Storage | OV5647 5 MP MIPI-CSI camera, internal NVS, and microSD card slot for rolling clips and firmware backups | [ESP32-P4 firmware README](../../Slave/firmware/esp32p4-wifi6/README.md) · [LCD & camera notes](LCD_FACE.md) |
| Audio | Onboard ES8311 codec/microphone, NS4150B speaker amplifier, and 8 Ω / 2 W 20 × 30 × 6.66 mm speaker | [Speaker output](../../Slave/firmware/esp32p4-wifi6/README.md#speaker-output) · [Resource budget](RESOURCE_BUDGET.md) |
| Face Display | XIITIA 1.9-inch ST7789 SPI LCD (`320 × 170` landscape on SPI GPIO20/21/22/23/26) | [LCD face design](LCD_FACE.md) |
| Power | 2S Li-ion pack (8.4 V full), Mini560 5 V / 5 A servo buck converter, HiLetgo 2S USB-C charger | [Electrical connections & power](SPECIFICATIONS.md#electrical-connections-and-power) |

## Wiring Guides

- [Combined connection table and resolved pin assignments](ASSEMBLY_REFERENCE.md) · [Combined diagram](Assembly_Reference.png)
- [ESP32-P4 header pinout (PNG)](ESP32P4_Pinout.png) · [Editable pinout (SVG)](ESP32P4_Pinout.svg)
- [Servo-to-PCA9685 socket and multiplexer channel map](SERVO_SOCKET_MAP.md) · [Diagram](Servo_Socket_Map.png)
- [Multiplexer-to-P4 wiring diagram](Multiplexer_Wiring.png)
- [PCA9685 wiring table and servo power rail](PCA9685_WIRING.md) · [Diagram](PCA9685_Wiring.png)
- [LSM6DS3 IMU wiring, mounting axes, and calibration](LSM6DS3_IMU.md) · [Diagram](LSM6DS3_Wiring.png)

Remove power before adding or moving servo, power, or multiplexer connectors. Follow the [ESP32-P4 startup and assembly guide](../../Slave/firmware/esp32p4-wifi6/README.md#startup-and-assembly) when bringing up or remounting joints.

## Design Assets

[`Slave/hardware/v2-12servo/`](../../Slave/hardware/v2-12servo/) holds the working Blender assembly (`Ainekio-Motion-Working.blend`), recovery checkpoints ([`CHECKPOINTS.md`](../../Slave/hardware/v2-12servo/CHECKPOINTS.md)), STEP/STL/GLB exports, and component reference models. Keep CAD edits and exports inside that directory.

## Firmware, Motion, and Host Stack

- **ESP32-P4 firmware** ([`Slave/firmware/esp32p4-wifi6/`](../../Slave/firmware/esp32p4-wifi6/README.md)): Implements `protocol-v1` over Wi-Fi 6 (`ESP32-C6` SDIO), PCA9685 output supervision with 3-minute local `lay_down` inactivity rest, 20 ms 12-joint potentiometer feedback (`servo_feedback_v1`) with recovery-first stall reporting, IMU attitude estimation and `balance_control_v1` self-leveling, adaptive OV5647 stills/preview with SD rolling clips, OTA firmware updates, `microWakeWord` voice gating, and layered ST7789 face expressions (`face_feedback_v1`).
- **Kinematic model, clips, and embedded Microduck gait** ([`Slave/software/models/v2-12servo/`](../../Slave/software/models/v2-12servo/README.md)): Owns the closed 4-bar linkage geometry (`35 / 20 / 28 / 38 / 55 mm`), 23 active finite postures/gestures compiled to compact cubic segments, analytic `Walk` / `Run` / `Crawl` / `Crab` gaits with composed steering (`walk_steering_v1`), and the compiled on-board `v2_microduck` PPO neural gait policy (`motions/microduck/policy.bin`).
- **Body Control gateway & neural simulation** ([`Master/gateway/`](../../Master/gateway/README.md)): Runs on a workstation or Radxa Dragon Q6A (`Master/run-physical-gateway.sh` / `Master/stop-physical-gateway.sh`), providing the Body Control cockpit (`127.0.0.1:8791`), host MuJoCo/MJX simulation and neural policy service (`127.0.0.1:8796`), continuous camera object/face recognition, and the `/environment` bridge to Ainekio OS.
- **12-joint Freestyle choreography** ([`experiments/freestyle/`](../../experiments/freestyle/README.md)): Generates natural-language 12-joint `motion_plan` sequences via local Qwen LoRA or Big Brother cloud inference, validated through closed-chain IK and executed on the P4 controller.
- **Calibration and qualification**: `servo_profile.json` defines the `300–3000 µs` authoring window and non-inverted mounting references (`1650 µs` shoulder, `856 µs` carrier, `723 µs` crank; reindexed crank walk profile in [`SERVO_ASSEMBLY.md`](../../Slave/software/models/v2-12servo/SERVO_ASSEMBLY.md)). Per-device pulse mapping and 4th-wire ADC curves live in NVS via Body Control calibration (`body_calibration_v2`). Keep source/simulation verification distinct from loaded physical hardware qualification; see [Walking System](WALKING_SYSTEM.md) and [Gait Research Journal](GAIT_RESEARCH_JOURNAL.md) for current locomotion status.
