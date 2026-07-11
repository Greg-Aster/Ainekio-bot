# Ainekio Motion Module

This package is the robot-body motion boundary for Ainekio. It accepts semantic
commands, applies safety rules, renders servo sequences, and can drive either a
virtual backend or an explicitly enabled physical backend.

It is intentionally small and standard-library-only in this first slice so the
adapter and emulator tooling stay portable while the ESP32-S3 firmware path is
specified separately.

## Boundaries

- AI callers send semantic commands such as `walk`, `turn_left`, `wave`, or
  `stop`.
- The module does not expose raw servo-angle control to AI callers.
- Virtual walking emits both joint telemetry and root-motion intent. A game
  adapter must apply root motion to the world/body transform.
- The MetaHuman bridge receives actions over a persistent server-sent event
  stream.
- Hardware actuation is disabled unless config explicitly enables it.

## Validation

```sh
PYTHONPATH=motion/src python3 -m unittest discover -s motion/tests
```
