# Body Control Gateway and Operator Cockpit

`Master/gateway/` owns the Python Body Control runtime that terminates the robot's `protocol-v1` `/robot` WebSocket, serves the local operator web cockpit, processes camera/audio/IMU/joint-feedback streams, runs host neural gait and Freestyle bridges, and exposes the authenticated `/environment` adapter to Ainekio OS.

## Architecture and Module Owners

| Module | Responsibility |
| --- | --- |
| `server/service.py` & `server/__main__.py` | `GatewayService` core: authenticated `/robot` WebSocket (`127.0.0.1:8790` / LAN), session/epoch/sequence fencing, capability negotiation, and `operations.jsonl` audit log. |
| `dashboard/server.py` & `dashboard/auth.py` | Operator cockpit HTTP server (`127.0.0.1:8791`), session authentication (`AINEKIO_DASHBOARD_NO_LOGIN=1` opt-out for local launchers), CSRF checks, and `/api/*` maintenance proxies. |
| `environment_adapter/` | Loopback `/environment` WebSocket (`bridge.connect` control session and read-only `bridge.watch` availability), translating `requestMotion`, `move`, `stop`/`release`, `faceExpression`, `captureImage`, and `sendText` with correlated `action_receipts.py`. |
| `body_capabilities.py` & `body_events.py` | Capability-filtered manual catalog and IMU/stall/feedback/wake event classification (`tipped`, `rapid_movement`, `servo_stall`, `servo_feedback_fault`, `wake`). |
| `perception.py`, `yolo_backend.py`, & `person_identity.py` | Background camera recognition worker: Ultralytics YOLO / YOLOE open-vocabulary object detection plus OpenCV YuNet + SFace named-person enrollment and matching. |
| `depth_motion.py`, `depth_motion_worker.py`, & `ground_plane.py` | On-demand metric distance/odometry (`depthDemand`): calibrated ground-plane geometry or isolated MoGe-2 + IMU-constrained SIFT landmark odometry. |
| `host_audio.py` & `environment_adapter/speech_transport.py` | Speech routing to either the robot's onboard speaker or host PulseAudio/PipeWire (`paplay` / Bluetooth) with heartbeat `external_speech` mic suppression. |
| `hotspot.py` & `launch_connection.py` | Managed `ainekio-hotspot.target` (`hostapd`/`dnsmasq`) vs LAN Wi-Fi connection-mode control and startup mode prompts. |
| `neural_gait/` | Independent host neural walking & MuJoCo/MJX simulation service (`127.0.0.1:8796`), MicroDuck `mjlab` PPO training/export, and Pupper MJX policy import/inference. |

## Body Control workspace

The browser cockpit (`http://127.0.0.1:8791`) organizes live robot operation and diagnostics into a left-hand **Tools** drawer alongside the **Ainekio Cockpit** camera/telemetry split view:

- **Operate**: *Ainekio Cockpit*, *Overview*, *Movement* (Walk / automatic Run / Crawl / Crab + live steering), *Neural gait* (virtual MuJoCo body, MicroDuck `mjlab`, and Pupper MJX policies), *Poses and emotes* (Freestyle prompt & manual library), *Faces and assets*, *Self-leveling* (`balance_control_v1` / `balance_tuning_v1` / gyro bias calibration), *Mode and power* (`idle_rest_v1` inactivity lay-down, sleep/restart), and *Motion speeds* (`joint_speed_limit_v1`).
- **Perception**: *Camera settings* (stream/still resolutions, `AUTO` / `960P` / `FHD`, `max_exposure_us`, depth/odometry source), *Recognition* (YOLO/YOLOE prompts & enrolled people), *Audio and wake word* (mic gain, VAD/wake sensitivity, speaker volume, speech destination), *Body events* (tilt/shake thresholds & cooldowns), and *MetaHuman control* (`/environment` bridge status & handoff toggle).
- **Recordings & Maintenance**: *Video and SD card* (`storage_control_v1` rolling AVI clips), *Calibration* (`body_calibration_v2` 12-joint pulse/angle mapping & 4th-wire ADC calibration), and *Firmware & logs* (Wi-Fi OTA upload/activation).

## P4 recording and firmware in Body Control

Body Control proxies pairing-token-authenticated HTTP maintenance requests to the connected ESP32-P4 without exposing robot credentials to the browser:

- **4th-wire potentiometer calibration**: Captures unloaded ADC endpoints across all 12 joints (`CD74HC4067` mux channels `C4–C15`), persists curves on the P4, and streams 20 ms `joint_feedback` (`filtered_model_deg`, `velocity_deg_s`, `raw_adc`, `usable_mask`) plus periodic `servo_feedback` health status.
- **Rolling microSD video & storage**: Lists, downloads, and clears bounded Ainekio AVI clips and diagnostic logs on the robot's SD card (`storage_control_v1`), rotating oldest segments automatically near capacity.
- **Wi-Fi application OTA**: Uploads a new ESP-IDF `esp32p4` binary to the inactive `ota_0`/`ota_1` partition with LCD progress feedback and activates it as a separate explicit step with rollback verification (see [`RECORDING_OTA.md`](../../Slave/firmware/esp32p4-wifi6/RECORDING_OTA.md)).

## Physical Robot Gateway operation

Configure an untracked `.env` in the repository root (`AINEKIO_ROBOT_ID`, `AINEKIO_ROBOT_TOKEN`, `AINEKIO_ENVIRONMENT_ADAPTER_TOKEN`, `AINEKIO_HOTSPOT=0|1`) and start or stop the physical stack with the launchers in `Master/`:

```sh
# Start physical Body Control (offers local, LAN / Wi-Fi, or Cloudflare access on interactive terminals)
./Master/start-physical-gateway.sh

# Non-interactive validation, systemd user service installation, and clean shutdown
./Master/start-physical-gateway.sh --check
./Master/start-physical-gateway.sh --install-service && systemctl --user daemon-reload
./Master/stop-physical-gateway.sh

# Optional neural gait service (127.0.0.1:8796) and Cloudflare /robot relay
./Master/start-neural-gait.sh
./Master/start-physical-relay.sh --check
```

- **Local login behavior**: Dashboard access uses the saved operator password verifier (`dashboard/auth.py`) unless `AINEKIO_DASHBOARD_NO_LOGIN=1` is explicitly set for a trusted loopback (`127.0.0.1:8791`) or local display.
- **Single connected robot selection**: The Environment Bridge automatically routes to whichever single robot (V2 12-servo or V1 8-servo) is connected; `AINEKIO_ROBOT_ID` seeds pairing identity rather than pinning the bridge.
- **Robot hotspot mode (`hotspot.py`)**: On Linux hosts with `Master/install-robot-hotspot.py` installed (`ainekio-hotspot.target` managing `hostapd` + `dnsmasq`), **Settings → Robot connection mode** switches live between upstream LAN Wi-Fi and the dedicated robot hotspot without restarting Body Control. If hotspot activation fails at startup, the launcher logs a warning and falls back to normal LAN gateway startup so the dashboard remains reachable.

## Using more than one computer

Robot pairing identity belongs to the robot. To move Body Control between a desktop workstation and a robot-local SBC (such as a Radxa Dragon Q6A), export and import the encrypted/hashed credential store rather than copying machine-specific `.env` paths:

```sh
# Source host
./Master/start-physical-gateway.sh --export-pairing /tmp/ainekio-pairing.json

# Target host (after private transfer)
chmod 600 /tmp/ainekio-pairing.json
./Master/start-physical-gateway.sh --import-pairing /tmp/ainekio-pairing.json
./Master/start-physical-gateway.sh --check
rm -f /tmp/ainekio-pairing.json
```

- **Connection handoff**: P4 `gateway_switching_v1` stores up to four ordered `(SSID, controller URL)` slots plus `_ainekio._tcp` DNS-SD discovery on plain-WS LAN profiles. A healthy `/robot` session is sticky; stop the active host (`./Master/stop-physical-gateway.sh`) so the robot cleanly closes the old epoch and connects to the alternate host.
- **Remote Ainekio OS bridge**: Ainekio OS's single Environment Bridge watches `/environment` across configured local and SSH/Cloudflare-forwarded loopback endpoints (`bridge.watch` → `bridge.availability`) and connects its active control stream where the selected robot is online (see [`STARTUP.md`](../../docs/STARTUP.md)).

## Continuous camera processing

When camera streaming or snapshots arrive from the body, `GatewayService` routes frames to two non-blocking host consumers without stalling command admission or telemetry:

1. **Background object/person recognition (`perception.py`)**: Processes only the latest pending RGB frame (dropping intermediate preview backlog) and attaches timestamped detections to robot observations.
2. **On-demand depth & camera odometry (`depth_motion.py`)**: Remains unloaded during ordinary chat/streaming and activates only while an active navigation/locomotion consumer holds `depthDemand` (or **Measure depth now** is clicked). Supports calibrated ground-plane projection or isolated **MoGe-2 + SIFT/IMU landmark odometry** (`AINEKIO_DEPTH_PYTHON`, `AINEKIO_DEPTH_COMFY_ROOT`, `AINEKIO_DEPTH_MODEL`), reporting explicit `learned-metric-estimate` provenance rather than claiming loop-closing SLAM.

## Configured recognition and Ainekio OS handoff

Body Control's **Perception → Recognition** panel configures open-vocabulary or fixed-class Ultralytics YOLO / YOLOE detection (`yolo_backend.py`) and governs which structured observations cross `/environment` into Ainekio OS:

- **Detection handoff**: Recognized objects, bounding boxes, confidences, source frame resolution, and CSI `frame_completed_us` / `boot_id` metadata accompany camera stills (`origin: "audio" | "action" | "request"`) and live perception updates so Ainekio OS receives attributed visual context without re-running local vision models on every preview frame.
- **Operator control toggle**: Disabling **MetaHuman control** in the cockpit header withholds autonomous `/environment` action admission while keeping manual Body Control and diagnostics live.

### Named people (optional local models)

When OpenCV YuNet face detection and SFace recognition ONNX weights are installed locally (`person_identity.py`), Body Control matches detected faces against operator-enrolled reference galleries:

- Enrollment and gallery labels stay in local host state outside Git.
- Matched identities attach to person detections with explicit cosine-similarity scores; low-confidence or off-angle faces remain `unknown` rather than guessing a name.

## Speech destination

Body Control routes synthesized speech received over `/environment` (`sendText` / PCM audio stream) according to **Perception → Audio and wake word → Speech destination** (reading and saving the active owner's `tts.outputTarget` preference over `/environment` rather than keeping a duplicate store in Body Control):

- **Robot speaker**: Streams 16 kHz mono PCM in 20 ms `protocol-v1` binary frames (`0x01`) to the robot's speaker output with no arbitrary reply-duration cutoff, scaled on P4 firmware by the persistent `speaker_volume_percent` master volume. Interrupted speech cancels via the audio command handshake rather than a motion stop.
- **Body Control computer**: Plays audio locally on the gateway host through PulseAudio/PipeWire (`paplay`, including paired Bluetooth speakers) via `host_audio.py`. While host playback is active, heartbeats send transient `external_speech` / `external_speech_ms` notices so the P4 suppresses microphone capture and `microWakeWord` self-triggers until playback finishes.

## V2 body events and IMU status

`body_events.py` evaluates calibrated 20 ms P4 IMU telemetry (`body_nominal` vs `sensor_unverified`), active `data.motion` execution context (`expected_up`, `activity`, `phase`), foreground `data.face_token`, and 4th-wire servo telemetry:

- **Event routing**: Emits attributed `body_event` notifications over `/environment` for `tipped`, `rapid_movement` (suppressed during commanded locomotion or active `be_*` reaction-face tokens and bounded by configurable cooldowns, default 10 s), `servo_stall` (`outputs_released: false`), `servo_feedback_fault` / `servo_feedback_restored`, and single-shot boot/manual `wake` (**Good morning**).
- **Wake vs inactivity**: Boot/wake dispatches `"Stand up, stretch, and finish standing"` through Freestyle alongside a correlated camera snapshot without blocking greeting speech. Inactivity rest (`idle_rest_v1`, default 3 minutes) runs locally on the P4 (`lay_down` followed by `OE` release) without LLM calls.

## Neural walking simulation and policy service

`Master/gateway/neural_gait/` runs as an independent local HTTP/simulation service (`127.0.0.1:8796`, started on demand or standalone via `python3 -m gateway.neural_gait.server`) owning virtual MuJoCo/MJX body simulation and the two supported locomotion policy families:

- **MicroDuck `mjlab` PPO (`microduck.py`, `microduck_actor.py`, `microduck_mdp.py`, `requirements-microduck-training.txt`)**: Trains velocity-tracking quadruped policies in MuJoCo Warp (`vendor/microduck_rl`), serves live host `walk_nominal_v1` foot targets via ONNX Runtime, renders MuJoCo evaluation replays (`evaluation.py`, `replay.py`), and exports quantized `int8` weights (`Slave/software/models/v2-12servo/tools/compile_microduck.py`) for standalone 50 Hz on-chip ESP32-P4 execution.
- **Pupper MJX & virtual body (`import_pupper_mjx.py`, `pupper_mjx_actor.py`, `jax_hardware.py`, `virtual.py`, `virtual_body.c`)**: Imports RTNeural JSON checkpoints trained with MJX/JAX kinematics, serves live host `walk_nominal_v1` joint targets, and runs the native C V2 linkage/controller loop inside MuJoCo for side-by-side virtual robot evaluation before physical floor trials.

## Validation

Run the gateway, perception, and neural gait test suites from the repository root:

```sh
PYTHONPATH=Master:Slave/software:.:tests \
  python3 -m unittest discover -s tests -p 'test_*.py'
```
