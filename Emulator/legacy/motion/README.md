# Legacy Ainekio Motion Adapter

This package is the pre-protocol-v1 MetaHuman SSE adapter and Python motion
prototype. It is retained for simulator comparison and migration only. It is
not the physical robot firmware, the protocol-v1 body emulator, or the current
safety authority.

The shared local renderer transport now lives in
`Emulator/emulator/backends/sesame_shim.py`. The compatibility module at
`src/ainekio_motion/simulator_shim.py` formats old motion results and delegates
publication to that host-emulator owner.

## Boundaries

- AI callers send semantic commands such as `walk`, `turn_left`, `wave`, or
  `stop`.
- The module does not expose raw servo-angle control to AI callers.
- Virtual walking emits both joint telemetry and root-motion intent. A game
  adapter must apply root motion to the world/body transform.
- The MetaHuman bridge receives actions over a persistent server-sent event
  stream.
- Hardware actuation is disabled unless config explicitly enables it.
- New robot-body behavior belongs in `Slave/`; master-side behavior belongs in
  `Master/`; host emulation belongs in `Emulator/emulator/`, not in this package.

## Validation

```sh
PYTHONPATH=Emulator:Emulator/legacy/motion/src \
  python3 -m unittest discover -s Emulator/legacy/motion/tests
```
