# Ainekio twelve-servo turn commands

Eight independent motion sources, generated from the corrected robot geometry on 2026-09-15. The approved right-180 motion is retained. Left turns use reflected body/foot paths, swapped left/right step order, and independent inverse kinematics on the measured mechanism. No robot parts were mirrored or remodeled.

## Command index

| Command | Heading change | Active turn | Total duration | Source and Blender clip |
| --- | ---: | ---: | ---: | --- |
| `turn_right_180` | −180° | 24 s | 35 s | [Right 180](commands/turn_right_180/README.md) |
| `turn_left_180` | +180° | 24 s | 35 s | [Left 180](commands/turn_left_180/README.md) |
| `turn_right_90` | −90° | 12 s | 23 s | [Right 90](commands/turn_right_90/README.md) |
| `turn_left_90` | +90° | 12 s | 23 s | [Left 90](commands/turn_left_90/README.md) |
| `turn_right_45` | −45° | 8 s | 19 s | [Right 45](commands/turn_right_45/README.md) |
| `turn_left_45` | +45° | 8 s | 19 s | [Left 45](commands/turn_left_45/README.md) |
| `turn_right_15` | −15° | 4 s | 15 s | [Right 15 — new command](commands/turn_right_15/README.md) |
| `turn_left_15` | +15° | 4 s | 15 s | [Left 15 — new command](commands/turn_left_15/README.md) |

All clips use 120 Hz source samples, three actuators per leg, a 78 mm body-height target, and 5 mm sole clearance. The total duration includes five seconds of entry and six seconds of settling. Smaller angles use fewer cycles; 45° uses two 22.5° cycles, and 15° uses one 15° cycle. These durations are explicit research settings, not requirements for the finished product.

Each command directory contains its **own** `source.json`, `source.csv`, `schema.json`, `config.json`, `manifest.json`, evaluated Blender checks, interpolation checks, and README. The archive contains the compact research sources; the full `.blend` files remain alongside the sources in the Blender workspace. Open a command's `.blend` and play the preview range: the turn begins at frame 529, after the retained original range tests. Every command starts in the same initial world heading; each file is an independent clip.

The saved walking files and the original right-180 working file remain separate. `Before-Turn-Family.blend` preserves the live model immediately before making the family.

## Firmware and Body Control handoff

Read [FIRMWARE_HANDOFF.md](FIRMWARE_HANDOFF.md) first. `catalog.json` lists all eight commands. Each command's manifest supplies the semantic wire envelope, its complete duration, start/final-pose contract, and source/geometry hashes.

The two 15° names are new. Existing 45°/90°/180° names stay the same. This package supplies motion assets and integration instructions; it does not register new dashboard commands, modify firmware execution, assign electrical channels, flash a board, or qualify hardware motion.

## Reproduce the source

Use Python with NumPy installed, from this directory:

```bash
python3 generate_turns.py
python3 export_sources.py
python3 validate_sources.py
python3 sample_reference.py turn_left_15 7000
```

To regenerate one command, pass its name to `generate_turns.py`. It currently uses the named defaults in `generate_turns.config()`; edit those settings or call `turn_planner.generate(settings)` with a changed configuration. A failed reach/angle check rejects generation instead of clamping a servo.

`sample_reference.py` is a read-only reference for a firmware port. It returns signed geometric centidegrees and derivatives for all twelve joints. The generator/Blender animation use radians. Its sample clock uses integer rational 120 Hz indexing; it holds the actual recorded final pose after completion.

For Blender, use the preserved model file as input:

```bash
/home/greggles/blender-5.0.0-linux-x64/blender \
  -b Before-Turn-Family.blend -t 4 --python-exit-code 1 --python build_blends.py
```

This background batch saves each command separately, reopens it, compares the evaluated mechanism against the solver, checks preservation of the model/original tests, and creates a still preview. It never opens another file in the live GUI. To apply a chosen command to the existing rig through Blender's Python console:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-turn-commands-20260915/apply_turn.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p), 'COMMAND_NAME': 'turn_left_90'})
```

The full model is required for Blender playback, but the geometry JSON and sole samples are sufficient to regenerate all kinematic source files without Blender.

## Validation limits

All eight files were saved and reopened. Measured mechanism connections and foot predictions agree with evaluated Blender geometry to better than 0.0001 mm at the checked extrema/intermediate poses; preserved meshes, parenting and original test keys are unchanged. Full per-command results are retained.

**These are research motions, not qualified ground-walking commands.** Assumed-COM minimum support margins are negative: approximately −1.821 mm for 90°/180°, −2.591 mm for 45°, and −4.442 mm for 15°. Existing intended mount interference remains. Measured mass distribution, collisions over the whole motion, floor friction/yaw scrub, loaded servo travel/speed/torque, electrical calibration, stop behavior and dynamics still need hardware work.

Interpolation has continuous position and velocity; acceleration may jump at keys or sole-contact feature changes. `interpolation-validation.json` records the actual cubic-curve demands, which can exceed the finite-difference estimates in `validation.json`. No physical stability or energy-efficiency claim is made.
