# Freestyle v8 data revision

## Pending apple correction

`artifacts/spatial-v8/apple-review/` contains seven replay-checked training rows:
the owner's recorded imaginary-apple failure and six synthetic contrasts for
hand, bite count and explicit ending. The original five-step attempt completed
but lacked Stand and ended up to 27.95 degrees from the measured starting joint
positions. Its 2.5 seconds of authored actions took 4.16 seconds including host
and transport work. The correction teaches a one-hand reach, bring-to-face,
bite/withdraw phases, and a full twelve-joint Stand; explicit starting-pose or
raised-hand instructions override that ending. The original recording now has
an incorrect-outcome review and a separately identified proposed correction.

These rows are **pending the next training pass**, not included in the completed
v8 run and not deployed. Replay proves geometric reach and the requested
endpoint, not balance, shell clearance, or physical recognition. The review
also corrected replay's final interpolation sample to use the exact emitted
centidegree endpoint, avoiding numerical residue in the next IK solve. The
completed run's dataset remains frozen with its original audit provenance.

The finalized candidate finished training as a LoRA continuation of v7 in
1,553.8 seconds on 879 examples. On 2026-10-24 the owner requested production
activation: the Q8_0 export and matching final contract now serve on the desktop
GPU. Three generation-only checks (wave, stretch and left point) replayed fully
in 1.24–3.00 seconds of generation. Wave and stretch ended in exact native Stand;
the point ended near Stand with a zero-offset foot call, rather than the explicit
full pose. These are activation checks, not a held-out benchmark or physical
qualification. Current
source data and native trainer input are `artifacts/spatial-v8/final-dataset/`
and `artifacts/spatial-v8/final-qwen-data/`. These artifacts are ignored by Git.
`run-plan.json` records the training run and frozen input hashes.

## Final data

The revision prunes duplicate weighting, repeated target aliases and excessive
numeric rehearsal from v7's 4,127 weighted rows / 2,785 distinct requests. It
adds state-aware Cartesian movements and ordered two/three-task compositions
from standing, sitting, crouching and resting poses. All 12 native gait commands
remain represented. Original source-wave phases, movement range and holds remain;
its default ending now follows the owner's standing preference.

| Fold | Rows | Distinct requests | Distinct programs | Composition groups |
| --- | ---: | ---: | ---: | ---: |
| Training | 879 | 775 | 820 | 181 |
| Development | 28 | 28 | 28 | 16 |
| Test | 47 | 47 | 47 | 26 |
| Recovery probe | 28 | — | — | — |
| Historical regression | 446 | — | — | — |

The main folds share zero exact requests or normalized motion structures.
Structural grouping ignores timing and magnitude and canonicalizes left/right
reflection, while retaining operation order, limb relationships, travel
directions and repetition counts. Primitive tasks and source rehearsal stay in
training. This measures composition generalization within this revision, not
whether a pretrained model has ever encountered the underlying concept.
Sequences retain up to 91 operations; none was shortened to fit a token budget.

The new labels are agent-authored synthetic programs, not captured human
movement demonstrations. Six corrected programs use actual recorded robot
observations, requests, errors and operator feedback, but their corrected
targets are still unexecuted proposals. All labels retain explicit provenance
and physical qualification remains false. HumanML3D supplies 24 additional
frozen external requests from unused source groups, without invented target
programs or a claim that human skeleton coordinates directly transfer to this
robot.

## Endings, expressions and recorded corrections

The owner chose native **Stand** as the default gesture ending. Explicit
instructions to return to the starting pose, remain seated or leave a hand
raised override that default. Programs contain the ending themselves; no runtime
posture is forcibly appended. Native Stand is the production C gait pose at
phase zero: shoulder/carrier/crank `[0, 3.46, -21.63]` degrees on all four legs.
Calibration Home is different. `native-standing.json` preserves the native
probe evidence.

All 148 weighted source-wave rows in v7 started with zero shoulder angles.
The new ending overlay repairs 16 retained source-wave endpoints and adds 37
examples, including nonzero starting shoulders and matched explicit-ending
variants. It addresses the observed mixed final pose without removing the wave.

The model can emit `face` operations using the 59 names owned by
`Slave/software/faces/faces.def`. There are 679 training examples with face cues,
including every face individually and explicit expression requests. Cues in a
gesture are scoped to that program; normal body expression resumes afterward.
Face-only programs retain normal face-selection lifetime. Faces consume no
motion time. Expression selection in this dataset is an offline teacher choice,
not a runtime request-keyword map.

Six real attempts now have reviewed corrections in training:

- Wave preserves its generated movement and replaces the partial eight-joint
  ending with full twelve-joint Stand.
- Two clap attempts gain a standing preparation and reachable elevated
  inward/outward hand paths, retaining the original cycle durations.
- Two sawing attempts use complete fore/aft strokes, preserving their respective
  cycle counts and durations, with preparation and a standing ending.
- Stretch preserves the full 30 mm four-leg excursion and both 20 mm spread
  cycles, fixes the malformed final leg/offset arrays and ends standing.

Each correction replays from that attempt's actual initial observation, with
request history/event evidence retained. Raw failed outputs are not successful
training labels. `recorded-motion-evidence.jsonl` and its summary preserve the
six attempts, their command-associated telemetry, errors and reviews; the
original recording database remains intact.

## Replay evidence and limitations

The final current-compiler audit checked 1,005 candidates: 982 accepted and 23
rejected for compilation/replay errors from unconverged IK. Complete failed
examples remain in `final-dataset/rejected.jsonl`; target ranges were not clipped.
Training contains 776 fully replayed trajectories and 103 explicitly identified
prefix-only examples, including native gait dispatch and recovery ending at
`reassess`. Prefix evidence does not qualify an unreplayed continuation.

Checks cover endpoints, phase completion and programmed timing. At the actual
20 ms output cadence, 120 fully replayed examples exceed the former 0.15 mm
continuous-line approximation metric; their maximum measured path deviation is
1.091 mm. This approximation is reported separately from reaching each target
and completing its timing. The IK convergence threshold was not relaxed.
Kinematic replay does not prove balance, ground contact, collision clearance,
friction or successful physical recovery.

The earlier base audit checked 1,020 candidates, retaining 895 and rejecting 125;
its evidence remains separate from the final audit. Folded hands was the only
new task with no accepted base trajectory. Rejected combinations are retained
as failure evidence rather than relabeled as smaller motions. Teacher fixes
also corrected doubled figure-eight counts and reversed shuffle phase meanings.

## Recovery and held-out evaluation

The original 112 synthetic recovery rows were replaced with coherent timestamp,
quaternion/gravity and source-joint observations. Wave-jam examples start with
the arm actually extended and distinguish the blocked target from the measured
position. Slip/fall examples condition the next correction on the measured
trend of a prior attempt. They teach adaptation and reassessment, not a proven
universal get-up maneuver.

Of these reconstructed episodes, 84 enter training and 28 form a separate
sensor/pose recovery probe. Probe scenarios share action structures with training
but no exact requests; this is numerical/event generalization, not unseen-motion
or physical-recovery proof. The old 446-row numerical development fold remains
unchanged as historical regression data, separate from current replay evidence.
The 24 external HumanML3D requests remain outside training.

## Export, validation and cleanup

All five native folds preserve source targets, IDs and provenance; `labelOrigin`
is separate from the shared trainer's `targetAuthor=assistant` response-role
field. The pinned tokenizer processed every row without truncation:

| Fold | Maximum total tokens | Maximum response tokens |
| --- | ---: | ---: |
| Training | 6,731 | 3,940 |
| Development | 5,546 | 2,775 |
| Test | 6,062 | 3,301 |
| Recovery probe | 3,387 | 97 |
| Historical regression | 3,900 | 798 |

`final-qwen-data/all-fold-token-report.json` records all 1,428 examples. The
shared trainer manifest and configuration validate. Fifteen focused offline
tests pass across `test_curriculum`, `test_face_contract` and
`test_reviewed_curriculum`; native export checks also verify all folds against
their source targets and metadata.

The continuation retains v7's rank 16, alpha 32, learning rate 8e-5 and three
epochs, using parent `artifacts/spatial-v7/qwen-fit` and base
`unsloth/Qwen3.5-0.8B` at revision
`23c69c53358a07516b5827588b3fdb12ae78fd65`. Training uses
`/home/greggles/metahuman/venv/bin/python`, which contains Unsloth. Offline
SciPy/tokenizer work used `/home/greggles/ComfyUI/venv/bin/python`; that environment
is not the training environment. The generic exporter has a different initial
learning-rate default; the frozen final configuration contains 8e-5.

After final export verification, cleanup removed 30,288,640 bytes of superseded
draft caches, obsolete native exports, preflight files and completed progress
logs. `cleanup.json` lists exactly what was removed. Active v7, adapters, final
inputs, structured rejection evidence, source snapshots and all real recordings
were preserved. Training run status belongs to `run-plan.json`; evaluation and
physical trials remain necessary before claiming improved robot behavior.

## Pending next-pass corrections

The frozen v8 inputs and adapter remain unchanged. The separate
`artifacts/spatial-v8/apple-review/` contains seven earlier proposed apple-mime
rows. `artifacts/spatial-v8/pending-motion-review/` now adds thirteen reviewed
proposals: five actual recorded requests (bread selection, sigh, hip wiggle and
two right-hand raises), plus eight meaningful handedness, repetition-count and
explicit-ending contrasts. These additions are pending another training pass;
they are not part of the completed v8 training run.

The bread teacher surveys two imaginary choices before reaching, miming a gentle
grasp and lifting. It assumes no fingers or gripper. The sigh keeps the original
0.8/0.6/0.8-second inhale/hold/exhale, lowering the torso and attached shoulders
below their preparatory height before settling. The hip wiggle uses alternating
20 mm lateral body excursions instead of diagonal-foot shuffling. Hand raises
use a visible elevated front-foot target and retain the original one-second
outward travel. Nine proposals finish with all twelve native Stand targets;
four explicitly request that the hand remain raised and preserve that ending.

All thirteen pass complete replay, independent Cartesian phase-target/timing
checks and their specified ending checks. Maximum endpoint error is 0.0154 mm;
final standing-joint error is zero. They contain thirteen distinct queries and
eleven distinct programs; neither query nor normalized motion structure overlaps
v8 development/test folds. Five focused tests verify choosing/lifting phases,
wiggle excursion/count semantics, reviewed handedness/explicit endings and
telemetry association across reused epoch/sequence identifiers. Both recorded
hand requests say exactly "Raise your right hand."; left-hand requests in this
overlay are explicitly synthetic contrasts. The five original requests specify
no repetition count or raised final pose; the hip-wiggle request explicitly
asks to settle standing. Reviewed side/ending/count choices are stored in each
recorded proposal rather than inherited silently from teacher defaults.

These labels are agent interpretations of the requested semantics, not inferred
operator judgments or demonstrated physical successes. The five recorded rows
preserve the actual initial observations, requests and original program IDs.
The separate evidence snapshot contains 539 records and associates raw telemetry
only within each operation's wall-clock and monotonic packet interval. This
avoids mixing packets when gateway restarts reuse epoch/sequence counters.

Recent execution timing must be fixed at its owning layer rather than encoded
as shorter gestures. The latest reviewed stretch transmitted exactly 2.8 seconds
of frames but consumed 7.348 seconds across operations: 1.069 seconds before
dispatch, 4.385 seconds dispatch-to-receipt including the travel, and 1.894
seconds obtaining/completing subsequent observations. Hip wiggle transmitted
3.4 seconds but consumed 5.964 seconds. Those measurements do not establish
physical trajectory duration or recognition. The pending teachers preserve
corresponding authored travel durations and do not train around transport delays.

`pending_motion_review.py` builds only this offline proposal set. It is never
imported by serving code and introduces no runtime request-keyword routing.

### October 24 recorded requests

The Body Control and inference recording databases contain no October 24
00:00–12:00 America/Los_Angeles requests at this review point. The new records
are from 14:31–14:36 PDT; earlier apple/bread/wiggle/hand requests occurred on
October 23 evening PDT. This time distinction is preserved rather than treating
UTC dates as local morning activity.

`artifacts/spatial-v8/oct24-motion-review/` adds two proposed corrections from
those new actual observations, separate from the previous thirteen-row overlay:

- `d468768b64e04d44bb21d721443e9bab`, "stretch": seven operations completed,
  then the arm return failed IK (1.37293 mm residual). The new teacher prepares
  Stand, retains the 30 mm front lift, two 20 mm forward stretches, both holds
  and every 0.6-second phase (4.8 seconds total), and finishes full Stand.
- `0c679e2d9560457c8fa0811ad95ce737`, "stretch": six operations reported
  completion, but the program lifted all four legs and returned only the front
  pair. The proposal retains the full 30 mm lift and both 20 mm spread cycles,
  restores all four legs and finishes full Stand. Spatial/hold timing remains
  2.8 seconds; measured original operation wall time was 4.621 seconds.

Both proposals pass complete phase/endpoint/timing replay with no overlap with
v8 development/test queries or normalized motion structures. They remain
unexecuted proposals. No operator review labels were present for these trials.

The third new job, `81cd66f2d9694a18a5529553f9c3fe65`, requested recovery from
a rapid-movement event while measured tilt was only 1.94 degrees and yaw rate
was high. It generated a large relative joint pose and repeated rotations before
being superseded. This is retained as reviewed, unlabeled evidence: the event's
cause and an effective physical recovery are unknown, so no successful recovery
target is invented. The new snapshot includes all three jobs with bounded
packet association. Frozen v8 data, its adapter and the seven apple proposals
remain unchanged; all twenty-two pending rows await a subsequent training pass.

## Q6A audience-wave correction and live-test protocol, 2026-10-25

The canonical evidence batch is on DNDIY at
`artifacts/spatial-v8/pending-motion-review/q6a-20261025-audience-wave/`.
It retains the original request/output, candidate revisions, recording snapshots,
offline replay, three live correction trials and explicit operator assessments.

The Cartesian revision failed live IK. The first joint-reference revision
completed in 11.45 seconds; the owner found the sequence good but too slow and
reported a sitting ending. A subsequent rear-right crank stall released outputs.
The faster revision completed in 6.56 seconds with all eight motion receipts.
The owner explicitly approved that last command as excellent. Its exact program
and actual starting observations are the single approved training addition
`93605debe36c7b1a`, trial `ab07f9ee990e46be8a23bdd79252ae91`.
DNDIY's existing pending `train.jsonl` now contains 14 rows. The frozen v8 run
and held-out folds remain unchanged; no training run was started.

New corrections remain `awaiting_physical_trial` and are excluded from the
training export. Replay the program offline, use **Test selected correction**,
observe the physical motion and ending, then save the operator's outcome.
Only a completed trial explicitly reviewed as successful becomes a physically
qualified positive row. Earlier failures and source correction IDs remain linked.
Recovery-first stall behavior is a separate firmware/executor repair, not a
training label inferred from these trials.

## Next dataset with the 14 reviewed examples, 2026-10-25

On DNDIY, `artifacts/spatial-v9-compact/next-reviewed/dataset/` contains the
879 existing balanced compact examples plus all 14 rows from
`artifacts/spatial-v8/pending-motion-review/train.jsonl`: 893 training rows.
Use `artifacts/spatial-v9-compact/next-reviewed/qwen-data/` for the next trainer
input, including its `train.jsonl`, `evaluation.jsonl`, `manifest.json` and
`training-config.json`. Paths are relative to `experiments/freestyle/` in
`/home/greggles/Ainekio` on DNDIY.

`next-reviewed/preparation-result.json` maps all 14 source IDs to compact IDs.
Their decoded motion targets and physical-qualification labels are preserved;
only the approved audience wave is marked physically qualified. Existing 879
examples and held-out files are retained. Exact tokenization fits 3,412 tokens
without truncation. This dataset is prepared for the next run; preparation did
not start training or activate a model.
