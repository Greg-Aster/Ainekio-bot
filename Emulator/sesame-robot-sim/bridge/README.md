# Simulator Bridge

This folder is reserved for bridge code that connects Ainekio semantic robot commands to development runtimes.

The active Ainekio simulator path is:

```bash
./Emulator/sesame-robot-sim/run.sh
./Emulator/start-simulator-shim.sh
./Emulator/start-ainekio-adapter.sh
```

Then open:

```text
http://127.0.0.1:8765/
```

The browser page loads `app/ainekio-shim.js`, which listens to the local Ainekio
simulator shim at `http://127.0.0.1:8788/events`. After handing a command to the
Sesame UART runtime, the browser reports its result to `/result`; a host motion
request is not complete merely because `/events` published it.

The bridge boundary stays the same:

- AI callers send semantic robot commands, not raw servo angles.
- Servo conversion and simulator publication are owned in Ainekio bridge code.
- The Ainekio path does not depend on Megameal controller events.

Legacy note: `megameal_bridge.py` is old bridge code kept for reference only. It is not the current Ainekio simulator path.

Useful dry-run commands for the motion event builder:

```bash
PYTHONPATH=Emulator:Emulator/legacy/motion/src python3 Emulator/sesame-robot-sim/bridge/megameal_bridge.py --dry-run stand
PYTHONPATH=Emulator:Emulator/legacy/motion/src python3 Emulator/sesame-robot-sim/bridge/megameal_bridge.py --dry-run walk
PYTHONPATH=Emulator:Emulator/legacy/motion/src python3 Emulator/sesame-robot-sim/bridge/megameal_bridge.py --dry-run left
PYTHONPATH=Emulator:Emulator/legacy/motion/src python3 Emulator/sesame-robot-sim/bridge/megameal_bridge.py --dry-run right
PYTHONPATH=Emulator:Emulator/legacy/motion/src python3 Emulator/sesame-robot-sim/bridge/megameal_bridge.py --dry-run wave
PYTHONPATH=Emulator:Emulator/legacy/motion/src python3 Emulator/sesame-robot-sim/bridge/megameal_bridge.py --dry-run stop
```
