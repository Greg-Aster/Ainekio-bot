# Point — twelve-servo motion

The robot crouches toward its rear-right leg before lifting and extending the
front-left arm to point. It holds for two seconds, replaces the foot, then
returns to standing. The full demonstration is 11 seconds. The extended revision reaches 97.20 mm
from pivot O to the foot bolt, about 32 mm farther forward than the initial
Point. Both versions are recorded in the package.

- [Motion description, results and reproduction instructions](gait-research/point-20260916/README.md)
- [Full preview](gait-research/point-20260916/point-preview.mp4)
- [Complete source handoff ZIP](gait-research/point-20260916/ainekio-point-12servo-20260916.zip)
- [Timestamped source JSON](gait-research/point-20260916/source.json)
- [Timestamped source CSV](gait-research/point-20260916/source.csv)
- [Configuration](gait-research/point-20260916/config.json)
- [Execution and phase timing contract](gait-research/point-20260916/execution-contract.json)
- [Coordinates and schema](gait-research/point-20260916/schema.json)

Saved Blender file:
`/home/greggles/blender-5.0.0-linux-x64/robot-point-20260916/Ainekio-Point.blend`.
Point occupies frames 1849–2113, after Swim. The model and previous motions are
preserved; the source backup is `Before-Point.blend` in the same directory.

The package contains 1321 samples at 120 Hz. Leg order is CAD FL, FR, RL, RR,
physically rear-left, rear-right, front-left, front-right. Each triplet is
shoulder h/Part002, carrier alpha/Part006, crank theta/Part005, in signed
geometric radians. Servo calibration and operating timing remain pending.

The minimum assumed-COM support margin is 24.858 mm. Fifteen evaluated Blender
poses preserve four-bar connections and floor contact to numerical tolerance.
Full collisions, measured masses, load performance and electrical capability
remain unverified. This package changes motion research documentation only.
