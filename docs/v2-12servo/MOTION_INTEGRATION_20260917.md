# P4 motion integration — 2026-09-17

**Software built and checked; board disconnected, flash pending.**
`0.4.0-p4-motions` contains thirty geometric motions plus the independent stop
command. Physical motion remains unavailable (`motion=false`). This update does
not accept Step 1 or supply electrical, calibration or loaded-motion evidence.

## Commands and ownership

Added: **Sit, Rest, Wave, Dance, Swim, Point, Nod, Pushup, Bow, Cute, Freaky,
Worm, Shake, Shrug, Dead, Crab, Celebrate, Stretch, Surprised, Sad and Curious**.
Walking and all eight left/right turns remain installed. The [gesture inventory](../../Slave/software/models/v2-12servo/motions/gestures/README.md)
records the chosen revisions and durations. Current seated Wave, shallow Nod and
deep Pushup are separate assets; historical packages remain preserved.

- `Slave/software/models/v2-12servo/motions/gestures/` owns retained source and
  execution contracts: 201 files plus shared policy and an independent timing
  reference, verified byte-for-byte against
  their original handoffs and every original contract source binding.
- `tools/compile_clips.py`, `clip.c` and `include/ainekio/v2_motion.h` within that
  model replace the turn-only compiler/sampler/API. One finite-clip registry owns
  eight turns and twenty-one gestures; the existing repeating-walk implementation stays
  separate. CMake, generated-file references and source tests use the new names.
- The P4 `main/controller.c` derives installed command names from that registry,
  recognizes native Sit and existing emote envelopes through common admission,
  and provides read-only `gait <command> <elapsed-ms>` sampling. Its hello version
  comes from the application descriptor. The reply buffer accommodates the larger
  declaration and maximally escaped bounded credentials.
- `Master/gateway/environment_adapter/translation.py` already owns all twenty-one
  semantic names. Only Nod's description needed adjustment to avoid claiming
  V1's particular repetition count for every body. Existing Body Control buttons,
  per-body capability selection and MetaHuman's advertised command contract are
  reused. No second catalog or raw-angle interface was added.
- `Emulator/tests/test_v2_commands.py` covers both bodies' existing envelopes,
  correlated ACK/terminal results, undeclared/unready rejection and catalog
  selection. Model tests cover all twenty-nine finite clips and invalid imports,
  including preview-recovery exclusion and semantic endpoint binding.
- P4 `CMakeLists.txt`, `main/CMakeLists.txt` and `partitions.csv` set the version,
  application-descriptor dependency and required larger app partition.

The source's 120 Hz command timing is preserved. Sampling holds each clip's
recorded semantic terminal pose, including the lowered Sit and Rest postures.
Dead finishes at 7.4 seconds and holds its flat pose; the preview's optional
standing recovery is not executable through `dead`. Freaky, Worm and Crab also
exclude their explicitly optional final 0.5-second preview holds, completing at
9.2, 12 and 30.1 seconds respectively. Full original sources remain retained.
Research
retiming, current-pose transitions, ordinary braking, servo pulse conversion and
physical execution are still pending. The model contains no controller URL or
transport dependency. Authentication, session ownership, sequencing, expiry,
cancellation and emergency-disable ownership remain in their existing layers.

## Verification

| Check | Result |
| --- | --- |
| Native model and shared-core CTest suite | **19/19 passed**, including 19 compiler validation cases within the compiler test |
| New gesture/source numerical comparison | **62,067 sample times**, all twelve positions, velocities and accelerations; includes every source knot, off-grid samples, phase boundaries, optional preview intervals and late terminal holds |
| Maximum new-gesture numeric errors | **0.000999437 centidegrees**, **0.152787 centidegrees/s**, **80.242534 centidegrees/s²**; existing tolerances unchanged |
| Existing turn/source comparison | **44,224 times**; maximum errors 0.000504010 centidegrees, 0.082582 centidegrees/s, 38.881442 centidegrees/s² |
| Existing walk/source comparison | **1,302 times**; maximum position error 0.000002471° |
| Gateway, dashboard, adapter, catalog, receipts, P4 foundation and V2 command regressions | **93 tests passed** (15 command/catalog tests and 78 affected regressions) |
| Isolated headless browser, actual dashboard HTML/JS and synthetic robot status | **32 checks passed**: all twenty-one envelopes/CSRF/selection, installed-but-unready display, motion gating, independent emergency detach, stale/disconnected bodies and V1 controls |
| Hello capacity probe using the target's hello function, portable encoder and pinned cJSON | **3 cases passed**: maximum-length ordinary, quoted and control-character credentials; all 31 names and identity fields retained; largest message 1,777 bytes within 2,048 bytes |
| P4 ESP-IDF 5.5.4 build | **Passed**, version `0.4.0-p4-motions`, app 5,100,000 bytes, 39% free in 8 MiB app partition |
| Board flash, runtime reconnection and on-board sampling | **Not performed**; board disconnected |
| PWM/OE timing, servo motion or loaded tracking | **Not measured**; calibration and electrical acceptance remain open |

Browser and hello probes are isolated software checks, not a live gateway or board
test. The native checks use the supplied independent source reference samplers
and default timing schedule, with explicit terminal holds at semantic completion;
numerical agreement is not measured actuator tracking. S3 source and shared-core
C implementation were not changed for this integration; S3 was not rebuilt or
flashed. The live gateway was not restarted during this update.

Reproduce the maintained software tests from the repository root:

```bash
cmake -S Slave/software/models/v2-12servo -B /tmp/ainekio-v2-motions-tests
cmake --build /tmp/ainekio-v2-motions-tests -j4
/usr/bin/ctest --test-dir /tmp/ainekio-v2-motions-tests --output-on-failure
PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests:. python3 -m unittest \
  Emulator.tests.test_v2_commands Emulator.tests.test_environment_command_catalog \
  Emulator.tests.test_gateway_service Emulator.tests.test_gateway_dashboard \
  Emulator.tests.test_environment_adapter Emulator.tests.test_action_receipts \
  Emulator.tests.test_p4_foundation
```

The host socket regressions and headless browser required permission to run
outside the sandbox. Affected-file whitespace checks passed. A full-repository
`git diff --check` encountered a short read and then SIGBUS while checking the
unrelated existing `Emulator/tests/test_gateway_handshake_timeout.py`; it is not
reported as a full-worktree pass. No unrelated file was
repaired or reverted. Temporary build/probe logs are under
`/tmp/ainekio-motions-20260917/`; CTest details are in
`/tmp/ainekio-v2-motions-tests/Testing/Temporary/LastTest.log`.

## Build artifact and partition change

Build command used, from the repository root:

```bash
source /home/greggles/esp/esp-idf-v5.5.4/export.sh
cd Slave/firmware/esp32p4-wifi6
idf.py -B build -D IDF_TARGET=esp32p4 build
```

This existing build cache embeds `build/c6/network_adapter.bin`, the matching
Hosted 2.12.8 maintenance image. For a fresh build, follow the target's
[C6 image build steps](../../Slave/firmware/esp32p4-wifi6/README.md#build-and-flash).
Normal P4 flashing does not update the installed C6.

Application: `Slave/firmware/esp32p4-wifi6/build/ainekio_p4_body.bin`

- Version: `0.4.0-p4-motions`.
- Size: **5,100,000 bytes** (`0x4dd1e0`).
- SHA-256: `df80ee9dee772068d1c5b5e00177c3726ace15acf5a0af5a21ce5555c3b76fe6`.
- Partition table SHA-256: `f01e27b37358ba8deb5df95553ee7d1fc2b20654c6cbab85188f982326c8a304`.

The motion image exceeds the old 4 MiB app slot by 905,696 bytes. The factory
partition grows to **8 MiB**, starting at the same `0x20000`, within this board's
previously verified 32 MiB flash. NVS stays at `0x9000` and PHY at `0xf000`.
No command samples were discarded or timing/precision reduced to fit the old
partition. Only explicitly optional preview tails are excluded by their contracts.

## Next hardware session — commands not yet run

Connect the same P4 through its **USB-C debug connector** with all servo plugs
and servo V+ disconnected. Recheck serial permissions and board identity. Keep
the flash backup private: it includes saved Wi-Fi and robot credentials.

From the target directory, with ESP-IDF exported:

```bash
port=/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B90184020-if00
python -m esptool --chip esp32p4 -p "$port" flash_id
umask 077
backup_dir="$HOME/.local/state/ainekio/firmware-backups"
install -d -m 700 "$backup_dir"
backup_path="$backup_dir/p4-before-0.4.0-$(date -u +%Y%m%dT%H%M%SZ).bin"
python -m esptool --chip esp32p4 -p "$port" -b 921600 \
  read_flash 0 0x820000 "$backup_path"
```

Confirm the backup succeeded before continuing. The saved range covers the
bootloader, partition table, NVS and the complete expanded application region.
Then flash **both partition table and app** using the normal full-target command:

```bash
idf.py -B build -p "$port" -b 921600 flash
idf.py -B build -p "$port" monitor
```

This writes the bootloader at `0x2000`, partition table at `0x8000` and app at
`0x20000`; it does not erase NVS. Do not use the previous application-only command
for this upgrade. Do not run `erase-flash` or a C6 update for this motion change.

After flashing, verify `0.4.0-p4-motions`, disarmed startup, authentication,
all thirty-one installed names, and `motion=false`. Query each new clip at a
midpoint and beyond its duration using `gait <name> <elapsed-ms>`; compare all
twelve angles and terminal holds with the source. Confirm Body Control still
selects `ainekio-p4-e6ebe5` and preserves V1's registration. These are pending
runtime checks; they do not require connecting or powering servos.

## Remaining physical work

The [Step 1 evidence record](STEP1_EVIDENCE.md) still governs output-disable
acceptance. Actual OE bias/pull resistors, PWM/fault/reset timing, channel mapping,
servo zero/direction/pulse/travel/dynamic limits and power/load behavior are not
established by this integration. Current-pose entry, supported trials and the
calibrated actuator executor must be completed before advertising ready motion.
