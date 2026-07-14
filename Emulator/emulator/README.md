# Ainekio Body Emulator

This directory owns the protocol-v1 body behavior required by System
Specification v1.0. It is separate from `Emulator/sesame-robot-sim`, which is
an optional visual motion renderer and does not make protocol or safety
decisions.

Phase 1 currently implements the body-initiated WebSocket handshake, epoch and
sequence reset, schema validation, portable-C freshness and safety decisions,
JSON ping/pong, status messages, reconnect liveness, and the `stand`, `neutral`,
`walk`, and `stop` command path. Other valid capabilities return an explicit
`busy` response until their emulator ports exist.

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

Install the pinned host-only WebSocket dependency from
`Emulator/requirements-host.txt`.
It is not linked into ESP32 firmware and does not affect the firmware flash
budget.

`backends/sesame.py` translates accepted protocol-v1 motion into optional Sesame
renderer messages. `backends/sesame_shim.py` owns the local HTTP/SSE renderer
transport. A motion request completes only after the browser reports that the
command was handed to the Sesame UART runtime; publication alone is not reported
as protocol `done`. Neither module is imported by ESP32 firmware.
