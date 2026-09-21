# Rest — twelve-servo handoff

Rest lowers all four legs into a level crouch over three seconds, then holds. The body datum ends at 32 mm, with about 6.75 mm chassis clearance. Existing command: `{"t":"intent","name":"emote","asset":"rest"}`.

- [Source, measured results and reproduction](gait-research/rest-20260915/README.md)
- [Download the complete source package](gait-research/rest-20260915/ainekio-rest-12servo-20260915.zip)
- [Manifest and integration contract](gait-research/rest-20260915/manifest.json)
- [Timestamped twelve-joint CSV](gait-research/rest-20260915/source.csv)
- [Preview](gait-research/rest-20260915/rest-preview.mp4)
- [Blender working copy](/home/greggles/blender-5.0.0-linux-x64/robot-rest-20260915/Ainekio-Rest.blend)

Geometric source only; electrical calibration and physical qualification remain pending. Firmware and Body Control implementation belong to their existing owners.

## Timing and engagement supplement — 2026-09-16

[Rest timing contract](gait-research/execution-20260916/contracts/rest.json) ·
[Shared execution guide](MOTION_EXECUTION_12SERVO.md).
Lowering and hold durations are separately configurable; completion continues
holding the resting pose. Operating limits and electrical scheduling remain for
loaded calibration and firmware integration.
