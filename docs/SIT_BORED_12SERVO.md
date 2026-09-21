# Sit · bored — twelve-servo source

The existing `sit` intent lowers the rear legs near their geometric fold limit, extends the front legs, and holds a 27.5° nose-up sitting posture with the existing bored face.

- [Source and firmware handoff](gait-research/sit-bored-20260915/README.md)
- [JSON/CSV provenance and command contract](gait-research/sit-bored-20260915/manifest.json)
- [Five-second preview](gait-research/sit-bored-20260915/sit-bored-preview.mp4)
- [Portable source archive](gait-research/sit-bored-20260915/ainekio-sit-bored-12servo-20260915.zip)
- [Blender working file](/home/greggles/blender-5.0.0-linux-x64/robot-sit-bored-20260915/Ainekio-Sit-Bored.blend)

The package contains all twelve geometric joint tracks, body/foot/contact data, face assets, configuration, generator and validation. The movement takes three seconds, followed by two seconds of recorded hold; completion holds the final posture until another command. Electrical calibration and physical capability remain unqualified.

## Timing and engagement supplement — 2026-09-16

[Sit timing contract](gait-research/execution-20260916/contracts/sit.json) ·
[Shared execution guide](MOTION_EXECUTION_12SERVO.md).
Lowering and hold durations are separately configurable; completion continues
holding the seated pose. Operating limits and electrical scheduling remain for
loaded calibration and firmware integration.
