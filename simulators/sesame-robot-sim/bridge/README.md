# Simulator Bridge

This folder is reserved for bridge code that connects Ainekio semantic robot commands to development runtimes.

The active Ainekio simulator path is:

```bash
./simulators/sesame-robot-sim/run.sh
./start-simulator-shim.sh
./start-ainekio-adapter.sh
```

Then open:

```text
http://127.0.0.1:8765/
```

The browser page loads `app/ainekio-shim.js`, which listens to the local Ainekio simulator shim at `http://127.0.0.1:8788/events`.

The bridge boundary stays the same:

- AI callers send semantic robot commands, not raw servo angles.
- Servo conversion and simulator publication are owned in Ainekio bridge code.
- The Ainekio path does not depend on Megameal controller events.

Legacy note: `megameal_bridge.py` is old bridge code kept for reference only. It is not the current Ainekio simulator path.

Useful dry-run commands for the motion event builder:

```bash
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run stand
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run walk
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run left
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run right
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run wave
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run stop
```
