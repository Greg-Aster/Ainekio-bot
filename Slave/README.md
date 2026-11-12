# Slave

This folder contains the physical robot bodies and all firmware, kinematics, protocol, and hardware assets that belong to them.

- `hardware/v1-8servo/` — V1 eight-servo body CAD, Blender parts, and printable STLs.
- `hardware/v2-12servo/` — V2 twelve-servo body Blender snapshots, reference models, and printable STLs.
- `software/core/` — Portable C control, command admission, NVS configuration, and safety logic shared across firmware targets.
- `software/protocol/` — Machine-checkable `protocol-v1` control and binary media contract shared with `Master/gateway/`.
- `software/imu/` & `software/faces/` — Portable LSM6DS3/Fusion attitude estimator and LCD/OLED face asset libraries.
- `software/models/v2-12servo/` — V2 closed-chain kinematics, postures, analytic locomotion (`walk`, `run`, `crawl`, `crab`), self-leveling balance, gesture clips, and embedded `microduck` neural policy inference.
- `firmware/esp32s3/` — V1 (`v1-8servo`) ESP32-S3 platform firmware (`main/app_main.c`).
- `firmware/esp32p4-wifi6/` — V2 (`v2-12servo`) Waveshare ESP32-P4-WIFI6 firmware (`main/app_main.c`), PCA9685 50 Hz servo output owner, fourth-wire ADC feedback, OV5647 camera/SD recorder, ES8311 audio/wake word, ST7789 display, and Wi-Fi OTA maintenance.

See [Robot Models](../docs/ROBOT_MODELS.md) for model separation and [Slave/software/protocol/README.md](software/protocol/README.md) for the wire contract.
