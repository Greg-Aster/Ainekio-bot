# ESP32-P4-WIFI6 Body Firmware

`Slave/firmware/esp32p4-wifi6/` owns the production RTOS firmware for the twelve-servo V2 Ainekio body (`Waveshare ESP32-P4-WIFI6`, P4 revision 1.3, 32 MiB flash, 32 MiB PSRAM, onboard `ESP32-C6` Wi-Fi 6 over SDIO).

## Architecture Overview

| Module | Responsibility |
| --- | --- |
| `main/board.c` | Single owner of the I2C1 PCA9685 bus (`0x40`, GPIO2/3) and active-low `OE` pin (GPIO4). |
| `main/body.c` & `controller_motion.c` | 50 Hz servo output supervision, staggered rise, closed-chain V2 gaits/gestures, `motion_plan_v2` Freestyle execution, embedded `v2_microduck` neural gait, and IMU balance leveling. |
| `main/servo_feedback.c` & `servo_feedback_position.c` | 16-channel `CD74HC4067` multiplexer scanning (GPIO27–30, `ADC2` ch 0), calibrated shaft-angle conversion, arrival verification, and recovery-first stall telemetry. |
| `main/idle_rest.c` | Configurable local inactivity timer (`idle_rest_v1`, default 180 s) executing built-in `lay_down` and releasing `OE` on completion. |
| `components/ainekio_p4_media/` | OV5647 MIPI-CSI camera (`camera.c`), 208 Hz LSM6DS3 IMU acquisition & attitude estimator (`imu.c`), ES8311/NS4150B audio playback, and `microWakeWord` / VAD capture (`media.c`). |
| `main/display.c` & `face_timeline.c` | ST7789 `320 × 170` SPI LCD driver with independent foreground and background expression layers (`face_feedback_v1`). |
| `main/network.c`, `gateway_selection.c`, & `portal.c` | ESP-Hosted C6 SDIO networking, outbound `/robot` WebSocket with partial-write/backpressure recovery, 4-slot `gateway_switching_v1` + DNS-SD discovery, and WPA2 setup AP (`192.168.4.1`). |
| `main/storage.c`, `video_avi.c`, & `ota.c` | microSD card management (`storage_control_v1`), rolling AVI clip recording with oldest-clip rotation, and dual-slot (`ota_0`/`ota_1`) Wi-Fi application OTA with rollback verification. |

## Resource ownership

`main/board.c` initializes the dedicated PCA9685 bus and owns `OE`. Callers operate through the board output driver and never open a second I2C handle or toggle `OE` directly.

| Resource | Assignment / Reservation |
| --- | --- |
| PCA9685 PWM | I2C1, `SDA` GPIO2, `SCL` GPIO3, address `0x40`, 400 kHz; active-low `OE` on GPIO4 |
| 4th-wire feedback mux | `CD74HC4067` select `S0–S3` on GPIO27/28/29/30; analog input on `ADC2` channel 0 (channels `C4–C15` map joints `0–11`) |
| Face display | 1.9-inch ST7789 LCD on SPI2: `SCLK` GPIO20, `MOSI` GPIO21, `CS` GPIO22, `DC` GPIO23, `RESET` GPIO26; `VCC`/`BLK` on 3V3 |
| IMU & onboard codec I2C | Shared I2C0 on `SDA` GPIO7, `SCL` GPIO8 (`LSM6DS3` at `0x6A`, `ES8311` codec, camera SCCB) |
| ESP32-C6 SDIO link | `CLK` GPIO18, `CMD` GPIO19, `D0–D3` GPIO14–17, slave reset GPIO54; C6 boot GPIO6 reserved |
| Debug console | UART on GPIO37/38 via onboard `CH343P` USB Type-C port (`115200` baud) |
| Reserved interfaces | Native USB HS (`P1` MX1.25; VBUS tied to 5 V rail), USB FS GPIO24/25, boot GPIO35, SDMMC GPIO39–45, I2S GPIO9–13, PA enable GPIO53, MIPI CSI lanes |

Header positions (`L/R` top-down rows with USB-C up) differ from chip GPIO numbers; see [PCA9685 wiring](../../../docs/v2-12servo/PCA9685_WIRING.md) and [V2 assembly reference](../../../docs/v2-12servo/ASSEMBLY_REFERENCE.md) before wiring hardware.

## Startup and assembly

Power off the servo rail and USB before connecting or moving servo plugs or indexing horns. Feed PCA9685 `V+` from the dedicated 5 V servo buck converter sharing common ground with the ESP32-P4; keep `VCC` on 3.3 V logic and never join two +5 V supplies.

- **Joint & channel order**: Physical leg order is rear-left (`0–2`), rear-right (`3–5`), front-left (`6–8`), front-right (`9–11`), with `[shoulder, carrier, crank]` in each triple (see [V2 socket & feedback map](../../../docs/v2-12servo/SERVO_SOCKET_MAP.md) and [SERVO_ASSEMBLY.md](../../software/models/v2-12servo/SERVO_ASSEMBLY.md)).
- **Saved calibration (`p4_config/joint_mapping`)**: Stores 12 compact 12-byte records (`channel`, `home_us`, `invert`, `home_cd`, `us_per_degree`) in NVS via Body Control's `body_calibration_v2` service. Missing or invalid calibration keeps startup PWM outputs off until calibrated.
- **Staggered Stand & 4th-wire verification**:
  - Rising from detached outputs (`Stand`) staggers front and rear leg pairs by 100 ms (fold at `0/100 ms`, shoulders at `600/700 ms`, 1.2 s body rise at `1200/1300 ms`), verifies 4th-wire shaft arrival at each lift/placement landmark and terminal goal when calibrated feedback is active, and finishes with a 2 mm / 200 ms body-lift settle. Fault/brownout/panic resets inhibit automatic power-on rise until an explicit `Stand`.
  - **Recovery-first stall handling**: When 4th-wire sensing detects shaft non-progress, firmware emits `servo_stall` (`outputs_released: false`, model `joint_mask`) without cancelling the command or dropping `OE`, allowing host Freestyle recovery to intervene. Explicit `disable`, `stop` (`detach: true`), 4-second control silence, and I2C driver faults still disable `OE` immediately.
  - **Local inactivity rest (`idle_rest_v1`)**: After the saved idle interval (default 3 minutes; `0` disables), a single one-shot timer triggers built-in `lay_down` and releases `OE` once completed. Active motion, speech playback, and listening defer rest.

## Camera, Audio, Display, and Storage

### OV5647 Camera
- **Profiles**: Advertises `camera_profiles_v1`, `camera_adaptive_v1`, and `camera_motion_exposure_v1`. Preview streams `QVGA` or `VGA` (`0–15 fps`) from the `1280×960` binned sensor mode; stills support `QVGA`, `VGA`, `XGA`, full-field `960P` (`1280×960`), cropped `FHD` (`1920×1080`), and `AUTO` (meters in `960P` and switches to `FHD` in bright scenes). All frames rotate 180° before hardware JPEG encoding (quality 75, 256 KiB transport ceiling) to match the inverted physical camera mount, and stream in 4,096-byte `0x03` chunks interleaved with audio.
- **Metering & AWB**: Uses sensor-native AEC/AGC (`46/255` brightness target) and sensor-native AWB ahead of a neutral-preserving ISP color matrix (preventing P4 rev 1.3 `esp_video` magenta highlight clipping). Optional `max_exposure_us` caps automatic shutter integration in whole sensor lines to reduce motion blur during walking trials while leaving AGC automatic.

### Speaker output
- **Playback & saved master volume**: `ES8311` codec runs at unity output (`100`) and scales 16 kHz PCM frames by the saved NVS master volume (`p4_media/spk_volume`, `0–100%`, set via Body Control's `speaker` command and reported in heartbeat `audio.speaker_volume_percent`). Applies to streamed TTS, local LittleFS sound assets, and dashboard test tones.
- **Wake word & microphone capture**: Runs on-device `microWakeWord` (`p4_mic` task, 10 KiB stack) with configurable ES8311 `gain_db` (`0–42 dB`), `vad_mode` (`0–4`), `silence_ms`, `max_recording_ms`, and saved wake `threshold`. Wake-triggered utterances (`>= 300 ms`) emit `vad_open` + `wake_word` in-band with the PCM FIFO and queue a correlated `origin: "audio"` camera snapshot on `vad_close`. Heartbeat `external_speech` notifications temporarily suppress mic capture and wake triggers while host or Bluetooth speakers play TTS.

### Layered LCD Face & SD / OTA Maintenance
- **Foreground & background expressions**: `display.c` maintains independent foreground and background `face_feedback_v1` slots (`token`, `if_token`, `timeout_ms`, `background: true`). Background states (such as `thinking`) yield to foreground reactions (`be_*`), speech, and motion cues without clobbering active tokens.
- **SD storage & OTA**: `partitions-full.csv` allocates `NVS` (`0x9000`), `PHY` (`0xf000`), `otadata` (`0x10000`), dual 8 MiB app slots `ota_0` (`0x20000`) and `ota_1` (`0x820000`), and `LittleFS` (`0x1020000`) for local audio/wake assets. Body Control uploads and activates firmware over Wi-Fi with automatic rollback protection and manages rolling microSD AVI recordings via `storage_control_v1` (see [RECORDING_OTA.md](RECORDING_OTA.md)).

## Console Diagnostics

Connect a 115200-baud serial monitor to the Type-C `CH343P` debug port (`ainekio-p4>` prompt; opening serial DTR/RTS may reset the board):

| Command | Behavior |
| --- | --- |
| `board` / `system` / `controller` | Chip revision, pin/driver state, profile (`home`/`tether`), heap, OTA/SD status, and gateway session/epoch readiness |
| `imu` / `imu probe` / `imu sample` / `imu watch` / `imu body` | 208 Hz LSM6DS3 status, sensor-axis snapshots, and body-frame `m/s²` + `rad/s` readouts |
| `imu calibration` / `imu calibration set r00..r22 bx by bz` | Read or write sensor-to-body rotation matrix and gyro bias in `p4_imu/cal_v1` |
| `face` / `face list` / `face <name>` / `face auto` | LCD diagnostics, expression catalog, manual preview, or automatic motion-driven restore |
| `gait walk <cycles> <ms> [speed \| stride rate]` / `gait <clip> <ms>` | Dry-run V2 gait or finite clip kinematics without driving PWM |
| `disable` / `home` / `config home [ch pulse\|off]` | Immediate `OE` latch disable, staggered Home resume, or NVS Home pulse inspection/update |
| `net` / `net ap` / `net retry` / `net key` / `net reset` | C6 Wi-Fi status, WPA2 setup AP (`http://192.168.4.1/`), setup key readout, or Wi-Fi slot reset |
| `config <ssid> <psk> <url> <robot-id> <token>` / `config controller <url>` | Provision Wi-Fi + `/robot` WebSocket endpoint (`ws://HOST:8790/robot` or `wss://...`) |
| `system storage retry` / `system storage clear` / `system restart` | Remount SD card, clear bounded Ainekio logs/captures, or drain services and reboot |

## Build and flash

Requires **ESP-IDF 5.5.4** targeting `esp32p4` (pre-3.0 silicon revision 1.3 in `sdkconfig.defaults`, pinned `esp_hosted` `2.12.8`, `esp_wifi_remote` `1.6.4`, `esp_websocket_client` `1.7.0`). Always `source` the full ESP-IDF `export.sh` before configuring or building so `ESP_IDF_VERSION` Kconfig symbols resolve properly. If regenerating `sdkconfig` from `sdkconfig.defaults`, remove any stale local `sdkconfig` first.

```bash
source /path/to/esp-idf-v5.5.4/export.sh
cd Slave/firmware/esp32p4-wifi6
idf.py -B build -D IDF_TARGET=esp32p4 -D AINEKIO_C6_IMAGE= build
idf.py -B build -p /dev/serial/by-id/<your-ch343-port> -b 460800 app-flash
idf.py -B build -p /dev/serial/by-id/<your-ch343-port> monitor
```

- **ESP32-C6 coprocessor image (optional maintenance only)**: Normal builds pass `-D AINEKIO_C6_IMAGE=` when the onboard C6 already runs Hosted `2.12.8`. To embed and run an SDIO coprocessor update (`net c6-update`), first run `bash tools/build_c6.sh` and pass `-D AINEKIO_C6_IMAGE="$PWD/build/c6/network_adapter.bin"`.
- **Host unit & native driver tests** (executed on workstation without hardware):
  ```bash
  # PCA9685 C driver suite
  cmake -S Slave/firmware/esp32p4-wifi6/components/ainekio_pca9685 -B /tmp/ainekio-p4-driver-tests
  cmake --build /tmp/ainekio-p4-driver-tests -j4
  ctest --test-dir /tmp/ainekio-p4-driver-tests --output-on-failure

  # Full native P4 body/camera/feedback/gait suite (see Slave/software/models/v2-12servo/README.md)
  PYTHONPATH=Master:Slave/software:. python3 -m unittest tests.test_p4_audio_transport -v
  ```
