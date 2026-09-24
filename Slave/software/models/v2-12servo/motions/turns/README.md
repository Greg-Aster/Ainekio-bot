# Historical twelve-servo fixed-angle turns

These eight recordings are retained for desktop comparison and existing Blender
deliverables. They are no longer compiled, advertised or executed by current V2
firmware. Operating mode uses gait-based Left/Right with Speed, stride/cadence
and Finish. V1 retains its separate working fixed-angle motions.

`sole-hulls.npz` is also a shared geometry-provenance input for the gesture
compiler and desktop tools; it remains here to preserve their recorded hashes.
Neither the full hull file nor these turn recordings occupy P4 firmware space.

| Names (left / right) | Geometric heading change | Full duration |
| --- | --- | --- |
| `turn_left_15` / `turn_right_15` | +15° / −15° | 15 s |
| `turn_left_45` / `turn_right_45` | +45° / −45° | 19 s |
| `turn_left_90` / `turn_right_90` | +90° / −90° | 23 s |
| `turn_left_180` / `turn_right_180` | +180° / −180° | 35 s |

Each source contains five seconds of entry and six seconds of settling around
its active turn. These are eight independent complete trajectories, not cropped
or mirrored angle tables. The recorded final pose is held indefinitely after
the duration; sampling never loops or resets the joints to zero.

## Provenance and ownership

The [2026-09-15 handoff archive](../../../../../../docs/TURN_COMMANDS_12SERVO.md)
remains preserved as historical choreography. This directory retains historical
turn sources: all 22,088 body/foot/contact/twelve-joint samples were solved
again against the present linkage and sole geometry. Updated manifests,
configurations, schemas and reports bind the rebuilt sources. Original CSVs,
previews and Blender files remain with the research package.

The geometry hash matches the model's existing `geometry.json`. `catalog.json`
and each manifest pin the full JSON source. The original import checked source/geometry
hashes, joint order, units, sample times, heading, entry and terminal poses.
The supplied `sample_reference.py` remains an independent numerical reference.

## Runtime retirement

`tools/compile_clips.py` now imports gestures only. The turn loader, generated
turn tables, turn-specific phase/heading metadata and CMake dependencies on
the turn catalog/commands have been removed. The native runtime turn-source
test was retired; current tests verify that all eight names are unsupported
without disturbing an active gait. Other gestures keep identical compact data.
See [current validation and resource costs](../../CONTROLLER_VALIDATION.md).

The following dated records describe the original integration, not the current
runtime, readiness or deployment. Its old console turn commands are no longer
available in a build of the current source.

## Verification and application flash (2026-09-15)

| Check | Result |
| --- | --- |
| Native model/shared-core tests | **17/17 CTest tests passed** |
| Independent turn-source comparison | **44,224 sample times**, all twelve positions/velocities/accelerations; maximum errors 0.00050401 centidegrees, 0.082582 centidegrees/s and 38.88145 centidegrees/s² |
| Existing walk-source comparison | **1,302 times**, maximum position error 0.00000248° |
| Affected gateway/dashboard/adapter/receipt/P4 tests | **90 tests passed** across the affected suite and separate receipt-suite run |
| Protocol regressions | **14/14 passed**; no turn-specific wire format |
| Isolated dashboard browser checks | **12/12 passed** using the actual HTML/JS and test body statuses; V1 retains six turns, new 15° buttons require declaration, all eight V2 turns require motion readiness |
| P4 ESP-IDF 5.5.4 build | Passed; application **3,659,040 bytes**, 13% free in its 4 MiB partition |
| Actual P4 application flash | `0.3.0-p4-turns`, application at `0x20000`; esptool verified the written-data hash |
| Actual P4 read-only samples | **16/16 passed**: each turn sampled at 7.123 s and after completion, twelve joints each; maximum observed position error 0.000000754°; recorded terminal pose held |
| Actual gateway after restart | P4 authenticated/connected with `walk`, `stop` and eight turn names; `motion=false`, zero pending commands. Both V1 and P4 registrations and the dashboard password were retained. |

The compiled application SHA-256 is
`fb86cf530685f31d3283ed86587ff97cf351a414b76b383dd6f32cb2f31285d0`.
The previous occupied 4 MiB app region was backed up before the application-only
flash. NVS, bootloader, partition table and installed C6 were not rewritten.
S3 firmware was not flashed or rebuilt for the turn integration; no S3 source or
shared-core C implementation changed in this turn integration.

The P4 reported disarmed/unverified before and after the geometric queries.
It remains configured for `ws://192.168.0.44:8790/robot`. A first serial check
queried during connection retries; repeating the read-only check after
authentication passed. This did not change a firmware timeout or acceptance
target. No PWM, servo movement, actual heading change or fault timing was measured.

Reproduce software checks from the repository root:

```bash
cmake -S Slave/software/models/v2-12servo -B /tmp/ainekio-v2-turn-integration-tests
cmake --build /tmp/ainekio-v2-turn-integration-tests -j4
/usr/bin/ctest --test-dir /tmp/ainekio-v2-turn-integration-tests --output-on-failure
PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests:. python3 -m unittest \
  Emulator.tests.test_gateway_service Emulator.tests.test_gateway_dashboard \
  Emulator.tests.test_environment_adapter Emulator.tests.test_environment_command_catalog \
  Emulator.tests.test_action_receipts Emulator.tests.test_p4_foundation \
  Emulator.tests.test_v2_commands
PYTHONPATH=Master:Slave/software:Emulator:. python3 -m unittest discover \
  -s Slave/software/tests/protocol -v
node --check Master/gateway/dashboard/static/dashboard.js
```

The initial affected-suite invocation omitted `Emulator/tests` from PYTHONPATH;
75 tests passed and the receipt module failed to import its existing helper.
The receipt suite then passed all 15 tests with the corrected path and host
loopback access. The sandboxed socket run was stopped; it is not reported as a
pass. Numerical interpolation tolerances are not physical acceptance limits.

Exact build and application flash commands used:

```bash
source /home/greggles/esp/esp-idf-v5.5.4/export.sh
cd Slave/firmware/esp32p4-wifi6
idf.py -B build -D IDF_TARGET=esp32p4 build
idf.py -B build \
  -p /dev/serial/by-id/usb-1a86_USB_Single_Serial_5B90184020-if00 \
  -b 921600 app-flash
```

Local build/flash/console records and the prior-app backup are in
`/tmp/ainekio-turn-integration-20260915/`; these temporary files are not committed
and may be removed by the workstation. Console evidence can contain network
details; do not publish it indiscriminately.
