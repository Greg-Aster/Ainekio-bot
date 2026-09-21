# Twelve-servo motion model

The first registered V2 motion is the owner's
`vertical_limit_099p2mm_4s_loop`, from
`robot-extended-crawl-20260915/Ainekio-Part023-Continuous-Walking.blend`.
The original Blender package remains unchanged. This directory owns the retained
geometric source, twelve-joint identity, command mapping and compiled sampler.
It does not reuse V1 servo angles or change V1's eight-joint protocol/assets.

The current model contains **30 motions**: bounded forward walking, eight turns,
and twenty-one [postures and gestures](motions/gestures/README.md). Together with the
independent `stop` command, the P4 declares 31 installed names. See the
[2026-09-17 integration and pending flash record](../../../../docs/v2-12servo/MOTION_INTEGRATION_20260917.md).

## Same command, body-specific motion

MetaHuman's existing `robotCommand: walk` (and `move: forward`) still translates
to the same protocol-v1 request for either body:

```json
{"t":"intent","name":"walk","dir":"fwd","steps":3}
```

The gateway adds sequence, session epoch and expiry where negotiated. The body's
common admission path owns authentication/session/sequence/expiry; the model
selects its own trajectory. No controller hostname or transport is used by the
sampler. Changing the P4's `config controller <URL>` between a remote gateway
and a Q6A gateway requires no motion changes.

`walk` keeps its existing meaning: bounded forward walking with an optional
step count. V2 defines a step as one complete four-leg steady gait cycle. It
accepts the existing range of 1–10. A step is not a promise of measured distance.
Backward walking and held directional steering still need their own V2 mappings
and validation; they are not aliased to this forward gait.
Eight [finite turn assets](motions/turns/README.md) now have independent mappings:
left/right 15°, 45°, 90° and 180°. The six existing 45°/90°/180° names use the
same `intent/emote/asset` envelope as V1. The two new 15° names are offered only
by bodies explicitly declaring them. V1's existing seed assets remain unchanged.
`sit` uses V1's existing native sit intent; the other twenty postures and gestures
use the existing emote envelope, with their own twelve-joint sources. Turns and
gestures share one finite-clip
compiler and sampler; no turn-specific compatibility implementation remains.

The gateway retains one semantic catalog and its descriptions. Negotiated
`body_commands_v1` selects the body's registered subset, gated by motion readiness.
Body Control uses that subset for buttons, keyboard and gamepad movement.
Legacy V1 bodies retain their existing catalog. Raw V1 calibration controls are
unavailable on V2; they must not be relabeled as twelve-joint controls.

## Source and timing

- [manifest](motions/walk/manifest.json): source hashes, command mapping, sections
  and explicit qualification blockers.
- [source](motions/walk/source.json): unchanged 3,889-sample full demonstration,
  including timestamped body/foot/contact geometry and all actuator angles.
- [loop contract](motions/walk/loop-contract.json): original repetition rules.
- [geometry](geometry.json) and [joint definition](model.json): CAD zero, signs,
  physical leg identity and unassigned electrical channels.

The imported full source's 12.2–16.2 second section matches all actuator angles
in the owner's separately saved loop exactly. Retaining the full source also
preserves its entry/exit data without maintaining duplicate trajectory files.

| Section | Source time | Command behavior |
| --- | --- | --- |
| Entry | 0–12.2 s | Posture change, placement, acceleration and settling, once |
| Steady walk | 12.2–16.2 s | Repeat for `steps` cycles; 4 s and nominal 99.2 mm/cycle |
| Exit | 24.2–32.4 s | Deceleration and standing transition, once |

Total geometric command duration is **20.4 + 4 × steps seconds**: 24.4 seconds
for one step, 32.4 seconds for three, 60.4 seconds for ten. There is no standing
between steady cycles. Entry/exit also advance the model, so total command
distance is not simply `steps × 99.2 mm`. These entry/exit sections are retained research
trajectories, not qualified hardware transitions. The final standing angles
are slightly different from CAD zero; the sampler preserves them. Entering a
new command from an arbitrary/current pose is not yet implemented or qualified.

The build compiles 120 Hz knots into flash-resident tables: 1,465 entry, 481 loop
and 985 exit knots. A rational time index keeps the loop exactly four seconds.
Row 480 closes interpolation; it adds no held interval. Monotone cubic Hermite
interpolation reproduces the source curve convention. Entry/loop/exit share a
common position and tangent at their joins. Acceleration continuity is not
claimed. The shared core evaluates each segment; the V2 model owns phases and
repetition. No network message is needed for an individual frame.

The firmware sees signed CAD centidegrees, velocity in centidegrees/second and
acceleration in centidegrees/second². The original source retains radians.
Physical order is rear left, rear right, front left, front right; each leg is
shoulder (Part002), carrier (Part006), crank (Part005). The historical CAD labels
FL/FR correspond to the physical rear legs. The Part005 re-clocking is already
included in geometric zero.

## Current executable scope

Implemented: source compilation, twelve-joint sampling, bounded `walk` and finite-clip request
recognition, common admission rejection while unready, per-body capability
selection, and a read-only P4 console diagnostic:

```text
gait walk 3 16200
gait turn_left_15 7000
gait sit 3000
gait bow 2500
```

The first samples the start of the second steady walk cycle; the others sample
their named finite clips at elapsed milliseconds. These print all twelve CAD
angles/derivatives without driving PWM or emitting a movement `done` receipt.

**Physical motion execution remains unavailable.** The P4 declares all 31 installed
names with `motion=false`. The gateway does not offer these motions
to MetaHuman or enable its movement controls. A direct authenticated walk request
or finite-clip request is rejected by common admission with `busy` while boot/actuator readiness is
false. Unsupported intents consume their sequence and return `unknown`.
Emergency disable retains its independent path.

No electrical center, pulse conversion, measured travel/dynamic limits or channel
assignment has been invented. A calibrated twelve-joint actuator executor,
current-pose entry, ordinary braking/hold and operator calibration remain work
before enabling these motions. The existing output task still runs only the
bounded disconnected-servo diagnostics. Setting a manifest boolean cannot arm it.

The source itself records an assumed-COM steady support margin of **−5.885 mm**,
unqualified balance and incomplete collision evidence. Electrical OE/reset
verification, power/load checks and supported physical motion tests also remain
open. See [Step 1 evidence](../../../../docs/v2-12servo/STEP1_EVIDENCE.md).
Importing this visually accepted gait does not accept Step 1 or ground walking.

## Initial walk verification (2026-09-15)

- Portable C tests pass, including the existing shared core: 15/15 CTest tests.
- Compiled C matches all twelve source angles at 1,302 times; maximum error
  **0.00000248 degrees**. Loop repetition and phase position/velocity continuity
  also pass; no physical stability or timing measurement is implied.
- P4 and S3 ESP-IDF 5.5.4 builds pass. Neither board was flashed for this change.
  The P4 build is `0.2.0-p4-gait`, SHA-256
  `26d84aa06690bc1fb51aaec30e69841c009b6730a5c1f5bdd4e1aa384d40eb94`.
- Gateway/adapter/dashboard/action lifecycle regressions: 89/89 Python tests.
  Protocol regressions: 14/14. New tests cover per-body subsets, identical `walk`
  envelopes, unready/unsupported rejection, stop, and correlated terminal results.
- Isolated headless-browser checks: 11/11 using the actual dashboard HTML/JS
  with test body status. Covers V1/V2 switching, movement buttons, keyboard walk,
  release-to-stop and suppression of V1 calibration on V2. This is not a live
  robot/dashboard integration test.

From the repository root:

```bash
cmake -S Slave/software/models/v2-12servo -B /tmp/ainekio-v2-motions-tests
cmake --build /tmp/ainekio-v2-motions-tests -j4
/usr/bin/ctest --test-dir /tmp/ainekio-v2-motions-tests --output-on-failure
```

The [native P4 target](../../../firmware/esp32p4-wifi6/README.md) has the exact
build and flash commands. Generated C tables stay in the build directory; only
the canonical source, model and generator belong in this directory.

The subsequent [turn integration and flash record](motions/turns/README.md#verification-and-application-flash-2026-09-15)
documents `0.3.0-p4-turns`, including the actual P4 application flash, all eight
read-only turn checks and unchanged disarmed hardware status.
