# Simulator Bridge

This folder is reserved for bridge code that connects Ainekio semantic robot commands to development runtimes.

The current Megameal game project no longer owns a copied Sesame player-avatar mesh or physics rig. Visual verification should use the simulator runtime in `../app/`, either directly at `http://127.0.0.1:8765/` or through Megameal `/simulator` while the simulator server is running.

The bridge boundary stays the same:

- AI callers send semantic robot commands, not raw servo angles.
- Servo conversion is owned in Ainekio bridge code, outside Megameal.
- Any future Megameal link must target the simulator runtime or a simulator-owned bridge, not a copied Megameal player-avatar rig.

Useful dry-run commands for the existing motion event builder:

```bash
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run stand
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run walk
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run left
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run right
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run wave
PYTHONPATH=motion/src python3 simulators/sesame-robot-sim/bridge/megameal_bridge.py --dry-run stop
```
