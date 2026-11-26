# V1 robot specifications

Scope: `v1-8servo`, the eight-servo V1 Ainekio body. For the companion's
purpose and maintenance method, start with the [robot design core](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/ROBOT_BIBLE.md).
For the other body, use the [V2 specifications](../v2-12servo/SPECIFICATIONS.md).

**Work status (owner-confirmed 2026-11-21): V1 redesigned on ESP32-P4 (`v1-p4-clockspring-20261121`); legacy ESP32-S3 V1 hardware is retained below for historical reference.**

Source reconciliation: **2026-11-21**. This is the concise V1 hardware and
integration reference. **Source** means inspected CAD/code/configuration; **recorded**
means an existing owner or hardware-evidence record; **estimated** means computed
from CAD/datasheet inputs without physical measurement; **unknown** means that the
reviewed records do not establish the value. Physical bench qualification of the
redesigned P4 build remains pending assembly and bring-up.

## Hardware (Redesigned V1-on-P4 — Active Target)

| Component | V1-on-P4 specification | Basis and remaining uncertainty |
| --- | --- | --- |
| Body | Four-legged eight-servo quadruped frame with under-arm clockspring wire routing; eight servo outputs | CAD source `Slave/hardware/v2-12servo/v3-2.blend` (scene `v1`, `geometry_id`: `v1-p4-clockspring-20261121`); V2 geometry is not interchangeable |
| Controller | Waveshare ESP32-P4-WIFI6 (ESP32-P4 rev 1.3 + ESP32-C6 Wi-Fi 6/BLE over SDIO) | Owner-confirmed redesign target; shared firmware target `CONFIG_AINEKIO_MODEL_V1_8SERVO` in [esp32p4-wifi6](../../Slave/firmware/esp32p4-wifi6/README.md) |
| Servo output | Adafruit PCA9685 16-channel PWM driver on `I2C1` (`SDA=GPIO2`, `SCL=GPIO3`, `OE=GPIO4`, addr `0x40`), channels `0..7` | Firmware source [config.c](../../Slave/firmware/esp32p4-wifi6/main/config.c) and [body_v1.c](../../Slave/firmware/esp32p4-wifi6/main/body_v1.c) |
| Servos | Eight MG90S (`500–2500 µs`, center `1500 µs`, nominal `11.111 µs/deg`, `600 deg/s` / `10.47 rad/s` no-load) with 4th-wire potentiometer feedback | Source/datasheet defaults; installed travel, calibration, torque and loaded tracking require per-unit bench calibration |
| Joint feedback | Eight direct ESP32-P4 ADC channels (no analog multiplexer): `ADC1 CH4..7` (`GPIO20..23`) for `J0..J3`, `ADC2 CH0..3` (`GPIO49..52`) for `J4..J7` | Firmware source [servo_feedback.c](../../Slave/firmware/esp32p4-wifi6/main/servo_feedback.c) (`CONFIG_AINEKIO_FEEDBACK_DIRECT_ADC=y`); physical divider/noise verification pending bring-up |
| IMU | GY-LSM6DS3 6-axis IMU on `I2C0` (`SDA=GPIO7`, `SCL=GPIO8`, addr `0x6A`) | Shared P4 hardware/firmware bus; physical mounting orientation calibration pending bring-up |
| Camera | Arducam B0066 (OV5647) MIPI-CSI camera | Shared P4 CSI pipeline; snap-in front enclosure in `v3-2.blend` |
| Audio / Wake | Onboard ES8311 codec (speaker + microphone) and microWakeWord | Shared P4 audio pipeline |
| Display | 0.96-inch SSD1306 128×64 I2C OLED (`addr=0x3C`, `SCL=GPIO26`, `SDA=GPIO27`) | Firmware source [display_ssd1306.c](../../Slave/firmware/esp32p4-wifi6/main/display_ssd1306.c) (`CONFIG_AINEKIO_DISPLAY_SSD1306=y`); pins chosen to leave `GPIO20..23` dedicated to ADC1 |
| Storage | Board microSD slot + internal LittleFS and NVS | Shared P4 storage owner |

Build the V1-on-P4 firmware from `Slave/firmware/esp32p4-wifi6` using the V1 defaults overlay ([sdkconfig.v1-8servo](../../Slave/firmware/esp32p4-wifi6/sdkconfig.v1-8servo)):

```bash
idf.py -B build-v1 -D IDF_TARGET=esp32p4 \
  -D SDKCONFIG=build-v1/sdkconfig \
  -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.v1-8servo" \
  -D AINEKIO_C6_IMAGE= build
```

## Geometry and dimensions (`v1-p4-clockspring-20261121`)

Authoritative CAD-exported geometry package:
[geometry.json](../../Slave/software/models/v1-8servo/geometry.json),
[model.json](../../Slave/software/models/v1-8servo/model.json), and
[v1_model.h](../../Slave/software/models/v1-8servo/include/ainekio/v1_model.h).

| Quantity | Established value / source |
| --- | --- |
| Body frame & standing height | `+X` forward, `+Y` left, `+Z` up; CAD standing root height `56.665 mm` (`feet` at `±66.14 mm X`, `±42.96 mm Y`, `-56.665 mm Z`) |
| Hip mount centers (in body) | `(±48.35, ±38.50, +3.475) mm`; neutral leg yaw `±45°` (front) / `±135°` (rear) |
| Upper / lower link vectors (FR nominal) | Hip→Knee `[28.0, +6.744, +6.1] mm`; Knee→Foot `[-12.270, +2.685, -66.24] mm` (inward-curved lower blade; mirrored symmetrically for FL/RR/RL) |
| Assembled mass (estimated) | **Estimated `0.376 kg`** (`mass_measured: false`: torso `0.270 kg`, 4× upper leg `0.022 kg`, 4× lower leg `0.0045 kg` from CAD volumes + datasheets). Replace with physical scale measurement once assembled. |
| Joint count/order | Eight, frozen map-1 order: `0=R1 (FR hip), 1=R2 (RR hip), 2=L1 (FL hip), 3=L2 (RL hip), 4=R4 (RR knee), 5=R3 (FR knee), 6=L3 (FL knee), 7=L4 (RL knee)` |
| Mechanical joint limits (model) | Hips `[-45°, +45°]`, knees `[-15°, +115°]` (`0°` = standing CAD pose; `+` knee folds foot inward/upward) |
| Calibration and usable travel | Device-owned per-joint NVS calibration (`home_us`, `invert`, `us_per_degree`, 4th-wire ADC slope/offset); datasheet values do not prove installed hardware travel |

## Joint and peripheral connections (V1-on-P4)

Source: [config.c](../../Slave/firmware/esp32p4-wifi6/main/config.c),
[servo_feedback.c](../../Slave/firmware/esp32p4-wifi6/main/servo_feedback.c),
[Kconfig.projbuild](../../Slave/firmware/esp32p4-wifi6/main/Kconfig.projbuild).

| Joint ID | Label | Leg / Axis | PCA9685 Ch (`I2C1 0x40`) | 4th-Wire Direct ADC |
| --- | --- | --- | --- | --- |
| 0 | `R1` | FR hip | CH0 | `ADC1_CH4` (`GPIO20`) |
| 1 | `R2` | RR hip | CH1 | `ADC1_CH5` (`GPIO21`) |
| 2 | `L1` | FL hip | CH2 | `ADC1_CH6` (`GPIO22`) |
| 3 | `L2` | RL hip | CH3 | `ADC1_CH7` (`GPIO23`) |
| 4 | `R4` | RR knee | CH4 | `ADC2_CH0` (`GPIO49`) |
| 5 | `R3` | FR knee | CH5 | `ADC2_CH1` (`GPIO50`) |
| 6 | `L3` | FL knee | CH6 | `ADC2_CH2` (`GPIO51`) |
| 7 | `L4` | RL knee | CH7 | `ADC2_CH3` (`GPIO52`) |

- `I2C0` (IMU + audio codec): `SDA=GPIO7`, `SCL=GPIO8` (`GY-LSM6DS3` at `0x6A`).
- `I2C1` (servo driver): `SDA=GPIO2`, `SCL=GPIO3`, `OE=GPIO4` (`PCA9685` at `0x40`).
- `SSD1306` OLED (`0x3C`): `SCL=GPIO26`, `SDA=GPIO27` (configurable via Kconfig `AINEKIO_OLED_SCL`/`AINEKIO_OLED_SDA`).
- Legacy ESP32-S3 hardware details (Freenove ESP32-S3-WROOM N16R8, direct MCPWM pins `1, 2, 14, 21, 47, 48, 45, 46`, OV3660, INMP441/MAX98357A, no IMU/feedback) remain archived in [Slave/firmware/esp32s3/README.md](../../Slave/firmware/esp32s3/README.md) and [HARDWARE_BRINGUP_CHECKLIST.md](HARDWARE_BRINGUP_CHECKLIST.md).

## Neural gait and neural pose (simulation-only status)

- **Embedded Neural Gait (`ainekio-v1-neural-gait-v2-cpg`)**: Trained in GPU MuJoCo (`mjlab`) against `v1-p4-clockspring-20261121` using [v1_microduck.py](../../Master/gateway/neural_gait/v1_microduck.py) (`38×8=304` obs with `3.0 Hz` CPG phase, `128→64→32→8` ELU/Tanh), compiled to int8 C weights via [compile_v1_microduck.py](../../Slave/software/models/v1-8servo/tools/compile_v1_microduck.py) into [v1_microduck_data.c](../../Slave/software/models/v1-8servo/motions/microduck/v1_microduck_data.c) and executed on-device by [body_v1.c](../../Slave/firmware/esp32p4-wifi6/main/body_v1.c). **Simulation-only (`physical_qualified: false`) until bench and floor qualification.**
- **Freestyle Neural Pose (`ainekio-v1-neural-pose-v1`)**: Reflection-equivariant goal-anchored residual policy (`54×15=810` obs, `256→128→64→8`) trained via [v1_trainer.py](../../experiments/freestyle/neural_pose/v1_trainer.py) and [v1_contract.py](../../experiments/freestyle/neural_pose/v1_contract.py) for 8-DOF whole-body posture control. **Simulation-only (`physical_qualified: false`).**

## Power

The [owner-recorded topology](HARDWARE_BRINGUP_CHECKLIST.md#owner-confirmed-power-topology)
uses a 2S 7.4 V nominal Li-ion battery with separate 5 V buck converters for the
5 V servo rail and 5 V electronics rail; grounds are common and servo load current
uses its dedicated rail. Loaded voltage drop, current draw, thermal behavior and
cutoff evidence for the ESP32-P4 + PCA9685 + 8× MG90S build remain pending
physical bench measurement.

## Body Control and remote Ainekio OS connections

```text
V1 ESP32-P4 -- Wi-Fi 6 / authenticated robot WebSocket --> Body Control host
Ainekio OS Environment Bridge -- local or tunneled WebSocket --> same Body Control
```

Both sessions are bidirectional. The robot initiates its connection to the
gateway's `/robot` route (advertising `model: "v1-8servo"` with `body_calibration_v2`,
`face_feedback_v1`, `walk_nominal_v1`, and `map: 1` `targets` + 8-joint `joint_feedback`).
Ainekio OS initiates its connection to `/environment`; that endpoint accepts loopback
access at the gateway, including a tunnel ending on that host. Body Control can run on
a supported desktop or Q6A host; the V1 body does not require the brain to be physically
onboard.

| Interface | Default / ownership |
| --- | --- |
| Robot and Environment WebSockets | Gateway port `8790`; distinct `/robot` and `/environment` routes and authentication |
| Body Control dashboard | `127.0.0.1:8791` on the gateway host; browser access is not proof of a robot session |
| Ainekio OS on the same host | Bridge connects to `ws://127.0.0.1:8790/environment` |
| Ainekio OS on another host | Its existing forwarder uses the configured SSH or Cloudflare TCP route to gateway loopback; SSH can run over the configured WireGuard network |
| Pairing, tokens, addresses and calibration | Existing per-device/private configuration owners; credentials and installation-specific values are not copied into this specification |

The [gateway reference](../../Master/gateway/README.md#physical-robot-gateway-operation)
owns transport and pairing; Ainekio OS's [connection owner](https://github.com/Greg-Aster/ainekio-os/blob/main/brain/agents/environment-bridge/connections.ts)
and [forwarder](https://github.com/Greg-Aster/ainekio-os/blob/main/brain/agents/environment-bridge/forwarder.ts)
own host selection and tunnel lifetime. Current source uses one Environment Bridge
with configured local/remote endpoints, not separate Local/Remote agents. A public
web portal and a remote model provider are separate connections from the body bridge.

The [protocol](../../Slave/software/protocol/README.md) and advertised body
capabilities own supported requests and receipts. Protocol-v1 does not mean every
body has eight joints. Preserve V1's joint/asset format when changing shared code.

## Maintaining this specification

Update the affected entry when hardware, geometry, wiring or a connection contract
changes; link its source and label design values versus physical evidence. Keep
firmware versions, installation status, benchmarks and repair narratives in their
existing dated records. The [documentation authority](../README.md) retains the
normative specification and hardware-evidence process; this file does not silently
amend their behavior policies. It introduces no new runtime restrictions.
