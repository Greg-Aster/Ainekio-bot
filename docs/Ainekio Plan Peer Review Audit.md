# Ainekio Coding Project Plan Peer Review Audit

This is an engineering peer review of the three DOCX planning documents against the current local repository. I interpreted "bardown file" as a Markdown file and saved this audit as Markdown.

## Reviewed Inputs

Source documents:

- D2: `docs/Ainekio - Software & System Discussion (v2).docx`, 98 extracted content lines.
- D1: `docs/Ainekio - Software & System Discussion.docx`, 96 extracted content lines.
- S: `docs/Ainekio - System Specification v0.3.docx`, 148 extracted content lines.

Current repo references:

- `docs/MOTION_MODULE_PROGRESS.md`
- `simulator bridge progress scratchpad.md`
- `motion/src/ainekio_motion/*.py`
- `motion/tests/*.py`
- `simulators/sesame-robot-sim/**`

External reference checks used for hardware/protocol feasibility:

- Espressif ESP32-S3 GPIO summary: https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/gpio.html
- Espressif ESP32-S3 I2S docs: https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/i2s.html
- Espressif ESP32-S3 MCPWM docs: https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/mcpwm.html
- Espressif ESP32-S3 LEDC docs: https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/peripherals/ledc.html
- Espressif NVS encryption docs: https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/storage/nvs_encryption.html
- Cloudflare Workers WebSocket docs: https://developers.cloudflare.com/workers/runtime-apis/websockets/

## Executive Assessment

The v0.3 specification is directionally strong as a future architecture: semantic intents, robot-side safety, a protocol-first emulator, firmware last, event-driven transport, and explicit acceptance tests are all the right instincts.

The main repository concern is cleanup and migration, not a need to start over. The active code is a Python motion adapter plus Sesame simulator tooling, while some repo notes still reflected an older rejected hardware idea. Since that hardware path is not feasible, those references should be removed and the remaining Python code should be treated as simulator/emulator support for the ESP32-S3 body, robot-initiated WebSocket, Python gateway, dashboard, binary media frames, and ESP-IDF firmware plan.

There is also a likely hardware blocker: the plan relies on GPIO33/34 to make the SD-enabled pin map work on an N16R8 / R8 octal-PSRAM ESP32-S3 target. Espressif's GPIO guidance says GPIO33-37 are also not recommended when octal PSRAM is used. That means MAP_B and the "SD fits cleanly" conclusion should be treated as invalid until proven otherwise by the exact Freenove board schematic and an electrical test. If GPIO33/34 are unavailable, the SD-plus-8-direct-servos plan needs a redesign.

## Critical Findings

### CF1 - MAP_B likely conflicts with ESP32-S3 R8/octal PSRAM

Severity: Critical.

Affected lines: D2 L046-L050, S L080, S L094-L097, S L140, D2 L086.

The v2 document says GPIO33/34 are free on the R8 variant if the board breaks them out. The v0.3 spec then defines MAP_B using GPIO33 and GPIO34 for servos while the SD card uses GPIO38/39/40.

Espressif's ESP32-S3 GPIO summary says GPIO33-37 are not recommended for other uses on boards using octal flash or octal PSRAM. The target is explicitly N16R8 / 8 MB octal PSRAM. This directly undermines the MAP_B premise.

Impact:

- The SD-enabled design may not have enough safe GPIOs for 8 direct servo outputs plus camera, I2S, I2C, battery ADC, UART/debug, and SDMMC.
- The line "SD fits cleanly" should be changed to "SD is blocked unless the exact board proves GPIO33/34 are usable despite R8 constraints."
- If SD is required, use an external PWM driver or IO expander, reduce direct GPIO needs, change target hardware, or defer SD.

Required action:

- Update S L096 and D2 L046-L050 immediately.
- Do not implement MAP_B until the exact Freenove schematic/pinout and bench tests prove it.
- Add an acceptance test: boot, WiFi, camera, PSRAM init, SD, and all servo GPIOs active together.

### CF2 - GPIO19/20 are assigned to I2S but are USB-JTAG pins by default

Severity: High.

Affected lines: S L095-L096, D2 L044.

The spec assigns I2S mic DIN and amp DOUT to GPIO19/20. Espressif documents GPIO19/20 as USB-JTAG by default. Reconfiguring them may be acceptable, but the plan does not mention the debug/programming tradeoff.

Impact:

- You may lose USB-JTAG debugging when I2S is enabled.
- The plan reserves GPIO43/44 for UART logs, but it does not explicitly say USB-JTAG is sacrificed.
- Firmware bring-up will be harder if camera, I2S, and servo timing issues need JTAG-level debugging.

Required action:

- Add "GPIO19/20 USB-JTAG conflict" to the risk register and pin-map constraints.
- Decide whether UART logs on 43/44 are sufficient or whether I2S pins must move.

### CF3 - Obsolete hardware references obscure the ESP32-S3 target

Severity: High.

Affected lines: S L004-L011, D2 L011-L036, D1 L011-L021.

Repo cleanup facts:

- Older repo notes described a hardware path that has since been rejected as not feasible.
- The active Python motion, adapter, and simulator code is isolated enough to keep as emulator/simulator support.
- The disabled hardware backend and config should be generic rather than tied to the discarded hardware path.

The new spec says the body is a Freenove ESP32-S3-WROOM CAM running C firmware. That should be treated as the hardware direction of record.

Impact:

- A developer or coding agent could follow stale docs or code names and reintroduce the discarded path.
- Tests validate the old adapter contract, not the new protocol.
- The plan says it is self-contained, but stale repository context can still confuse implementation order.

Required action:

- Remove obsolete hardware references from active docs and code.
- Mark which current Python modules are retained as reusable logic and which are superseded.

### CF4 - Transport and protocol conflict with current implementation

Severity: Critical.

Affected lines: D2 L015, D2 L021-L022, S L019-L026, S L109-L116.

The spec requires exactly one robot-initiated WebSocket between body and gateway. The current implementation uses:

- HTTP POST to `/api/environment-bridge/observation`.
- SSE read from `/api/environment-bridge/stream`.
- HTTP POST to `/api/environment-bridge/action-result`.
- Action types `robotCommand`, `move`, `stop`, and `sendText`.

Those are visible in `motion/src/ainekio_motion/adapter.py:15-17`, `adapter.py:66-87`, and `adapter.py:157-158`.

Impact:

- The current adapter cannot speak protocol v0.3.
- The current tests cannot validate protocol v0.3.
- The spec's Robot Gateway is missing from the repo.
- The MetaHuman OS adapter contract is not defined beyond a paragraph.

Required action:

- Decide whether to replace the SSE adapter with the gateway or wrap the existing MetaHuman environment bridge behind the gateway.
- Add a migration diagram: MetaHuman Environment Bridge -> Gateway API -> robot WebSocket.
- Add a protocol package and golden test vectors before firmware work.

### CF5 - Protocol examples are not machine-valid JSON

Severity: High.

Affected lines: S L024-L025, S L031-L058.

The spec says text frames carry exactly one JSON object, but the message examples are not all valid JSON:

- Placeholders such as `<deg -90..90>`, `<ISO8601...>`, and empty `""` values are not schemas.
- `bool` is not a JSON literal; JSON uses `true` or `false`.
- Some fields have empty values after colons, for example `epoch`: and `ms`:.
- `ping` has no `seq` despite "every brain-to-body command carries seq."

Impact:

- A coding agent cannot implement cJSON validation safely from these examples.
- Firmware and Python code may diverge on field names, required fields, ranges, and defaults.
- Acceptance tests cannot be generated automatically.

Required action:

- Add JSON Schema or a compact normative message table with valid examples and required/optional fields.
- Add golden encode/decode fixtures for every message.
- Decide whether `ping`/`pong` are exempt from `seq`.

### CF6 - Liveness, stale-command, and failsafe timing are inconsistent

Severity: High.

Affected lines: D1 L064, D2 L062, S L058, S L065-L069, S L123.

Conflicts:

- D1 and D2 say failsafe enters on link loss after 1 second.
- S says body failsafe after 3 seconds of no received frame.
- S L058 says stale if local receive-time is older than 2 seconds after a link stall, but receive-time age is hard to define if the message was blocked in a WebSocket/TCP buffer.
- "Any frame counts" can mask one-way liveness problems. For example, the brain may receive camera frames while the body receives no control traffic.

Impact:

- E-stop and failsafe may be delayed behind media traffic.
- Different implementations could choose 1 second or 3 seconds.
- A WebSocket that is still carrying one direction of traffic may hide failure in the other direction.

Required action:

- Pick one failsafe timeout and update all docs.
- Define liveness per direction, not just "any frame."
- Add priority rules: `stop`, `ping`, and safety messages must not wait behind camera/audio queues.

### CF7 - Single WebSocket carrying media and control needs explicit backpressure design

Severity: High.

Affected lines: D2 L022, D2 L026-L031, S L022, S L060-L063, S L065-L069.

The spec multiplexes JSON control, mic PCM, camera JPEG, and speaker PCM over one WebSocket. It says audio wins over camera when congested, but does not define queues, maximum frame sizes, drop policy, or how control priority is preserved.

Impact:

- A large JPEG frame can delay E-stop, `mic`, `cam`, or `profile` commands if the implementation writes frames serially.
- ESP32 memory pressure can spike from complete JPEG frames plus audio chunks plus outbound queue.
- Binary header has no stream id beyond type and a sender-local counter; loss/latency diagnostics are underspecified.

Required action:

- Define bounded queues per class: control, audio, camera, telemetry.
- Define maximum camera JPEG size and drop behavior.
- Require control writes to preempt media writes or use separate logical priority queues inside the single socket.

### CF8 - Security model is incomplete

Severity: High.

Affected lines: D2 L004-L005, D2 L015, D2 L037-L038, D2 L096, S L019-L027, S L104-L112, S L146.

Good decisions:

- Robot dials out and does not expose inbound ports during normal operation.
- Credentials are not stored on SD.
- NVS encryption is considered.

Gaps:

- Long-lived token is assumed but rotation is open.
- NVS encryption key generation/storage is not specified.
- TLS is only SHOULD for relay and MAY be plaintext on LAN.
- Captive portal provisioning accepts credentials and auth token, but no local setup password, physical-button window, or CSRF/session rules are described.
- Dashboard has E-stop and calibration controls but no auth/authorization requirements.
- Cloudflare relay details are out of scope even though the architecture depends on relay mode.

Impact:

- Anyone with LAN access could potentially hit dashboard controls if auth is omitted.
- Stolen long-lived token gives persistent robot control.
- Provisioning mode could be abused if reset behavior is weak.

Required action:

- Define a minimal threat model.
- Require dashboard auth.
- Define token rotation or at least revocation.
- Define provisioning safety: physical presence, timeout, setup password, and no persistent setup AP.

### CF9 - Brain-side services are named but not contract-defined

Severity: High.

Affected lines: D2 L014-L020, S L109-L116.

The docs name MetaHuman OS, Whisper, face detection, sleep/training, dashboard, and gateway. Only the body-gateway protocol is detailed. The internal brain APIs are not specified.

Impact:

- The Gateway could be implemented in a way MetaHuman OS cannot use.
- Whisper and face detection may receive incompatible audio/frame formats.
- Sleep/wake schedule semantics are underdefined.

Required action:

- Add gateway internal API contracts for queueing intents, streaming transcripts, receiving events, and TTS audio.
- Define the adapter contract to current MetaHuman environment bridge or declare a new MetaHuman integration point.

### CF10 - Emulator plan does not match the current simulator path

Severity: Medium-High.

Affected lines: D2 L020, D2 L082-L083, S L113-L114.

The spec wants a Python body emulator that implements body behavior completely. The current repo has:

- A Python adapter and virtual backend.
- A local simulator shim.
- A prebuilt browser Sesame simulator.
- A browser-injected `ainekio-shim.js`.

Current simulator notes say the Sesame simulator lacks WiFi/API behavior and is only a visual backend.

Impact:

- The current simulator is not the protocol-faithful body emulator described in the spec.
- A developer may mistake the shim/visual simulator for the body emulator acceptance stand-in.

Required action:

- Create a separate `emulator/` module that dials into the Gateway using protocol v0.3.
- Reuse the current `motion` sequence logic only if it is explicitly adapted.
- Keep the Sesame shim as a visual backend, not as the normative body emulator.

### CF11 - Power and battery safety is under-specified

Severity: High.

Affected lines: D2 L031, D2 L090-L092, S L071-L077, S L136, S L143, S L148.

The docs set 7.0 V warning and 6.8 V cutoff thresholds, but do not specify:

- Battery chemistry and exact pack voltage curve.
- Voltage divider values/tolerances.
- ADC calibration method.
- Servo rail current budget under stall.
- Whether E-stop only sends neutral PWM or also removes servo power.
- Brownout recovery behavior beyond one event name.
- Bulk capacitance sizing and regulator transient validation.

Impact:

- The robot may brown out or reset under servo stall.
- Low-battery thresholds may be wrong for the actual pack.
- E-stop may not remove torque if a servo stalls mechanically.

Required action:

- Add an electrical validation section before hardware bring-up.
- Define battery ADC calibration and divider math.
- Decide whether the servo rail has a hardware enable/cutoff.

### CF12 - Acceptance tests are good but not sufficient

Severity: Medium-High.

Affected lines: S L127-L144.

The acceptance tests cover important happy paths and some safety paths, but missing tests include:

- Malformed JSON, missing fields, type mismatch, unknown fields, overlarge frames.
- Duplicate `seq`, wraparound, reconnect race, queued command while disconnecting.
- Two robot connections with the same id and "newest wins."
- E-stop during camera congestion, audio playback, calibration, and OTA.
- Provisioning reset and credential replacement.
- NVS corruption and missing calibration.
- LittleFS missing assets.
- SD present/absent hot/fault cases if SD remains planned.
- Dashboard auth and unauthorized command attempts.
- Flash partition size check against actual built firmware image.

## Compatibility With Current Code

Reusable concepts:

- Semantic command boundary in `motion/src/ainekio_motion/types.py:13` and `commands.py`.
- Current safety concepts in `motion/src/ainekio_motion/safety.py:19-74`.
- Sequence rendering in `motion/src/ainekio_motion/sequences.py:9-98`.
- Virtual backend and simulator publishing path for visual testing.
- Tests proving no raw-servo API for AI callers and stale-action rejection.

Not compatible without a bridge/rewrite:

- Current MetaHuman transport uses HTTP/SSE, not robot WebSocket.
- Current message schema is MetaHuman environment actions, not protocol v0.3 JSON.
- The generic disabled hardware backend is only a guard; there is no ESP-IDF/MCPWM implementation yet.
- Current simulator shim is not a protocol-faithful body emulator.
- Current tests do not cover binary media, gateway epochs, hello/welcome auth, profile enforcement, or ESP32 pin maps.

Recommended repo structure for the ESP32-S3 plan:

- `protocol/`: Python schema, golden fixtures, binary frame helpers.
- `gateway/`: Python WebSocket gateway, dashboard, MetaHuman adapter.
- `emulator/`: protocol-faithful Python body emulator.
- `firmware/esp32s3/`: ESP-IDF project.
- `docs/`: updated spec with obsolete-hardware cleanup and corrected pin maps.
- `tests/protocol/`: cross-language fixtures shared by gateway, emulator, and firmware.

## Required Clarifications Before Implementation

These are stop-and-ask items because implementation would require assumptions:

1. Is microSD a hard requirement for v1, or can it be deferred completely?
2. If SD is required, is adding a servo driver board or other GPIO-reducing hardware acceptable?
3. Should the gateway replace MetaHuman's existing environment bridge or sit behind it?
4. What exact board SKU is being bought, and is N16R8 guaranteed?
5. Does the dashboard need authentication in v1? My recommendation is yes.
6. Should tokens be long-lived, rotated, or revocable from MetaHuman OS?
7. Does E-stop need to cut servo power or only command neutral PWM?
8. Is home-LAN plaintext `ws://` acceptable, or should `wss://` be required everywhere?
9. Should the current Python motion module remain the source of truth for sequences, or should firmware own a separate pose table from day one?

## Detailed Technical Review

### Architecture

The three-layer model in D2 and S is sound, but it needs a transition plan from the current Python adapter/simulator tools to the gateway plus ESP32-S3 firmware architecture. The simulator stack can remain useful, but it should be explicitly labeled as emulator/simulator support rather than the hardware path.

The rule "anything changing weekly lives in Python; anything that must never fail lives in C" is a good design principle. The plan should convert it into ownership boundaries:

- Python owns planning, protocol validation, dashboard, media services, and emulator.
- Firmware owns servo limits, battery lockout, E-stop execution, stale rejection, link failsafe, and provisioning.
- Shared schema owns message names, field names, ranges, and compatibility.

### Protocol

Protocol v0.3 is a good start but not implementable as-is. It needs:

- A formal schema.
- Valid example messages.
- Error code table.
- State-specific command accept/reject table.
- Media frame limits.
- Queue/backpressure policy.
- Version negotiation that does not depend on "higher version decides compatibility."

Recommended protocol rule change:

- Every control command except `ping`/`pong` has `seq`.
- Every command response includes `seq`, `code`, and optional `detail`.
- Every media frame header includes type, stream id, flags, and timestamp/counter, or the spec explicitly says the current 5-byte header is final and why.

### Firmware

The FreeRTOS task decomposition is reasonable. The key missing firmware design details are:

- Queue sizes and priorities.
- Which task owns global state transitions.
- How E-stop preempts media and motion.
- Whether servo outputs are disabled or neutraled on failsafe/deep sleep.
- How calibration mode protects against unsafe ranges.
- How NVS schema migrations work.
- Whether missing LittleFS assets are fatal or ignored.
- How OTA rollback success is confirmed.

### Hardware

The hardware plan needs a pin-map correction before code. The MAP_B SD plan is likely not viable on R8/octal PSRAM as described. Also, GPIO19/20 for I2S conflicts with USB-JTAG default usage. GPIO3/45/46 strapping pins need more than delayed attach; the electrical effect of servo signal wires and any pull behavior at boot must be tested.

Recommended hardware gate before firmware architecture freezes:

- Exact board SKU and module marking.
- Vendor schematic/pinout review.
- `gpio_dump_io_configuration()` after boot.
- PSRAM and camera init with proposed pins.
- USB/UART debugging plan.
- 20 clean boots with all servo signal wires connected.
- Servo rail transient test with camera and WiFi active.

### Security

Security is currently treated as a transport detail. It should be a first-class safety requirement because this is a remote-actuated device with camera, microphone, speaker, and servos.

Minimum v1 security requirements:

- Dashboard auth.
- Token revocation path.
- Provisioning mode requires physical action and times out.
- No unauthenticated calibration or E-stop clearing.
- Logs must not print auth tokens.
- TLS required for relay, and strongly preferred on LAN if practical.

### Data Budget

The data budget thinking is good. The missing detail is enforcement:

- The body must reject out-of-profile `cam` and `mic` settings.
- The gateway should know profile caps and avoid sending impossible commands.
- The dashboard should display effective caps, not only requested caps.
- Camera frame drops should be counted and reported.
- Audio VAD false-open/false-close metrics should be logged.

### Build Order

The build order is mostly right but should be adjusted:

1. Confirm SD policy.
2. Write protocol schemas and fixtures.
3. Build gateway skeleton and protocol emulator.
4. Adapt current motion sequences or write firmware pose-table source format.
5. Build dashboard against emulator.
6. Add MetaHuman adapter contract.
7. Only then start ESP-IDF firmware modules.

## Line-By-Line Disposition: D2

Each source line is included by range. Consecutive lines with the same review finding are grouped intentionally.

| Lines | Disposition |
| --- | --- |
| D2 L001-L002 | Good versioning note. Should add "supersedes v1 but spec v0.3 is normative" and mark older hardware notes as obsolete. |
| D2 L003-L010 | Operating narrative is coherent. Security login, Cloudflare role, and mobile tether behavior need concrete deployment and auth details. |
| D2 L011-L013 | Three-layer split is strong. Needs migration text from the current Python adapter/SSE simulator tools to the gateway/WebSocket architecture. |
| D2 L014-L020 | Brain modules are plausible, but Robot Gateway, Dashboard, Face service, and Body Emulator do not exist locally. Add explicit build artifacts and API contracts. |
| D2 L021-L022 | Single WebSocket is a clean target. It conflicts with current SSE adapter and needs backpressure, relay, and priority rules. |
| D2 L023-L036 | Firmware task decomposition is reasonable. Needs queue sizes, priorities, state ownership, E-stop preemption, and hardware pin corrections. |
| D2 L037-L038 | NVS decision is correct direction. Missing NVS encryption key lifecycle, token rotation, provisioning auth, and dashboard auth. |
| D2 L039-L045 | Storage math is useful but the GPIO count is incomplete because USB-JTAG and R8 GPIO33-37 constraints are missing. |
| D2 L046-L050 | Critical issue: GPIO33/34 may not be usable on R8/octal PSRAM. SD plan should be marked blocked, not clean. |
| D2 L051 | Partition plan is plausible but must be verified by an actual ESP-IDF partition table and built firmware image sizes. |
| D2 L052-L053 | Audio data-budget math is good. Need VAD/wake false-positive behavior, privacy policy, and profile enforcement. |
| D2 L054-L055 | Event-driven rule is good. Heartbeat/status periods need one normative source and control-priority handling. |
| D2 L056-L063 | State table is useful. Failsafe says 1 second here but 3 seconds in spec. Deep sleep and dozing wake semantics need exact behavior. |
| D2 L064-L071 | Data profiles are sensible. Body and gateway enforcement rules need exact caps and rejections. |
| D2 L072-L083 | Build order is mostly right. It should first create schemas/fixtures, and it must distinguish the current simulator shim from the required body emulator. |
| D2 L084-L092 | Running risk list is good. Add GPIO33-37/R8 conflict, GPIO19/20 USB-JTAG conflict, security/dashboard auth, and current adapter-to-gateway migration risk. |
| D2 L093-L098 | Open questions are valid. Add SD requirement, E-stop power behavior, token revocation, Cloudflare deployment, and sequence source-of-truth. |

## Line-By-Line Disposition: D1

D1 is superseded by D2 and S, but it still matters because it remains in the requested review set and contains conflicts.

| Lines | Disposition |
| --- | --- |
| D1 L001-L002 | Historical discussion doc. Should be marked superseded in the file itself to avoid implementation from stale guidance. |
| D1 L003-L010 | Similar operating narrative to D2. D1 treats Cloudflare as primary meeting point; S makes LAN primary and relay optional. Reconcile. |
| D1 L011-L021 | Division of labor is sound. It lacks the gateway/dashboard/body-emulator architecture that appears in D2/S. |
| D1 L022-L034 | Provisioning/NVS reasoning is good. It assumes SD deferred, unlike D2/S which plan for optional SD. |
| D1 L035-L044 | Storage section conflicts with D2/S: says card not included and SD currently pinned out. Keep only as historical unless updated. |
| D1 L045-L050 | Audio policy is still valid. Needs same enforcement/privacy additions as D2. |
| D1 L051-L056 | No-polling rule aligns with later docs and current adapter direction. Current implementation uses SSE, not protocol WebSocket. |
| D1 L057-L065 | State table conflicts with S on failsafe timing: 1 second here versus 3 seconds in S. |
| D1 L066-L073 | Data budget profile concept carried forward. Good, but not fully testable yet. |
| D1 L074-L080 | Mockup plan references protocol v0.2, while S is v0.3. Update or mark superseded. |
| D1 L081-L090 | Compatibility list is older. SD and pin-map findings are no longer sufficient; R8 GPIO33-37 conflict must be added. |
| D1 L091-L096 | Open questions mostly carried into D2/S. Add new platform and hardware feasibility questions. |

## Line-By-Line Disposition: S

S is the normative document, so these findings are more important than D1/D2.

| Lines | Disposition |
| --- | --- |
| S L001-L002 | Good normative framing. Add that this spec supersedes obsolete local hardware notes. |
| S L003-L004 | Scope is clear. N16R8 dependency is a critical procurement gate. |
| S L005-L011 | Build order is good. Add repo paths, deliverables, and acceptance criteria per component. |
| S L012-L016 | Definitions are helpful. Add "body emulator" as a defined body implementation and define "gateway" formally. |
| S L017-L022 | Transport target is clear. Needs migration from current SSE bridge and priority/backpressure rules. |
| S L023-L027 | Session establishment is conceptually good. Examples need valid JSON and version compatibility cannot be "higher version decides" without a policy. |
| S L028-L030 | JSON control section needs formal schema. "Every command carries seq" conflicts with `ping`. |
| S L031-L043 | Intent messages need valid JSON, required/optional fields, ranges, defaults, and state-specific rejection rules. |
| S L044-L050 | Calibration messages are necessary but risky. Require auth, timeout, safe rate limits, and no persistence until explicit save. |
| S L051-L058 | Body-to-brain responses are a good base. Add richer `done`/progress/cancelled semantics and clarify stale detection. |
| S L059-L063 | Binary frame header is minimal. Need max sizes, queue policy, stream counters, and control/media priority. |
| S L064-L069 | Liveness constants are useful. Resolve 1s vs 3s conflict and define per-direction liveness. |
| S L070-L077 | Safety requirements are good but incomplete. Add servo power, ADC calibration, brownout, and e-stop hardware behavior. |
| S L078-L080 | ESP-IDF target is clear and needs an ESP-IDF project scaffold. |
| S L081-L090 | Task layout is plausible. Needs concrete priorities, queue ownership, and failure-mode handling. |
| S L091-L092 | MCPWM requirement is reasonable. Confirm exact MCPWM channel/resource count in implementation and tests. |
| S L093-L097 | Pin map has critical issues: MAP_B likely invalid on R8/octal PSRAM; GPIO19/20 USB-JTAG conflict; strapping pins need bench validation. |
| S L098-L099 | Partition plan needs an actual CSV and build-size check. S says NVS 64 KB minimum; D2 says 0.5 MB. Reconcile. |
| S L100-L101 | NVS contents list is useful. "SD-enable flag (MAP_B builds)" is confusing because build flag and runtime NVS flag are different mechanisms. |
| S L102-L103 | Storage rules are good. SD should remain out of v1 until pin map is proven. |
| S L104-L105 | Provisioning flow is plausible. Needs setup security, timeout, and physical-presence constraints. |
| S L106-L107 | I2S plan is supported by ESP-IDF full-duplex docs. Need pin conflict resolution and underrun/backpressure tests. |
| S L108-L110 | Gateway responsibilities are strong. Missing local implementation and internal API details. |
| S L111-L112 | Dashboard MVP is appropriate. Must add auth and command authorization. |
| S L113-L114 | Emulator scope is correct but large. Split into MVP phases and do not confuse with current Sesame shim. |
| S L115-L116 | MetaHuman adapter is under-specified. Current repo uses existing environment bridge; decide integration point. |
| S L117-L124 | State machine table is useful. ACTIVE entry by "traffic" may prevent idle if media/heartbeat counts as activity; define intent traffic separately. |
| S L125-L126 | Data profile rule is good. Need exact enforcement and tests for out-of-profile rejection. |
| S L127-L137 | Protocol/emulator acceptance tests are strong. Add malformed input, security, duplicate connection, and queue congestion cases. |
| S L138-L144 | Hardware tests are good. Add MAP_B feasibility test, USB-JTAG/I2S debug plan, ADC calibration, and flash-size check. |
| S L145-L146 | Out-of-scope list is reasonable except Cloudflare relay details may not be fully out of scope if relay mode is an architectural requirement. |
| S L147-L148 | Risk register is useful but incomplete. Add MAP_B/R8 GPIO issue, USB-JTAG conflict, security/auth, current repo migration, and power rail validation. |

## Recommended Spec Edits

1. Replace MAP_B with a blocked/conditional design:

```text
MAP_B is not approved for implementation. On ESP32-S3 R8/octal-PSRAM targets, GPIO33-37 may be unavailable or not recommended. SD support requires exact board schematic confirmation and bench validation, or a GPIO-reducing hardware change such as a PWM driver.
```

2. Add an obsolete-hardware cleanup note:

```text
The ESP32-S3/ESP-IDF/WebSocket architecture is the hardware direction of record. Older rejected hardware references are obsolete and should not guide implementation. The existing Python motion module remains useful as simulator/emulator support and a reference for semantic commands and sequence rendering until superseded by protocol v0.3 fixtures and firmware pose tables.
```

3. Add a transport migration note:

```text
The current MetaHuman environment bridge uses HTTP POST plus SSE. The Robot Gateway will either wrap that bridge or replace it. Firmware must only know protocol v0.3 over its robot-initiated WebSocket.
```

4. Add a machine-readable schema requirement:

```text
Every protocol message MUST have a JSON Schema entry and at least one valid golden fixture. Firmware, gateway, and emulator tests MUST consume the same fixtures.
```

5. Add security requirements:

```text
Dashboard and calibration endpoints MUST require authentication. Provisioning mode MUST require physical presence and MUST time out. Tokens MUST be revocable. Logs MUST NOT include auth tokens.
```

## Suggested Next Work Order

1. Confirm the SD requirement.
2. Correct the pin map before any firmware code is written.
3. Define protocol schemas and golden fixtures.
4. Implement the Python gateway and protocol-faithful emulator.
5. Adapt or retire the current SSE adapter.
6. Add dashboard with auth and E-stop path.
7. Only then start ESP-IDF firmware modules.
8. Run hardware gates before freezing pin assignments.

## Validation Notes

I could not run the local Python tests in this Windows session. `python`, `py`, and `python3` resolve to local Windows app aliases that fail with "The file cannot be accessed by the system." The existing docs report prior test success, but this audit did not independently re-run the suite.

The three DOCX files were read through DOCX ZIP/XML extraction in PowerShell. The DOCX files themselves were not modified.
