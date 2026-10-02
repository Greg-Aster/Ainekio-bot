# Body Control Integration

Started: 2026-09-28

Updated: 2026-10-02 — portable Body Control pairing and P4 connection switching

Status: Living research, implementation and decision record

## Purpose and current direction

Record how ROS 2 can supplement Ainekio and MetaHuman OS, compare the two ways
to connect the ESP32-P4 body controller to Q6A, and preserve the findings and
implementation targets for later work.

**Selected direction: wireless P4/C6 body to offboard Q6A, with a separate
Q6A connection to remote MetaHuman OS.** The owner selected this to reduce robot
weight and carried compute power. Both Q6A and the remote machine run MetaHuman:
Q6A handles responsive local processing; remote MetaHuman handles heavy reasoning,
long-term memory and training. The remote machine may be geographically distant.

The previous native-USB recommendation compared transport with power excluded.
Its capacity advantages remain valid, but it is now the alternative rather than
the implementation priority. Wi-Fi already has an Ainekio implementation; the
two-installation MetaHuman division of labor still needs defined contracts.

The [distributed robot foundation](DISTRIBUTED_ROBOT_FOUNDATION.md) records the
function allocation, existing source owners, proposed communication contracts,
failure behavior and staged migration. **Define those boundaries before migrating
features.** The owner confirmed that Q6A should continue defined local skills
while remote-dependent tasks pause when the remote server is unavailable.

**Latest control requirement:** P4 is the robot brain and accepts the same
control contract from interchangeable authorized sources. Q6A, remote MetaHuman
and standalone manual Body Control must each be usable without requiring the
other hosts. Available-gateway connection switching is implemented in source;
general source grants and cross-installation task continuation remain planned. The shared
gateway is the existing integration point; extend P4 admission/connection
ownership rather than making Q6A a mandatory intermediary. Manual client hardware
remains undecided.

Keep gait execution and fast IMU feedback local to P4, with perception and
expensive planning on the host. Measure concurrent resource use and end-to-end
update latency before offloading additional computation. Neither connection has
a qualified full-load latency bound.

**ROS 2 is an optional Q6A integration layer.** Preserve the existing gateway,
body controller and MetaHuman responsibilities. Start with telemetry and tools;
keep the local motion/IMU feedback loop on P4. Details and sources are below.

**Use the [complete system budget](v2-12servo/RESOURCE_BUDGET.md) for design
decisions.** Native USB HS provides a higher-capacity interface and removes radio
contention on the body link; offboard Q6A/Wi-Fi removes carried compute power/mass
and frees a dedicated 3 A servo branch. Those are distinct benefits. Neither
transport is qualified for maximum concurrent media and loaded motion.

The [2026-09-28 audit](v2-12servo/BUDGET_AUDIT_EVIDENCE.md) covers P4 firmware,
gateway and MetaHuman speech paths, manufacturer specifications, Q6A interface
capabilities and a new offline Kokoro timing/memory measurement. It also records
why chip typical-current figures cannot form a guaranteed whole-robot total.

The owner reports Q6A operation from 5 V / 3 A and plans a headless workload
without USB peripherals, monitor, or fan. Do not treat Radxa's recommended supply
rating as actual consumption or use it alone to select onboard versus offboard
placement. The earlier cable comparison excluded power at the owner's request.
The later wireless/offboard selection explicitly considers robot weight and power.
Preserve both rationales when revisiting the decision.

This record separates planning from the tested software increments below. It
does not amend the system specification, record a completed transport migration,
or authorize firmware flashing or body motion.
Existing implementation and hardware boundaries remain documented in the
[V2 firmware design](v2-12servo/FIRMWARE_DESIGN.md) and
[P4 firmware README](../Slave/firmware/esp32p4-wifi6/README.md).

The first software increment is [portable IMU estimation](../Slave/software/imu/README.md):
timestamped SI-unit samples, explicit mounting/calibration, attitude estimates,
freshness and recovery state, with host tests and P4 compilation. There is no
live sensor task, wire telemetry or movement correction yet. The GY-LSM6DS3 is
not wired; GPIO7/8 on the existing media/control I2C bus is the recommendation,
pending the owner's wiring choice and physical axis verification. MetaHuman
retains command authority through the existing gateway and Environment Bridge.

The host now uses MetaHuman's existing durable execution and Work Coordinator
for one active task program. Environment Mode and the autonomy executor both
select ordered semantic actions, generated gestures, and ongoing behaviors for
that same executor. A behavior starts one continuous gait; fresh recognition can
update forward movement and turning together while a separate finite model job
identifies a free-text target from a correlated still. Identifying a target ends
that phase, then the executor performs the remaining gestures before recording
whole-task completion. Conversation alone creates no body action. The active
executor and its two entry graphs use event-driven loops without a fixed count
on recognition events or steering instructions.

The temporary repeated-motion local-task route and per-motion Action Result
workflow have been removed. Task-level cognitive review still handles unfinished
conversational objectives; it is not called between physical phases. The existing
Bridge sends ongoing updates with the original action identity and body lease;
the P4 interpolates steering without restarting gait phase. No ROS execution
owner, obstacle/edge policy, lost-vision stop, or model-error recovery command was
added. Metric navigation, target tracking, live IMU feedback, Q6A deployment,
recognition quality and loaded wireless latency require prototype work. The owner
prefers recognition-model comparisons on the assembled prototype.

Camera streaming and remote snapshots now share one P4 capture/encoder owner
with independently configurable output resolutions. The negotiated
[`camera_profiles_v1` contract](../Slave/software/protocol/README.md#existing-lifecycle-and-media-contracts)
keeps lower-resolution preview local and preserves correlated per-call stills
for the Environment Bridge. Native camera-owner and gateway tests cover their
coexistence, including snapshots with streaming disabled; hardware throughput,
capture age and recognition accuracy remain unqualified.

## Intended responsibility split

| Device | Intended responsibility |
| --- | --- |
| ESP32-P4 | Execute the existing gait and servo control; acquire the planned LSM6DS3 IMU; own local movement supervision and future fast posture correction. |
| Offboard Q6A | Host the existing Ainekio gateway and local MetaHuman; provide lightweight task coordination, bounded media transport, responsive feedback and defined local skills. |
| Remote computer/server | Run heavy inference and perception, long-term memory, training and expensive tools; may run on a distant server. |

The deployment split and takeover policy are still design work. All sources
must use the common Ainekio control contract and P4 admission/output owner.
The existing gateway serves manual and MetaHuman requests. P4 now selects another
available paired gateway after losing its current connection, without replaying
movement or transferring an active objective. The LSM6DS3 has been received; its installation and integration
are planned, not verified. Whether ROS is used for sensors or diagnostics is a
separate decision from wired versus wireless transport.

## 2026-10-02 implementation: portable Body Control and host switching

The owner selected both shared-LAN and separate-hotspot operation, with any
authorized Body Control host using the same robot identity and command/result
contract. This increment changes source and tests only. No service was started
against the robot, credentials/configuration changed, firmware flashed, or new
changes committed/pushed. The earlier steering/recognition increment is retained;
its approved `walk_steering_v1` signs, percentage units and ACK semantics are
unchanged. No historical speech/catalog patch was reapplied.

The owner subsequently authorized committing and pushing this increment to
`origin/dev`. Publication preserves the remote structural crossbar additions;
the outstanding SDK build, dependency-lock regeneration and hardware checks
below remain outstanding. That instruction does not authorize deployment,
flashing or robot movement.

The worktree started clean on local `main` at
`eb3e50e2c00fb76096e8538022f62474349fb361`. Fetching remote refs left the checkout
unchanged: `origin/dev` is `7cf5a543e086bd94f3c0833e5e7d1bd054df5bf2` and
`origin/main` is `022bda54ebd97711d656313513d29c3a80bb3f28`. The remote dev increment
contains only front/rear structural crossbar STL exports and overlaps none of
this repair. No merge was performed. The supplied prep, parent `AGENTS.md`,
distributed foundation, maintained MetaHuman boundaries and protocol/firmware
records were read; no Ainekio repository-specific `AGENTS.md` exists.

**Connection and identity contract.** P4 advertises `gateway_switching_v1`
through existing protocol-v1 feature negotiation. The existing four-slot
`robot_settings_v1` wire/NVS structure is unchanged. Same-SSID slots can hold
different computer or tunnel URLs and share one Wi-Fi password; duplicate
SSID/URL pairs reject, password updates apply to all slots for that network, and
legacy recovery preserves alternate URLs. Wi-Fi selection cycles distinct SSIDs
when offline. A working Wi-Fi association is retained, so switching to a
different hotspot requires the previous hotspot to stop. The existing managed
hotspot lifecycle does that on gateway shutdown when enabled.

P4's existing `link_task` selects configured URLs on that association, followed
by at most eight discovered protocol-v1 LAN candidates. An authenticated
connection remains selected until loss or explicit gateway shutdown. Discovery
requires a configured plain-WS LAN profile on that network; WSS-only networks
never downgrade to discovery. Configured WSS retains certificate-bundle checks.
Network-generation changes clear discoveries. The old WebSocket/admission owner
closes before another opens; sequence/session fencing and output disable remain
with P4. An unauthenticated attempt expires after 10 seconds, retry delay is
1 second, and a discovery query is bounded to 2.5 seconds. These are configured
bounds, not measured handoff latency or Q6A performance.

The S3 DNS-SD implementation was moved into one shared component and extended
with a list API. Its existing single-result API retains explicit ambiguity
rejection. Filters still require the current station IPv4 subnet, the existing
protocol/path/transport/TLS TXT values and a nonzero port. Older P4 firmware
retains its supported network commands; fresh correlated settings readback
lets the gateway reject unsupported same-network alternates before assigning
a sequence or dispatching. No substitute command is sent.

The existing security owners export/import a versioned, owner-only bundle of
saved robot tokens (including pending rotation) and dashboard password verifier.
The bundle excludes sessions, task/action databases, logs, `.env`, machine paths,
MetaHuman and tunnel credentials. Imports validate the whole bundle and both
stores first, preserve conflicting credentials with an explicit error, and
allow identical retries. Each new store is written exclusively and atomically;
an explicit disk failure may leave one imported store, and the same import
finishes it. This is credential portability, not another writable authority.
Later credential changes must be coordinated across the hosts.

Standalone Body Control no longer requires a MetaHuman Bridge token; configured
recognition still requires the authenticated Bridge. Start, stop and relay now
share the existing trusted `.env` loader and preserve explicit environment
precedence. Stop uses the same configured runtime directory as start. Production
SIGTERM stops admission, cancels pending commands with `disconnect`, releases
body/Bridge/incomplete-handshake sockets and exits. This also fixes a shutdown
hang with the installed WebSocket/Python 3.12 server lifecycle.

The integrated regression uses two independent real loopback gateway servers
and the production native P4 selector, settings, decoder and admission code.
One ongoing walk ACK remains pending; stopping its host returns correlated
`cancelled/disconnect`. The next paired host receives no replay and admits a new
finite command. The old generation rejects even if both hosts reuse epoch 1.
Device transport/execution is simulated. A TLS fixture tests an untrusted
certificate rejection and authenticated configured relay transport, using a
simulated Cloudflare header. A real production subprocess shutdown test covers
an authenticated body, authenticated Bridge and incomplete HTTP handshake.
The existing recognition/steering and emergency-stop regressions also run in
the aggregate. No second queue, durable executor, inference runtime or LLM
behavioral substitute was introduced; task ownership remains in MetaHuman.

Changed files, grouped by owner (paths are relative to the named directory):

| Directory | Files |
| --- | --- |
| `Master/` | `gateway-env.sh` (new), `start-physical-gateway.sh`, `stop-physical-gateway.sh`, `start-physical-relay.sh` |
| `Master/gateway/` | `security.py`, `server/service.py`, `server/__main__.py`, `dashboard/static/dashboard.html`, `dashboard/static/dashboard.js`, `README.md` |
| `Slave/firmware/esp32p4-wifi6/` | `CMakeLists.txt`, `README.md`, `main/CMakeLists.txt`, `main/config.c`, `main/controller.c`, `main/gateway_selection.c` and `.h` (new), `main/idf_component.yml`, `main/network.c`, `main/network.h`, `main/robot_settings.c`, `main/robot_settings.h` |
| `Slave/firmware/components/ainekio_discovery/` | `CMakeLists.txt` (new), `local_discovery.c`, `include/ainekio/platform/local_discovery.h`; implementation/header moved from S3 `components/ainekio_platform/src/local_discovery.c` and `include/ainekio/platform/local_discovery.h` |
| `Slave/firmware/esp32s3/` | `CMakeLists.txt`, `components/ainekio_platform/CMakeLists.txt` |
| `Slave/software/` | `core/include/ainekio/protocol.h`, `protocol/control_v1.py`, `protocol/README.md` |
| `Slave/firmware/esp32p4-wifi6/tests/` | `CMakeLists.txt`, `test_robot_settings.c`, `test_robot_settings_store.c`, new `test_gateway_selection.c`, `test_gateway_discovery.c`, `discovery_shim/esp_netif.h`, `discovery_shim/mdns.h` |
| `Emulator/` | new `tests/test_pairing_transfer.py`, `tests/test_gateway_switching.py`; `tests/test_physical_gateway_launcher.py`, `tests/test_robot_settings.py`, `tools/run_acceptance.py`, `tools/dashboard_browser_acceptance.mjs` |
| Root/docs | `.env.example`, `docs/BODY_CONTROL_INTEGRATION.md`, `docs/DISTRIBUTED_ROBOT_FOUNDATION.md` |

**Configuration changes to use after review/build.** Export pairing once from
the working host with `./Master/start-physical-gateway.sh --export-pairing FILE`;
privately copy that file, retain mode 0600, then use `--import-pairing FILE` and
`--check` on the other host. Each host installs its own dependencies and uses
its own `.venv`; machine paths, local Bridge tokens and tunnel credentials stay
local. Configure the robot's LAN or WSS URLs using its existing settings UI.
Start the desired host, stop the currently selected host, and stop the old
hotspot if changing SSIDs. A returning host does not seize a healthy connection.
The [gateway README](../Master/gateway/README.md#using-more-than-one-computer)
contains the exact commands. Phone browsers use a host dashboard explicitly
bound to its private LAN address; the default stays loopback. The P4 setup
portal is not a body-control dashboard.

Final software validation:

| Check | Exact result |
| --- | --- |
| Pairing, launcher, legacy/current settings, security, real-socket/native switching and production shutdown | 53/53 passed, 11.786 s; exit 0 |
| Native CMake configure/build | Passed with configured `-Wall -Wextra -Werror`, new shared discovery/selection and core/model `-Wpedantic`; exit 0 |
| Focused P4 settings/store/discovery/admission/body/camera/calibration | 9/9 passed, 0.90 s; exit 0 |
| Full native CTest | 37 cases: 33 passed, 1 failed (`v2_run_source`), 3 skipped (`v2_crab_geometry`, `v2_gait_geometry`, `v2_locomotion_generator`); 36.26 s; exit 8 |
| Headless Chromium dashboard | All 23 browser checks passed; exit 0 |
| Required A-series aggregate | 29/31 passed, including new A31; A16 and A27 fail; exit 1 |
| Aggregate emulator component | 390 tests: 383 passed, 6 failures, 1 error; 65.335 s; no skipped tests |
| Aggregate protocol component | 14 tests: 11 passed, 3 failures; 0.033 s |
| Aggregate portable C component | 13/13 passed |
| Aggregate browser component | 23 checks passed; A29 passed |
| This checkout's actual `./Master/start-physical-gateway.sh --check` | Interpreter/dependency loading passed, then exit 2: no saved robot pairing or `AINEKIO_ROBOT_TOKEN` here. Import the working computer's pairing bundle; no listeners/services started |
| Python syntax, shell syntax, JavaScript syntax, YAML and whitespace | 9 changed/new Python files parsed; 4 shell scripts pass `bash -n`; 2 JavaScript files pass `node --check`; P4/S3 manifests parsed and mDNS pins agree; local documentation links and `git diff --check` pass; exit 0 |

The full native failure is the existing exact `run_blend` source assertion;
the skips require scientific Python dependencies. Existing aggregate failures
in asset counts/sit poses, the missing Sesame source header, run-to-walk blending
and protocol schema/fixture coverage are outside this increment. Their source
inputs are unchanged from starting HEAD, and the prior implementation record
below reports the same failures. Chromium is installed here instead of Google
Chrome: the browser test now accepts `AINEKIO_TEST_BROWSER`; its first cold
launch missed the existing five-second DevTools readiness window, and the
subsequent full run passed. There is no configured Python lint/type check and
Ruff/Mypy/Pyright/ShellCheck are absent; syntax checks do not prove Python static
type correctness. No MetaHuman/TypeScript source changed in this increment.

**Remaining build/hardware blockers.** ESP-IDF 5.5.4 and `idf.py` are absent on
this machine. The P4 manifest pins the shared `espressif/mdns` dependency to
`1.11.3`, matching S3, but its committed P4 dependency lock predates this
addition. Run the required IDF reconfigure/build to resolve and regenerate that
lock; no dependency hash was fabricated. Both P4 and S3 need SDK builds before
firmware release. Real mDNS/radio switching, TLS time synchronization,
Cloudflare-to-P4 transport, board memory/timing and physical servo/output-disable
behavior remain untested. No external perception service or robot was contacted.
The fixtures do not establish Q6A performance, perception quality, physical
motion, automatic objective transfer or hardware handoff latency.
The local checkout also needs the existing robot pairing imported before
startup. Credentials were not generated or guessed, and this configuration
blocker does not affect the isolated test fixtures.

Reproduce from the repository root:

```sh
env PYTHONPATH=Master:Slave/software:Emulator .venv/bin/python3 -m unittest \
  Emulator.tests.test_pairing_transfer Emulator.tests.test_physical_gateway_launcher \
  Emulator.tests.test_robot_settings Emulator.tests.test_gateway_security \
  Emulator.tests.test_gateway_switching

cmake -S Slave/firmware/esp32p4-wifi6/tests -B build/host-switching/p4 \
  -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=/usr/bin/python3
cmake --build build/host-switching/p4 --parallel 2
ctest --test-dir build/host-switching/p4 --output-on-failure \
  --output-junit "$PWD/build/host-switching/native-final.xml"

env AINEKIO_TEST_BROWSER=/snap/bin/chromium \
  AINEKIO_V2_WALK_COMMAND="$PWD/build/host-switching/p4/v2_model/v2_walk_command" \
  .venv/bin/python3 Emulator/tools/run_acceptance.py
```

The aggregate report is `build/acceptance/a-series.json`; full native results
are `build/host-switching/native-final.xml`. These ignored artifacts contain
software evidence, not deployment approval.

## 2026-10-01 implementation: steering and remote recognition

Implementation and simulated-device testing were authorized; publishing,
deployment, flashing and robot movement were excluded. Starting refs were
recorded after fetching remote refs without changing either checkout:

| Repository | Starting refs |
| --- | --- |
| Ainekio-bot | Local `main` HEAD, `origin/dev` and `origin/main`: `022bda54ebd97711d656313513d29c3a80bb3f28` |
| MetaHuman OS | Local `main` HEAD and `origin/dev`: `3445379711a58c2360928e700d418728e839bd4b`; `origin/main`: `c3f56d41dfb396cd68391d12a2910aee8c32870b` |

The initial Ainekio edits were gateway/launcher documentation and launcher
changes, this record, docs index, resource budget, plus untracked distributed
foundation and launcher tests. A backup of those exact files, the starting
binary diff and refs is at
`/tmp/ainekio-steering-recognition-start-hie6r8r_/`. Existing unrelated edits
were preserved. MetaHuman initially had a local backend configuration edit;
its consumer implementation changed concurrently during this task. This
Ainekio repair did not edit MetaHuman source or configuration.

Historical speech cleanup commit `9e1e402c` is already an ancestor of the
MetaHuman starting HEAD. The maintained architecture/source retains the current
speech chunk/delivery owners and active-task executor. No separate patch bundle
was found. Reapplying that cleanup would conflict with newer code. The old
speech/catalog test doubles were instead updated to supply the real gateway
instance identifier; their existing assertions and production speech/catalog
owners were retained. Aggregate discovery also now uses the package-qualified
receipt-test import.

The owner approved the steering contract before source changes:
[`walk_steering_v1`](../Slave/software/protocol/README.md#directional-locomotion-and-automatic-run)
is distinct from `walk_controls_v2`. Paired finite `forward` and `turn` use
signed percentages from −100 to +100; positive forward advances and positive
turn turns left. ACK confirms admission, and an update ACK cannot complete the
original action or goal. The existing MetaHuman action/update fields agree with
these signs, units and receipt semantics. Current P4 source advertises the new
feature for its existing decoder/model. The gateway rejects either steering
field on an unsupported body before allocating a sequence or dispatching,
including zero-valued fields, and advertises only supported controls.
Run alias normalization cannot discard steering: those fields require an
explicit walk intent and otherwise reject before dispatch. Existing
directional commands, speed/stride/rate, Finish, deadlines, disconnect fencing,
calibrated limits and emergency stop retain their existing execution owners.

The existing camera worker now accepts one operator-configured recognition
endpoint. Remote service requires authenticated, certificate- and
hostname-verified HTTPS. Local loopback HTTP remains supported. URL credentials,
queries, fragments, control characters, invalid ports and unauthenticated remote
configuration are rejected before transport; redirects and proxies are not
followed. JPEG/result/object bounds and request/read deadlines remain. Failures
reach the existing observation route with robot/epoch/frame/gateway correlation
and a reason, rather than becoming empty successful observations or causing a
new behavioral policy. Q6A transports bounded requests/results, the remote
service performs perception, MetaHuman's LLM/executor owns behavior, and P4's
existing owner performs body execution. No queue, inference runtime or durable
execution authority was added.

Configuration uses the existing `AINEKIO_VISION_URL`, `AINEKIO_VISION_MODEL`,
`AINEKIO_VISION_API_KEY`, timeout and frame-age options documented in the
[gateway README](../Master/gateway/README.md#configured-recognition-and-metahuman-handoff).
Both URL/model and an authenticated Environment Bridge are required. Remote
URL must name an HTTPS Chat Completions route; API key comes from the ignored
environment configuration. Optional private CA trust uses standard
`SSL_CERT_FILE`. The default request timeout is 2 seconds and the frame-age
limit is 1 second; configure freshness deliberately for the selected service.
Only `.env.example` guidance changed; no live endpoint or credentials were set.

The integrated software regression runs the real authenticated HTTPS client
against a simulated recognition service, then the existing adapter/gateway and
SQLite receipts, and feeds the exact emitted steering commands/updates into the
native production P4 decoder/model. It verifies that recognition alone sends no
motion, update results retain action/revision/original sequence correlation,
and the original receipt remains started until its terminal result. Inference
responses, task/model decisions and device ACK/DONE transport are simulated.
Separate MetaHuman consumer tests exercise the actual coordinator/task-state
code. This establishes software integration; it does not demonstrate hosted
inference, Q6A performance or physical motion.

Repair files (existing unrelated dirty files are excluded):

| Area | Changed files |
| --- | --- |
| Gateway | `Master/gateway/server/service.py`, `Master/gateway/environment_adapter/server.py`, `Master/gateway/perception.py`, `Master/gateway/plugins.py`, `Master/gateway/server/__main__.py` |
| P4/protocol | `Slave/firmware/esp32p4-wifi6/main/controller.c`, `Slave/software/core/include/ainekio/protocol.h`, `Slave/software/protocol/control_v1.py`, `Slave/software/protocol/schemas/control-v1.schema.json` |
| Regression tests | `Emulator/tests/test_active_movement.py`, `Emulator/tests/test_recognition_backend.py`, `Emulator/tests/test_camera_perception.py`, `Emulator/tests/test_action_receipts.py`, `Emulator/tests/test_environment_command_catalog.py`, `Emulator/tests/test_environment_speech.py`, `Slave/software/core/tests/test_control_encode.c`, `Slave/software/models/v2-12servo/tests/test_locomotion.c` |
| Configuration/docs | `.env.example`, `Master/gateway/README.md`, `Slave/software/protocol/README.md`, `Slave/firmware/esp32p4-wifi6/README.md`, this record |

Final validation (software only):

| Check | Exact final result |
| --- | --- |
| Focused gateway/perception/receipt/steering/speech/catalog/P4 regressions | 130 tests, 130 passed, 24.730 s; exit 0 |
| Native P4/core/model build | CMake build passed with configured `-Wall -Wextra -Werror` and core/model `-Wpedantic`; no ESP-IDF cross-build |
| Full native CTest | 35 cases: 31 passed, 1 failed (`v2_run_source`), 3 skipped (`v2_crab_geometry`, `v2_gait_geometry`, `v2_locomotion_generator`); exit 8 |
| Required A-series aggregate | 27/30 cases passed; A16, A27 and A29 failed; exit 1 |
| Aggregate emulator component | 367 tests: 360 passed, 6 failures, 1 error; 103.444 s |
| Aggregate protocol component | 14 tests: 11 passed, 3 failures; 0.159 s |
| Aggregate portable C component | 13/13 passed |
| MetaHuman `pnpm test:environment-perception` | 33/33 passed, 199401.668296 ms; exit 0 |
| MetaHuman Bridge lifecycle tests | 4/4 passed, 11814.459383 ms; exit 0 |
| MetaHuman `pnpm typecheck:core` | Passed; exit 0 |
| MetaHuman `pnpm check:architecture` | Passed, 0 violations; exit 0 |
| Syntax and whitespace checks | 12 changed Python files parsed successfully; protocol schema JSON parsed; `git diff --check` passed |

Ainekio has no configured Python lint/static-type check and its venv has no
Ruff, Mypy or Pyright. The Python syntax and whitespace checks above do not
establish Python static type correctness. C compiler warnings and MetaHuman's
configured TypeScript/architecture checks passed. The five original unrelated
dirty files remain byte-identical to the starting-state backup; additions to
the two overlapping documentation files preserve their prior content.

Reproduce the focused check from Ainekio root:

```sh
env PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests \
  .venv/bin/python3 -m unittest \
  Emulator.tests.test_active_movement Emulator.tests.test_recognition_backend \
  Emulator.tests.test_camera_perception Emulator.tests.test_action_receipts \
  Emulator.tests.test_environment_adapter Emulator.tests.test_environment_speech \
  Emulator.tests.test_environment_command_catalog Emulator.tests.test_gateway_service \
  Emulator.tests.test_p4_foundation

cmake -S Slave/firmware/esp32p4-wifi6/tests -B build/steering-recognition/p4 \
  -DPython3_EXECUTABLE=/usr/bin/python3
cmake --build build/steering-recognition/p4 --parallel 2
ctest --test-dir build/steering-recognition/p4 --output-on-failure \
  --output-junit "$PWD/build/steering-recognition/native-final.xml"

env PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests \
  AINEKIO_V2_WALK_COMMAND="$PWD/build/steering-recognition/p4/v2_model/v2_walk_command" \
  .venv/bin/python3 Emulator/tools/run_acceptance.py
```

From MetaHuman root, the consumer commands are `pnpm test:environment-perception`,
`pnpm typecheck:core`, `pnpm check:architecture`, and:

```sh
node --experimental-test-module-mocks --import tsx --test \
  brain/agents/environment-bridge/core-lifecycle.spec.ts
```

Generated logs live in ignored `build/steering-recognition/`:
`focused-final.log`, `acceptance-final.log`, `native-final.xml`,
`consumer-tests-final.log`, `bridge-lifecycle-final.log`,
`typecheck-core-final.log` and `architecture-final.log`. The aggregate's
machine-readable report is `build/acceptance/a-series.json`. These include final
repair regression results even when the aggregate gate fails.

The native Run recording assertion and gateway Walk→Run→Walk assertion both
fail identically using archived pristine starting-commit sources. The asset
counts (38 versus expected 36), owner Sit pose/excursion mismatches, missing
ignored Sesame source header, and schema/fixture message-type coverage gaps
also reproduce there. No assertion was relaxed, assets regenerated or Run
behavior changed. The protocol gaps concern `robot_settings`,
`robot_settings_status`, `motion_speed` and `motion_speed_status`. A29 cannot
start its browser because `/usr/bin/google-chrome` is absent. Native geometry
generator checks skip because their scientific Python dependencies are missing.
Baseline reproduction logs are `baseline-assets-run.log`,
`baseline-session.log`, `baseline-protocol.log`; the pristine native reproduction
build is under the temporary starting-state backup. These remain blockers to a
completely green aggregate, outside the two repaired defects.

Real hosted perception is still blocked by the missing operator-supplied remote
URL, served image/JSON model and existing API-key environment variable name.
The software fixtures exercise HTTPS success, timeout, HTTP 401/403, invalid and
oversized/truncated responses, redirects, untrusted certificates and wrong TLS
hostnames. They do not establish remote inference availability or accuracy.
ESP-IDF/toolchain is absent on this checkout host, so the P4 source advertisement
has only native protocol/model validation. Installed firmware capabilities,
physical turn signs/magnitudes, calibrated loaded movement, link timing and
emergency-stop latency under hardware/media load remain untested. No Q6A
throughput/latency benchmark or physical-motion success is claimed. No push,
merge, deployment, firmware flash or robot movement occurred.

## Where ROS 2 fits

For the proposed shared status/router/queue system, see
[foundation section 5](DISTRIBUTED_ROBOT_FOUNDATION.md#5-shared-status-routing-and-queues).
Reuse MetaHuman's Robot Status projection and Work Coordinator. ROS diagnostics
can supply component-health reporting and monitoring; control-source arbitration,
durable job ownership and application state synchronization still need explicit
contracts. The existing status file is not a distributed coordination service.

ROS 2 provides communicating nodes and reusable tooling. It is not a single
robot application with an on/off GUI. Nodes exchange topics, services and
actions; RViz is a separate visualization application. Installing ROS 2 does
not connect Ainekio automatically. [ROS 2 Jazzy node concepts](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Concepts/Basic/About-Nodes.rst).

**Recommendation: supplement the existing system with a Q6A adapter when the
following tools are needed.** No required feature in the audited design was
identified as depending on ROS 2. The benefit is reuse of its interfaces and
tools; adopting it does not require replacing MetaHuman or the P4 gait code.

| Use | Proposed integration | Boundary |
| --- | --- | --- |
| Sensor and robot visualization | Publish camera data, timestamped IMU samples and available body state through a Q6A ROS adapter; inspect them in RViz | Robot pose visualization needs a model and transforms; commanded joint positions must remain distinguishable from measured positions |
| Recording and replay | Use rosbag2 for selected telemetry topics during diagnosis | Recording adds disk/network load; replay of recorded sensor topics is not evidence of live physical response |
| Future perception/planning packages | Exchange observations and bounded action requests through the existing gateway interface | The gateway remains the body-command authority; no second connection writes servo targets |
| Robot status | Expose the existing status projection to ROS consumers, including sample age and service/link health | ROS displays consume status; the local P4 output supervisor retains its existing responsibility |
| Fast balance correction | P4 acquires IMU data and applies corrections inside the existing motion/output owner | A ROS message round trip and desktop/LLM response are outside the local correction loop |

[RViz capabilities](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Intermediate/RViz/RViz-User-Guide/RViz-User-Guide.rst)
include images, robot models and coordinate transforms.
[rosbag2 recording/replay](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Beginner-CLI-Tools/Recording-And-Playing-Back-Data/Recording-And-Playing-Back-Data.rst)
operates on ROS topics. Both require the relevant data to be published first.
Run visualization on the desktop when desired; Q6A can remain headless.

Add the adapter first as a telemetry consumer. Extend it to action requests only
through Ainekio's existing admission, cancellation and result handling. Keep
MetaHuman responsible for cognition/personality and high-level intent, and the
embodied runtime responsible for perception, state estimation and skill execution.
ROS is not selected as a replacement controller in this recommendation.

Installed ROS package size is not its runtime RAM cost. Charge each selected
node, message copy, history queue and recorder to the Q6A budget. Keep camera
queues bounded and consume fresh frames. The audit identified no deployed ROS
robot graph, balance controller or selected YOLO pipeline; these remain
implementation work. See the [host budget](v2-12servo/RESOURCE_BUDGET.md#9-q6a-metahuman-and-desktop-budget).

## Recommended operating targets

These retain quality targets from the audit, updated for the wireless decision.
They are not enabled settings or proof of simultaneous full-load operation. The
[resource budget](v2-12servo/RESOURCE_BUDGET.md#11-operating-targets-and-adjustment-rules)
owns the detailed arithmetic and alternative profiles.

| Function | Target | Implementation consequence |
| --- | --- | --- |
| Body transport | Existing Wi-Fi/WebSocket path to offboard Q6A; USB HS remains an alternative | Establish network topology and bounded media/control scheduling; qualify concurrent latency and queues before increasing load |
| Camera | Preserve 1920 × 1080 RGB565/hardware JPEG/YUV420 as the quality target, initially quality 75; desired 30 fps remains subject to encoded-byte admission | At 256 KiB/frame, 30 fps needs 62.915 Mbit/s before audio, above the linked 53.4 Mbit/s TX reference; define stream purpose, codec, queue and byte budget before choosing the final rate |
| Physical audio | 24 kHz, 16-bit mono duplex | Shared I2S/codec clock; resize and relocate buffers where required |
| Speaker transport | 24 kHz, 16-bit mono | Preserve Kokoro's native rate across MetaHuman, gateway and firmware |
| Mic for wake/STT and transport | Resample physical capture to 16 kHz, 16-bit mono | Account separately for resampling and physical-rate input buffers |
| IMU | Initial 208 Hz local acquisition | Integrate driver and attitude/controller code; sampling rate alone does not establish fall recovery |
| Servo targets/PWM | Retain 50 Hz | Loaded gait speed remains a separate mechanical qualification |
| LCD | Native pixel resolution; 30 fps target using partial updates | Identify the purchased panel and supported SPI clock before finalizing its driver/pin map |
| Vision inference | Consume the newest frame at the selected model's measured rate | Do not accumulate old frames or equate camera FPS with detector FPS |

H.264 is a later 1080p30 hardware option if streaming requirements justify the
encoder/protocol/decoder changes. The audited firmware disables it, and its
buffer budget must be calculated separately from the current JPEG path.

## Findings that affect the build

| Audit result | Design consequence |
| --- | --- |
| OV5647 supports 5 MP, but the P4 ISP used by the current path is specified to 1920 × 1080 | Use 1080p as the main processed-video target; full 5 MP requires a different capture/processing path |
| Three full 5 MP RGB888 frames require 43.249 MiB, exceeding 32 MiB PSRAM | Reducing copies and selecting formats matters; no blanket claim that every maximum setting fits |
| 256 KiB JPEGs at 30 fps require 62.915 Mbit/s before audio, above the matching 53.4 Mbit/s Hosted TX reference | Wireless media admission must consider encoded bytes and concurrent audio; full-HD capture does not require forwarding every frame to the remote server |
| P4 internal RAM, DMA-capable allocations and PSRAM have distinct constraints | PSRAM free space does not cure internal allocation failures or enlarged microphone stack arrays |
| The link loop can wait 20 ms, then send at most one microphone packet and one JPEG; authenticated send failure disables PCA output | Address media/control scheduling and failure handling within existing owners; changing the cable alone does not repair this behavior |
| Q6A Kokoro generated a five-second phrase in 15.068–15.904 seconds, with 1,537.797 MiB peak process RSS | Speech synthesis is an independent response-time bottleneck; neither ROS nor USB removes it |
| The inspected P4 firmware has no IMU feedback controller | Implement local posture correction through the current gait/output owner; installing the sensor or ROS does not implement balance |

Sources, conditions and exclusions are in the
[complete budget](v2-12servo/RESOURCE_BUDGET.md) and
[audit evidence](v2-12servo/BUDGET_AUDIT_EVIDENCE.md). Whole-robot concurrent
processing and loaded motion remain unqualified; the earlier two-unloaded-servo
timing record is not a full-system result.

## Choice 1: Wired native USB

```text
LSM6DS3 -> P4 <--- native USB ---> Q6A <--- Wi-Fi/router ---> desktop
```

Use the Q6A as USB host and the P4 as USB device. Keep the existing command
admission, authentication, command identity, cancellation, and result handling
behind the transport boundary.

**Advantages**

- Avoids wireless contention, interference, retries, and radio channel switching
  on the body-to-Q6A path.
- Leaves Q6A Wi-Fi resources available for the remote desktop.
- Offers greater potential capacity for camera/audio traffic and more
  predictable delivery timing.
- Keeps local communication independent of the external wireless network.

**Costs and unfinished work**

- Native USB transport is not implemented in the inspected Ainekio firmware.
- Select a USB device class and host integration approach; preserve one gateway
  and one command owner. This document does not select USB networking versus
  another USB protocol.
- The P4 board's normal USB-C connector is the CH343P programming/debug serial
  path. Native high-speed USB is exposed separately on the four-pin P1 connector.
- Resolve VBUS/power ownership before connecting independently powered boards:
  the existing hardware notes say P1's 5 V pin joins the P4 power rail.
- Provide suitable internal cabling and strain relief. Confirm sustained media
  delivery and reconnect behavior after implementation.

USB still incurs host scheduling, firmware, and buffering delays. It does not
make Linux or the complete robot application hard real-time. The existing Wi-Fi
transport can remain available during development, without introducing automatic
controller failover or two simultaneous command authorities.

Hardware references: [Waveshare board documentation](https://docs.waveshare.com/ESP32-P4-WIFI6)
and [Q6A USB ports](https://docs.radxa.com/en/dragon/q6a/hardware-use/usb).

## Choice 2: Wireless to offboard Q6A — selected

An independent private LAN is the proposed first deployment. The P4 currently
uses one configured gateway URL and retries that host; DNS-SD advertisement by
the gateway does not establish discovery in this firmware target. A direct Q6A
hotspot is the second topology below; wireless
selection does not require hotspot/client concurrency. No network topology has
been configured by this document. The remote MetaHuman connection is separate
from the body connection and can traverse the Internet.

Q6A cannot be the robot's only access point/Internet route if remote takeover
must survive loss of Q6A. Host failover needs a surviving network path as well as
the source/endpoint policy described in the foundation.

### Direct Q6A hotspot variant

```text
LSM6DS3 -> P4/C6 <-- private 2.4 GHz hotspot --> Q6A
                                                |
                                         upstream Wi-Fi
                                                |
                                           router/desktop
```

The Q6A provides a private hotspot for the P4 while its client interface connects
to the upstream network. Body traffic terminates at the gateway on the Q6A;
it does not need to traverse the home router. The Q6A makes separate requests
to the desktop. NAT/internet sharing is only needed if the P4 itself needs access
beyond its local Q6A connection.

**Evidence for feasibility, checked 2026-09-28**

- Waveshare uses an ESP32-C6 coprocessor linked to the P4 over SDIO. The C6 is
  a 2.4 GHz device, so the private hotspot must support that band.
- This Q6A identified its wireless device as AIC8800D80, USB ID `a69c:8d81`.
- On kernel `6.18.2-3-qcom`, `iw phy` reported a valid combination containing
  one managed/client interface and one AP interface, with up to three channel
  contexts. NetworkManager also reported AP support.
- The AIC8800D80 datasheet explicitly supports concurrent station, AP, and
  Wi-Fi Direct modes. These findings establish advertised capability; concurrent
  operation was not configured or exercised during this research.

**Advantages**

- Reuses the existing Wi-Fi/WebSocket transport.
- Avoids an additional internal data cable and USB transport development.
- Supports placing the Q6A offboard, reducing onboard weight, heat, and power
  demand, while accepting dependence on the wireless link for Q6A functions.

**Limitations and configuration work**

- Hotspot and upstream connections share wireless resources. Multichannel
  capability does not mean two independent radios or penalty-free simultaneous
  2.4/5 GHz operation.
- Interference, channel switching, retries, power saving, and software queues
  can increase delay even when the boards are close together.
- Configure separate AP/client interfaces, addressing, authentication, and
  startup/reconnect behavior. Do not assume a desktop hotspot toggle preserves
  the existing upstream connection.
- Establish power-saving behavior explicitly. Espressif documents receive
  delays up to the DTIM/listen interval with modem sleep; `WIFI_PS_NONE`
  minimizes those delays at increased power consumption. No explicit override
  was found in the Ainekio networking source inspected; live behavior is unverified.
- For responsiveness, bound media queues and avoid accumulating old camera
  frames. Local image processing can reduce how much data must travel upstream.

Sources: [ESP32-C6 datasheet](https://documentation.espressif.com/esp32-c6_datasheet_en.html),
[AIC8800D80 datasheet hosted by Radxa](https://dl2.radxa.com/zero3/docs/hw/3w/AIC8800D80_DataSheet_v0.1.pdf),
and [Espressif Wi-Fi power-saving documentation](https://docs.espressif.com/projects/esp-idf/en/v5.5.2/esp32c6/api-guides/wifi.html#esp32-c6-wi-fi-power-saving-mode).

## Performance foundation

### Movement latency

The P4 executes gait updates locally; individual servo updates do not require
a Q6A round trip. Link delay affects new commands, changes, and feedback.
Future fast IMU-based posture correction should likewise remain local to the P4.
Camera-guided steering also depends on frame capture, transmission, inference,
and command processing, so network latency is only part of its response time.

A configured local Wi-Fi link is a reasonable engineering choice for semantic
movement commands and moderate media traffic. No source found guarantees
end-to-end latency for this exact Q6A/P4/application combination. Neither
"negligible latency" nor a specific worst-case timing bound is established.

No measured command-delivery bound exists for this hardware/application pair.
Retries, queues, and concurrent Q6A hotspot/client traffic add delay.
Minimum radio sleep and minimum latency are competing objectives:
Espressif documents receive delays up to the DTIM/listen interval with modem
sleep. For example, a configured 100 ms beacon period and DTIM of 3 imply a
300 ms DTIM cycle; these are illustrative settings, not this robot's settings.
`WIFI_PS_NONE` removes that sleep delay at increased power use, but does not
remove congestion or scheduling delays. No explicit power-saving override was
found in the inspected application network initialization.

### Wireless power cost

The [ESP32-C6 datasheet, table 5-7](https://documentation.espressif.com/esp32-c6_datasheet_en.html)
lists active receive current of 78–82 mA and transmit figures of 252–354 mA
at 3.3 V, depending on radio mode and transmit power. Calculated power is
approximately 0.26–0.27 W receiving and 0.83–1.17 W in those transmit conditions.
The table labels these peak figures; transmit characterization uses 100% duty
cycle and receive characterization has CPU idle/peripherals disabled.

These establish the scale of C6 consumption, not average P4-board power, the
increment relative to USB, or the whole link's consumption. Traffic duty cycle,
sleep settings, host processing, conversion losses, and Q6A Wi-Fi operation
remain relevant. A total Q6A-plus-P4 wireless power delta has not been measured.
Replacing an onboard cable with Wi-Fi does not itself establish a power saving;
moving Q6A offboard also moves its supply demand off the robot.

### Audio and image bandwidth

The inspected audio implementation uses 16 kHz, 16-bit mono PCM in 20 ms frames.
The camera sends JPEG frames and accepts a configured rate up to 15 frames/sec;
that configuration ceiling is not measured sustained performance.

| Payload | Calculated bandwidth before protocol overhead |
| --- | --- |
| Continuous microphone audio | 32 kB/s, or 0.256 Mbit/s |
| Continuous speaker audio | 32 kB/s, or 0.256 Mbit/s |
| Both simultaneously | 64 kB/s, or 0.512 Mbit/s |
| Example only: 50 kB JPEGs at 5 frames/sec | 250 kB/s, or 2 Mbit/s |
| Example only: 100 kB JPEGs at 15 frames/sec | 1.5 MB/s, or 12 Mbit/s |

JPEG sizes above are illustrations, not observations of this camera.
Espressif publishes 53.4 Mbit/s TCP transmit and 44 Mbit/s receive for its
ESP-Hosted four-bit SDIO setup using C6 in a shield box with 40 MHz Wi-Fi
bandwidth. This establishes useful capacity for the architecture, not a throughput
promise for Ainekio or concurrent Q6A hotspot/client operation.
[Published benchmark](https://components.espressif.com/components/espressif/esp_hosted/versions/2.12.8/readme?language=en).

### Processing and queues

The C6 handles wireless functions, while the P4 still handles its TCP/IP stack,
WebSocket traffic, buffers, and SDIO transfers. Commands and audio are expected
to have manageable overhead; continuous images add compression, copying, and
transport work. No CPU utilization percentage has been established.
[ESP-Hosted architecture](https://github.com/espressif/esp-hosted-mcu/blob/main/docs/getting-started-mcu.md).

The coprocessor does not eliminate P4 processing overhead. USB also requires
host/device processing; the relative CPU cost depends on the selected USB class
and implementation. There is no basis here for claiming either zero Wi-Fi
overhead or a quantified CPU saving from USB.

The inspected Ainekio implementation shares one WebSocket for control and media.
Its sending loop checks replies and audio before camera packets, but an image
send already underway can occupy the outbound path. Queue behavior remains
relevant with either transport. See [controller.c](../Slave/firmware/esp32p4-wifi6/main/controller.c)
and [media implementation](../Slave/firmware/esp32p4-wifi6/components/ainekio_p4_media/media.c).

## Falling and active walking

Research added 2026-09-28. Wi-Fi suitability for movement commands does not
establish suitability for the complete fast balance feedback loop.

The inspected V2 controller generates gait trajectories and modeled contact
timing. It does not currently use measured IMU attitude or ground-contact/force
feedback to correct a physical fall. See the [model description](../Slave/software/models/v2-12servo/README.md)
and [motion source](../Slave/software/models/v2-12servo/motion.c). The current
[validation record](../Slave/software/models/v2-12servo/CONTROLLER_VALIDATION.md)
does not qualify loaded balance. Older gait timing figures in the firmware
design history must not be treated as measurements of the current application.

Proposed responsibility split:

```text
Q6A -- Wi-Fi: bounded direction, speed --> P4 gait + planned balance controller
                                            ^              |
                                            |              v
                                         wired IMU    PCA9685 / servos
                                            ^              |
                                            +-- body motion+
```

The LSM6DS3 supplies acceleration and angular-rate measurements. A controller
must estimate body attitude and rotation, then adjust the gait's leg targets
and, where feasible, step placement/timing. Those corrections should enter the
existing P4 motion/output owner, not create a second servo writer. Initial local
posture stabilization is a narrower task than dynamic push recovery. IMU data
alone do not establish which feet are supporting weight or actual joint angles.

Keep fast correction independent of wireless packet arrival. Wi-Fi may have
adequate typical latency, but no bound is established for this application's
round trip under contention and media load. If a future balance controller
requires Q6A computation, prefer a wired sensor/command path with an explicit
timing budget; USB and Linux also require scheduling and queue control. Required
rates and recoverable disturbances depend on the mechanism, actuator response,
contact/friction, and control design. No fall-catching performance is promised.

References: [ST LSM6DS3 datasheet, mirrored](https://pccomponents.com/datasheets/ST_MI-LSM6DS3TR.pdf)
and [MIT legged-robot control notes](https://underactuated.mit.edu/humanoids.html).
ROS can support integration, planning, and diagnostics, but installing it does
not supply a tuned balance controller for this robot.

## Power and weight: SHARGE Pouch

Research added 2026-09-28. The owner identified the battery as SHARGE Pouch and
confirmed the proposed load is all twelve MG90 servos plus the P4 on one 3 A
output, using staggered servo activity to reduce peaks.

### Published supply limits

The manufacturer's [Pouch manual](https://cdn.shopify.com/s/files/1/0611/2234/7259/files/Pouch_3_in_1.pdf?v=1735982667),
page 10, identifies power bank P065A, approximately 240 g and 36 Wh. It lists
5 V / 3 A and 12 V / 3 A among the individual-port output modes, but simultaneous
USB-C outputs are limited to **20 W + 20 W**. It does not enumerate the dual-port
voltage/current profiles. The [product page](https://sharge.com/products/pouch)
also lists 5 V / 6 A total and approximately 220 g; retain the owner's 240 g
figure for planning rather than replacing it with the conflicting web weight.

Radxa specifies **12 V input**, recommending a supply rated **2 A or above**
(24 W or more). This is supply capacity, not a measurement of continuous Q6A
consumption. The Pouch's listed single-port 12 V / 3 A mode meets that rating;
its dual-port 20 W allocation per port falls below that recommendation. This
comparison does not establish the actual power needed by the owner's headless
workload or prove that the proposed arrangement cannot run it. The owner reports
operation from 5 V / 3 A; that observation has not been independently measured
here. Do not assume the bank retains 12 V / 3 A when the second port is connected.
[Q6A power requirements](https://docs.radxa.com/en/dragon/q6a/hardware-use/power-header).

### Twelve servos on a shared 3 A branch

At 5 V, 3 A provides 15 W for the entire branch. Dividing 3 A among twelve
servos gives 250 mA each before reserving anything for the P4, radio, camera,
audio, or other peripherals. This is budget arithmetic, not a measured servo
current or a claim that every servo draws the same current.

Staggering movement starts can reduce coincident acceleration peaks. Staggering
PCA9685 control pulses does not guarantee non-overlapping motor current:
supporting joints still exert torque while another joint moves, and motor drive
can extend beyond the command pulse. Scheduling alone does not enforce a 3 A
ceiling. The exact servos' loaded and peak currents remain unqualified; there is
no established basis to promise twelve-servo walking plus P4 within this limit.
[Pololu's measured servo signal/current examples](https://www.pololu.com/blog/17/servo-control-interface-in-detail).

### Distribution and communication

- Feed servo power directly to PCA9685 **V+** through a suitably rated supply
  path. Keep its logic **VCC** at P4 3.3 V and retain a common ground. If sharing
  one 5 V source, split its feed upstream of the P4; this avoids routing servo
  current through the P4 but does not increase the source's 3 A allowance.
- The [Waveshare schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf),
  sheet 1, shows USB0_5V feeding VCC_5V through Q2 (AO3401). Even an upstream
  VBUS header connection uses board copper and connectors. No verified 2–3 A
  servo-feed rating for the header was found. An absent fuse does not establish
  that rating. Follow the existing [servo power wiring guidance](v2-12servo/PCA9685_WIRING.md).
- Occupying P4 USB-C with power does not eliminate wired communication. Native
  USB uses the separate P1 connector; use a Q6A USB host port and a designed
  VBUS/power arrangement. P1 shares the P4 power rail, so do not simply join
  independently powered 5 V outputs. The USB class/firmware work remains pending.
- A header UART is another possible command link after verifying voltage levels,
  pin selection, and configuration. Native USB remains the preferred wired
  candidate for combined body commands, sound, and images.

**Placement implication:** keeping Q6A offboard removes its weight, any cooling,
and supply demand from the robot and allows separate Pouch outputs for P4 and
servos. That gives the servos their own 3 A allocation but does not establish
that 3 A is sufficient. Actual Q6A consumption under the intended workload,
payload, and communication requirements should determine placement; the adapter
recommendation alone does not decide it.

## Complete robot resource budget

The [robot power, pins, memory and processing budget](v2-12servo/RESOURCE_BUDGET.md)
audits the actual V2 firmware, its recorded build/bench results, and the
Waveshare board schematic. It includes twelve servos, LSM6DS3, OV5647, onboard
audio, C6 Wi-Fi, microSD, and the owner's generic 1.9-inch LCD without touch.
It also covers Q6A services and storage, the remote-desktop ownership boundary,
measured local Kokoro latency/RSS, and wired versus wireless media profiles.

The board has 20 unassigned header GPIOs after existing allocations and the
USB FS reservation. Sharing the media I2C bus for the IMU, adding one interrupt,
and using a conditional six-signal SPI LCD would leave 13. The exact LCD
interface remains unidentified, so this is a proposed allocation, not a final
wiring map. The latest recorded app occupies 2.26 MiB of an 8 MiB app slot.

Prior motion measurements show a maximum 2.897 ms calculation/output frame
within the 20 ms cadence, but did not include the complete camera/wake/display
workload. The resource document separates recorded costs from published
component limits and calculated buffer/transfer requirements. Total concurrent CPU use and whole-board
power remain unmeasured; chip datasheets do not establish the complete robot's
current draw.

**Correction:** the previously assigned aggregate CPU, RAM and electronics-power
allowances have been withdrawn. They were not derived from measured use or
component specifications and do not establish spare capacity. The budget now
uses repository evidence, manufacturer specifications/benchmarks and explicit
buffer/transfer arithmetic. The LCD resolution/interface remains unidentified.

The updated research covers OV5647 1080p30/720p60 capability, ES8311 audio up to
96 kHz/24-bit mono, the P4 encoder's format-dependent benchmark, version-matched
Hosted TCP throughput, and LSM6DS3 output/interface limits. It identifies actual
constraints in the present firmware: image copies, shared blocking media sends
whose failure disables PWM, and audio arrays that cannot simply be enlarged
inside the current microphone stack. Full concurrent operation remains
unqualified; the resource document records the specific evidence and sources.

## Questions to revisit

1. Complete the [distributed foundation](DISTRIBUTED_ROBOT_FOUNDATION.md): allocate
   functions, identity, memory, work ownership and failure handling across both
   MetaHuman installations before feature migration.
2. Address shared media/control scheduling and failure handling before increasing
   stream rates. Define response deadlines and acceptable frame age separately
   from the local 20 ms servo cadence.
3. Implement the recommended media formats across firmware, gateway and MetaHuman;
   retain the budget's buffer ownership, stack and DMA constraints.
4. Integrate LSM6DS3 acquisition and local correction into the current P4 owners;
   identify the LCD before implementing its native-resolution display path.
5. Resolve measured speech latency, install the selected STT service, choose a
   vision runtime and measure their concurrent Q6A demand.
6. Add a ROS telemetry adapter if visualization/recording is selected; keep a
   single command authority and budget the chosen nodes and queues.
7. Establish the selected wireless network topology, byte-rate limit and
   power-saving policy. Start from the existing private-LAN path unless a direct
   hotspot is selected; advertised AP/client capability is not demonstrated
   concurrent throughput.
8. Revisit placement, mass, electrical distribution and loaded/peak current as a
   separate physical-design task. Native USB remains a future alternative if
   body-link requirements exceed the qualified wireless envelope.

Research should establish the design and expected behavior before physical
scenario testing. Later validation should confirm an agreed design, rather than
serve as a substitute for selecting one.

## Research history

| Date | Finding or decision | Evidence level |
| --- | --- | --- |
| 2026-09-28, latest clarification | P4 is the robot brain; Q6A, remote and standalone manual Body Control are interchangeable authorized sources. Shared status/routing/queues should reuse existing owners. P4 currently retries one configured gateway; cross-host takeover remains to be designed. | Owner requirements and targeted source inspection; ROS diagnostics/control packages researched; no feature migration. |
| 2026-09-28, latest | Owner selected wireless body/offboard Q6A to reduce carried weight and power; clarified that both Q6A and remote run MetaHuman with different responsibilities. Define the foundation before feature migration. Continue defined local skills during remote outages and pause remote-dependent tasks. | Explicit owner decisions; distributed contracts are proposed, not implemented. |
| 2026-09-28 | Native USB recommended for onboard P4/Q6A; Q6A Wi-Fi reserved for upstream desktop communication. | Engineering recommendation; implementation pending. |
| 2026-09-28 | Q6A hotspot plus Wi-Fi client is advertised by the installed driver and chipset documentation. | Read-only capability inspection; no networking changes or concurrency trial. |
| 2026-09-28 | Audio payload rates calculated from code; media transport and queue owners inspected. | Source evidence and arithmetic; no live throughput or latency measurement. |
| 2026-09-28 | Pouch dual-port rating is 20 W + 20 W, below Radxa's recommended 24 W supply capacity for Q6A on either port. Twelve servos plus P4 on 3 A remain unqualified; staggering does not guarantee the limit. | Manufacturer specifications, schematic inspection, and budget arithmetic; no physical power or motion tests. |
| 2026-09-28 | Owner clarified headless Q6A operation from 5 V / 3 A and priority of comparing wireless costs. Removed placement inference based solely on recommended adapter capacity. Added C6 active power scale and latency/CPU qualifications. | Owner report, manufacturer radio characteristics, source inspection, and engineering assessment; no complete-link power or latency measurement. |
| 2026-09-28 | Added a firmware-backed P4 resource budget, including generic 1.9-inch LCD without touch. GPIO and flash capacity support further integration; complete concurrent CPU and power totals remain open. | Current source, prior build/bench records, schematic and revision-matched datasheets; conditional display arithmetic and explicitly proposed balance allowances. |
| 2026-09-28 | Withdrew assistant-assigned CPU/RAM/power totals and low-quality workload assumptions after owner correction. Replaced them with repository measurements, identified-part specifications and transparent calculations at higher hardware capabilities. | Published component benchmarks retain their conditions; unidentified parts and unmeasured application costs are explicitly unresolved. |
| 2026-09-28 | Completed the whole-system budget and recorded native USB P4→Q6A / Wi-Fi Q6A→desktop as the recommendation with power excluded from the comparison. Added final media/sensor targets and concrete memory, ISP, transport, scheduling and speech constraints. | Engineering recommendation grounded in the linked audit; implementation and concurrent qualification pending. |
| 2026-09-28 | Clarified ROS 2 as an optional Q6A adapter for telemetry, RViz, recording and future package integration, preserving MetaHuman cognition, gateway command authority and P4 local feedback. | ROS Jazzy documentation and existing ownership boundaries; no robot ROS graph deployed by this document update. |

When revisiting this document, date new findings and label manufacturer claims,
source inspection, calculations, and measured behavior separately. Preserve the
reason for any change to the recommendation.
