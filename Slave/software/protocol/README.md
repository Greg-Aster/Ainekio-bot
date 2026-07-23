# Ainekio Protocol v1

This directory owns the machine-checkable Ainekio wire contract. It is shared by
the gateway, emulator, host tests, and firmware tests.

`schemas/control-v1.schema.json` is the language-neutral JSON control contract.
It follows section 3 of `docs/Ainekio - System Specification v1.0.docx` and
allows additional fields on known messages for forward compatibility. Semantic
rules that standard JSON Schema cannot express are named with
`x-ainekio-rules` and remain mandatory in every implementation.

`control_v1.py` is the host Python validator for that contract. Protocol errors
raise `ProtocolValidationError`; they never partially execute a command.

`schemas/binary-v1.json` describes the five-byte media header, frame types,
direction, counter behavior, and payload limits without depending on a
programming language. `binary_helpers/frame_v1.py` is the host Python
encode/decode implementation. Firmware will use equivalent bounded C code, not
the Python module or a JSON Schema runtime.

Fixtures are stored as JSON so every implementation can consume the same source
data. Authentication values in fixtures use the literal `REDACTED-TOKEN`.
Contract tests verify that all fixture message types remain represented by both
the language-neutral schema and the Python validator.

The current protocol-v1 liveness contract sends an application control ping
after one second without a control transmission. User-message timing is
irrelevant: the lightweight heartbeat continues while conversation is idle.
Four seconds without a valid control frame stops active motion but does not
destroy the authenticated session. A real WebSocket, gateway, or Wi-Fi failure
enters FAILSAFE/offline and starts reconnection. This keeps the home companion
connected while preserving an action-level actuator guard.

Wake-word preferences use a separate persistent command from the session-only
microphone stream command:

```json
{"t":"wake","seq":42,"enabled":false,"model":"ainekio"}
```

`model` is a bounded trained-model identifier, not arbitrary text to be turned
into a wake word. The ESP32 stores the accepted setting in NVS. Status frames
may report `camera_ready`, `wake_enabled`, `wake_model`, and `wake_ready`;
`camera_ready=false` means snapshot/visual capability must not be advertised,
and `wake_ready=false`
means firmware must reject both enabling the setting and opening a microphone
with `gate="wake"`. These status additions remain optional so an older
protocol-v1 body is still accepted by the gateway validator.

Firmware-owned perception snapshots use optional correlation fields without
embedding media in JSON. VAD boundary events carry one robot-generated
`origin_id`; the following snapshot metadata repeats that identifier:

```json
{"t":"event","name":"vad_close","origin_id":73}
{"t":"cam_meta","res":"XGA","fps":0,"counter_base":18,"origin":"audio","origin_id":73}
```

The JPEG remains the next bounded camera binary frame with counter `18`.
Completed physical actions use `origin="action"` and the command sequence as
`origin_id`; firmware sends the JPEG before `{"t":"done","seq":...}`. An
explicit `snap` command uses `origin="request"`. These fields are optional for
protocol-v1 compatibility with older bodies, but when present they must occur
as a validated pair.

Run the host fixture suite from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=Slave/software \
  python3 -m unittest discover -s Slave/software/tests/protocol -v
```
