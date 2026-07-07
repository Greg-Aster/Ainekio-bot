# Ainekio Motion Module Progress

This document tracks the repo-local motion-module work for Ainekio. Work in
Megameal, MetaHuman OS, Sesame simulator sources, or other repositories is
deferred until the owner decides to open those repos for edits.

## Goal

Build a compact motion module that can run on the Raspberry Pi Zero 2 W body,
drive the Sesame-style servo chassis safely, and expose the same semantic
motion behavior to a virtual Megameal adapter for testing.

The motion module owns robot-body behavior. MetaHuman OS should send intent.
Megameal should render/test the body and move the root transform in the game
world, but it should not own physical servo safety.

## Current Slice

Implemented inside `motion/`:

- Semantic command model with no raw servo-angle API for AI callers.
- Root-motion intent alongside locomotion commands so virtual walking can move
  the game-world body instead of only animating joints in place.
- TTL-aware reconnect catch-up helper that discards expired queued actions.
- Safety controller with e-stop latch, low-battery lockout, command leases,
  stale-command stop behavior, and offline fallback idle behavior.
- Sequence engine with provisional Sesame servo names, basic built-in
  sequences, clamping, and per-servo start staggering.
- Virtual backend that emits joint telemetry for Megameal-style adapters.
- Disabled physical backend guard that refuses hardware actuation unless
  hardware is explicitly enabled in config.
- JSON config loader and `config.example.json` for bridge URL, ports, backend,
  telemetry, and safety settings.

## Important Architecture Decisions

- Do not poll the environment bridge as the primary transport. Reconnect may do
  one catch-up read, then the bridge must return to push/event delivery.
- Reconnect catch-up must respect command TTLs. Expired actions are dropped
  instead of replayed.
- Locomotion has two outputs: joint animation and root-motion intent. The
  Megameal adapter must map root-motion intent into Megameal's existing player
  or body movement system while the joint sequence animates the rig.
- Offline fallback is not safety-stop. When disconnected and otherwise safe,
  the robot may run local idle/canned behavior. E-stop and low-battery lockout
  still override fallback.
- The command list and servo order are provisional until verified against the
  exact target firmware and wiring guide.

## Deferred Outside-Repo Work

These items are intentionally not implemented in this slice because they require
editing or deeper validation outside `/home/greggles/Ainekio`.

- Megameal adapter: consume virtual joint telemetry and root-motion intent,
  then move the robot root through Megameal's existing movement/player system.
- Megameal contract/register updates and focused validation for any new adapter
  channel.
- MetaHuman OS bridge changes: connect the event-driven environment bridge to
  this motion module without adding a primary polling loop.
- Sesame simulator asset import: decide whether to import URDF/mesh assets from
  the simulator repo or use a separate authored GLB rig.
- Physical hardware driver: wire the PCA9685 backend to the selected Python
  hardware library after confirming the Pi image and dependency budget.
- Battery telemetry: choose and wire the I2C ADC before enforcing real voltage
  thresholds from live readings.
- OLED face channel: define the local face/expression transport and render
  backend.
- Firmware truth pass: verify final command names, servo order, subtrim,
  timing, and motor-current delay behavior against the actual target firmware
  and wiring.

## Validation

Run from `/home/greggles/Ainekio`:

```sh
PYTHONPATH=motion/src python3 -m unittest discover -s motion/tests
```

Current result: passed on Python 3.12.3 with 10 tests.
