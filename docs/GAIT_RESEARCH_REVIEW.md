# Ainekio 12-servo gait research: first findings and next experiment

15 September 2026 • Offline research using the supplied geometry • No hardware commands generated

**Recommendation:** develop a slow crawl with deliberate body shifts as the first walking candidate; use the original OpenHarmony Puppy and Stanford Pupper as references for a later trot. Adapt their contact schedules, foot paths, and body-motion ideas through Ainekio's own linkage IK. Select the final parameters through measurement and P4 trials.

The working objective is repeatable, stable walking on level ground, followed by improvements in speed and energy use. A geometric model can identify reachable motion and estimate joint speeds. It cannot establish an optimal physical gait without actuator, mass, contact, and hardware measurements.

## What the existing robots contribute

| Reference | Verified useful material | How to apply it here |
|---|---|---|
| [OpenHarmony Puppy developer account](https://www.cnblogs.com/openharmony/p/16740454.html) | The designer describes a 12-DOF robot with parallel four-bar legs, single-leg FK/IK, cycloidal foot trajectories, trot, and body-pose control. | Closest mechanical ancestry. Compare trajectory shape and contact timing. Its original dimensions and motor angles are not parameters for the modified legs. |
| [Spot Micro gait configuration](https://github.com/mike4192/spotMicro/blob/2a34f5d303dff91b62180031b31ef512a672f3c3/spot_micro_motion_cmd/config/spot_micro_motion_cmd.yaml) and [walking implementation](https://github.com/mike4192/spotMicro/blob/2a34f5d303dff91b62180031b31ef512a672f3c3/spot_micro_motion_cmd/src/smfsm/spot_micro_walk.cpp) | An eight-phase walk with four body shifts and four individual leg swings; an alternative four-phase diagonal trot. | Best concrete starting reference for the crawl's phase structure. Calculate body shifts from this robot's COM and contacts, replacing the example's fixed offsets. |
| [Stanford Pupper gait configuration](https://github.com/stanfordroboticsclub/StanfordQuadruped/blob/dc0c5e2089cf2c0aac3c59982a4f140c31803175/pupper/Config.py), [scheduler](https://github.com/stanfordroboticsclub/StanfordQuadruped/blob/dc0c5e2089cf2c0aac3c59982a4f140c31803175/src/Gaits.py), [stance controller](https://github.com/stanfordroboticsclub/StanfordQuadruped/blob/dc0c5e2089cf2c0aac3c59982a4f140c31803175/src/StanceController.py), and [swing controller](https://github.com/stanfordroboticsclub/StanfordQuadruped/blob/dc0c5e2089cf2c0aac3c59982a4f140c31803175/src/SwingLegController.py) | Separate contact scheduling, stance motion, swing motion, and velocity/yaw-dependent placement. The inspected configuration alternates diagonal swing pairs with all-feet overlap. | Reuse the separation of responsibilities and placement ideas. Supply our own FK/IK, dimensions, calibration, and timing. |
| [MangDang Mini Pupper adaptation](https://github.com/mangdangroboticsclub/StanfordQuadruped/blob/05717e5019a082c33bc901c25fb111223566211b/README.md) | A Stanford Pupper adaptation supporting Mini Pupper 1 and 2; the inspected swing controller retains the same basic implementation. | Useful example of adapting the controller family to another robot. It is related evidence, not an independent gait algorithm. |

The original Puppy source is linked by its developer on Gitee, but its actual gait code was not accessible during this research. The source-level comparisons above therefore come from the accessible Stanford, MangDang, and Spot Micro code. Spot Micro's README targets an older ROS Kinetic/Ubuntu 16.04 environment; use its algorithms as a reference, rather than importing that runtime into the P4 project. The inspected LICENSE files in these three GitHub repositories identify MIT licensing; retain applicable notices if copying code.

The Stanford/MangDang swing implementation uses a triangular height profile. It demonstrates a working controller structure, but that profile has vertical-velocity changes at its corners. Our comparison also includes a smooth polynomial profile and a cycloidal profile. The cycloidal comparison is an independently implemented mathematical candidate, not a recovered copy of Puppy's inaccessible code.

## What the supplied files establish

The analysis uses `robot-gait-parameters.json` and `gait_kinematics.py` unchanged. Input SHA-256 hashes are recorded in `research_results.json`.

| Item | Consequence for gait design |
|---|---|
| FL coupler ≈40 mm; FR/RL/RR ≈24.64 mm | The supplied snapshot has mixed geometry. Confirm whether this describes the intended physical robot. If all four legs will use the new linkage, export a complete updated model and repeat the analysis. |
| Shoulder `h`, upper carrier `alpha`, and four-bar crank `theta` are the actuators | A generic serial hip/knee IK is insufficient. The passive lower-leg angle follows the four-bar closure. |
| Angles are offsets from CAD neutral | They are not servo electrical-center angles or PWM values. |
| FL's re-clocking is already represented in its neutral geometry | Do not add the reported 46.46° correction again. |
| Only FL individual planar sweeps have recorded range evidence | This does not prove a collision-free combined workspace or limits for the other legs. |
| The default endpoint is the foot attachment bolt | Bolt lift is not guaranteed sole clearance. Actual ground contact needs the foot shape and pose. |
| Body datum is a coordinate origin, not measured COM | Balance calculations must use the assembled robot's mass distribution. |
| FL/FR/RL/RR are literal CAD labels | Confirm physical front and motion signs before mapping user-facing forward/backward commands. |

The shoulder socket's greater-than-180° clearance does not require a large shoulder sweep for ordinary walking. It does require bounded, continuous physical-angle handling. The supplied IK normalizes angles into a principal interval and sorts candidates by wrapped distance. Before actuator use, choose equivalent angles within measured limits, preserve the assembly branch, and reject discontinuities. The research wrapper follows nearby angle representatives but has no measured mechanical limits to apply.

## Numerical checks and initial candidates

The reference FK/IK passed 400 deterministic round trips across all four legs, sampling each actuator within ±15° of neutral. This checks internal consistency; it is not an independent validation against CAD meshes or hardware.

Fourteen isolated leg-cycle variants were evaluated, with 800 samples per leg per variant: **44,800 target evaluations**. Every sampled target had a geometric solution. The profiles move the foot bolt along body X with its lateral coordinate fixed; their shoulder angle therefore remains zero. Separate body-shift probes below exercise all three actuators together.

For the nine main comparisons, each leg cycle lasts 4 seconds and spends 85% of its time in stance. The listed advance is the **world distance between consecutive placements of the same foot**; the stance sweep relative to the body is 85% of that distance. These are benchmarks for leg motion, not completed four-leg walking programs.

| World advance | Bolt lift | Highest joint speed across all legs |
|---:|---:|---:|
| 10 mm | 5 mm | 47.9°/s |
| 10 mm | 10 mm | 72.1°/s |
| 10 mm | 15 mm | 95.7°/s |
| 20 mm | 5 mm | 77.0°/s |
| 20 mm | 10 mm | 94.5°/s |
| 20 mm | 15 mm | 114.1°/s |
| 30 mm | 5 mm | 108.9°/s |
| 30 mm | 10 mm | 124.9°/s |
| 30 mm | 15 mm | 140.4°/s |

**The 10 mm advance / 5 mm bolt-lift profile is a useful first small-motion benchmark.** It is not yet an approved ground gait: body shifts, sole clearance, calibration, combined collisions, load, and transitions remain to be incorporated.

The 20 mm / 10 mm polynomial benchmark requires approximately:

| Actuator | FL | FR/RL/RR |
|---|---:|---:|
| Shoulder `h` | 0° | 0° |
| Upper carrier `alpha` | −9.82° to +12.27° | Approximately the same |
| Four-bar crank `theta` | −11.72° to +7.68° | Approximately −8.59° to +5.22° |

That difference is a concrete reason to generate angles per leg. Near neutral, the calculated ratio of passive lower-leg rotation to crank rotation is about 0.699 for FL and 0.997 for the other three. A common angle table would produce different foot motion.

Additional comparisons for the 20 mm / 10 mm benchmark:

| Change | Peak joint speed | Interpretation |
|---|---:|---|
| Baseline: polynomial, 4 s, 85% stance | 94.5°/s | Peak estimated joint acceleration ≈817°/s². |
| Cycloidal comparison | 91.5°/s | Peak estimated acceleration ≈722°/s²; its vertical acceleration changes at contact boundaries. |
| Lower body by 5 mm | 94.7°/s | Reachable in this probe; no claim of lower torque or better stability. |
| Lower body by 10 mm | 96.5°/s | Reachable in this probe; actual contact and collisions remain untested. |
| Halve cycle to 2 s | 189.0°/s | Speed doubles; acceleration approximately quadruples. |
| Increase stance fraction to 90%, keep 4 s | 144.7°/s | More contact time leaves less time to swing. |

The polynomial profile has continuous position, velocity, and acceleration across the modeled stance/swing joins. This smoothness does not make it automatically optimal in motor space; the cycloidal candidate illustrates the trade-off. No speed in these tables is asserted to be acceptable for the installed servos under load. Numerical derivatives are estimates from the stated sampling resolution.

## Why body shifts need to be part of the solution

For a slow, approximately static gait on level ground, use the horizontal COM projection and the polygon of supporting contacts as a first balance test. Dynamic motion additionally depends on acceleration, angular momentum, and contact forces; the static test cannot qualify a trot. [MIT's treatment of contact forces and center of pressure](https://underactuated.mit.edu/humanoids.html) explains that distinction.

The neutral bolt positions are approximately X = −39 mm on the CAD FL/FR pair and +73 mm on RL/RR, with Y = ±63.7 mm. They are not longitudinally centered on the body datum.

**Illustrative assumptions only:** project the bolt positions onto a horizontal contact plane and place COM at the body datum. This produces:

| Lifted leg | Signed margin to remaining triangle | Example body translation for at least 10 mm margin |
|---|---:|---|
| FL | −12.83 mm: outside | X +17.13 mm, Y −15.09 mm |
| FR | −12.79 mm: outside | X +17.09 mm, Y +15.07 mm |
| RL | +12.79 mm: inside | None in this neutral illustration |
| RR | +12.83 mm: inside | None in this neutral illustration |

The shifts are the nearest points in an inset triangle under those assumptions. They are not calibrated walking offsets. As feet advance, recompute the polygon and the required body motion. Neither three feet down nor an arbitrary lateral sway guarantees stability.

Both example shifts were also sampled while keeping all four world bolt positions fixed and moving the body over 1 second. All sampled poses were geometrically reachable. The larger shoulder excursion was about 12.34°; the FL crank reached about 24.83° in one shift. Thus body motion can require substantially more actuator travel than the isolated foot loop. The shifts and the subsequent swing have **not** yet been checked as one combined trajectory.

Measure mass and COM for the intended battery and electronics arrangement. Treat Q6A installed and Q6A absent as separate payload configurations; also account for COM changes as legs move. Actual sole contacts may differ from the bolt projections used here.

## The next research experiment

1. **Reconcile the physical geometry.** Confirm the final four couplers, shoulder axes, physical front, and pad/contact geometry. Re-export all four legs if the current mixed snapshot is transitional.
2. **Use the available hardware to measure the missing parameters.** Record per-servo direction, neutral pulse, usable bounded travel, and loaded motion response. Measure assembled mass/COM and observe the sole's actual contact behavior. These measurements can proceed while the P4 foundation work continues.
3. **Build one complete crawl cycle offline.** Alternate all-feet body-shift phases with individual leg swings, following the Spot Micro structure. Start the search with small 10–20 mm advances and 5–10 mm nominal lift; resolve actual sole clearance. Explore leg order, body height, stance placement, shift amplitude/timing, and duty fraction together.
4. **Evaluate the whole cycle and its transitions.** Keep stance contacts fixed in world coordinates. Include start, stop, cycle wrap, direction reversal, COM margin throughout each phase, joint limits and derivatives, linkage branch, and mesh collisions. Do not independently clamp individual servo angles: reject or regenerate an infeasible path.
5. **Generate a P4 test artifact from the surviving candidate.** Use our IK to produce a timed 12-actuator trajectory, tagged with geometry/calibration versions, leg order, units, and profile parameters. Run a supported single-leg trial, body-shift trial, then short assembled crawl trials. Measure displacement, slip, body roll/pitch, supply current if instrumentation is available, and loaded tracking. Refit timing and geometry from these results.
6. **Compare trot after the crawl is repeatable.** Use the Puppy/Stanford diagonal-pair pattern as a second family. Evaluate it under the installed actuator and payload constraints; static support margin alone will not establish its stability.

Judge candidates first by feasibility and repeatability, then by useful speed, slip, body disturbance, and measured energy/current. Preserve several candidates if they trade these objectives differently. A slow successful crawl is a foundation for comparison, not proof that crawl is the most efficient gait at every speed.

## Adapting the previous movement catalog

Keep the old command meanings as the future compatibility target. Rebuild locomotion commands through the validated gait; rebuild stand/sit/bow and similar postures through body/foot targets; retarget gesture choreography through the new leg model. For third-party movements, prefer task-space paths or contact schedules. If only angle tables exist, reconstruct the donor's pose/foot path with its geometry before retargeting; simple rescaling of angle values is not enough.

The resulting Ainekio angles may be compiled into movement tables for deterministic P4 playback. Online IK can be added or retained if the executor supports it. Either way, the source of truth should retain the foot/body trajectory and geometry version so tables can be regenerated when the mechanism changes. Reuse the timing and intent of an old gesture only after its contacts and transitions work on this robot.

The remote computer and optional Q6A should request the same high-level motions. Their location does not change the leg mathematics; the P4 retains body execution and command-admission rules. Installing the Q6A does change the payload used for gait tuning.

## Reproduce these findings

The accompanying archive contains the unchanged input files, `research_gait.py`, `research_results.json`, `candidate_comparison.csv`, and `gait_research.png`. Run `python3 research_gait.py` in the extracted directory with NumPy and Matplotlib installed. The script has no robot connection and emits no PWM or servo-command table.

The current analysis omits a full four-leg cycle with sway, mesh collision detection, actual ground-contact geometry, mass/inertial dynamics, friction, electrical calibration, and measured actuator limits. It is a reproducible first screening of geometry, not a hardware-ready gait or an optimization certificate.
