# Twelve-servo postures and gestures

The 23 gestures include the new experimental Upright. The preceding 22 gestures and eight finite turns retain their choreography. V1 assets are preserved. Sit uses the native `sit` intent; other gestures use `emote` with the named asset.

| Command | Duration | Completion |
| --- | --- | --- |
| `sit` | 5 s | Hold the recorded command endpoint |
| `rest` | 5 s | Hold the recorded command endpoint |
| `wave` | 16 s | Hold the recorded command endpoint |
| `dance` | 12.5 s | Hold the recorded command endpoint |
| `swim` | 23.5 s | Hold the recorded command endpoint |
| `point` | 11 s | Hold the recorded command endpoint |
| `nod` | 8.5 s | Hold the recorded command endpoint |
| `pushup` | 14.5 s | Hold the recorded command endpoint |
| `bow` | 8.5 s | Hold the recorded command endpoint |
| `cute` | 13.5 s | Hold the recorded command endpoint |
| `freaky` | 9.2 s | Hold the recorded command endpoint |
| `worm` | 12 s | Hold the recorded command endpoint |
| `shake` | 7 s | Hold the recorded command endpoint |
| `shrug` | 10.2 s | Hold the recorded command endpoint |
| `dead` | 7.4 s | Hold the recorded command endpoint |
| `crab` | 30.1 s | Hold the recorded command endpoint |
| `celebrate` | 12.5 s | Hold the recorded command endpoint |
| `stretch` | 6.7 s | Hold the recorded command endpoint |
| `surprised` | 11.95 s | Hold the recorded command endpoint |
| `sad` | 8.8 s | Hold the recorded command endpoint |
| `curious` | 9.75 s | Hold the recorded command endpoint |
| `crouch` | 4 s | Hold the recorded command endpoint |
| `upright` | 22 s | Hold the experimental hind-leg pose |

Sit places the rear lower legs along the floor at 1.8° above horizontal. Rest makes all four lower legs horizontal and puts the chassis base plate on the floor; its contact scope deliberately excludes carapace and mask. Wave replays the exact Sit entry, extends the front-left arm, makes three shoulder waves, replaces the foot and reverses Sit into standing.

Point retains its original95.02mm forward extension and original recorded path. Bow preserves the eight-servo gesture: brace, slide both hands forward about 73.42 mm with the front low and rear high, hold three seconds, then reverse. Sliding friction is unqualified.

Nod retains exactly two up/down cycles. Its original amplitude and timing are preserved, as are all other gestures. Crouch lowers four planted feet to a held squat at body translation -35 mm, with the chassis above ground. Ongoing Crawl and directional walking are native commands, not finite clips.

Upright is distinct from four-foot Stand. It replays the accepted Sit, moves the front feet backward one at a time, shifts weight over the planted rear lower legs, then raises the chassis to vertical. [Upright geometry and limitations](upright/README.md).

## Source and execution

`catalog.json` binds canonical sources, measured posture dependencies, schemas and execution contracts. Historical choreography under `docs/gait-research/` supplies task-space intent and timing, not current servo angles. `../../tools/retarget_clips.py` regenerates the finite library; `generate_locomotion.py` records Crouch and native walking demonstrations.

The compiler checks units, joint order, hashes, exact endpoints, semantic duration and preserved cubic interpolation. `clip.c` uses harmonic-secant monotone cubic interpolation with zero endpoint velocity and a single clock for all twelve joints. The common P4 output task handles calibrated entry, execution, cancellation and electrical bounds.

Dead completes at 7.4 seconds and holds. Its optional preview recovery remains separate from the compiled command. Freaky, Worm and Crab omit their optional final preview holds in firmware. Face cues and research timing profiles remain source metadata; animated face execution is not implemented by this library.

Each posture file records current constraints. Wave depends on Sit and must regenerate after Sit changes. Root geometry or motion geometry changes require all affected sources to regenerate, then native checks and saved-file Blender verification. The scene `Motions - Current Geometry` in `ainekio-variable-gait-Recovery.blend` shares meshes and keeps editable modeling work.

## Qualification

All assets retain `hardware_qualified=false`. The coupled internal-leg sweep and floor/closure checks do not qualify shoulder/body clearance, loaded motion, servo travel, traction or balance. Firmware motion availability comes from confirmed calibration and runtime readiness; it is separate from research qualification. Assembly references, pulse-center arithmetic, migration and measurement procedures are in [SERVO_ASSEMBLY.md](../../SERVO_ASSEMBLY.md).

Original motions conflict with portions of the modeled clearance envelope and the300–2900µs reference span. See `../../mechanics/original-motion-range-audit.json`. These conflicts are reported without shrinking the movements.
