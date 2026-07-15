# Ainekio and MetaHuman Closed-Loop Status

Status: implemented software foundation
Updated: 2026-07-14

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

MetaHuman owns the connection agent and cognition. Ainekio owns device-specific
translation, protocol-v1 correlation, media bounds, and robot safety. Ainekio
does not contain a MetaHuman URL or make MetaHuman API calls.

## Implemented

- The MetaHuman Environment Bridge is a real PID-tracked agent with Start, Stop,
  Restart, Run On Boot, Adapter URL, and Graph controls.
- The agent and Ainekio gateway use one authenticated full-duplex WebSocket.
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

Ainekio:

```text
AINEKIO_ENVIRONMENT_ADAPTER_TOKEN=<random shared adapter token>
AINEKIO_ENVIRONMENT_SESSION_ID=ainekio-sim-1
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

- Physical camera, microphone, speaker, servo, display, SD, and sensor behavior
  still require hardware validation when the ESP32-S3 board arrives.
- Robot PCM utterance assembly and Whisper routing are not connected yet.
- Wake-word detection is not implemented.
- Continuous video is intentionally not sent to the model; the current loop uses
  correlated still images.
- GPS and additional sensor drivers are future work, although generic state and
  location observation fields already exist.
- Durable objectives beyond the bounded in-memory continuation chain remain a
  separate autonomy feature.
