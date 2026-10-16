# Upright bounding Run

Normal Walk Speed 1–100 selects Walk; above 100 through 200 blends into Run.
Zero requests Finish. Advanced Run retains independent stride 1–100% and
cadence 0.25–3×. These controls and the ongoing command ownership are unchanged.

Run retains the owner-requested **front-pair/rear-pair bound**, not a diagonal
trot. Each pair has 42% stance, half a cycle apart: front support, flight, rear
support, flight. Contact timing is a command schedule, not sensed contact.

## Current installed-linkage trajectory

`config.json` owns the trajectory for the 35 mm carrier, 20 mm crank, 28 mm
pickup, 38 mm rod and 55 mm lower leg with original fixed shafts. Ground contact
uses bare Part027, as on the assembled robot.

The current centered trajectory uses body Z +5 mm, a 44 mm full planted
stroke, and 5–12 mm lift. It retains zero fore/aft bias, zero scripted pitch/bob,
and the nominal foot lanes. Compared with 0.8.49 this is 10% more stroke and
50% more peak lift; the body reference is 3.75 mm lower to fit the longer
path through the installed linkage. This is not proof of loaded stability.

Automatic forward Run opens the sweep continuously from 37 mm just above 100%
to 44 mm at 200% (40.5 mm at 150%). Cadence remains
`2 + (Speed - 100) / 150` against a 1.2-second base period: approximately
0.6 s per cycle at the threshold, 0.514 s at 150%, and 0.45 s at 200%.
Full-stride modeled travel is 44 / 0.42 = 104.76 mm per cycle; physical travel
depends on tracking and slip. Backward and turning Run use the same body
height, zero fore/aft bias and original turn command rate.

Swing retains its short velocity ramps and constant-speed middle section.
The six-cycle Walk/Run interpolation retains existing planted anchors and
committed touchdown targets. Finish retains its existing coordinated landing
behavior. No Home/Stand sequence, cadence limiter, pulse clamp, automatic stop
or new runtime restriction was added. Servo calibration and self-leveling
settings are unchanged.

## Validation and archived animation

Native Run tests cover paired contact/flight, upright body targets, foot reach,
linkage leverage, common-clock cadence, startup, rate changes, Walk transitions,
Finish and command ownership. Calibration checks cover the existing 400–2900 µs
review window and now include forward/reverse curved Run at 100/150/200% Speed
and 50/100 Hz. The gait research journal records build and deployment results.

`source.json` and its validation/Blender reports are historical recordings. They
are retained for reference and do **not** preview the current trajectory.
`test_run_source.py` verifies archived spatial targets independently and runs
their command sequence through the current native planner. No Blender animation
is rewritten by this firmware update. Loaded bounding must be checked on the
physical robot; the configuration remains `hardware_qualified:false`.
