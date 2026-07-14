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

Run these commands from `Slave/firmware/esp32s3`. The checked-in defaults do not yet
enable PSRAM because the exact module and board wiring must be confirmed during
hardware bring-up. No WiFi credentials or other secrets belong in `sdkconfig`,
NVS images, build logs, or committed source.

The current cross-built port includes the portable safety core, MCPWM motion,
LittleFS assets, NVS configuration and migration, WPA2 SoftAP provisioning,
outbound protocol-v1 WebSocket runtime, full-duplex I2S audio/microphone, SSD1306
display, ADC battery safety, SD_MMC storage, deep sleep, and OTA rollback
validation after gateway authentication. Camera capture remains disabled until
the H2 board/sensor/pin evidence exists; camera-on and snapshot requests reject
explicitly instead of claiming success.
