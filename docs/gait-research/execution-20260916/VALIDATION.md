# Execution supplement validation

2026-09-16. Offline data/clock validation only.

## Completed

- Built twelve command contracts from the existing source and manifest files.
- Verified all bound source/manifest/loop hashes and the eight turn archive mirrors.
- Verified source timestamps at 120 Hz and the twelve-joint ordering.
- Seven focused tests passed (`python3 -B -m unittest -v test_timing.py`): all
  demonstration phase clocks, uniform speed/acceleration scaling, nonuniform
  monotone timing and boundary derivatives, retimed cues, repeated walk seams,
  terminal holds, invalid/unconfigured settings, catalog/policy bindings.
- Three selected walk cycles give 32.4 s including entry and exit. One gives
  24.4 s; ten give 60.4 s. A 2× Wave clock gives 8 s, with the stand face at 7.6 s.
- Source endpoints and the approved demonstrations are preserved. No servo
  calibration, firmware output, physical operation or Blender edits were made.

## Requested joint demands at reference timing

Values below are maxima across the twelve tracks using analytic extrema of
full-source monotone cubic interpolation over the selected source intervals.
They are not measured actuator limits. Degrees are used only for readability;
contracts use radians. Walk values precede the canonical compiler's seam tangent
normalization. The margin column is the original full source's reported minimum
under its assumed COM, including transitions; it is not a new balance check or
just the steady loop. Retimed/compiled demands must be recalculated.

| Command | Peak speed °/s | Peak acceleration °/s² | Source assumed COM margin mm |
| --- | ---: | ---: | ---: |
| walk | 225.17 | 2225.48 | -21.57 |
| turn_left_15 | 105.26 | 1652.44 | -4.44 |
| turn_left_45 | 159.72 | 2143.94 | -2.59 |
| turn_left_90 | 243.89 | 4267.02 | -1.82 |
| turn_left_180 | 243.89 | 4267.02 | -1.82 |
| turn_right_15 | 105.26 | 1652.44 | -4.44 |
| turn_right_45 | 159.72 | 2143.94 | -2.59 |
| turn_right_90 | 243.89 | 4267.02 | -1.82 |
| turn_right_180 | 243.89 | 4267.02 | -1.82 |
| sit | 39.91 | 50.67 | 35.59 |
| rest | 26.01 | 33.78 | 39.12 |
| wave | 125.00 | 551.26 | 15.79 |

## Remaining hardware/integration work

All contracts retain `hardware_ready: false`. Loaded travel/speed/acceleration,
braking/jerk limits, actual mass/COM, tracking latency/skew, collision clearance,
power/current limits and pulse-phase/engagement measurements are unverified.
Negative source support margins remain unresolved. Faster timing does not remove
them or establish dynamic balance. Source cubic acceleration continuity is not
guaranteed; the clock tests do not validate foot interpolation, physical tracking
or geometric closure after independent joint interpolation.

The firmware owner must implement/calibrate the operating profile, coordinated
transition/interruption behavior, initial engagement, pulse scheduling and output
cadence in its existing executor. No arbitrary staggering was inserted into the
joint trajectories. The canonical loop sampler still owns seam matching and
world translation. Source completion is not physical pose confirmation.
