# Twelve-servo motion timing and engagement

The 2026-09-16 execution supplement covers **Walk, all eight left/right turns,
Sit, Rest, and the current seated Wave**. Each command has its own source-bound
timing contract with editable phase durations, exact joint ordering, contact
events and entry/completion data.

- [Execution guide and all twelve command contracts](gait-research/execution-20260916/README.md)
- [Shared coordination, engagement and PWM scheduling policy](gait-research/execution-20260916/execution-policy.json)
- [Contract catalog and source hashes](gait-research/execution-20260916/catalog.json)
- [Validation results](gait-research/execution-20260916/VALIDATION.md)
- [Download timing supplement](gait-research/execution-20260916/ainekio-motion-execution-20260916.zip)

Demonstration timing stays intact. Research timing can be accelerated globally or
edited per phase. Operating timing and loaded servo limits remain uncalibrated.
The offline Python reference preserves one motion clock for coordinated joints,
body, feet, contacts and face cues. PWM pulse phase offsets and controlled initial
engagement are separate requirements for the firmware executor.

This supplement updates the motion handoff; it does not change the live Blender
scene, implement electrical scheduling, or qualify the robot for physical motion.

## Added command: Dance

[Dance source and execution contract](DANCE_12SERVO.md) adds a thirteenth motion
handoff using the same timing/coordination policy. Its separate versioned package
contains the 12.5-second demonstration and editable phase timing; the original
twelve-command supplement and its catalog remain the recorded baseline.

## Added command: Swim

[Swim source and execution contract](SWIM_12SERVO.md) adds the belly-supported
90°-shoulder breaststroke with continuous overlapping front/rear motion, including explicit body/foot support events and
phase timing. It is the fourteenth motion handoff; the original twelve-command
supplement and the separate Dance package retain their recorded sources.

## Added command: Point

[Point source and execution contract](POINT_12SERVO.md) adds the rear-right
support crouch followed by a front-left forward point, with an 11-second
demonstration, original Point face animation, 120 Hz source and editable phase
timing. It is the fifteenth motion handoff and uses the existing shared
coordination and electrical-engagement policy.

## Updated command: Pushup

[Pushup source and execution contract](PUSHUP_12SERVO.md) now uses a near-bottom
crouch of both rear legs before five front-leg presses. The 14.5-second deep
revision has its own versioned source package and retains the shared timing and
engagement policy. The original shallow Pushup package remains historical.

## Added command: Nod

[Nod source and execution contract](NOD_12SERVO.md) preserves the former shallow
Pushup exactly, as requested by the owner. It is a separate `nod` command with
its own source data, Blender file and timing contract. There are now seventeen
named motion handoffs; Nod occupies frames 2137–2485 and the revised Pushup
follows at 2509–2857 in the combined scene.

## Added command: Bow

[Bow source and execution contract](BOW_12SERVO.md) adapts the V1 stance,
front-leg stretch and front-low/rear-high bow, sustained pose and standing return. Its separate
8.5-second source package contains 120 Hz geometric tracks and the original
Bow face/reference data. It is the eighteenth named motion handoff, appended
after deep Pushup at frames 2881–3085.

## Added library batch

The [twelve-command library](MOTION_LIBRARY_12SERVO.md) adds Cute, Freaky, Worm,
Shake, Shrug, Dead, Crab, Celebrate, Stretch, Surprised, Sad and Curious, bringing
the named motion total to thirty. Its contracts distinguish semantic command
completion from optional preview recovery. Dead finishes at 7.4 seconds and
holds; standing recovery belongs only to its optional demonstration sequence.

## Firmware integration (2026-09-17)

All thirty named motions are now compiled into the P4 target with their
recorded command timing and semantic completion boundaries. Optional preview
tails remain source data and are excluded from firmware execution. The
[gesture source owner](../Slave/software/models/v2-12servo/motions/gestures/README.md)
retains the current seated Wave, shallow Nod and deep Pushup as distinct assets,
with source-bound execution contracts. Existing Body Control and bridge command
names and envelopes are reused. Research retiming and the future calibrated
actuator executor remain separate from these geometric samplers.

See the [build, test and pending flash record](v2-12servo/MOTION_INTEGRATION_20260917.md).
The board was disconnected for this update; the new image has not been flashed
or physically tested. Motion readiness remains false.

## Added twelve-command motion library

[Motion library and individual source handoffs](MOTION_LIBRARY_12SERVO.md) adds Cute, Freaky, Worm, Shake, Shrug, Dead, Crab, Celebrate, Stretch, Surprised, Sad and Curious. Each adapts its original eight-servo reference, with an independent 120 Hz geometric source, timing contract and preview. The combined Blender animation follows Bow at frames 3109–6865. Dead retains its held endpoint; standing recovery is optional. Visor/inter-part collisions and hardware qualification remain unverified. There are now thirty named motion handoffs.
