# Slave

This folder contains the physical robot body and all code that belongs to it.

- `hardware/` contains CAD and physical-body assets.
- `software/` contains portable robot logic, safety, protocol, and host tests.
- `firmware/` contains platform firmware flashed to the robot.

The ESP32-S3 firmware entry point is
`firmware/esp32s3/main/app_main.c`. The portable control and safety core is
`software/core/` and is compiled into that firmware. Portable WiFi provisioning
state and the versioned NVS contract also live in `software/core/`.
