# ESP32-S3 Firmware Port

This directory is the ESP-IDF platform composition root for the Ainekio slave
brain. Portable command, state, lifecycle, and safety behavior remains in
`../../software/core`; ESP32-S3 networking, storage, tasking, and hardware integrations
belong in this platform port.

## Toolchain

- ESP-IDF v5.5.4
- Target: ESP32-S3 N16R8 (16 MB flash, 8 MB PSRAM)
- Project defaults: size optimization, dual 3 MB OTA slots, 9.875 MiB LittleFS

The board-mounted microSD slot is implemented through a dedicated low-priority
SD task. GPIO 38 (CMD), GPIO 39 (CLK), and GPIO 40 (DAT0) belong exclusively to
SD_MMC in 1-bit mode and must not be assigned to servos, audio, display, sensors,
or other accessories. The service mounts without card-detect, retries on demand,
uses bounded CRC-protected rolling logs, repairs torn tails, and applies capture
retention without blocking motion or network tasks.

FreeRTOS is included with ESP-IDF. Do not install or vendor it separately.

## Build

```bash
source /home/greggles/esp/esp-idf-v5.5.4/export.sh
idf.py set-target esp32s3
idf.py build
idf.py size
idf.py size-components
```

Run these commands from `Slave/firmware/esp32s3`. The checked-in Freenove N16R8
profile enables 8 MB octal PSRAM at 80 MHz and pins `esp32-camera` 2.1.7. No WiFi
credentials or other secrets belong in `sdkconfig`, NVS images, build logs, or
committed source.

The current cross-built port includes the portable safety core, MCPWM motion,
LittleFS assets, NVS configuration and migration, WPA2 SoftAP provisioning,
outbound protocol-v1 WebSocket runtime, full-duplex I2S audio/microphone, SSD1306
display, ADC battery safety, SD_MMC storage, deep sleep, and OTA rollback
validation after gateway authentication. The OV2640 camera path now supports
QVGA/VGA JPEG snapshots and bounded streaming when the sensor and expected PSRAM
initialize; commands still reject explicitly if the physical camera is
unavailable.

The audio service also includes a real microWakeWord/TensorFlow Lite Micro
backend. It loads `/assets/wake/<model>/manifest.json` plus its quantized TFLite
model, verifies the package and tensor contract, and reports ready only after the
interpreter and frontend initialize. No trained `Ainekio` weights are checked in,
so the current seed image safely reports `wake_ready=false`. See
`../../../docs/LOCAL_WAKE_WORD.md` for the owner-local training and packaging
workflow.

The central MAP_B definition is
`components/ainekio_platform/include/ainekio/platform/pin_map.h`. It preserves
SD_MMC and the specification's provisional GPIO33/34 servo assignments. Software
checks detect definite duplicate, capability, SD, GPIO35-37 PSRAM, and MCPWM
conflicts, but only physical H2 can accept or reject GPIO33/34. Battery
monitoring is enabled on GPIO3 with the planned `3.12766` divider factor; H9
still refines its ADC correction against a multimeter. Per the owner's bring-up
decision, all eight servo outputs are enabled after startup at their calibrated
centers with a 20 ms channel stagger. Normal semantic
motions and calibration commands use 25 percent of the source range around
logical center (`67.5`-`112.5` degrees) and a 100 ms minimum frame duration.
`stop` still returns every servo signal GPIO to high impedance.
