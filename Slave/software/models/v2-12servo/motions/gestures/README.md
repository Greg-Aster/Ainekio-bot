# Twelve-servo postures and gestures

The 23 gestures include Lay Down and experimental Upright. Worm and Shrug derive from the reviewed Blender recordings with the calibrated trajectory adjustments below. Play Dead retains its reviewed recording. Crab is now ongoing locomotion and has no finite runtime clip. V1 assets are preserved. Sit uses the native `sit` intent; other gestures use `emote` with the named asset.

The durations below describe the source recordings. Runtime travel is timed by
joint distance at full configured speed, while intentional holds retain their
source duration divided by the requested hold/entry rate (default 2×).

| Command | Source duration | Completion |
| --- | --- | --- |
| `sit` | 5 s | Hold the recorded command endpoint |
| `rest` | 5 s | Hold the recorded command endpoint |
| `wave` | 6.2 s | Hold the recorded command endpoint |
| `dance` | 12.5 s | Hold the recorded command endpoint |
| `swim` | 23.5 s | Hold the recorded command endpoint |
| `point` | 6.1 s | Hold the recorded command endpoint |
| `nod` | 8.5 s | Hold the recorded command endpoint |
| `pushup` | 14.2 s | Hold the recorded command endpoint |
| `bow` | 7.3 s | Hold the recorded command endpoint |
| `cute` | 13.5 s | Hold the recorded command endpoint |
| `freaky` | 9.2 s | Hold the recorded command endpoint |
| `worm` | 6.4 s | Three body waves; return to standing |
| `shake` | 7 s | Hold the recorded command endpoint |
| `shrug` | 14 s | Seated front-arm shrug; return to standing |
| `dead` | 7 s | Play Dead: collapse and hold with front arms outstretched |
| `lay_down` | 7 s | Hold the previous reviewed Dead pose as Lay Down |
| `celebrate` | 12.5 s | Hold the recorded command endpoint |
| `stretch` | 6.7 s | Hold the recorded command endpoint |
| `surprised` | 11.95 s | Hold the recorded command endpoint |
| `sad` | 8.8 s | Hold the recorded command endpoint |
| `curious` | 9.75 s | Hold the recorded command endpoint |
| `crouch` | 4 s | Hold the recorded command endpoint |
| `upright` | 22 s | Hold the experimental hind-leg pose |

Sit places the rear lower legs along the floor at 1.8° above horizontal. Rest makes all four lower legs horizontal and puts the chassis base plate on the floor; its contact scope deliberately excludes carapace and mask. Wave replays the exact Sit entry, extends the front-left arm, makes three shoulder waves, replaces the foot and reverses Sit into standing.

Point uses a coupled carrier/crank extension on the reachable branch of the linkage. Its 92.17 mm arm reach replaces the original 95.02 mm reach; its pointing endpoint is within 1.49 mm of the original world-space target. Bow preserves the eight-servo gesture: brace, slide both hands forward about 73.42 mm with the front low and rear high, hold five source seconds, then reverse. Sliding friction is unqualified.

Nod retains exactly two up/down cycles. Its pitch amplitude and timing are preserved; body translation and joint paths adjust to the mounted calibration. Crouch lowers four planted feet to a held squat at body translation -35 mm, with the chassis above ground. Ongoing Crawl and directional walking are native commands, not finite clips.

Upright is distinct from four-foot Stand. It replays the accepted Sit, moves the front feet backward one at a time, shifts weight over the planted rear lower legs, then raises the chassis to vertical. [Upright geometry and limitations](upright/README.md).

## Source and execution

`catalog.json` binds canonical sources, measured posture dependencies, schemas and execution contracts. Historical choreography under `docs/gait-research/` supplies task-space intent and timing, not current servo angles. `../../tools/retarget_clips.py` regenerates legacy-derived clips and dispatches approved `reviewed.json` recordings to `import_reviewed_clips.py`; `generate_locomotion.py` records Crouch and native walking demonstrations.

The compiler checks units, joint order, hashes, exact endpoints, semantic duration and preserved cubic interpolation. It integrates joint travel along the existing path and retains every authored phase endpoint and joint reversal. Following the owner's 2026-10-20 correction, gesture travel uses 50% of the configured joint speed; all repetitions, ranges and original hold durations remain intact. Sit, Rest and Crouch decelerate over their final 20% of joint travel (at most 10 degrees). The legacy rate now affects entry easing only.

The P4 emits each target before advancing and uses the existing calibrated servo feedback and arrival tolerance to confirm it. Time spent reaching a target never consumes the next movement or its pause. Completion follows measured terminal arrival. Missing or untrusted feedback leaves that target commanded and reports waiting; there is no timeout that skips it. New commands and Stop remain available through the existing asynchronous owner. Face cues and expected attitude follow actual source progress, including target waits. These are executor semantics tested with simulated servo lag; physical acceptance of this revision remains separate.

Play Dead and Lay Down have seven-second source recordings and hold their completed poses. Their rear support is identical; Play Dead extends the front hands 45.35 mm farther forward. Rest remains the separate all-lower-legs-flat, chassis-grounded pose. The reviewed clips retain the 30 Hz Blender keys; the offline importer resamples them at 120 Hz for the existing compact cubic compiler. `reviewed-hulls.npz` holds measured support geometry only on the development computer. Changing root geometry invalidates a reviewed recording and requires review again. Freaky still excludes its optional preview recovery from firmware. Face cues and research timing profiles remain source metadata; animated face execution is not implemented by this library.

Each posture file records current constraints. Wave depends on Sit and must regenerate after Sit changes. Root geometry or motion geometry changes require all affected sources to regenerate, then native checks and saved-file Blender verification. The scene `Motions - Current Geometry` in `ainekio-variable-gait-Recovery.blend` shares meshes and keeps editable modeling work.

## Qualification

All assets retain `hardware_qualified=false`. The coupled internal-leg sweep and floor/closure checks do not qualify shoulder/body clearance, loaded motion, servo travel, traction or balance. Firmware motion availability comes from confirmed calibration and runtime readiness; it is separate from research qualification. Assembly references, pulse-center arithmetic, migration and measurement procedures are in [SERVO_ASSEMBLY.md](../../SERVO_ASSEMBLY.md).

Point, Nod, Pushup, Worm, Shrug and Upright have reauthored trajectories for the mounted mirrored calibration and the requested 400–2900 µs span. Their source durations remain unchanged. The other 17 sources remain unchanged. Those source adjustments change recorded poses, independently of runtime timing and servo calibration. Each adjusted source records its baseline hash and exact calibration in `metadata.calibrated_path_fit`.

The canonical adjusted paths are `source.json`. Older generators and `reviewed.json` files describe the pre-adjustment choreography and do not reproduce these calibration fits. Historical Blender and interpolation reports are labeled as prior-recording evidence; the adjusted paths have not been reviewed in Blender or physically qualified. The independent native `clip_calibration` test checks all 23 compiled trajectory extrema and entry interpolation from Home and every named-motion terminal pose using the mounted profile. Changing that profile requires checking the pulse ranges again.

`../../mechanics/original-motion-range-audit.json` describes the earlier recordings and modeled clearance envelope; it is not a pulse-range verdict on these corrected sources. Electrical pulse bounds do not establish mechanical collision clearance.
