# V2 servo mounting and calibration

Profile `v2-24-38-centered-shaft-heads`. The original motion geometry and timing are retained. The retained mapping references below are provisional; they do not establish the installed horn angles.

| Joint | Part | Default Home reference (non-inverted) | Model angle at that pulse |
| --- | --- | --- | --- |
| Shoulder | Part 002 / 003 | 1650 µs | 0° |
| Carrier | Part 006 / 023 | 856 µs | 1.17° |
| Crank | Part 005 / 009 | 723 µs | -40.41° |

The owner reports 300–2900 µs crank travel. The original motion curves are retained. The attempted whole-library recentering was removed because it changed the physical leg poses. Home pulse and model angle must describe the same physical joint pose; fitting waveform extrema inside a pulse span does not establish that relationship.

The mapping assumes non-inverted direction and 11.111111 µs/degree. Actual shaft travel, spline alignment and installed direction remain unmeasured. All four legs use the model angles in their own CAD frame. Physical rear legs are CAD FL/FR; physical front legs are CAD RL/RR.

Body Control remains the owner of channel, Home pulse, Model angle at Home, inversion and scale. Firmware defaults do not overwrite saved calibration. Physical joint angles at the saved Home pulses remain unmeasured. Correct physical mapping must be established before claiming installed motion parity.

| ID | Physical joint | CAD leg | Default channel | Home µs | Model angle |
| --- | --- | --- | --- | --- | --- |
| 0 | rear left shoulder | FL | 0 | 1650 | 0° |
| 1 | rear left carrier | FL | 1 | 856 | 1.17° |
| 2 | rear left crank | FL | 2 | 723 | -40.41° |
| 3 | rear right shoulder | FR | 3 | 1650 | 0° |
| 4 | rear right carrier | FR | 4 | 856 | 1.17° |
| 5 | rear right crank | FR | 5 | 723 | -40.41° |
| 6 | front left shoulder | RL | 6 | 1650 | 0° |
| 7 | front left carrier | RL | 7 | 856 | 1.17° |
| 8 | front left crank | RL | 8 | 723 | -40.41° |
| 9 | front right shoulder | RR | 9 | 1650 | 0° |
| 10 | front right carrier | RR | 10 | 856 | 1.17° |
| 11 | front right crank | RR | 11 | 723 | -40.41° |

## Motion paths

Full Walk uses 92 mm planted sweep. Forward Run retains 104 mm, with coordinated body pitch and foot timing. Starts, control changes and Finish follow the same native planner. All original recorded joint curves are retained. Named motions and entry transitions use the same existing affine mapper; numerical curve parity alone does not prove physical motion parity.

The internal model includes 4 mm diameter × 1.5 mm shaft screw heads, captured moving linkage meshes and stationary Part 003/005/006 on all four legs. It does not establish cable clearance, print tolerances, torque, tracking or balance. A surface-intersection check is modeled evidence, not a physical collision guarantee.

The profile records connected carrier/crank limits. These are coupled: independent extrema cannot be combined arbitrarily. Shoulder-to-body and leg-to-leg clearance require separate evidence. The existing PWM capacity and joint-speed policy remain unchanged. No additional runtime limiter is introduced.

Home is an operator-selected literal pulse; its model association is independently configurable. CAD Neutral, Stand, Sit and Rest remain distinct model poses. Updating source does not flash firmware, change NVS calibration or command physical motion.

See [the current range audit](mechanics/original-motion-range-audit.md), [the joint table](mechanics/servo-mounting-reference.csv) and [the canonical profile](servo_profile.json).
