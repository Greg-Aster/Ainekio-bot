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

## Megameal View

Megameal should view this simulator runtime directly instead of loading copied robot meshes as a player avatar. With the simulator running on the default port, open this route from the Megameal dev server:

```text
http://127.0.0.1:4322/simulator
```

For a different simulator URL:

```text
http://127.0.0.1:4322/simulator?url=http://127.0.0.1:8766/
```

## Notes

This is not a full source checkout. Rebuilding the simulator from source requires additional sibling dependencies used by upstream, including `gorilla-physics` and `esp32rs`, plus the Rust/WASM and ESP32 firmware toolchains.

The simulator is useful for motion and firmware experiments, but upstream currently describes it as rudimentary: servo simulation and serial monitor are present; OLED and Wi-Fi are not implemented.

The `source/` folder is provenance only. The old Megameal GLB avatar generation path has been removed; keep exact visual loading routed through `app/`.
