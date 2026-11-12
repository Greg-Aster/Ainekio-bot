# Ainekio Protocol v1

`Slave/software/protocol/` owns the machine-checkable `protocol-v1` wire contract shared across Body Control (`Master/gateway/`), host tests, and the ESP32-P4 (`v2-12servo`) and ESP32-S3 (`v1-8servo`) firmware targets.

## Core Contract Owners

| File | Responsibility |
| --- | --- |
| `schemas/control-v1.schema.json` | Language-neutral JSON control schema (`hello`, `welcome`, `intent`, `motion_plan`, `calibration`, `balance`, `motion_speed`, `storage`, `speaker`, `mic`, `wake`, `cam`, `snap`, `ping`/`pong`, `ack`/`nak`, `done`, `event`, `status`). Semantic invariants beyond JSON Schema are named in `x-ainekio-rules`. |
| `control_v1.py` | Host Python validator enforcing both JSON Schema and `x-ainekio-rules`. Validation failures raise `ProtocolValidationError` without partial command execution. |
| `schemas/binary-v1.json` & `binary_helpers/frame_v1.py` | Five-byte binary media header (`type`, 32-bit counter), frame types (`0x01` PCM audio, `0x02` complete JPEG, `0x03` chunked JPEG), direction rules, and payload bounds. |
| `joints_v2.py` | Canonical 12-joint V2 ordering: rear-left (`0–2`), rear-right (`3–5`), front-left (`6–8`), front-right (`9–11`), each `[shoulder, carrier, crank]`. |
| `fixtures/` | Canonical JSON fixtures (`REDACTED-TOKEN` auth placeholders) verified against both `control-v1.schema.json` and `control_v1.py`. |

## Capability and Command Negotiation

- **`body_capabilities_v1` & `body_commands_v1`**: During `hello` (and dynamically in subsequent `status` updates), a body declares its model (`v2-12servo` or `v1-8servo`), feature flags (up to 32 entries), peripheral readiness (`motion`, `camera`, `mic`, `speaker`, `wake`, `storage`), and bounded `capabilities.commands` subset drawn from the gateway's semantic catalog.
- **Admission fencing**: Every sequenced command carries `seq`, connection `epoch`, and `deadline_ms`. Unsupported features, undeclared commands, or unready capabilities are rejected by the gateway before dispatch and independently checked by firmware after session, epoch, and expiry validation. Emergency `stop` (`detach: true`) remains independently available regardless of motion readiness.

## P4 twelve-joint Freestyle

Firmware advertising `motion_plan_v2` accepts 12-joint `motion_plan` packets using `map: 2`:

- **Frame representation**: `1–32` frames of `[duration_ms, [12 signed centidegree model targets]]` in `joints_v2.py` order (up to 8,192-byte JSON control frames on P4; V1 `map: 1` 8-joint plans remain unchanged). Targets are signed model centidegrees from CAD neutral, converted on-device through saved per-joint mounting offsets, inversion, and `us_per_degree` scaling.
- **Execution & 4th-wire arrival**: Each frame endpoint is resolved once through the calibrated pose fitter and interpolated through the 50 Hz staggered PCA9685 output owner without prepending Home, Stand, or named-motion speed scaling. On P4 bodies with `servo_feedback_v1`, Freestyle target execution waits for fresh measured potentiometer arrival at the applied endpoint. If the pose fitter adjusted any joint target, `done` reports `position_verified: false` and the 12-bit `target_adjusted_joints` mask; unadjusted measured arrival reports `position_verified: true`.
- **Balance & terminal posture**: Arbitrary Freestyle plans clear active IMU balance offsets without altering the saved self-leveling preference. `end: "hold"` holds the final target; `end: "stand"` or `end: "neutral"` transitions into that posture (`end: "stand"` resumes normal Stand leveling).

## Saved Joint Speed, Named-Motion Rate, and Self-Leveling

- **`motion_speed_v1` & `joint_speed_limit_v1`**:
  ```json
  {"t":"motion_speed","op":"get","seq":72}
  {"t":"motion_speed","op":"save","rate":1.35,"seq":73}
  {"t":"motion_speed","op":"save","joint_speed_limit_deg_s":900,"seq":74}
  {"t":"motion_speed_status","seq":74,"rate":1.35,"saved":true,"joint_speed_limit_deg_s":900,"joint_speed_limit_saved":true}
  ```
  `joint_speed_limit_deg_s` governs posture entry, finite clips (50% of configured joint speed along a joint-distance cubic clock), and IMU balance increments. `rate` scales intentional holds and entry easing (default `2.0`, or per-command `playback_rate` on `emote`). Semantic gaits (`Walk`, `Run`, `Crawl`, `Crab`) always run on the fast coordinated `545.45 deg/s` stroke clock. Saving either value disarms PWM before writing its NVS record.
- **`balance_control_v1`, `balance_tuning_v1`, & `balance_feedback_v1`**:
  ```json
  {"t":"balance","op":"get","seq":75}
  {"t":"balance","op":"save","seq":77,"enabled":true,"strength":1.5,"damping":1.0,"roll_deg":0,"pitch_deg":2}
  {"t":"balance","op":"calibrate_gyro","seq":78}
  ```
  Persists self-leveling `enabled` (default `true`) plus nonnegative `strength`/`damping` multipliers (default `1.0`) and `roll_deg`/`pitch_deg` target attitude offsets without starting or stopping motion. `calibrate_gyro` averages 256 stationary raw IMU samples into `p4_imu/cal_v1` gyro bias and reports progress via `status.balance.gyro_calibration`. `balance_feedback_v1` exposes modeled leg `extension_mm` and `joint_delta_deg` relative to the nominal pose.

## Host nominal targets in the existing V2 Walk

`walk_nominal_v1` allows the host neural policy service (`Master/gateway/neural_gait/`) to stream foot-space targets inside an active `Walk` command:

- **Start**: `intent: "walk"` with `source: "host"`, `steps: 0`, compiled `geometry` ID, 12-joint `reference_cd`, and `twist: [vx_m_s, vy_m_s, yaw_rad_s]`.
- **Stream**: Sequenced ACK-only `walk_target` frames carrying `walk` (original Walk `seq`), strictly increasing `sample`, matching `geometry`, and 12 flattened `feet_mm` offsets (`[RL, RR, FL, FR] × [x, y, z]`) relative to `reference_cd`. Late samples after replacement, Stop, or Finish (`speed: 0`) are rejected.
- **Resolution & telemetry**: P4 resolves `feet_mm` through its closed-chain linkage solver, geometric heading correction, and IMU balance owner. IMU `data.motion` reports `walk_source: "host" | "native"`, `nominal_sample`, and `sampled_us`.

## Directional locomotion and automatic Run

Locomotion extensions layer onto `{"t": "intent", "name": "walk", ...}` with sequence-preserving live updates (`"update": <original_seq>`):

- **`walk_controls_v1` & `walk_controls_v2`**: Negotiate `speed` (`0–100`, where `0` requests controlled Finish), advanced `stride` (`1–100`) + `rate`, directions `fwd | back | turn_l | turn_r`, `gait: "walk" | "crawl"`, and ongoing `steps: 0` (finite `steps: 1–10` remain supported). Only the original Walk sequence emits `done` or `cancelled`; update ACKs settle only their settings change.
- **`run_gait_v1`**: Extends Walk-family `speed` through `100–200` (`1–100` walks, `101–200` blends smoothly into bounding `Run` and back without changing sequence owner) and allows explicit `gait: "run"`. Bare semantic `run` dispatches ongoing V2 Walk-family `speed: 150`.
- **`crab_gait_v1`**: Adds wide-stance `gait: "crab"` (`speed: 0–100`) plus lateral directions `side_l` and `side_r` (`crab`, `crab_right`, `crab_forward`, `crab_backward`, `crab_turn_left`, `crab_turn_right`).
- **`walk_steering_v1` & `walk_lateral_v1`**: Adds composed signed percentages `forward` (`-100..100`, positive forward) and `turn` (`-100..100`, positive left) on `walk` and its updates; `walk_lateral_v1` adds `lateral` (`-100..100`, positive left). Rejected prior to sequence allocation if the connected firmware has not advertised the corresponding feature.

```json
{"t":"intent","name":"walk","dir":"fwd","gait":"walk","steps":0,"speed":80,"forward":80,"turn":25,"seq":50}
{"t":"intent","name":"walk","dir":"fwd","gait":"walk","steps":0,"speed":140,"forward":100,"turn":0,"update":50,"seq":51}
{"t":"intent","name":"walk","dir":"fwd","gait":"walk","steps":0,"speed":0,"update":50,"seq":52}
```

## Joint Feedback, Stall Telemetry, and IMU Context

- **20 ms IMU + `joint_feedback` (`event` / `name: "imu"`)**:
  - Carries calibrated body attitude/rates, `data.face_token` (active foreground display token for body-event reaction suppression), and `data.motion` (`command`, `activity`, `phase`, `sequence`, `connection`, `started_us`, `sampled_us`, `expected_up`).
  - With 4th-wire sensing (`servo_feedback_v1`), `data.joint_feedback` (`map: 2`) attaches 12-entry arrays `filtered_model_deg`, `velocity_deg_s`, `commanded_model_deg`, `raw_adc`, and `signal_millivolts`, plus validity bitmasks (`usable_mask`, `calibrated_mask`, `unavailable_mask`, `clipped_mask`, `below_calibration_mask`, `above_calibration_mask`, `stalled_joints`) and monotonic `sampled_us` / `device_us` timestamps.
- **Health summary (`event` / `name: "servo_feedback"`)**: Periodic health frame consumed by Body Control to surface `servo_feedback_fault` and `servo_feedback_restored` notices without commanding motion or releasing outputs.
- **Recovery-first stall notice (`event` / `name: "servo_stall"`)**: Emits `event_id`, `clock_us`, `seq`, 12-bit model `joint_mask`, and `outputs_released: false` when observed shaft progress stalls. On current P4 firmware (`0.8.120+`), stall detection reports the episode without terminating the active command or releasing PWM outputs, allowing host Freestyle recovery while preserving manual `stop` and hardware-fault shutdowns.

## Operator Calibration, Storage, Inactivity Rest, and Gateway Switching

- **12-joint calibration (`body_calibration_v2`)**: Operator-only `{"t": "calibration", "op": "get"|"set"|"move"|"home"|"save", ...}` service on P4 (V1 retains `servo`/`limits`/`cal_save`). Manages 12 joint records (`id`, `channel`, `home_us`, `invert`, `home_cd`, `us_per_degree`) and confirms every operation with a correlated `calibration_status` readback (`dirty`, `saved`, `ready`, hardware `pulse_min_us`/`pulse_max_us`, and last commanded `pulse_us`).
- **Storage control (`storage_control_v1`)**: Operator `{"t": "storage", "op": "get"|"retry"|"clear", ...}` settling on `storage_status` (`available`, `mounted`, `busy`, `total_bytes`, `free_bytes`, `dropped_records`, `error`). `clear` deletes bounded Ainekio logs/clips without formatting the microSD card.
- **Inactivity rest (`idle_rest_v1`)**: Configurable NVS timeout (default `180 s`; `0` disables) after which the P4 body locally executes its built-in `lay_down` clip and releases PCA9685 `OE` upon completion without host LLM involvement.
- **Multi-gateway switching (`robot_settings_v1` & `gateway_switching_v1`)**: Supports four ordered Wi-Fi/controller slots, including multiple `ws://` or `wss://` controller endpoints sharing one SSID credential, plus DNS-SD `_ainekio._tcp` fallback on plain-WS LAN profiles.

## Timed display expressions

`face_feedback_v1` extends `{"t": "intent", "name": "face", ...}` with layered foreground and background display ownership:

- `token` and `if_token` (`[a-z0-9_]{1,32}`): Correlate, conditionally update, or `release: true` a specific expression without clobbering newer reactions.
- `timeout_ms`: Robot-measured duration (`0` = untimed); expiry restores the underlying layer or motion/default face.
- `background: true`: Maintains a low-priority expression (such as `thinking`) in a separate background slot that yields to foreground reactions, speech, and motion cues without overwriting them.

## Existing lifecycle and media contracts

- **Heartbeat & control silence**: Application `ping`/`pong` runs after 1 s of control idle. Four seconds without valid control traffic stops active motion and disables PWM outputs while keeping the authenticated WebSocket open for telemetry and media; transport loss triggers `FAILSAFE` and reconnect.
- **Audio, wake word, & speaker volume (`audio_input_v1`)**:
  - `mic` configures `on`, `gate` (`open | vad | wake`), ES8311 `gain_db` (`0–42 dB` in `6 dB` steps), `vad_mode` (`0–4`), `silence_ms`, and `max_recording_ms` (`20–15000 ms`).
  - `wake` persists `enabled`, `model` (`ainekio`), and `threshold` (`0..1`).
  - `speaker` persists `volume_percent` (`0–100`) in NVS (`audio.speaker_volume_percent` in `ping`/`pong`).
  - Unsequenced `external_speech` / `external_speech_ms` fields on `welcome`/`ping`/`pong` temporarily suppress P4 mic capture and wake-word triggers while host/Bluetooth TTS is playing.
- **Camera profiles & chunked stills (`camera_profiles_v1`, `camera_adaptive_v1`, `camera_motion_exposure_v1`)**:
  - `cam` independently configures preview (`QVGA` / `VGA`, `0–15 fps`), `snapshot_res` (`QVGA | VGA | XGA | 960P | FHD | AUTO`), and optional automatic AEC shutter ceiling `max_exposure_us` (without advertising manual `camera_controls_v1` on P4).
  - `cam_meta` correlates stills to speech (`origin: "audio"`, `origin_id` matching `vad_open`/`vad_close`), completed motions (`origin: "action"`), or `snap` (`origin: "request"`), and includes CSI `frame_completed_us` and `boot_id` on V2.
  - Binary JPEG frames transmit either whole (`0x02`) or in 4,096-byte chunks (`0x03`) interleaved with ready microphone PCM packets.

## Validation

Run the protocol schema and validator suite from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=Slave/software \
  python3 -m unittest discover -s Slave/software/tests/protocol -v
```
