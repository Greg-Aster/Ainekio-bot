# V3 robot specifications

Scope: `v3-12servo`, the larger twelve-servo Komatsu industrial-shell Ainekio V3
body with onboard compute and DS3225 PRO high-torque coreless servos. For the
companion's purpose and maintenance method, start with the
[robot design core](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/ROBOT_BIBLE.md).
For the other bodies, use [V1 specifications](../v1-8servo/SPECIFICATIONS.md) or
[V2 specifications](../v2-12servo/SPECIFICATIONS.md).

Source reconciliation: **2026-11-22**. **Source** means inspected CAD/code/configuration;
**estimated** means computed from CAD volumes and datasheets without physical
measurement. Physical assembly, weighing, calibration, and floor bring-up remain
pending (`mass_measured: false`, `physical_qualified: false`).

## Hardware (`v3-p4-ds3225pro-optA1-ankle-20261122`)

| Component | V3 specification | Basis and remaining uncertainty |
| --- | --- | --- |
| Body | Larger four-legged twelve-servo quadruped with Komatsu industrial shell, Option A-1 4-bar closed-chain legs, PETG knee flat spiral spring (`~0.167 N·m/rad`), preloaded bidirectional PETG servo-saver connecting rod (`~22 N`, `±1.3 mm`), and 2-stage double-parallelogram self-leveling pivoting crawler foot (`1:1` flat sole + outboard compliant ankle damper) | CAD source `Slave/hardware/v2-12servo/v3-2.blend` (scene `v3`, `geometry_id`: `v3-p4-ds3225pro-optA1-ankle-20261122`); all four legs (`FR`, `RR`, `FL`, `RL`) built and mirrored in CAD; physical print & assembly pending |
| Onboard Body Control Computer | Radxa Dragon Q6A v1.21 (with Armor 7056A heatsink/case) mounted inside the torso | CAD packaging in `V3 \| Electronics & Control`; runs Body Control gateway onboard over WebSocket to ESP32-P4 |
| Real-Time Body MCU | Waveshare ESP32-P4-WIFI6 (ESP32-P4 + ESP32-C6 Wi-Fi 6 over SDIO) | Shared firmware target `CONFIG_AINEKIO_MODEL_V3_12SERVO` in [esp32p4-wifi6](../../Slave/firmware/esp32p4-wifi6/README.md) |
| Servo Driver | Adafruit PCA9685 on `I2C1` (`SDA=GPIO2`, `SCL=GPIO3`, `OE=GPIO4`, addr `0x40`), channels `0..11`, reinforced with 14 AWG V+/GND underside busbars | Firmware source [body_v3.c](../../Slave/firmware/esp32p4-wifi6/main/body_v3.c) and CAD electronics model |
| Servos | Twelve DSServo DS3225 PRO 25kg-class HV coreless servos (`270°` travel variant on direct 2S `7.4 V` rail: `500–2500 µs`, center `1500 µs`, `7.4074 µs/deg`, `35 kg·cm / 3.43 N·m` stall, `0.075 s/60° = 800 deg/s` no-load, `60 g` each) | Owner-confirmed variant & voltage; installed per-servo travel, center offset, and loaded tracking require bench calibration |
| Joint Feedback | HiLetgo CD74HC4067 16-channel analog mux on `ADC2_CH0` (`GPIO49`, `S0..S3 = GPIO27..30`) for 12-joint 4th-wire feedback | Shared P4 mux backend (`CONFIG_AINEKIO_FEEDBACK_MUX_CD74HC4067=y`); requires 4th-wire tap & per-joint ADC calibration |
| IMU | GY-LSM6DS3 6-axis IMU on `I2C0` (`SDA=GPIO7`, `SCL=GPIO8`, addr `0x6A`) | Shared P4 IMU stack; physical mounting axis calibration pending bring-up |
| Camera | Arducam B0066 (OV5647) MIPI-CSI camera | Shared P4 CSI pipeline |
| Audio / Wake | Onboard ES8311 codec (speaker + microphone) and microWakeWord | Shared P4 audio pipeline |
| Display | 2.8-inch ILI9341 `320×240` SPI TFT (`MSP2807`, `SCK=GPIO20`, `MOSI=GPIO21`, `CS=GPIO22`, `DC=GPIO23`, `RESET=GPIO26`, landscape BGR) | Firmware source [display_ili9341.c](../../Slave/firmware/esp32p4-wifi6/main/display_ili9341.c) (`CONFIG_AINEKIO_DISPLAY_ILI9341=y`) |
| Power | 4× 21700 Li-ion cells in `2S2P` (`7.4 V` nominal direct to HV servo rail), Mini560 `5 V` logic buck converter, HiLetgo 2S USB-C charger | CAD packaging in `V3 \| Power & Battery`; continuous load sag and thermal limits pending bench measurement |
| Deferred Bring-Up Peripherals | Dual `VL53L5CX` ToF arrays (L/R) and 4× `WS2812B` 2×2 front LED matrices | Packaged in CAD; firmware drivers deferred until physical bring-up per owner scope |

Build the V3-on-P4 firmware from `Slave/firmware/esp32p4-wifi6` using [sdkconfig.v3-12servo](../../Slave/firmware/esp32p4-wifi6/sdkconfig.v3-12servo):

```bash
idf.py -B build-v3 -D IDF_TARGET=esp32p4 \
  -D SDKCONFIG=build-v3/sdkconfig \
  -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.v3-12servo" \
  -D AINEKIO_C6_IMAGE= build
```

## Geometry and dimensions (`v3-p4-ds3225pro-optA1-ankle-20261122`)

Authoritative CAD-exported package:
[geometry.json](../../Slave/software/models/v3-12servo/geometry.json),
[model.json](../../Slave/software/models/v3-12servo/model.json),
[servo_profile.json](../../Slave/software/models/v3-12servo/servo_profile.json), and
[v3_model.h](../../Slave/software/models/v3-12servo/include/ainekio/v3_model.h).

| Quantity | Established value / source |
| --- | --- |
| Overall visible envelope (neutral) | `406.4 mm L × 236.5 mm W × 385.6 mm H` (CAD `v3` scene) |
| Standing height & clearance | Shoulder axis `180.93 mm` above ground; Belly Hull clearance `125.03 mm` above ground |
| Foot support polygon (neutral) | Front soles `(+163.50, ±95.36) mm`, Rear soles `(-55.95, ±95.36) mm` (`219.45 mm` wheelbase × `190.72 mm` track) |
| Option A-1 4-bar linkage & ankle | Carrier `54.00 mm`, Crank `22.00 mm`, Pickup `46.00 mm`, Rod `56.00 mm` (preloaded PETG servo-saver), Lower leg `135.0 mm` (`|D→sole| = 142.91 mm`), Ankle pivot `F = (106.5, ∓43.05, -4.5) mm` in knee frame with `1:1` double-parallelogram self-leveling (`±27.5°` range) |
| Assembled mass (estimated) | **Estimated `2.97 kg`** (`mass_measured: false`: torso `1.75 kg` incl. Q6A/21700/P4/shell, 4× legs `~0.306 kg` each incl. 2× shoulder servos + knee spiral spring + servo-saver rod + self-leveling ankle linkage). Replace with scale measurement once built. |
| Joint count/order (`map: 2`) | Twelve, matching V2 order: `[0..2] RL (h,α,θ)`, `[3..5] RR (h,α,θ)`, `[6..8] FL (h,α,θ)`, `[9..11] FR (h,α,θ)` |
| Non-singular 4-bar joint limits | Shoulder `[-30°, +30°]`, Carrier `[-40°, +50°]`, Crank `[-50°, +50°]` (`sin(transmission) >= 0.237` across full box) |

## Neural gait and neural pose (simulation-only status)

- **Embedded Neural Gait (`ainekio-v3-neural-gait-v1-cpg`)**: Trained in GPU MuJoCo (`mjlab`) against the closed-chain Option A-1 4-bar + knee spring + servo-saver + double-parallelogram self-leveling flat-sole crawler foot model via [v3_microduck.py](../../Master/gateway/neural_gait/v3_microduck.py) (`50×8=400` obs with `1.65 Hz` CPG phase, `128→64→32→12` ELU/Tanh, upright flat-footed alternating diagonal-stride MDP), compiled to int8 C weights via [compile_v3_microduck.py](../../Slave/software/models/v3-12servo/tools/compile_v3_microduck.py) into [v3_microduck_data.c](../../Slave/software/models/v3-12servo/motions/microduck/v3_microduck_data.c) and run on ESP32-P4 by [body_v3.c](../../Slave/firmware/esp32p4-wifi6/main/body_v3.c). **Simulation-only (`physical_qualified: false`).**
- **Freestyle Neural Pose (`ainekio-v3-neural-pose-v1`)**: Exact Left↔Right reflection-equivariant goal-anchored residual policy (`86×15=1290` obs, `256→128→64→12`) trained via [v3_trainer.py](../../experiments/freestyle/neural_pose/v3_trainer.py) and [v3_contract.py](../../experiments/freestyle/neural_pose/v3_contract.py). **Simulation-only (`physical_qualified: false`).**
