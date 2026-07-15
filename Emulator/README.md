# Emulator

This folder contains development-computer code. Nothing here is flashed to the
physical robot.

- `emulator/` is the protocol-v1 host body emulator.
- `tests/` verifies host body and gateway integration.
- `sesame-robot-sim/` is the runnable browser visual simulator.
- `start-*.sh` files launch host-only emulator tools.

Run the complete protocol-v1 emulator, visual Sesame renderer, gateway, and
operator dashboard with:

```sh
./start.sh
```

The launcher prints the generated local dashboard password and all inspection
URLs. Credentials and runtime records are written only beneath ignored `build/`
paths. Each launch uses a fresh runtime-data directory so the printed password
always matches that running dashboard.

`Emulator/start-protocol-v1-stack.sh` remains the internal stack supervisor used
by the root launcher.

The browser renderer is optional. With the simulator page open, motion waits for
its correlated renderer result. With no browser subscriber, the host body runs
the same bounded motion headlessly and completes its protocol lifecycle; commands
are never retained for replay when a browser connects later.

Run every A1-A30 software acceptance gate with:

```sh
python3 Emulator/tools/run_acceptance.py
```

The runner writes machine-readable evidence to
`build/acceptance/a-series.json`. It requires CMake, a C11 compiler, Node.js,
and Google Chrome at `/usr/bin/google-chrome` for the dashboard interaction gate.
