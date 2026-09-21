# Slave

This folder contains the physical robot body and all code that belongs to it.

- `hardware/v1-8servo/` contains the existing eight-servo body's CAD and parts.
- `hardware/v2-12servo/` contains the twelve-servo body's design assets.
- `software/` contains portable robot logic, safety, protocol, and host tests.
- `firmware/esp32s3/` contains the current V1 platform firmware.
- `firmware/esp32p4-wifi6/` contains the native V2 bring-up target and PCA9685 driver.

The ESP32-S3 firmware entry point is
`firmware/esp32s3/main/app_main.c`. The portable control and safety core is
`software/core/` and is compiled into that firmware. Portable WiFi provisioning
state and the versioned NVS contract also live in `software/core/`.

The portable core and protocol currently include V1's eight-joint assumptions.
The approved [model separation](../docs/ROBOT_MODELS.md) keeps reusable control
logic here and assigns each body's joints, poses, and motions to its own model.
V2 command admission and board/network bring-up are implemented. Model extraction,
twelve-joint motion and hardware acceptance remain pending; see the
[Step 1 evidence](../docs/v2-12servo/STEP1_EVIDENCE.md).
