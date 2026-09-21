# Seated Wave — twelve-servo handoff

Sit, extend the physical front-left leg with Part006 at −34.24° and Part005 at +45°, wave with a 65–95° shoulder sweep, then return to standing. The linkage retains a bend. Duration: 16 seconds. Command: `{"t":"intent","name":"emote","asset":"wave"}`.

- [Source and integration instructions](gait-research/wave-seated-20260916/README.md)
- [Complete source package](gait-research/wave-seated-20260916/ainekio-wave-seated-12servo-20260916.zip)
- [Manifest](gait-research/wave-seated-20260916/manifest.json)
- [Twelve-joint CSV](gait-research/wave-seated-20260916/source.csv)
- [Preview](gait-research/wave-seated-20260916/wave-preview.mp4)
- [Blender copy](/home/greggles/blender-5.0.0-linux-x64/robot-wave-seated-20260916/Ainekio-Wave-Seated.blend)

This 2026-09-16 seated version is the current Wave reference. Part005 was reduced by 35° from the previous wave, bringing the foot farther forward. The earlier overhead experiment remains in the Blender workspace. Joint endpoints are geometric research settings; hardware calibration and physical qualification remain pending.

## Timing and engagement supplement — 2026-09-16

[Wave timing contract](gait-research/execution-20260916/contracts/wave.json) ·
[Shared execution guide](MOTION_EXECUTION_12SERVO.md).
All thirteen phases have independent research timing, including the six shoulder
sweeps. Body, joints, contacts and face cues use one clock. The 16-second approved
demonstration is preserved; physical operating speed awaits loaded calibration.
