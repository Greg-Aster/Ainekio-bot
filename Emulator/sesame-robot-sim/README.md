# Sesame Robot Simulator

This folder contains a local copy of the prebuilt browser simulator from:

- Upstream simulator: https://github.com/one-for-all/sesame-robot-sim
- Upstream commit copied: `5e5299e92e72e579d5deb6746ab61ba316114a03`
- Related robot project: https://github.com/dorianborian/sesame-robot

The runnable app is in `app/`. It is the upstream `docs/` build, copied here so it can be served locally without rebuilding the Rust/WASM/ESP32 toolchain.

## Run

From the repo root:

```bash
./Emulator/sesame-robot-sim/run.sh
```

Then open:

```text
http://127.0.0.1:8765/
```

To use a different port:

```bash
PORT=8766 ./Emulator/sesame-robot-sim/run.sh
```

## Notes

This is not a full source checkout. Rebuilding the simulator from source requires additional sibling dependencies used by upstream, including `gorilla-physics` and `esp32rs`, plus the Rust/WASM and ESP32 firmware toolchains.

The simulator is useful for motion and firmware experiments, but upstream currently describes it as rudimentary: servo simulation and serial monitor are present; OLED and Wi-Fi are not implemented.

The `source/` folder is provenance only. Ainekio loads the exact visual runtime from `app/` inside the local operator dashboard.

The visual renderer is optional for protocol tests. If this page is not open,
the Ainekio host body executes motion headlessly and returns a normal terminal
lifecycle. A headless command is not cached or replayed when the page is opened
later.
