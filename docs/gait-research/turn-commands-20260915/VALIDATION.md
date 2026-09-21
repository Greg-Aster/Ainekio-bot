# Validation summary — eight finite turn commands

Generated and checked 2026-09-15. Each command has its own full source and saved Blender file.

| Command | Heading | Total s | Minimum assumed-COM margin mm | Peak cubic speed deg/s | Peak cubic acceleration deg/s² | Evaluated poses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `turn_right_180` | -180° | 35 | -1.821 | 243.887 | 4267.022 | 14 |
| `turn_left_180` | +180° | 35 | -1.821 | 243.887 | 4267.015 | 15 |
| `turn_right_90` | -90° | 23 | -1.821 | 243.887 | 4267.022 | 14 |
| `turn_left_90` | +90° | 23 | -1.821 | 243.887 | 4267.015 | 15 |
| `turn_right_45` | -45° | 19 | -2.591 | 159.716 | 2143.936 | 14 |
| `turn_left_45` | +45° | 19 | -2.591 | 159.716 | 2143.936 | 14 |
| `turn_right_15` | -15° | 15 | -4.442 | 105.257 | 1652.441 | 12 |
| `turn_left_15` | +15° | 15 | -4.442 | 105.257 | 1652.442 | 14 |

## Measured results

- All eight heading targets are met, without yaw wrapping; body XY returns to the initial position. All 22,088 samples supply all twelve joint angles.
- Angles stay continuous within the configured geometric research bounds. Interpolation midpoints remain inside the adjacent joint values. No servo-angle clamping is used.
- Maximum evaluated joint disconnection: 0.000051322 mm.
- Maximum evaluated foot-bolt prediction error: 0.000035458 mm.
- Lowest evaluated sole point: -0.000074395 mm; numerical-scale penetration below the 0.05 mm check tolerance.
- Actual sole swing target is 5 mm. At least three contacts remain active; the contact model allows discrete rolling feature transfers and yaw about a point.
- Original geometry and test animation preservation passed for 700 mapped objects per file after saving and reopening. No robot meshes or parenting were changed.
- Four independently solved left/right pairs agree after reflection to within 0.000034 degrees in joint coordinates. Remaining differences follow measured CAD rounding.
- Scene units checked live: Metric, scale_length approximately 0.001; coordinates here are millimeters.

## Limits of these results

- The COM is an explicit assumption at the body datum. Every candidate has a negative minimum support margin; static balance is not qualified.
- Collision checking over the full motion is unverified. The previously identified intended mount interference was retained.
- Component masses, loaded servo speed/acceleration/torque, electrical travel/calibration/channel assignment, yaw friction, foot scrub, stop dynamics and physical heading accuracy remain unverified.
- Position and velocity interpolation are continuous. Acceleration continuity is not guaranteed; contact changes can raise peak acceleration above the sampled finite-difference estimate.
- Entry requires the recorded neutral stance. Final positions are held exactly as recorded. Safe transitions from arbitrary current poses and between commands remain firmware integration work.

The geometric animation and these checks do not establish physical stability or actuator capability.
