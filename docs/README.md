# Ainekio Documentation Authority

## Normative set

The normative system set is:

- `Ainekio - System Specification v1.0.docx` - behavior, protocol, software,
  safety, and acceptance authority.
- [Parts Overview](https://docs.google.com/document/d/1wz0kyqttPK3HHL0P0_9lLtRW_B87U5u4kEt-UhttHFA/edit?usp=sharing)
  - externally maintained electrical-parts authority named by the specification.

System Specification v1.0 supersedes the archived v0.6 specification and its
Amendment 1 freeze. The Parts Overview supplies planned electrical facts, but
delivered markings, wiring, measurements, photographs, and H-series results are
required before those values count as installed-hardware evidence.

## Maintained implementation documents

| Document | Current purpose |
| --- | --- |
| [HARDWARE_BRINGUP_CHECKLIST.md](HARDWARE_BRINGUP_CHECKLIST.md) | Power topology, staged assembly procedure, open physical gates, and recorded board evidence |
| [PINOUT_DIAGNOSTICS.md](PINOUT_DIAGNOSTICS.md) | Physical Freenove header numbering, the flashed GPIO map, peripheral wiring, and expected diagnostic values |
| [SLAVE_BRAIN_PROGRESS.md](SLAVE_BRAIN_PROGRESS.md) | Current robot-body software status, implementation evidence, and deliberately pending work |
| [AINEKIO_METAHUMAN_CLOSED_LOOP_STATUS.md](AINEKIO_METAHUMAN_CLOSED_LOOP_STATUS.md) | Current generic Environment Bridge ownership and closed-loop software status |
| [LOCAL_WAKE_WORD.md](LOCAL_WAKE_WORD.md) | Owner-local microWakeWord training, packaging, installation, and validation workflow |
| [freestyle-movement.md](freestyle-movement.md) | Owner-approved bounded motion-plan extension, emulator evidence, and physical enablement gate |
| [REPOSITORY_MAP.md](REPOSITORY_MAP.md) | Current Master, Slave, Emulator, documentation, and reference ownership map |

These documents describe current implementation and evidence. They do not
silently amend the normative specification. A behavioral conflict requires a
numbered specification erratum or revision; installed electrical facts require
recorded H-series evidence.

## Current v1.0 deltas awaiting specification consolidation

System Specification v1.0 predates several implementation discoveries and
owner-approved extensions. Until they are consolidated by numbered erratum or a
new specification revision, readers must keep these boundaries explicit:

- The delivered N16R8 board cannot use the provisional GPIO33/34 servo map in
  specification section 6.3. Hardware testing proved those pins corrupt octal
  PSRAM. The flashed board profile uses GPIO47/48 for R4/R3 and hands GPIO0/43
  from BOOT/UART to the OLED. `PINOUT_DIAGNOSTICS.md` is the current physical
  wiring reference; the old provisional map must not be wired.
- The flashed battery monitor classifies three startup readings at or below
  0.25 V reconstructed battery voltage as a disconnected divider so USB-only
  operation remains awake. After a plausible battery is observed, later
  near-zero readings still follow cutoff behavior.
- The checked firmware uses a stable per-device eight-character WPA2 setup key
  instead of generating a new 12-character secret for every entry. Joining
  `Ainekio-Setup` is the only setup authentication step; the portal opens its
  configuration form directly at `http://192.168.4.1/` and rejects requests
  outside the setup AP interface. The OLED reports the setup address/key and
  then the joined SSID, DHCP address, and gateway state. This owner-approved UX and
  security change is flashed and broadcasting its setup AP, but still awaits
  physical form-submission evidence and numbered specification consolidation.
- The local wake-word control plane and inference engine are implemented, but no
  accepted production `Ainekio` model is installed. First boot remains
  `wake_enabled=false` and `wake_ready=false`.
- `motion_plan_v1` is an owner-approved bounded extension implemented in the
  protocol/core, gateway, environment adapter, and emulator. The ESP32-S3
  runtime does not advertise or execute it, so physical freestyle remains
  disabled pending specification consolidation and hardware-derived limits.

## Reference inputs

- `Freenove_ESP32_S3_WROOM_Board-main/` contains the vendor board pinout,
  tutorial, driver, and datasheet bundle used to identify physical headers and
  fixed onboard buses. It is reference material, not Ainekio behavior authority.
- `sesame-robot/` is the upstream Sesame source reference used by deterministic
  asset conversion and parity inspection. It is not linked into the runtime and
  does not own Ainekio protocol or safety behavior.

## Archive

`archive/` contains superseded specifications and historical progress material.
Archived files preserve lineage and evidence only; they must not be cited as the
current design. See [archive/README.md](archive/README.md).
