# Ainekio and MetaHuman Closed-Loop Status

Status: software loop implemented; controller USB bring-up verified; assembled
hardware loop pending
Updated: 2026-07-21

## Current Path

```text
MetaHuman Environment Mode
  -> semantic environment action
  -> real MetaHuman Environment Bridge agent
  -> authenticated ws://gateway/environment
  -> Ainekio semantic translation and safety gate
  -> protocol-v1 robot command
  -> robot ack/done/cancelled/nak
  -> environment feedback
  -> post-action JPEG snapshot
  -> environment observation
  -> MetaHuman Environment Mode
```

The microphone return path uses the same connection:

```text
Robot 20 ms PCM frames
  -> Ainekio VAD-bounded utterance assembly
  -> bounded WAV audio.utterance message
  -> MetaHuman Environment Bridge
  -> Whisper speech-to-text
  -> generic text observation
  -> MetaHuman Environment Mode
```

MetaHuman owns the connection agent and cognition. Ainekio owns device-specific
translation, protocol-v1 correlation, media bounds, and robot safety. Ainekio
does not contain a MetaHuman URL or make MetaHuman API calls.

## Implemented

- The MetaHuman Environment Bridge is a real PID-tracked agent with Start, Stop,
  Restart, Run On Boot, Adapter URL, and Graph controls.
- The agent and Ainekio gateway use one authenticated full-duplex WebSocket.
- Ainekio groups 16 kHz mono signed-16 PCM frames between `vad_open` and
  `vad_close`, preserves wake and frame-gap metadata, inserts silence for
  missing counters, and caps an utterance at 15 seconds.
- The gateway sends one validated WAV utterance to the Environment Bridge. The
  bridge uses MetaHuman's public Whisper service and emits one ordinary text
  observation with robot, utterance, timing, wake, gap, and truncation metadata.
- The transcription queue and binary envelope are bounded. Raw 20 ms PCM frames
  are not sent independently to Whisper or Environment Mode.
- Firmware and emulator capture 100 ms of microphone pre-roll. Microphone
  forwarding is suspended while robot speech plays and rearms after an 800 ms
  cooldown, preventing the robot from immediately transcribing its own voice.
- Actions remain semantic. Raw servo-like model output is rejected.
- Robot terminal lifecycle is returned as environment feedback.
- The action-result call settles the command task but does not own feedback
  history. The following observation is the single owner that records feedback
  for graph context; feedback IDs make transport retries idempotent.
- Every terminal result produces one follow-up observation. A completed action
  requests one camera snapshot; if no frame is available, state is returned.
- The gateway converts a bounded protocol-v1 JPEG into a data URL observation.
- MetaHuman validates one JPEG at a maximum of 120 KiB and creates an image_url
  model content part.
- Environment Context Builder sends text and image content together; the model
  router and vLLM client preserve that structured request.
- Environment Mode requires one model result containing a conversational
  `response` plus zero or more semantic `actions`. The response passes through
  Bridge Out to Stream Writer and Chat View, while actions continue independently
  to the robot coordinator. Ordinary conversation therefore remains visible even
  when no robot action is produced.
- Returned text and visual event IDs trigger serialized Environment Mode work.
  Automatic continuation is limited to eight steps per active chain.
- Transport is event-driven. There is no command polling loop. Periodic robot
  status remains gateway liveness data and does not enqueue Environment Mode
  work; connection changes, events, terminal results, text, and camera frames do.
- The host emulator completes motion headlessly when no browser renderer is
  connected. If the page is open, it still requires the correlated renderer
  acceptance before reporting completion.

## Configuration

Start the physical brain-side gateway from this repository with its robot and
Environment Bridge credentials supplied only at runtime:

```sh
export AINEKIO_ROBOT_ID=ainekio-01
export AINEKIO_ROBOT_TOKEN='<random robot pairing token>'
export AINEKIO_ENVIRONMENT_ADAPTER_TOKEN='<random shared adapter token>'
./Master/start-physical-gateway.sh
```

The physical launcher binds the shared WebSocket service to the brain's LAN on
port 8790 and keeps its dashboard on `127.0.0.1:8791`. On the currently observed
home network, the robot endpoint is `ws://192.168.0.44:8790/robot`; reserve that
address in the router because DHCP can change it.

Ainekio's setup form stores:

```text
endpoint_url=ws://<brain-lan-ip>:8790/robot
robot_id=ainekio-01
robot_token=<same robot pairing token used to seed the gateway>
```

MetaHuman:

```text
MH_ENVIRONMENT_BRIDGE_TOKEN=<random internal service token>
MH_ENVIRONMENT_ADAPTER_TOKEN=<same adapter token as Ainekio>
MH_ENVIRONMENT_ADAPTER_URL=ws://127.0.0.1:8790/environment
MH_ENVIRONMENT_GRAPH=environment
```

The two token roles are deliberately separate. Secret values are runtime
configuration and are not committed.

## Deferred

- The delivered ESP32-S3 controller has passed USB-only boot, OV3660 detection,
  8 MB PSRAM validation, and initialization of all eight remapped MCPWM channels.
  Physical JPEG output, servo signals and joints, the external 5 V rails,
  microphone, speaker, OLED, SD card, and combined-load behavior still require
  assembly and H-series evidence.
- The stable-key/direct-form firmware image and physical gateway launcher pass
  software validation. The image is installed with immutable-partition digest
  readback, boots on the delivered board, and broadcasts `Ainekio-Setup`. The
  home-WiFi form submission, gateway authentication, OLED IP/state, and physical
  full-duplex path still need live evidence.
- Physical microphone capture and acoustic behavior still need board-level
  validation. Emulator fixture evidence does not substitute for the installed
  INMP441 and enclosure.
- The local microWakeWord engine is implemented, but no accepted production
  Ainekio model is installed; wake therefore remains intentionally not ready.
- Full acoustic echo cancellation is not implemented. The current policy is
  deliberate half-duplex microphone suspension plus cooldown.
- Continuous video is intentionally not sent to the model; the current loop uses
  correlated still images.
- GPS and additional sensor drivers are future work, although generic state and
  location observation fields already exist.
- Durable objectives beyond the bounded in-memory continuation chain remain a
  separate autonomy feature.
