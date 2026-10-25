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
running dataset remains frozen with its original audit provenance.

The finalized candidate is training as a LoRA continuation of v7. Production
continues serving v7; the candidate has not been evaluated or deployed. Current
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

## Counterbalanced foot-lift correction, 2026-10-25

The owner observed the compact model's happy and surprised foot lifts. Both
faces and small movements worked after a robot power cycle, but the owner
reported insufficient visible lift, slow movement and disturbed balance. Those
programs are now partial outcomes rather than fully satisfactory training labels.

The reviewed correction uses the previously approved wave's rear-crouch and
Stand targets, with a 25 mm front-left foot lift/lower at 0.35 seconds each and
a 0.2-second hold. It is an authored teaching correction, not a new model output.
Trial `59e571979b1d4f6bbb8dd22913a1919c` completed in 2.745 seconds including
execution/feedback overhead (1.35 seconds in replay from its actual start).
The owner confirmed: "Good balance, lift, speed, and ending". This is visual
operator qualification, not measured center-of-mass or millimeter accuracy.

Approved row `f2e44c4751fbb2cc` is the fifteenth pending reviewed example.
Its evidence batch is DNDIY's
`artifacts/spatial-v8/pending-motion-review/q6a-20261025-counterbalanced-lift/`.
The Q6A copy is `build/gateway/physical/reviews/counterbalanced-lift-20261025/`.
Failed attempts, partial outcomes and the approved correction remain separate.

The next training input is now
`artifacts/spatial-v9-compact/next-reviewed-counterbalanced/qwen-data/` on DNDIY:
894 training rows (879 balanced-face rows plus 15 reviewed additions).

All examples start with a face; all 15 added programs round-trip unchanged.
Held-out files are unchanged, with no exact-query or motion-structure overlap
for the new correction. The 3,412-token maximum requires no truncation.
This prepares the correction for training; it has not been trained into the
candidate or production model. The previous 893-row preparation is preserved.

## Owner-approved fast rear sway, 2026-10-25

The request `wiggle your butt` is now paired with the owner-approved correction:
happy face, Stand, two rapid sideways rear sways about the front shoulder
midpoint, then Stand. It uses generated body translation/yaw segments with
durations 0.16/0.32/0.16 seconds per cycle. No request-to-motion lookup was added.

The final physical trial `39894b0c9f794cdba6f3404d3709f469` took 2.543 seconds and
received eight completion receipts. The owner approved it with “good enough!
lets save it for the training data.” Review `92552132662a43148ec294213f5215f9`
exports canonical training row `2eb4726c09394346`, family
`reviewed_fast_rear_sway`, with operator-reported physical qualification.
The failed pitch response and the two slower corrected trials remain separate
evidence. The training row includes the original observation and exact approved
program; measured endpoint errors remain evidence, not a claim of precise tracking.

The Q6A evidence is in `build/gateway/physical/reviews/rear-sway-20261025/`.
DNDIY's canonical pending dataset now contains 16 rows, including three approved
physical examples. The next compact preparation is
`artifacts/spatial-v9-compact/next-reviewed-fast-wiggle/`: 895 training rows
(879 balanced-face rows plus 16 pending additions). Canonical/compact targets
round-trip exactly, and held-out files remain unchanged. No training was launched;
the active 879-example compact model has not learned this correction yet.

The prepared fast-wiggle example contains 1,224 tokens, including 397 response
tokens, under the native training tokenizer. This is a dataset measurement, not
a fresh inference benchmark. The full preparation still fits 3,412 tokens with
no truncation; `next-reviewed-fast-wiggle/preparation-result.json` records the checks.

## Current targets only: library merge, 2026-10-25

The owner explicitly discarded failed and superseded refinements for all motions.
The working library and training exports now retain only current targets. Saving
an edit replaces its older versions; discarded example IDs and their source IDs
are retained as exclusion records so re-importing an older dataset cannot restore
them. Old original-program metadata is removed from the working rows and exports.

Six obsolete targets were removed: three earlier hip-wiggle proposals/contrasts,
both small open-ended hand lifts, and the original clap target that was replaced
by the elevated-hand correction. The hand-lift and clap matches were checked
against the recorded originals and their corresponding refined requests. A
sideways wiping program also matched the original incorrect *sawing* response,
but remains a distinct wiping example; it is not an obsolete sawing label.
Eight other repaired examples retain their accepted correction; their ancestor
targets were not present. No identical complete-input duplicate rows were found.

`wiggle your butt`, example `00b7c60fb57221bf`, retains only library revision 5:
one happy face, initial Stand, twelve body segments (four cycles), and final
Stand. Each cycle uses 0.071111/0.142222/0.071111 seconds. This latest saved edit
has no new recorded physical trial and does not inherit an older trial's
physical-success label. Older edit targets were discarded.

The desktop's next trainer input is
`artifacts/spatial-v9-compact/next-library-current-20261025/qwen-data/` under
`/home/greggles/Ainekio/experiments/freestyle/`. It contains **889 current training
examples**; the canonical pending subset contains 13. Older untrained
`next-reviewed*` and `next-library-reviewed-20261025` train files are discarded
and marked retired. Their hashes/receipts remain for provenance. The frozen
inputs used to produce deployed models remain unchanged, outside the working
library. Diagnostic recordings are not positive training labels.

Export verification checks exact target preservation and source identities.
The current library remains the editable source; export it again after further
edits. No training was launched and the deployed model was not changed. Raw
observations, local databases and model weights remain outside Git. The private
snapshot, discard list and merge receipt are under
`build/gateway/physical/reviews/training-merge-20261025/` on Q6A.

Current-only snapshot SHA256:
`ad07456ff512fd2f41675d5a0df76ef7a1698c0c880977cc4bfe1455b4bd3237`.

The verified export includes 889 training and 28 evaluation examples. Maximum
sequence length is 3,412 tokens, with zero truncation. Compact training JSONL
SHA256: `bc9eedb2002c30ae6e7d30aa004128d9e22cecf3a41da72eec684aa07a268064`.
