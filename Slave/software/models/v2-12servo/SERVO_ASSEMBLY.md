# V2 servo mounting and calibration

## Fourth-wire reference capture (2026-10-18)

Body Control Joint Calibration now offers **Rearward assembly pose** when
capturing a measured Home. The shared local model references are **-30.87° for
carriers** and **-117.68° for cranks**. All corresponding joints must physically
occupy that matching rearward pose. Their measured Home pulses remain individual;
inversion still accounts for mirrored servo mounting. Shoulders default to a
custom explicit reference angle and are not changed by leg calibration.

The carrier reference follows the original mapping at left 2800 / right 500 µs:
`1.17° - (2800 - 2444) / (1000 / 90) = -30.87°`. The crank value is the
photo-derived reindexed reference described below. Neither is a new independent
measurement of the installed linkage angle. The sensor measures each shaft;
matching the physical reference poses establishes the mapping to the model.

Capture assigns the selected reference angle to the measured pulse; it no
longer shifts the reference angle using the previous calibration. The previous
behavior preserved inconsistent mounting offsets. **Custom model angle entered
above** keeps that explicitly entered angle instead. Apply & save persists the
selected joint through the existing calibration owner. Startup still rises to
Stand rather than holding calibration Home; it uses this saved angle mapping.

## Reindexed-crank Walk candidate (0.8.59)

The owner has physically refitted the crank horns. The new rear-left Home is
2800 µs, with 1600 µs at the other full-Walk endpoint. The mirrored right-side
Home is 500 µs, with 1700 µs at the other endpoint. Carriers retain their existing
mounting and calibration. Corresponding left/right pulses sum to 3300 µs.

The new provisional **Model angle at Home is -117.68 degrees** for each crank,
reconstructed from the supplied rear-left photo; it is not a measured shaft
angle. Other horns must occupy corresponding mirrored physical poses for that
reference to apply. The previous -40.41-degree matchmark association below is
historical and must not be combined with the new endpoint Home pulses.
Changing only Home after reindexing would give the gait the wrong angle mapping.

This build does not write saved device calibration. Firmware and mounting
calibration are separate changes. Physical validation is pending. See
[the gait journal](../../../../docs/v2-12servo/GAIT_RESEARCH_JOURNAL.md).

## Previous mounting reference

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
