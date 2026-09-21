# Bow — twelve-servo motion

Based on the original eight-servo Bow: brace the stance, stretch both front forelegs forward and lower the front while
the rear stays raised, hold for three seconds, then stand. Duration **8.5 seconds**.

- [Description, original reference and validation](gait-research/bow-20260916/README.md)
- [Full preview](gait-research/bow-20260916/bow-preview.mp4)
- [Source handoff ZIP](gait-research/bow-20260916/ainekio-bow-12servo-20260916.zip)
- [Source JSON](gait-research/bow-20260916/source.json)
- [Source CSV](gait-research/bow-20260916/source.csv)
- [Configuration](gait-research/bow-20260916/config.json)
- [Execution and timing contract](gait-research/bow-20260916/execution-contract.json)

Saved Blender:
`/home/greggles/blender-5.0.0-linux-x64/robot-bow-20260916/Ainekio-Bow.blend`.
Frames **2881–3085** follow deep Pushup. The source includes 1021 samples at
120 Hz, in geometric radians and millimeters. The existing model and earlier
motions are preserved. The minimum assumed-COM support margin is 29.477 mm.
The reach includes an explicit 20 mm front-foot slide. Sliding friction, hardware calibration, loaded performance and full collisions remain unverified;
the README records the existing camera-reference floor issue separately from
passing leg-sole checks.
