# Ainekio Body Emulator

This directory owns the protocol-v1 body behavior required by System
Specification v1.0. It is separate from `Emulator/sesame-robot-sim`, which is
an optional visual motion renderer and does not make protocol or safety
decisions.

The emulator implements the complete A-series body surface: handshake and
reconnect, protocol lifecycles, portable-C safety, bounded queues and direct
stop, states and profiles, calibration, camera/microphone/speaker media, battery
cutoff/recovery, LittleFS-equivalent assets, display timing, deep sleep, and
fault injection. All 19 required motion routines can be sent to the optional
Sesame renderer. Protocol `look` still returns an explicit unavailable response
because v1 does not map yaw/pitch to the frozen eight-joint contract.

Build the host bridge to the portable C core:

```sh
cmake -S Emulator/emulator -B build/emulator
cmake --build build/emulator
```

Run the body emulator after setting the same local development token used by the
gateway:

```sh
export AINEKIO_ROBOT_TOKEN='local-development-token'
PYTHONPATH=Emulator:Slave/software python3 -m emulator.body
```

Calibration limits and named poses are committed atomically to
`build/emulator/calibration-v1.json` by default. Use `--calibration-file` to
select another generated runtime path.

Install the pinned host-only WebSocket dependency from
`Emulator/requirements-host.txt`.
It is not linked into ESP32 firmware and does not affect the firmware flash
budget.

`backends/sesame.py` translates accepted protocol-v1 motion into optional Sesame
renderer messages. `backends/sesame_shim.py` owns the local HTTP/SSE renderer
transport. A motion request completes only after the browser reports that the
command was handed to the Sesame UART runtime; publication alone is not reported
as protocol `done`. Neither module is imported by ESP32 firmware.
