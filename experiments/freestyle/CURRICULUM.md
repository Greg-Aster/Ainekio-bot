# Freestyle data and training revisions

The working custom-movement curriculum excludes output-release supervision.
The 92 examples containing a release target were retired through the editable
library owner and removed as complete records from the maintained snapshot;
unrelated examples and evaluation files are unchanged. Inactivity rest/release
belongs to the body, and failed-correction release belongs to Body Control.
Archived datasets and weights below retain their historical contracts; no new
adapter is implied by this curriculum change.

## Finite motion and event recovery, October 27

The production candidate and activation evidence are in
`artifacts/finite-event-repair/`. The owner requested activation of the latest
trained candidate with known misses retained for further learning. The model
uses the maintained finite-command contract; target arrival does not generate
another model request. Real stall/feedback-fault/tip events retain event recovery.

The final continuation used 339 rows, including 116 new synthetic contrasts for
lying down then releasing, already lying down, immediate release, hold then
release, and remaining powered. These 116 rows were originally added to the editable library
and snapshot; the current curriculum excludes their release-target records.
Inputs recompute servo-error/orientation fields using
the generator's existing enrichment. Native lay-down geometry supplies the
13 target poses. These are authored targets, not physical recovery labels.

Comparison: 40/62 exact/equivalent references, including 24/34 shared cases
(previous candidate 20/34) and 16/28 fresh contrast cases. Both owner-reviewed
hand examples remained exact. The recorded idle event completed all 13 targets
then released in one model call against an idealized shaft plant. Jam and tip
requests also completed finite corrections; the already-resting case repeated
the path unnecessarily. Keep-powered requests and some wave counts remain weak.
No physical recovery success is claimed. Unapproved stretch/sprinkler proposals
remain only in the saved correction-trial records.


## Complete programs and standing endings, October 26

The current curriculum removes internal continuation triggers. Ordinary requests
and real body fault events receive complete target/speed programs. Former
continuation endpoints are explicit normal standing poses. The training snapshot
and editable library remove synthetic rows whose only input was that retired
trigger; actual stall/fall examples retain their event attribution. Partial
Stand-prefix generators are replaced by complete ordered native target programs,
including the final standing target. Runtime does not append hidden motions.

The following training runs are historical, with their original frozen inputs.
They must not be treated as the current curriculum or as evidence that the revised
contract has been trained. Current training remains unlaunched; updated target
labels have no new physical qualification.

## Wave target and recovery repair, October 26

`artifacts/wave-tracking-repair/` freezes the 17:03 failed Wave and its recovery
requests. The first whole-body target requested rear-right carrier -28.76°;
the existing firmware fitter applied -23.22° and changed its coupled crank,
while output completion still compared against the original target. Native
before/after replay isolates that mismatch. Subsequent shoulder recovery moved
farther into the measured tracking error and repeatedly received stale pending
actions. The firmware now shares one resolved goal between ramping and arrival,
reports adjusted-target masks, and the host keeps pending actions owned by the
replacement program. Stall thresholds and saved calibration are unchanged.

The corrective dataset removes 44 conflicting old wave labels and contains
404 training and 139 evaluation rows. New teaching examples use compiled
spatial foot lifts, complete sweeps and Stand returns, plus signed tracking
corrections across all twelve joints and measured-completion contrasts.
Recorded observations are retained with provenance; corrected outcomes are
authored and **not physically qualified**. Eight left/right/count combinations
compile inside the recorded feedback domain and return to nominal Stand.
That is a measurement-domain/geometry check, not proof of mechanical clearance.
The dataset manifest preserves every pruned label ID and its review reason.
Production status remains the model/service assignment documented in README;
training loss alone does not authorize a deployment claim.

## Recovery completion, October 26

`artifacts/recovery-completion/` retains the periodic-twitch incident, reviewed
completion labels, synthetic paired contrasts, training, and offline executor
replays. The first focused continuation improved the 36-case next-step comparison
from 13 to 30 matches, but failed all three untrained continuations from the
recorded long loop. It was not deployed. These three requests are from the same
incident, not three independent physical trials.

The continuation in `balanced/` uses the same 286 examples: 110 new/reviewed
cases and 176 rehearsal examples covering every parent motion family. Its
36 development cases use different tolerances, errors and orientations.
Completed recovery is `[]`; pending gestures retain their remaining operations,
and newly disturbed shafts require a correction. Physical qualification remains
separate from synthetic geometry and recorded endpoint evidence.

The experiment's existing continuation trainer supports `loss_weighting=example`
with one-example microbatches. This uses each example's mean response loss and
the installed Trainer's normal accumulation scaling. Token-normalized batches
underweight a 3-token completion relative to a 294-token continuing wave.
The gradient comparison is tested against the installed Trainer; the shared
MetaHuman trainer is unchanged. Frozen manifests record the selected objective,
adapter ancestry, observation transform and complete untruncated input sizes.

The balanced candidate passed all three recorded completion replays and 35/36
recovery contrasts, but the broader regression check found altered wave targets
and endings. It was also withheld from production. `final/` retains the next
329-row pass, including reviewed motion regressions and additional examples
from those existing motion families. Its 71-case development fold excludes the
one reviewed recovery miss and adds 36 fresh tolerance/noise combinations.
The reviewed motion cases remain regression checks, not unseen-motion claims.

The final export was activated on DNDIY after 71/71 held-out recovery cases,
13/13 reviewed motion regressions and 3/3 recorded no-repeat executor replays
passed. The production generation-only replay also returned an empty program.
This does not qualify physical recovery or the remaining old-sequence failure;
deployment evidence and exact limitations are in `final/release-review.json`
and `final/activation/` under the artifact directory above.

The following v8 sections describe the earlier revision and its evidence.

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

## Measured target control and adaptive recovery, 2026-10-25

The target-control candidate is `artifacts/spatial-v10-targets/library-20261025-audit/`.
All 889 active examples converted to targets and speed; explicit holds retain
their durations. There are 24 new synthetic wave-adaptation training examples and
16 disjoint probes. Expressions vary across angry, confused and sad, followed by
a wave expression. Both front shoulders, obstruction directions, and standing or
raised-foot endings are represented. A retreat and reduced sweep remain inside
the observed obstruction. These examples are not physically qualified.

The new dataset contains 913 training, 28 evaluation, 47 test, 44 recovery-probe
and 355 older regression examples. Another 91 old regression cases have unresolved
IK conversion errors recorded in the manifest; none is an active training row.
The discard ledger is retained. Regenerate from the current library after edits;
do not restore superseded snapshots. `migrate_targets.py` builds the dataset and
adds the recovery curriculum reproducibly.

The editor now stores and exports the compact input/target directly. Its former
expanded representation and expanded canonical export were removed. The separate
one-time `migrate_library_storage.py` representation migration reproduces the
previous 889-row training JSONL hash exactly:
`bc9eedb2002c30ae6e7d30aa004128d9e22cecf3a41da72eec684aa07a268064`.
That storage migration alone does not change movement semantics or model weights.

Recovery projection keeps current joints and IMU, event facts, requested goal,
interrupted action and unfinished program. It omits repeated sensor histories
and packet buffers; full evidence stays in the recorder. The recorded recovery
used 4,975 prompt tokens, 278 output tokens and 90.869 seconds. A generation-only
replay with the compact input used 1,004 prompt tokens, 110 output tokens and
17.346 seconds on the existing Q6A model, with zero cached prompt tokens. Output
length changed too, so the timing difference is not solely input savings. This
is not a benchmark of the new, not-yet-trained target model.

Target firmware uses `motion_targets_v1`, `control: targets`, and speed in
centidegrees/second. Shaft arrival advances targets; elapsed time controls the
rate only. Jam observations remain nonterminal and replacement remains available.
The direct V2 Environment Bridge accepts `speedDegS` and no longer estimates
progress from elapsed frame durations. V1 body semantics remain separate.
The existing native Stand and balance owners remain in place. Spatial endpoints
are solved by IK; interpolation between them is joint-space, so this migration
does not claim to preserve straight Cartesian paths or physical qualification.

Host validation passed all 61 native tests; updated target wire fixtures and
focused Python/UI checks also passed. Firmware cross-build, model training,
serving validation and physical qualification are separate rollout steps.

The final refinement dataset is `artifacts/spatial-v10-targets/library-20261025-compact-speeds/`.
Speeds use the shortest decimal that produces exactly the same integer wire rate
at the recorded reference speed. This removes redundant digits from 8,184
training movement calls without changing their encoded speed. The final 913-row
training JSONL SHA256 is
`a94a275122a34ab86045660b8fb974b9fe1962c7a58c45f7bcd29385a1fdbd3c`.
Mean assistant targets are 322.6 tokens (previous library: 332.7); the current
four-cycle wiggle is 464 target tokens (previously 663). Maximum complete
sequence length is 3,453, without truncation. These are tokenizer measurements,
not inference timings or physical-motion results.

The first target-contract continuation completed three epochs with held-out
loss 0.59746 → 0.11163. A final two-epoch continuation at 8e-5 trains the shorter
speed values. Its final weights still require serialized-serving validation.

## Local feedback-conditioned Stand continuation, October 25

`artifacts/stand-feedback-v1/final-dataset/` is a separate local candidate,
continuing the verified local `spatial-v8/qwen-fit` adapter. The historical
Q6A/v10 notes above are retained; their artifact directory is not present on
this workstation. The live local v8 service was inspected and still uses the
older duration-based JSON contract. It has not been replaced by this candidate.

The candidate contains 1,270 training rows, 28 original development rows,
47 original test rows, 355 comparable older regression rows, 28 recovery probes,
40 Stand development contrasts and 159 Stand test contrasts. Every retained
answer validates against the current speed-only serving schema. Exact input
queries do not overlap training and held-out folds. Stand folds hold out native
ordering/observation episodes, not unseen motion primitives or unseen hardware.

`stand_geometry.c` links the production posture/contact solver and recorded
installed calibration. Fourteen level acquisition cases from nominal Stand and
5/10/15mm below it preserve the requested 8mm lift (minimum reconstructed
clearance 7.989mm). All 238 quantized acquisition targets pass native FK and
installed travel without fitting. Forty-six other acquisition cases remain
excluded with reasons: invalid 25mm-low starts, tilted-plane clearance deficits,
or nonzero target fitting. Eight additional native leveling contrasts teach
attitude-dependent correction. These results do not establish swept-path
clearance, carpet contact, successful recovery or floor-to-Stand capability.
The separate `mapped-sweep/` audit additionally checks 21 quantized interpolation
samples on each of 56 airborne placement segments across the accepted cases.
All 1,176 samples pass native FK and installed travel; minimum modeled clearance
is 7.984404mm. Native stage support flags are used and audited endpoints exactly
match the frozen teacher. This adds sampled placement-path evidence, not a
continuous-path, loaded-dynamics or physical contact guarantee.

Labels emit explicit poses plus reassessment, with no native Stand shortcut.
They contrast lagged and arrived shafts, loss of a lifted position, high versus
settled posture and gyro tilt. Histories retain accumulated prior action/effect
pairs and the bridge's `correction_delta_deg` fields. Fresh requests have no
pretend active command and commanded angles equal measured starting angles;
the proposed target never appears as a preexisting command. Sixty reviewed
default gesture endings hand off to learned Stand acquisition while preserving
gesture phases and explicit holds. Explicit endings remain unchanged.

Legacy spatial travel is converted to 50% speed when unspecified; explicit
travel durations become equivalent nominal joint rates. Holds retain seconds.
Four ambiguous slow-motion proposals remain review-only. Ninety-one old
regression references with IK conversion failures are listed individually in
the manifest rather than counted as valid targets. The full idle lie-down
sequence remains unlabelled because its resting endpoint is not validated;
explicit release, hold-then-release and keep-engaged contrasts are included.
Face remains operation9 and the new release operation is appended afterward.

`final-qwen-data/` contains the native trainer export of all 1,927 rows, with
no truncation. The longest complete example is 19,418 tokens. The run uses
rank16/alpha32, learning rate8e-5, three epochs, batch1/accumulation8, existing
Unsloth gradient checkpointing and one retained checkpoint. The corrected run
is `ainekio-freestyle-train-stand-v1-fixed.service`; its script restores the two
previously active general model services when it exits. An initialization
stopped before optimizer progress is retained as evidence of the corrected
initial-observation leak. No candidate is deployed or physically qualified.

Evaluation includes target compilation plus native FK/travel checks, matched
full-history reference prefixes, and self-fed idealized shaft rollouts. The
earlier 68-case short-history baseline is supplementary only. Per-generation
latency is insufficient: a complete learned acquisition can require about
20 inference rounds. Small-angle perturbations check the gap between nearly
exact teacher arrival and the robot's broader saved arrival tolerance. Any
finite rollout budget belongs only to this offline test, never robot runtime.

A late audit found seven zero-distance placement contrasts where synthetic
lagged and arrived measurements were identical. The frozen run retained four
incorrect reissue labels in training and three in the Stand test fold. Separate
corrected advancement references and their original IDs are saved under
`identical-state-corrections/`; frozen-label agreement cannot qualify those
cases. Four Wave-ending begin examples also used a fresh-request event despite
completed same-job Wave context. The offline builder now fixes both issues.
Its separate 569-row parity revision additionally carries complete Wave
before/after pairs, full wire motion commands, and commanded angles reconstructed
from integer PWM. These rows have not changed the running training input.
Actual generated lower-start behavior decides whether a short correction and
rehearsal continuation is needed. The active compact MotionLibrary editor and
canonical SQLite contents have not been overwritten by this expanded-JSON
experiment.

### Stand correction continuation

The first Stand adapter completed three epochs: evaluation loss decreased from
0.352766 to 0.083291 in 4,168 seconds. It is not ready for deployment: all seven
corrected placement probes reissued an already-reached target, and all four
self-fed nominal/lower-start trials exhausted their offline 24-round budget.
The nominal case used 26.23 seconds of inference while repeating effectively
the same pose. Loss and schema validity did not establish progress or completion.
Its frozen adapter, export hashes and failure traces remain in `stand-feedback-v1/`;
the failed Q8 file was removed after confirming it was unused.

`stand-feedback-correction/final-dataset/` is the separate correction candidate:
1,677 training rows, 174 Stand development rows and 580 Stand test rows, plus
the preserved 28 general development, 47 test, 28 recovery and 355 regression
rows. All 1,531 feedback rows pass current target compilation and native
measured-pose/target FK and installed-travel checks. This includes corrected
wire/PWM histories, noncontradictory progress labels, 0.1-degree near-arrival
contrasts, and short nominal-start high→nominal→finish histories. A fresh
nominal Stand request still performs the requested rise/settle; completed-goal
history teaches termination. Five actual failed offline contexts receive
proposed corrections. Three sampled off-path lower15 contexts remain unresolved:
their supplied-angle native paths failed the requested clearance qualification.

The new splayed starts exercise inward foot placement. Crank3200/4800 cases
provide training, while the entire crank4041 variant stays held out. Within
episode lift→place XY displacement is respectively 6.2185, 15.5889 and
11.1629mm. Separate 21-sample native sweeps found minimum modeled clearance
7.91769, 7.50294 and 7.75156mm: these paths stay above the modeled floor but
do not maintain 8mm throughout. Earlier near-Stand sweep cases had almost zero
horizontal reposition and cannot establish inward-step performance. No dataset
row claims physical clearance, carpet contact, loaded stability or successful
recovery. Noise magnitudes 0.25 and 1 degree remain held out.

The corrective run uses the first Stand adapter as parent, one epoch at 8e-5,
rank16/alpha32 and batch1/accumulation8. All 2,889 exported examples are measured
without truncation; the largest is 19,867 tokens. The one-epoch run completed
in 2,332 seconds; held-out general loss changed from 0.083291 to 0.077164,
with peak Torch allocation 5,190,434,304 bytes. Both approved general model
services were restored. Its adapter/export hashes remain; after the October 26
native/Q8 parity check, the unused failed Q8 file was removed. Temporary
merge/F16 files were removed by the exporter.

The first three corrected self-fed tests still failed completion within their
24-round offline trial budgets. Nominal start now produces high→nominal, then
repeats nominal instead of finishing. Lower15 and held-out crank4041 both jump
directly high, skipping stepping acquisition; lower15 finishes the trial about
8 degrees from nominal. Terminal nominal angles therefore cannot qualify the
splayed trial. These failures block production qualification despite lower loss.
On October 26, three direct saved-adapter checks (lower15 entry, held-out
crank4041 entry, and a training short-settled context) produced exactly the same
programs as Q8 inference. All three made the wrong next decision. This isolates
these failures to learned behavior rather than an export-only discrepancy;
the outputs and hashes are retained in `stand-feedback-correction/parity-review.json`.
The isolated candidate server was stopped after the check. An original-contract
v8 comparison is separate; production remains unchanged and no physical success
is claimed.

`state-diversity-review.json` records the remaining distribution weakness:
the 11 entry examples expose only six distinct measured starting joint vectors,
all level, while 659 rows teach lagged/arrived/near-arrived intermediate decisions.
There are only four short-settle examples. The model sees shaft angles, PWM,
attitude and action/effect history; Cartesian positions and native phase metadata
are not included in its prompt. This is evidence for balancing varied entry and
completion states, not yet evidence that model capacity or LoRA is the limit.

### Balanced Stand continuation, 2026-10-26

`stand-entry-balanced/dataset/` retains all 900 general-motion rehearsal rows
unchanged and replaces the intermediate-heavy feedback sampling with 361 rows:
86 entry, 117 intermediate, 54 settling, 97 completion and 7 attitude decisions.
Forty distinct synthetic starting geometries contribute fresh-Stand and
completed-Wave contexts. Selected contrasts cover every leg's lift/place/lower
phases; the complete qualified lower15 episode remains. Completed short and
full histories, small shaft-reading perturbations, and three actual nominal-loop
contexts teach ending the operation after the requested rise and settle.

All 361 feedback rows pass native measured-pose/target FK and installed-travel
checks. Reference swept-clearance evidence is retained separately; these are
not physical success labels. Reserved crank angles from -42 through -39 degrees,
the existing evaluation folds and 0.25/1-degree noise trials remain held out.
Twelve focused curriculum/evaluation tests pass. The trainer export contains
2,473 total examples across folds with a 19,866-token maximum and no truncation.

The continuation uses the corrected adapter as parent, two epochs at 8e-5,
rank16/alpha32 and batch1/accumulation8. Its run plan records weights, data and
configuration hashes. Production remains v8 while this candidate is trained and
assessed. Model quality requires generated trajectories and completion evidence;
the training loss is not a motion-success score.

The two-epoch run completed in 2,869.73 seconds. General evaluation loss changed
from 0.077164 to 0.069928; peak Torch allocation was 5,653,916,160 bytes. The
first-epoch checkpoint failed all three self-fed trials, despite learning one
previously failed short-completion probe. The final checkpoint completes the
already-standing high→nominal→finish trial in three responses. Lower15 instead
ends after four responses with a 53.51-degree maximum nominal-joint error, and
held-out crank4041 repeats an off-target pose throughout the 24-round offline
trial. Only the already-standing trial demonstrates the requested geometric
goal; none establishes physical behavior.

The final candidate matches 15/34 sampled known training decisions. Arrival
transitions match 0/5 (target errors 0.8–25.48 degrees); entry decisions match
1/10. High→nominal and terminal completion examples improve, so lower loss and
a learned ending alone do not establish acquisition. The model remains outside
production. Production v8 is unchanged, and both paused general LLM services
were restored after training.

A read-only data audit found no remaining duplicate-input contradictions, but
three older rehearsal examples bypassed the handoff migration: two used the
existing explicit `stand` ending policy, and one reviewed lift lacked an ending
annotation. The migration now accepts `stand` and `default_stand` while preserving
explicit numeric, return-to-start and keep-raised overrides. Separate reviewed
corrections and originals are in `stand-entry-balanced/ending-review/`; they were
found after this run began and are **not learned by this checkpoint**. Frozen
training data and exports were not changed. Fifteen focused tests pass.

The old correction Q8 and first-epoch Q8 were deleted only after verifying their
hashes and absence of open handles, reclaiming 1,623,686,336 bytes. Their adapters,
data and failed outputs remain, along with active v8 and the final candidate Q8.

The broader comparison attempted the same 148 requests on v8 and the final
candidate. V8 completed 147 outputs and the candidate 146; one v8 and two
candidate requests were manually cancelled while still generating long compound
programs. On the 145 mutually completed cases, reference-program matches improve
from 26 to 59. Target translation/compilation failures decrease from 26 to 12.
These counts are not physical success rates, and unmatched reference programs
can include valid alternatives. One completed candidate output also expands a
58-call reference into 476 calls and takes 90.59 seconds. The failed acquisition
trials and compound-generation failures still prevent deployment.

`stand-entry-balanced/final-review.json` records the full decision, hashes,
data corrections not yet trained, cleanup and runtime state. Temporary candidate
servers and training/evaluation processes have stopped; production remains v8.
The next data work is entry/reached-target advancement and the three reviewed
ending corrections. No noise-robustness or physical-recovery success is claimed.

### Owner-requested production activation, 2026-10-26

After reviewing those results, the owner explicitly directed deployment of the
trained model. The existing DNDIY Freestyle model and generator units now select
`stand-entry-balanced/served/model.Q8_0.gguf` and its matching `dataset/` contract.
The prior evaluation above remains unchanged historical evidence; activation is
not a claim that the failed tests passed. Both services are enabled and active.
Live API identity matched the exported Q8 hash, and a generation-only nominal
Stand request returned `pose` then `reassess` in 0.663 seconds. No robot commands
or firmware flash were issued. Inference recording remains enabled. Verification
and the prior service configurations are retained in
`stand-entry-balanced/activation/`; remote Q6A services were not modified.

### Stretch physical review and generic-target cleanup, 2026-10-27

The owner observed successful supported execution of correction trial
`bcc1a78011ed48b58a4f5c8a030035a8`; all nine movement receipts reported verified
positions, with no adjusted targets. The left crank Home mapping was corrected
to -117.68 degrees at 2750 us. The trial also required a left-crank extension
target of 84.82 degrees versus 64.63 degrees on the right. That asymmetric
compensation is physical evidence, **not the generic training stretch**. The
owner explicitly requires geometry-space motions independent of individual
servo calibration. A replacement training target remains pending verification
of matching physical calibration references. No retraining or model activation
was performed in this cleanup.

Retired four obsolete `calibrated_stretch_entry` examples from the editable
library. Removed the older `proposed_recorded_stretch_correction` and its two
unverified synthetic recovery derivatives from the maintained snapshot. Their
IDs and parent aliases are retired in both stores to prevent re-import. The
library now has 335 examples and the maintained snapshot has 2,515; these were
already different datasets, so this cleanup did not overwrite either with the
other. Unrelated examples, the owner-confirmed both-hands example, frozen
evaluation files, and original robot evidence remain unchanged. The manifest
records the exact retired IDs and the successful physical trial.

The pre-cleanup audit found no PWM pulse commands in either output dataset.
Forty-one snapshot rows and three library rows use Home-relative targets for
requests explicitly concerning Home. Those references are resolved at runtime;
they are not replaced with per-device pulses. Matching physical model angles,
per-servo direction, offset and scale remain calibration responsibilities.
Calibration does not establish that every generated multi-joint path is
physically reachable. Starting from a sagged released pose remains unqualified:
one trial was rejected before execution, and the successful full trial began
after positioning through the existing calibration controls.
