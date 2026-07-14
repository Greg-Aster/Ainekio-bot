# Emulator

This folder contains development-computer code. Nothing here is flashed to the
physical robot.

- `emulator/` is the protocol-v1 host body emulator.
- `tests/` verifies host body and gateway integration.
- `sesame-robot-sim/` is the runnable browser visual simulator.
- `legacy/` contains the superseded Python/SSE motion path.
- `start-*.sh` files launch host-only emulator tools.

Run the complete protocol-v1 emulator, visual Sesame renderer, gateway, and
operator dashboard with:

```sh
./Emulator/start-protocol-v1-stack.sh
```

The launcher prints the generated local dashboard password and all inspection
URLs. Credentials and runtime records are written only beneath ignored `build/`
paths. Each launch uses a fresh runtime-data directory so the printed password
always matches that running dashboard.

Run every A1-A30 software acceptance gate with:

```sh
python3 Emulator/tools/run_acceptance.py
```

The runner writes machine-readable evidence to
`build/acceptance/a-series.json`. It requires CMake, a C11 compiler, Node.js,
and Google Chrome at `/usr/bin/google-chrome` for the dashboard interaction gate.
