# Ainekio Motion Module

This package is the robot-body motion boundary for Ainekio. It accepts semantic
commands, applies safety rules, renders servo sequences, and can drive either a
virtual backend or an explicitly enabled physical backend.

It is intentionally small and standard-library-only in this first slice so it
can fit the Raspberry Pi Zero 2 W target.

## Boundaries

- AI callers send semantic commands such as `walk`, `turn_left`, `wave`, or
  `stop`.
- The module does not expose raw servo-angle control to AI callers.
- Virtual walking emits both joint telemetry and root-motion intent. A game
  adapter must apply root motion to the world/body transform.
- Reconnect catch-up filters expired actions and must not become a polling
  transport.
- Hardware actuation is disabled unless config explicitly enables it.

## Validation

```sh
PYTHONPATH=motion/src python3 -m unittest discover -s motion/tests
```
