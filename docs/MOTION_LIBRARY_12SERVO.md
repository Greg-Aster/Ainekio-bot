# Twelve-servo motion library

Twelve adaptations of the existing eight-servo motions, saved in `Ainekio-Motion-Library.blend` after Bow.

- [Full guide and playback instructions](gait-research/motion-batch-20260916/README.md)
- [Validation and remaining assumptions](gait-research/motion-batch-20260916/validation-report.md)
- [All twelve source packages](gait-research/motion-batch-20260916/ainekio-motion-library-12servo-20260916.zip)
- [Pose overview](gait-research/motion-batch-20260916/contact-sheet.png)

| Command | Demo | Frames | Individual handoff | Preview |
| --- | ---: | --- | --- | --- |
| [CUTE](gait-research/motion-batch-20260916/commands/cute/README.md) | 13.5 s | 3109–3433 | [ZIP](gait-research/motion-batch-20260916/commands/cute/ainekio-cute-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/cute/preview.mp4) |
| [FREAKY](gait-research/motion-batch-20260916/commands/freaky/README.md) | 9.7 s | 3457–3690 | [ZIP](gait-research/motion-batch-20260916/commands/freaky/ainekio-freaky-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/freaky/preview.mp4) |
| [WORM](gait-research/motion-batch-20260916/commands/worm/README.md) | 12.5 s | 3714–4014 | [ZIP](gait-research/motion-batch-20260916/commands/worm/ainekio-worm-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/worm/preview.mp4) |
| [SHAKE](gait-research/motion-batch-20260916/commands/shake/README.md) | 7 s | 4038–4206 | [ZIP](gait-research/motion-batch-20260916/commands/shake/ainekio-shake-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/shake/preview.mp4) |
| [SHRUG](gait-research/motion-batch-20260916/commands/shrug/README.md) | 10.2 s | 4230–4475 | [ZIP](gait-research/motion-batch-20260916/commands/shrug/ainekio-shrug-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/shrug/preview.mp4) |
| [DEAD](gait-research/motion-batch-20260916/commands/dead/README.md) | 12.3 s | 4499–4794 | [ZIP](gait-research/motion-batch-20260916/commands/dead/ainekio-dead-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/dead/preview.mp4) |
| [CRAB](gait-research/motion-batch-20260916/commands/crab/README.md) | 30.6 s | 4818–5552 | [ZIP](gait-research/motion-batch-20260916/commands/crab/ainekio-crab-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/crab/preview.mp4) |
| [CELEBRATE](gait-research/motion-batch-20260916/commands/celebrate/README.md) | 12.5 s | 5576–5876 | [ZIP](gait-research/motion-batch-20260916/commands/celebrate/ainekio-celebrate-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/celebrate/preview.mp4) |
| [STRETCH](gait-research/motion-batch-20260916/commands/stretch/README.md) | 6.7 s | 5900–6061 | [ZIP](gait-research/motion-batch-20260916/commands/stretch/ainekio-stretch-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/stretch/preview.mp4) |
| [SURPRISED](gait-research/motion-batch-20260916/commands/surprised/README.md) | 11.95 s | 6085–6372 | [ZIP](gait-research/motion-batch-20260916/commands/surprised/ainekio-surprised-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/surprised/preview.mp4) |
| [SAD](gait-research/motion-batch-20260916/commands/sad/README.md) | 8.8 s | 6396–6607 | [ZIP](gait-research/motion-batch-20260916/commands/sad/ainekio-sad-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/sad/preview.mp4) |
| [CURIOUS](gait-research/motion-batch-20260916/commands/curious/README.md) | 9.75 s | 6631–6865 | [ZIP](gait-research/motion-batch-20260916/commands/curious/ainekio-curious-12servo-20260916.zip) | [Video](gait-research/motion-batch-20260916/commands/curious/preview.mp4) |

Blender file: `/home/greggles/blender-5.0.0-linux-x64/robot-motion-batch-20260916/Ainekio-Motion-Library.blend`. Frames 3109–6865, 24 fps. Source units are mm and geometric radians, ordered CAD FL/FR/RL/RR × shoulder002/carrier006/crank005. Servo electrical calibration is not supplied.

Dead semantically finishes at 7.4 s in its held pose; its 12.3 s preview includes explicitly optional standing recovery. The shared timing helper excludes recovery by default. Visor/inter-part collision work is deferred, and physical contact loading, COM, servo/current capability and electrical timing remain unverified. Crab’s low assumed support margin and final contact slide are documented in its source guide. No V1 firmware or shared Body Control implementation was modified.

## Current model and resource policy

The 2026-09-17 final comparison found later front-panel, camera and display changes relative to the preserved integration baseline; those current edits are retained. No leg meshes appear in the changed/missing list, and earlier actuator/body curves match all 19 recorded baseline frames. All twelve new actuator/body tracks also match every exported source sample (see `current-curve-source-review.json`). Body-contact points and complete-body floor results in the command reports describe the earlier measured geometry snapshot and have not been requalified for the later front changes. Completed preview frames span the saved model revisions; visor work remains deferred.

Preview rendering completed sequentially with a 10 GiB hard memory limit and no worker swap. Peak measured worker RSS was 2.60 GiB; the service exited after all 913 images. See `gait-research/motion-batch-20260916/resource-policy.md`.
