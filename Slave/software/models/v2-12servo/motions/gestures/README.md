# Twelve-servo postures and gestures

These twenty-one clips extend the existing walk and eight turns. They reuse
the gateway-owned semantic names and V1 command envelopes; the P4 selects its
own twelve-joint geometry. `sit` is a native intent. The other twenty use
`{"t":"intent","name":"emote","asset":"<name>"}`.

| Command | Command duration | Retained handoff under `docs/gait-research/` |
| --- | --- | --- |
| `sit` | 5 s | `sit-bored-20260915` |
| `rest` | 5 s | `rest-20260915` |
| `wave` | 16 s | `wave-seated-20260916` |
| `dance` | 12.5 s | `dance-20260916` |
| `swim` | 23.5 s | `swim-20260916` |
| `point` | 11 s | `point-20260916` |
| `nod` | 14.5 s | `nod-20260916` |
| `pushup` | 14.5 s | `pushup-deep-20260916` |
| `bow` | 8.5 s | `bow-20260916` |
| `cute` | 13.5 s | `motion-batch-20260916/commands/cute` |
| `freaky` | 9.2 s | `motion-batch-20260916/commands/freaky` |
| `worm` | 12 s | `motion-batch-20260916/commands/worm` |
| `shake` | 7 s | `motion-batch-20260916/commands/shake` |
| `shrug` | 10.2 s | `motion-batch-20260916/commands/shrug` |
| `dead` | 7.4 s | `motion-batch-20260916/commands/dead` |
| `crab` | 30.1 s | `motion-batch-20260916/commands/crab` |
| `celebrate` | 12.5 s | `motion-batch-20260916/commands/celebrate` |
| `stretch` | 6.7 s | `motion-batch-20260916/commands/stretch` |
| `surprised` | 11.95 s | `motion-batch-20260916/commands/surprised` |
| `sad` | 8.8 s | `motion-batch-20260916/commands/sad` |
| `curious` | 9.75 s | `motion-batch-20260916/commands/curious` |

Nod preserves the former shallow Pushup. Pushup uses the separate deep revision;
Wave uses the current seated revision. Historical packages remain preserved in
the research directory and are not competing firmware inputs.

## Source ownership and timing

`catalog.json` records each original handoff, execution-contract path and retained
file hashes. The 201 per-command files, shared execution policy and independent
timing reference are byte-for-byte copies of their recorded handoffs. They include
all **30,741** original 120 Hz
samples, body/foot/contact data, configurations, schemas, independent reference
samplers and validation reports. Original CSVs, generators, face assets, previews
and Blender files remain in the handoff packages.

The model's `tools/compile_clips.py` validates source/geometry hashes, joint order,
units, native/emote envelope, source-bound contracts, uniform sampling, phase
coverage and recorded endpoint poses. It compiles all twenty-nine finite turns
and gestures into one set of flash-resident position tables. `clip.c` evaluates
the supplied monotone cubic convention with harmonic-secant tangents and zero
endpoint velocity. Each sample evaluates all twelve joints on one elapsed-time
clock. The separate bounded walk sampler retains its repeatable steady section.

Recorded command timing is preserved, including command holds. Sit and
Rest contain three seconds of lowering and two seconds of hold, then remain at
their recorded final posture indefinitely. Other gestures likewise hold their
recorded final pose after completion; they do not wrap or reset.

The batch contracts mark optional preview recovery separately from command
execution. Dead finishes at **7.4 s** and holds its flat pose indefinitely; its
12.3 s preview's standing recovery is retained in the source but excluded from
the compiled command. Freaky, Worm and Crab likewise exclude their contracts'
optional final 0.5 s preview holds (full previews: 9.7, 12.5 and 30.6 s). Their
command endpoints already hold the recorded standing poses. No firmware flag
silently enables preview recovery. Compiler checks bind semantic endpoints to
source knots, contract completion poses and phase execution roles.

The named phase
timing profiles, support events and face cues are retained source data. This
update does not implement research retiming, face playback, pulse scheduling,
current-pose entry or calibrated physical execution.

The P4 console accepts, for example, `gait sit 3000`, `gait nod 3500` and
`gait pushup 3500`. These are read-only geometric queries, without arming PWM or
emitting a physical movement receipt. Neither host location nor communication
transport appears in the model sampler.

## Readiness and verification

Every asset retains `hardware_qualified=false` and unset actuator calibration.
The P4 declares all thirty motions plus `stop`, with `motion=false`; common
admission and gateway capability checks reject movement while unready. Emergency
disable retains its separate path. Swim's required belly support, Bow's intentional
front-foot slide and the other source qualification limits remain attached to
their manifests and contracts. No electrical mapping or servo limits are inferred
from CAD geometry.

The [batch's current-model review](../../../../../../docs/MOTION_LIBRARY_12SERVO.md#current-model-and-resource-policy)
records later front-panel, camera and display changes. Its body-contact/floor
results describe the earlier geometry snapshot and have not been requalified for
those changes. Body/visor contact loading and inter-part collisions remain
unverified. Crab's approximately 1.01 mm assumed support margin and 1.58 mm final
contact slide remain provisional source findings, not physical acceptance.

The [2026-09-17 integration record](../../../../../../docs/v2-12servo/MOTION_INTEGRATION_20260917.md)
records independent C/source comparisons, command-lifecycle and dashboard checks,
the P4 build, its partition upgrade and the pending hardware flash. Numerical
agreement is not physical motion or electrical acceptance evidence.
