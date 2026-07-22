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
validation after gateway authentication. The OV3660 camera path now supports
QVGA/VGA JPEG snapshots and bounded streaming when the sensor and expected PSRAM
initialize; commands still reject explicitly if the physical camera is
unavailable.

Provisioning uses one stable eight-character device key as the
`Ainekio-Setup` WPA2 password. The key is stored separately from replaceable
network configuration and survives normal reboots and WiFi changes. After a
client joins the setup AP, `http://192.168.4.1/` opens the configuration form
directly; there is no duplicate portal password. Requests arriving from the
normal station LAN are excluded by binding accepted setup sessions to the AP
network interface. The OLED shows the setup key/address before configuration and
the joined SSID, DHCP address, and gateway state afterward.

The audio service also includes a real microWakeWord/TensorFlow Lite Micro
backend. It loads `/assets/wake/<model>/manifest.json` plus its quantized TFLite
model, verifies the package and tensor contract, and reports ready only after the
interpreter and frontend initialize. No trained `Ainekio` weights are checked in,
so the current seed image safely reports `wake_ready=false`. See
`../../../docs/LOCAL_WAKE_WORD.md` for the owner-local training and packaging
workflow.

The central MAP_B definition is
`components/ainekio_platform/include/ainekio/platform/pin_map.h`. Delivered
hardware rejected GPIO33/34 because the N16R8 octal PSRAM owns GPIO33-37. The
board-only remap moves servos R4/R3 to GPIO47/48 and moves the OLED bus to
GPIO0/43. GPIO0 remains the reset-time BOOT strap and long-press input; GPIO43
carries boot-time UART output before the display driver takes ownership. SD_MMC,
camera, audio, battery sensing, and all eight independent MCPWM channels remain
allocated. The onboard RGB LED is unavailable while GPIO48 drives its servo.

Battery monitoring remains enabled on GPIO3 with the planned `3.12766` divider
factor; H9 still refines its ADC correction against a multimeter. Three
consecutive startup readings at or below `0.25 V` are classified as a
disconnected battery so USB-only operation remains awake. Once any plausible
battery voltage has been observed, that exception latches off and a later
near-zero reading follows the normal cutoff path. All eight servo outputs are
enabled in the checked full-feature configuration. The existing 25 percent
range, 100 ms minimum frame duration, staggered centering, N16R8 PSRAM-pin
guard, and high-impedance stop behavior remain active.
