# Experimental V2 Freestyle

A dataset, standalone generator, and shared Body Control executor for a
request-driven, twelve-joint motion model. Freestyle owns semantic motion
requests from Body Control and MetaHuman. Body Control's manual selector also
offers the retained legacy library; that selection does not change MetaHuman,
startup, recovery, or inactivity requests. An unavailable generator is reported
as unavailable, without substituting a legacy motion. The generator itself has
no robot transport; execution uses the existing gateway and P4 target owner.

The Freestyle observation includes each joint's live `feedback_range_deg`,
`arrival_tolerance_deg`, `feedback_usable` and `feedback_faults`. The existing
saved servo mapping converts feedback calibration pulses into signed model
degrees, including inversion. The range describes where shaft arrival can be
observed; it is not a mechanical limit and does not clamp generated commands.
Missing calibration remains unknown. `servo_feedback_fault` uses the same
opt-in recovery and command ownership as jams and slips: inference can run
while the previous command is pending, and a generated correction replaces it
through the existing target executor. Stop/Release still cancels recovery.
Feedback-health transitions are independent of reaction faces and motion-event
cooldowns; repeated identical health samples are not new events.

A generated program runs once. The P4 receives movement targets and speeds,
uses fourth-wire feedback to establish shaft arrival, and returns the correlated
receipts. Program completion does not invoke the model again. Actual stall,
feedback-fault, tipping and slip events retain the existing event-triggered
Freestyle recovery path. A correction remains a generated movement, not a claim
that the body recovered physically.

The owner removed the model-requested continuation operation on October 26.
Its executor loop, tool/schema entry, prompt directives and maintained training
labels are removed. Affected training programs now finish with explicit normal
standing targets through the same measured-target executor. Existing explicit
endings without that operation remain unchanged. Stand geometry is represented
by target poses; there is no new posture shortcut or response filter.

`training-data/` is the maintained snapshot for subsequent training. The editable
Body Control library uses the same revised contract. Completed training runs and
running qualification artifacts retain their historical inputs and model hashes;
they are evidence, not the current curriculum. Existing weights require retraining
to change learned behavior. The revised serving contract is staged at
`artifacts/finite-programs/contract`; activation and physical qualification must
be reported separately from source and model-free tests.

The 84 focused executor and training-source tests pass. Serving qualification is
separate: deletion-only contract replays completed in 0.17 seconds (hand raise),
1.42 seconds (wave), and 2.93 seconds (stretch), and all compiled. None ended at
the requested normal standing targets. These were generation-only tests, not
physical trials. The changed executor/contract remain unactivated; the current
weights need corrected-ending training and qualification. An earlier diagnostic inadvertently reordered the two
last tool definitions and produced repeated output; the staged contract restores
the production order and preserves every remaining definition. Eight legacy
duration-format failures in the broader training suite also reproduce with the
pre-removal source. No output truncation or substitute motion was added.

The October 26 periodic-twitch incident is retained under
`artifacts/recovery-completion/`: one recovery repeatedly emitted a standing
pose and `reassess` despite successful target receipts. That run used paired
completion and disturbed-target examples for its former continuation contract.
Recorded requests and synthetic examples are labeled separately. The initial
calibration-aware candidate also reproduced the loop and was not activated.

The October 26 startup review and calibration-aware candidate are under
`artifacts/feedback-calibration-repair/`. The recorded 30 mm front lift requested
about 463 µs at the front-right carrier, outside the documented feedback sample
domain. The owner powered the unloaded robot off; the resulting disconnect is
not evidence of a Wi-Fi failure. Replacement stretch labels retain excursions,
holds and a feedback-confirmed high/nominal ending. Separate fault examples vary
joint, direction and calibration domain. Offline replay feeds an unverifiable
target back as a feedback fault instead of crediting a completed sequence.
These checks do not establish loaded stability, contact, or physical recovery.

The target/speed source contract and firmware 0.8.127 move boot/wake Stand and
inactivity rest to Freestyle. The model generates joint/foot/body targets and
does not invoke a native Stand or stored gesture shortcut. The shared P4 executor verifies measured shaft
arrival, and the model receives shaft positions and IMU attitude. Generated
`release` explicitly releases outputs through the existing Stop/Release owner.
The P4 gait executor remains shared. These source changes require coordinated
model, host, and firmware activation; the deployment records below describe
older installed contracts, not proof that this update is active.

`stand_curriculum.py` exports the existing native posture geometry using the
installed servo mapping, then prepares feedback-conditioned Stand labels:
lift/place/lower targets, a slightly higher Stand target, nominal settle,
lag/slip contrasts, and gyro leveling. Targets with clipped travel or lost
clearance are excluded. These are geometric teacher examples, not physical
success recordings. Shaft positions and attitude estimate sole clearance;
the robot has no measured foot-contact signal. Training and held-out replay
must precede deployment and supported physical verification.

The same native exporter accepts `--splayed` to audit synthetic spread-foot
starts under the installed mapping. Unlike vertical offsets that preserve foot
anchors, these cases require inward foot repositioning. Its placement sweep
samples the actual joint interpolation and reports the minimum modeled sole
clearance; an 8 mm endpoint lift is not a promise of constant clearance between
endpoints. These fixtures are not calibrated Home or recorded physical poses.
`--from-angles` audits an unintended generated posture through that same solver:
after the mapping rows, stdin supplies twelve model angles in degrees and
roll/pitch/yaw in radians (yaw zero for this local fixture exporter). Rejected
paths remain failure evidence rather than becoming shortened training targets.

Repository synchronization on 2026-10-25 combines the Q6A target-control
compiler and recovery work with DNDIY updates. Running model weights and
host-specific service configuration are separate from this source merge.
Offline challenge replay now uses the shared target compiler. Reviewed
duration-based labels are migrated offline by `speed_curriculum.py`; deliberate
holds retain their durations. The training export carries its matching tool
contract, rather than relying on the currently served model's older contract.

DNDIY production deployment, 2026-10-26:

At the owner's explicit request, the existing production services now use the
**recovery-completion/final Qwen3.5-0.8B LoRA, exported as Q8_0**, with its matching
target-and-speed contract, GPU inference and reasoning disabled. The model is
`artifacts/recovery-completion/final/served/model.Q8_0.gguf`; the contract is
`artifacts/recovery-completion/final/dataset/`. The model SHA256 is
`a8a9b7e2da6f40f1597e43ac7af46e82a779a5973bd5bf679248c7b75bf94943`.
Both existing services are active and enabled. Body Control retains its configured
`http://127.0.0.1:8794` endpoint; inference recording remains enabled.

The final two-epoch continuation used 329 examples after calibration and
completion training. It passes 71/71 held-out completion/pending-work cases,
13/13 reviewed motion regressions and three full recorded loop continuations
through the executor with a fake body. Reviewed regressions are not unseen
motion claims. The live production API also returned `[]` for a recorded
completed recovery in 1.25 seconds, with zero physical test motions. Body
Control was restarted to load operation-scoped receipts. Verification and
retirement of unused test exports are in
`artifacts/recovery-completion/final/activation/`; the previous production
weights remain available for rollback. The paused language-model services
were restored. Remote Q6A deployment was not changed.

This qualifies the recorded periodic-twitch failure, not universal recovery.
One old interrupted-sequence calibration-recovery replay still fails native
target validation; another reviewed fault replay ends near the high Stand
target rather than exact nominal settling. Those limits and the lack of
physical loaded/unloaded validation are recorded in
`artifacts/recovery-completion/final/release-review.json`.

Body Control records commands and received motion telemetry automatically while
the experiment is installed. The standalone API also records requests and model
outputs, including errors and cancellations, for either caller. Production
v7 activation was checked with a live-observation **generation-only** foot-lift,
hold and return request (0.605 seconds for this one request, zero motion commands),
a visible panel check, and persistence of an explicitly nonphysical review.

Q6A deployment notes recorded before synchronization:

The Q6A currently serves the balanced spatial-v9 compact model locally through
llama.cpp on port 8795 and the generator API on port 8794. The live editor exposes
the exact compact training input and target. Saving edits changes the working
training dataset; it does not change the running weights.

The target-and-speed model and firmware are being built from
`fix/measured-target-recovery`. Until that coordinated rollout completes, the
installed model and compiler retain their existing `motion-arrays-v1` contract.
Compact recovery-input projection is already compatible with that model.

## Editable training motion library

Body Control → **Poses and emotes → View training data** opens the Q6A's working
training library. It searches titles, requests and families, and fetches 25
summaries per page. First/Previous/Next/Last navigation appears above and below
the list. Sort by name, date added to this library, or last edited, in either
direction. Unedited examples follow edited examples in last-edited sorting.
Selecting an example loads the exact training input text and compact assistant-target
JSON. These are the stored/exported values, not an expanded command editor.
Both input and target are editable; the title is library metadata. The existing base gesture buttons remain
available above the expanded library.

**Save training example** updates the canonical working dataset in
`build/gateway/physical/motion-library.sqlite` (beside dashboard authentication
state if the data directory is overridden). Saves are transactional, replace superseded versions, and report conflicting
edits without overwriting the current target. Previous edit targets are discarded.
Explicitly retired examples retain only their IDs/reasons so importing an older
dataset cannot restore them. Failed original-program metadata is excluded from
training exports. This policy applies to every refined motion.
Editing the input changes its actual training context. Edited targets do not inherit
an older target's physical-success label or trajectory claims. Viewing and saving
require no connected robot and make no inference or motion request.

**Send motion to robot** decodes the editor's compact target only at the existing
execution boundary and submits it through `Bridge.submit(program=...)`, including
unsaved changes. It uses fresh
robot observations and the existing asynchronous compiler/executor. It does not
call the LLM or save the draft. Job progress appears in the editor through the
existing dashboard status updates; browser closure does not cancel execution.
The existing Stop and replacement-command behavior still applies.

**Export training data** downloads a consistent ZIP snapshot with the exact stored
`dataset/train.jsonl`, suitable for `prepare_compact.py`. The expanded canonical
export and expanded editor were removed.
The held-out files and tools travel with the export; saved edits are represented
in the training targets and source hashes. Training input preparation must use a
fresh library export, rather than an older `next-reviewed-*` snapshot. Exporting
or saving does not train or activate a model.

### Training data in Git

`experiments/freestyle/training-data/` contains the committed motion-library
snapshot: exact compact training examples, held-out splits, tool/wire contracts,
and a manifest with file hashes and retired example IDs. These text files travel
with the repository. The working SQLite database remains local; saving in Body
Control does not automatically update the committed snapshot.

After editing the library, refresh the snapshot from the repository root before
committing and pushing:

```bash
.venv/bin/python - <<'PY'
import io
from pathlib import Path
import zipfile
from experiments.freestyle.motion_library import MotionLibrary

library = MotionLibrary('build/gateway/physical/motion-library.sqlite')
destination = Path('experiments/freestyle/training-data')
destination.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(io.BytesIO(library.export())) as archive:
    for name in archive.namelist():
        (destination / Path(name).name).write_bytes(archive.read(name))
PY
git diff --stat -- experiments/freestyle/training-data
git add experiments/freestyle/training-data
git commit -m "Update motion library training data"
git push origin HEAD:dev
```

On another checkout, pass `experiments/freestyle/training-data` directly as
`prepare_compact.py --source` with the existing trainer/base/revision arguments.
This preserves the complete training split, including linked recovery examples.
The existing `motion_library import` command is a merge operation: it preserves
local edits and deduplicates shared parent IDs. It is not an exact restore of this
snapshot (the initial 2,506-row snapshot imports as 913 editor examples), so do
not re-export through it to prepare training data. Model weights and runtime
recordings remain outside Git.

The target-control migration is prepared in
`artifacts/spatial-v10-targets/library-20261025-compact-speeds/`. It converts all 889 active
examples, adds 24 synthetic multi-step wave adaptations (913 training rows), and
adds 16 separate recovery probes. The new examples are not physically qualified.
Movement targets use `speed_pct`; only explicit `hold` calls have durations.
The candidate's target arrays use `motion-targets-v1`. Target packets use
`control: "targets"` with `[speed_centidegrees_per_second, twelve_joint_targets]`.
The P4 ramps toward targets at that speed and advances on fresh shaft arrival.
Missing feedback or a jam never fabricates arrival or disables outputs; the goal
remains replaceable while the normal event/command tasks keep running.

Recovery input keeps the requested goal, current state, interrupted action and
compact unfinished plan. It does not copy full programs, packet buffers, old
sensor streams or repeated events. There is no one-action output restriction.
The full evidence remains in the recorder. New training and serving share
`compact_wire.model_query` for the same input projection.

That historical migration used an explicit native `stand` operation. The current
Freestyle contract above instead generates complete posture-target programs;
it cannot invoke that removed shortcut. Balance remains owned by the existing
configured body controller. The model, gateway contract and
P4 firmware must be deployed together; a `motion_plan_v2` advertisement alone
does not mean the body understands speed targets (`motion_targets_v1`).

The target model and firmware are staged for coordinated deployment after training and validation.
The old weights are not a trained target-control model. A separate older
regression split has 91 unresolved IK conversion cases recorded in the manifest;
none belongs to the 889 active training examples, and none was added to training.

The 2026-10-25 version-5 library export is merged on DNDIY in
`artifacts/spatial-v9-compact/next-library-current-20261025/qwen-data/`: 889 rows,
including the faster four-cycle wiggle. Six superseded targets and old edit
versions were discarded at the owner's request. See `CURRICULUM.md` for the merge receipt
and hashes. Later edits still require a fresh export before the next training run.

This installation was seeded with the 895 examples from the reviewed fast-wiggle
preparation. The current library has 889 examples after removing six superseded
targets, and uses the faster four-cycle wiggle (version 5). Deployed model weights
and the frozen inputs that produced them remain unchanged. Import only a dataset's training split; held-out examples
are retained for export, not offered as library commands. Future batches can be
added without overwriting existing library edits:

```bash
.venv/bin/python -m experiments.freestyle.motion_library import \
  --database build/gateway/physical/motion-library.sqlite --dataset /path/to/dataset
.venv/bin/python -m experiments.freestyle.motion_library export \
  --database build/gateway/physical/motion-library.sqlite --output /path/to/new-snapshot.zip
```

The authenticated API is `GET /api/motion-library?page=1&search=wiggle`,
`GET /api/motion-library?id=EXAMPLE_ID`, and `GET /api/motion-library/export`.
Listing also accepts `sort=name_asc|name_desc|added_asc|added_desc|edited_asc|edited_desc`.
CSRF-protected `POST /api/motion-library` accepts `operation: "save"` with
`id, revision, title, query, answers`, or `operation: "run"` with `id, robot_id`.
Run optionally accepts `query, answers` for an unsaved trial; omitted fields
use the saved example. Playback evidence records the example ID, revision and
draft status. Dataset I/O stays on HTTP worker threads, outside the motion loop.

## Historical workstation production and reviewed motion evidence

On 2026-10-24, the workstation units `ainekio-freestyle-model.service` and
`ainekio-freestyle-api.service` pointed to the following v8 deployment, superseded
by the owner-requested activation above:

- Model: `artifacts/spatial-v8/final-served/model.Q8_0.gguf`
- Model SHA256: `06435179aa494db8311fce73d74e5bae8fffb9eb53e8e17c9c0646173f78a6da`
- Contract: `artifacts/spatial-v8/final-dataset/`
- Standalone generator: `http://127.0.0.1:8794`; llama.cpp: port 8795.

V8 was activated at the owner's request on 2026-10-24. Generation-only checks
for wave, stretch and left pointing all replayed fully (1.24–3.00 seconds to
generate), with face cues. Wave and stretch ended in exact Stand; pointing ended
near Stand without an explicit final full-pose command. This small check is not
a held-out benchmark or physical qualification. Evidence is in
`artifacts/production/v8-activation-generations.json`; the 22 later reviewed
corrections remain pending a subsequent training pass. Export intermediates
were removed automatically; the prior v7 artifact remains available.

These unit files contain this workstation's Python and llama.cpp paths. Their
model server retains two inference slots, uses the GGUF's native context capacity
(`--ctx-size 0 --fit off --kv-unified`), and enables the installed llama.cpp
build's demand-allocated CUDA KV memory (`LLAMA_CUDA_DYNAMIC_KV=1`). The current
model advertises 262,144 context tokens; the unified pool lets either slot use
that capacity without a fixed half-context partition. This is a shared finite
capacity, not unlimited memory. Full request histories are preserved. No
output-token or elapsed-time cutoff was added. The
standalone service generates programs; Body Control retains robot execution.
Ordinary pose buttons retain their existing owners. Freestyle appears under
**Poses and emotes**; its default endpoint works without an initial settings
submission. Explicit recovery settings persist across Body Control restarts.

The previous 8,192-token per-slot configuration rejected recorded recovery
requests containing 21,683 and 25,676 prompt tokens. Replaying both unchanged,
concurrently, against the native-context configuration completed in 4.29 seconds
total with schema-valid programs and no truncation. The test server used
1,956 MiB GPU memory afterward. These are inference/transport checks, not physical
recovery qualification. Local evidence is
`artifacts/production/native-context-replay.json`. The 23 generator/program tests
also pass, including concurrent request admission and cancellation propagation.

The owner enabled automatic event recovery for `ainekio-p4-e6ebe5` on
2026-10-23. Its existing jam detector is enabled (3,000 ms without the configured
position progress); tip and rapid-movement event reporting are also enabled at
the existing settings. Incoming `servo_stall`, `tipped`, `rapid_movement`, or
caller-supplied `slip` events request a generated correction with fresh servo/IMU
observations and the interrupted program, action and packet progress. Manual
replacement commands retain ownership. This verifies event routing, not physical
recovery competence. A compilation error is recorded as a failed job; it does
not itself trigger another generation. There is no dedicated slip detector.

Recovery-first firmware (`0.8.120`) sends these jam observations with
`outputs_released:false`. The current motion and powered hold continue while
the model generates a correction. Recovery claims the existing executor only
when its program is available and reads fresh joint positions before dispatch.
Manual replacement/Stop cancels pending recovery. A model failure does not
release outputs or abandon current execution. A newer event retains earlier
event evidence while replacing its pending inference; no timeout or retry-count
policy is imposed on model decisions. Genuine driver faults and explicit Stop
retain their existing physical authority. The feedback panel reads the installed
jam policy rather than assuming every firmware uses recovery-first reporting.


Spatial compilation now schedules intermediate targets at the P4's 20 ms output
cadence. Previously, 8–9 ms frames each consumed a full output tick and stretched
recorded 700 ms strokes to roughly 1.5–2 seconds on the wire. Offline tick replay
of those strokes now preserves 700 ms; compilation and transport still add host
latency. Requested endpoints, cycles and holds remain in the program.

The optional executor supports generated `face` actions through the existing
face owner. A program-scoped selection stays visible across its motion packets
and releases only its own token on completion or interruption. The bridge creates
that protocol token independently of caller request IDs, which remain unchanged
for correlation. Face receipts do
not delay movement. Face-only requests keep the ordinary visible selection.
Interrupted actions remain recovery context; a new event-driven recovery plan
owns its remaining program. Body target-adjustment receipts remain in operation
history alongside measured endpoints, so applied execution is distinguishable
from attainment of an original authored pose. Normal standing differs from
calibration Home and all-zero Neutral.

Recordings live in the ignored Body Control runtime directory, alongside its
existing configuration, not in tracked training data:

- `build/gateway/physical/freestyle-recordings.sqlite`: Freestyle requests,
  initial/per-operation observations, generated programs and model identity,
  operations, receipts, errors, operator reviews, and gateway motion events.
- `build/gateway/physical/freestyle-inference.sqlite`: standalone requests,
  generated outputs, incomplete/error evidence and cancellations. The returned
  `inference_id` links a Body Control generation to this evidence.
- `build/gateway/physical/freestyle-settings.json`: per-robot endpoint and
  explicitly selected recovery setting.

The recorder uses a dedicated writer thread, compressed payloads, SQLite WAL
and wall/monotonic timestamps. It never submits motion or polls the robot.
Received IMU/status/servo-health events are captured during tracked motion;
Freestyle also retains before/after servo-position observations. This is not a
continuous twelve-servo trace or proof that every intermediate target was reached.
Command sequence, robot, epoch, job ID and timestamps accompany records. Epochs
restart with the gateway; correlate sequences within a job's time interval.
Recording failures are visible in dashboard status and logs and do not stop the
robot. No automatic deletion/retention policy is imposed; monitor store size.

Use **Save motion review** to record correct/partial/incorrect outcomes and a
plain-language account of the observed failure. Raw failed attempts remain in
the database. `/api/freestyle` operation `review` additionally accepts an
explicit `corrected_program`, `corrected_request`, and `generation_index` for
reviewed corrections. A written description alone is not a corrected target.
Reviews and proposed corrected programs do not themselves run on the robot.

### Corrected-motion test protocol

New corrected programs remain `awaiting_physical_trial` in the existing review
record and are excluded by the training export. First replay the complete
program offline: check geometry, requested side, repetitions, authored timing
and ending. Keep the original request, observations, program and correction ID.

In Body Control's Freestyle panel, use **Load saved corrections**, select the
correction, then **Test selected correction**. This runs the exact saved program
through the existing executor with fresh observations; it does not regenerate
the movement. The ordinary Stop and command replacement owners still apply.
Receipts, feedback, faults and timing remain in the existing recording database.
The model server is not needed to test a saved correction.

Watch the physical trial. Save **Performed correctly** only after observing the
intended movement, timing, repetitions and ending. Record **Partly correct** or
**Incorrect movement** with what differed when another correction is needed.
Inspect the ending after the final receipt: a later output release, reported
stall, or loss of the requested posture is part of the trial result.
Completion receipts alone do not approve a training target. Only a completed
trial with an explicit successful operator review is exported as a physically
qualified positive example; its source correction IDs remain attached.

Keep candidate programs and trial evidence on DNDIY under the existing
`experiments/freestyle/artifacts/spatial-v8/pending-motion-review/` tree. The
Q6A audience-wave batch is `q6a-20261025-audience-wave/`; its `candidates.jsonl`
is staged evidence, not an addition to `train.jsonl`. Copy consistent SQLite
backups including committed WAL data and verify transfer checksums. After the
live trial and operator assessment, export the approved trial to the pending
training set there. Preserve failed attempts; do not rewrite the frozen v8 run.

Export evidence or proposed training rows to a new output file:

```sh
python3 -m experiments.freestyle.recordings export \
  --database build/gateway/physical/freestyle-recordings.sqlite \
  --output /tmp/freestyle-evidence.jsonl
python3 -m experiments.freestyle.recordings corrections \
  --database build/gateway/physical/freestyle-recordings.sqlite \
  --output /tmp/freestyle-reviewed-corrections.jsonl
```

Only explicit corrections or operator-reported successful, completed physical
executions become proposed positive rows. Preview-only successes and failed
attempts without corrections are excluded. The latest review supersedes an
earlier review of the same generation. Proposed corrections are marked
unexecuted; operator reports retain that qualification basis. Export does not
validate geometry or auto-train/deploy a model. Keep failed originals with their
corrected targets for analysis. In a multi-generation recovery, review each
relevant generation explicitly; the UI selects the latest generation.

Removing the experiment directory leaves conventional Body Control behavior
intact on restart. Stop/disable its two user services before removal. Recording
stores are retained as owner data.

## Q6A compact motion deployment (2026-10-25)

`prepare_wire.py` converts the frozen v8 examples into `motion-arrays-v1`:
generated operation arrays with indexed joints/legs, decoded by `compact_wire.py`
into the existing executor's commands. Motion targets, timing, operation order
and existing face changes are retained. This is not a named-motion lookup.
The candidate has no system message or face catalogue in its prompt; the
operation format and face choices are taught in the training examples.

The revised candidate is
`artifacts/spatial-v9-compact/dataset-balanced/`. Its 200 missing initial face
labels are spread deterministically across all 59 renderer expressions, with
3–4 additions per expression. Each added target has a matching explicit face
request in its training input. Existing expressive examples remain intact.
Neutral starts 5 of the 879 training examples; the complete dataset is not
uniform because its original curious/thinking examples are preserved. The
earlier all-neutral additions and their interrupted training run are superseded.

Joint observations use compact columns and five decimal places; IMU measurement
vectors use six. Redundant raw servo pulse widths and IMU transport/acquisition
diagnostics remain in recordings but are omitted from candidate model input.
Measurement availability, freshness, events, unknown metadata and full histories
remain available. Generated motion targets are not rounded or truncated.

Training artifacts, served-model measurements and physical trials are distinct.
The owner requested activation on 2026-10-25. The Q6A model and generator services
now use `balanced-served/model.Q8_0.gguf` and `dataset-balanced`, respectively,
on the existing ports 8795 and 8794. Both are active and enabled. The model SHA256
is `8de6027ed46a5edc0687c0102627a9a1619911cbbb3808134947647e9608ae09`.
Previous service units are retained for rollback under
`build/gateway/physical/deployments/compact-20261025T044343Z/`.

The balanced run completed three epochs on 879 examples. A served-model recall
check covering all 59 initial expressions and all ten operations produced the
correct initial face in 68/68 cases and exact complete targets in 66/68. These
are training-recall checks, not unseen-motion qualification. A new dance request
repeated a leg identifier, and the recorded cheese request produced a target
that failed IK replay; these known limitations remain in the deployed model.

On the Q6A CPU, the same happy-face/10 mm foot-lift request with no prompt cache
took 72.89 seconds with v8 (3,154 input / 91 output tokens), and 17.90 seconds
with the compact candidate (823 input / 49 output tokens). Both decoded to the
same four operations and a planned two-second movement. These are individual
measurements, not a latency guarantee. The isolated candidate test used an
8,192-token context; production retains its native 262,144-token capacity.
A live-state candidate request took
16.25 seconds (741 input / 49 output tokens). Its first physical trial failed
the owner's visual assessment; after a power cycle and native Stand setup, the
owner confirmed the repeated lift and happy face worked. The failed attempt
and successful repeat remain separate recorded trials.

Subsequent owner feedback marked the small lifts partial: insufficient visible
movement, slow timing and disturbed balance. A rear-crouch/25 mm brisk-lift
correction then passed the owner's live review and was added to the pending
training data. `next-reviewed-counterbalanced/qwen-data/` on DNDIY contains
894 examples, including that correction; no further training has run. The active
879-example model has not learned this correction. See `CURRICULUM.md` for trial
IDs and qualification details.

After activation, the same frozen happy-foot-lift request completed in 10.23
seconds with 823 input tokens, 49 output tokens and zero cached tokens. The
decoded four-operation program matched the requested face, lift, hold and lower.
This generation-only check used the unchanged native context capacity and sent
no motion to the robot. All 14 compact-wire, generator and compact-dataset tests
passed. The request, response and model identity are saved in the deployment
directory above; this single timing is not a latency guarantee.

## Earlier compact Qwen experiment (historical results)

`refine.py` and `recovery.py` produce `artifacts/compact-v2-recovery/dataset/`:
3,253 training, 388 development and 503 test examples. There are 25 named
gestures/postures (including stand and neutral), all 12 existing gait commands,
explicit stop, arbitrary joint moves, simultaneous poses, oscillations, holds,
and compositions that are not named library entries. The 640 additional
training rows contain smaller-wave jam recovery, obstruction backoff,
feedback-conditioned fall/slip corrections, resumption, and novel sequences.
The previous 60 benchmark requests are now regression training material, not
independent evidence. The new fixed benchmark has 139 cases. A separate
12-case natural recovery challenge omits the teacher's correction instructions.

These are synthetic numerical examples, **not measured recovery trajectories**.
Fall examples teach repeating a correction that improved measured orientation
or reversing one that worsened it. They do not establish a successful first
get-up from every fallen configuration. The wire measures shaft position, not
torque, ground contact, or the cause of a slip. No physical recovery capability
is established by JSON accuracy or training loss.

The training run uses the same pinned Qwen3.5-0.8B base, response-only rank-16
LoRA, three epochs, and effective batch eight (four examples, two accumulation
steps). Complete examples fit 1,534 native tokens; none are truncated.
Thinking is disabled at serving. `export_qwen.py` merges the adapter in float32
before F16 export and quantization, without a separately applied quantized-base
adapter. The original compact run used Q4; spatial export now defaults to Q8_0
after the precision comparison described below.

The completed three-epoch training took 1,882 seconds. The original two
language-model services were restored and both returned healthy responses.
Both were subsequently stopped at 15:17 PDT, after training restoration;
the final setup check left that later service state untouched.
The first text export retained metadata for an MTP head that the text-only
Transformers model does not contain. The exporter now uses `--no-mtp`; no
model retraining was needed for that conversion fix.

The merged Q4 candidate scored **130/139 exact programs (93.5%)**, with a
2.562-second median and 5.180-second p95 on four CPU threads of this workstation.
All 91 ordinary motion cases passed. Recovery subsets scored fall 4/10,
slip 6/8, jam backoff 9/10, smaller wave 10/10 and resumption 10/10.
Reasoning was absent in every response. These are instruction/parameter tests,
not physical trials. The old 60-case benchmark scored 60/60 with a 1.608-second
median; those requests were included in this round's training, so this is
regression retention, not independent generalization.

The same merged model in F16 scored **135/139 (97.1%)**, with a
4.166-second median and 9.838-second p95. Its four errors were fall corrections.
Both formats passed all 91 ordinary motion cases. F16 matched none of the
12 natural recovery references; greater precision alone does not fix that
training gap. Q4 is the accepted first experimental candidate, prioritizing
response time. Full results and export provenance are retained in
`artifacts/compact-v2-recovery/comparison-summary.json` and `served/export.json`.

The natural recovery challenge matched the reference in only **3/12** cases.
One additional output was a plausible backoff-and-reassess first step instead
of the reference's complete smaller wave. Two outputs inserted an unrequested
stop, and all six fall/slip prompts resumed walking instead of correcting the
supplied body state. Therefore the headline 93.5% does **not** qualify automatic
recovery. The next training revision needs contrasting feedback states under
the same natural request, as well as physically grounded recovery examples;
simply adding more ordinary motion requests would miss this failure.

## Standalone service and optional Body Control execution

Start a llama.cpp server with the selected candidate and reasoning disabled,
then run from the repository root (substitute its endpoint and model alias):
Use a Python environment containing `aiohttp`; this workstation's existing
`/home/greggles/ComfyUI/venv/bin/python` provides it.

```sh
python3 -m experiments.freestyle.generator \
  --endpoint http://127.0.0.1:8795/v1 --model freestyle-qwen \
  --contract experiments/freestyle/artifacts/compact-v2-recovery/dataset \
  --model-file experiments/freestyle/artifacts/compact-v2-recovery/served/model.Q4_K_M.gguf
```

The service listens on `127.0.0.1:8794`. Both host applications can POST
`{"request":"...","observation":{...},"event":{...},"history":[]}` to
`/generate` and receive `{program, elapsed_s, usage}`. A plain request can omit
the other fields. `/health` reports service identity, not model qualification.
There is no application inference deadline, token cap, history truncation,
robot dispatch, or fallback motion in this service.
The Q6A owns generation independently of the robot's transport session. Robot
disconnect/reconnect events do not cancel inference or discard its result.
If generation finishes offline, the job reports `awaiting_connection`; its
delivery coroutine resumes on a connection event and obtains current joint
measurements before compiling the generated sequence. This has no polling loop,
reconnect timeout or global command barrier. Explicit cancellation, replacement
commands and gateway shutdown still retire their owned jobs. A packet already
sent before a disconnect retains its actual receipt or unknown outcome; this
change does not replay possibly executed motion or invent a completion receipt.

Contiguous generated joint/foot/body segments continue from their planned
endpoints, anchored at measured positions when the sequence starts. Measurement
error is recorded rather than added to the next relative target. Explicit
Native motions and a changed robot session establish a fresh anchor.
One successor is prepared concurrently with playback in a spawned compiler
process, keeping Python-heavy IK outside the gateway interpreter. Face changes
and authored holds preserve their order. Cancellation discards prepared work;
preparation does not dispatch packets. Existing 32-frame packet capacity and
replacement semantics still require the current packet's receipt before sending
the next packet. No new timeout, stop, range restriction or motion lookup is added.

The owner-approved rear-sway trial on 2026-10-25 improved from 9.96 seconds with
threaded preparation to 5.03 seconds with the separate process, for the same
2.8-second authored sway. At the owner's request, the sway duration was then
shortened to 1.28 seconds; that full trial finished in 2.54 seconds and was approved
for training. Endpoint feedback discrepancies remain recorded; operator approval
does not establish exact joint tracking. Evidence and the pending training row
are in `build/gateway/physical/reviews/rear-sway-20261025/`. The runtime changes are
deployed; the corrected natural-language target has not yet been retrained into
the active model.

Disconnection of the **local HTTP caller** (for example, explicit job cancellation)
cancels the pending downstream model connection. A two-hop
HTTP integration test verifies that cancellation reaches the model socket,
another request can complete concurrently, and a 1.1 MB history is preserved.
On 2026-10-22 the transient API service was restarted with the existing
aiohttp-capable environment and model-file provenance; the served model and
contract were unchanged. This connection test does not establish motion quality.

On 2026-10-21 the accepted Q4 model and API were started as transient user
services `ainekio-freestyle-model` and `ainekio-freestyle-api`. They do not
start automatically after reboot. The model now offloads all layers to the GPU,
with four CPU threads and two inference slots. The original allocation was 16,384
total context tokens (8,192 per slot); it has been replaced by the native-context,
demand-allocated configuration described above. The benchmarks used one slot.
Stop both with:

```sh
systemctl --user stop ainekio-freestyle-api ainekio-freestyle-model
```

Body Control has been restarted to load the optional workspace; existing settings
were restored, including the owner-enabled event recovery for the P4 robot.
The original API smoke test passed a generation-only request for front-right shoulder
20 degrees from home, a two-second hold, and return home. Its first response
took 7.46 seconds including the cold prompt; this is a service smoke check,
not the benchmark median above. Both experimental health endpoints returned
healthy responses.

`observations.py` computes roll/pitch/tilt and tracking errors for the separate
input-format experiment. It chooses no movement and applies no event threshold.
Adding these fields to the existing Q4 model at inference did not help: the
same 24 orientation cases changed from 10/24 to 8/24 exact, with no natural
fall/slip successes. The normal generator therefore retains its trained input
contract. A clearer compact state representation needs consistent training;
merely adding extra fields at inference is not a demonstrated fix.

**Poses and emotes** includes
**Freestyle motions (experimental)** below the named motions, providing the
generator address, Generate only, Generate and perform,
and a separate opt-in for responding to existing body events. Settings now
persist per robot. No new event thresholds, cooldowns, sensor requirements, or
automatic stops are installed. Existing event detection remains unchanged;
`rapid_movement` is evidence for the model, not a declaration that a slip was
proven. MetaHuman can call the standalone API; its production graphs and model
assignments have not been edited.
The current event owner does not emit a dedicated walking-slip event. Jam and
unexpected-tip notifications exist; a future slip detector or a caller can
supply a slip observation to this same interface. No new detector has been
silently installed.

The adapter reads calibrated home angles, signed model positions, actual
feedback readback and IMU state. It retains unknown positions as unknown and
does not interpret zero PWM after output release as a negative joint angle.
When rearming released servos, the first packet target is the measured starting
pose, followed by generated travel. One millisecond is the existing minimum
wire duration for that initial target. Actual body fault events supply current
observations and interrupted work to a recovery request; normal program
completion does not request another generation.

The P4 supports one physical body sequence at a time and 32 frames per packet.
Longer generated sequences are packetized with no omitted targets. The existing
walk-intent protocol accepts at most ten cycles; larger finite requests are
split into batches, which can include body entry/exit transitions. Ordered
packets use actual terminal receipts. This does not block new command admission,
sensing, speech or inference. Manual commands supersede pending experimental
execution. A P4 `done` receipt for a timed Freestyle packet is not proof that
every physical joint reached its target.

To remove: stop the experimental generator/llama.cpp processes, disable event
recovery or restart Body Control, then remove `experiments/freestyle/`. The
small optional loader remains dormant when that directory is absent; original
controls and firmware remain usable. Do not delete an experiment while its
training process is writing artifacts.

## Spatial generation and external request trials (in progress)

`motion_space.py`, `compositional.py` and `kinematics.py` add continuous foot
translations and body poses to joint programs. The spatial contract has no
named-emote lookup. Its prepared `artifacts/spatial-v1/dataset/` contains 3,709
training, 446 development and 523 test examples. These teach spatial primitives,
compositions and source-derived Wave phases; they do not establish arbitrary
English motion understanding or physical recovery. The optional bridge compiles
these controls through the existing V2 four-bar geometry. The compiler is loaded
in Body Control; the older active model does not yet produce the spatial contract.

The first spatial run completed three epochs in 4,696 seconds. An initial
baseline-evaluation batch of two exhausted VRAM; its failed result/log remain
separate. The successful retry used train/evaluation microbatch one and eight
gradient accumulation steps, preserving full examples and effective batch eight.
The final Q4 scored 82/87 exact structured programs, but none of its first eight
external requests passed independent semantic review. Later refinements address
that difference between numerical instructions and natural movement requests.

The existing `ainekio-freestyle-model` service was switched to all-layer GPU
inference on 2026-10-21, keeping two inference slots and reasoning disabled.
It still serves the older compact-v2-recovery checkpoint. One identical
three-operation request took 2.744 seconds on CPU and 0.395 seconds on GPU;
this single comparison is not a general latency benchmark.

`challenge.py` imports the published **text annotations** from
[HumanML3D](https://github.com/EricGuo5513/HumanML3D), pinned at
`9176e8fb446b71c7d2a725eb5cf6fec1ae3b3c23`. Downloaded files, repository license,
source hashes and bank manifest are under ignored `artifacts/external/`.
There are 87,384 annotation rows including mirrors, 14,616 original clips,
and 8,238 connected holdout groups. Crops of one source motion, mirrors and
identical normalized descriptions stay together. Human motion coordinates
were not downloaded or retargeted; these descriptions supply external request
variety, not correct robot trajectories. Their originating AMASS motion data
has separate access/distribution terms from this annotation repository.

The CLI has `import`, `draw`, `run` and `corrections` commands; use `--help` for
their arguments. `draw --previous ...` excludes every earlier selected source
group. This does not prove that a semantic skill was absent from fine-tuning
or base-model pretraining. Familiar skills, new combinations and new motion
families must be distinguished when interpreting results.

`run --workers 2` uses two concurrent model requests, keeps model/contract/state
and training hashes, and saves generated programs plus sampled FK trajectories.
It never dispatches to the robot. Criteria may test trajectory range, direction,
return and duration. Criteria should be specified before inspecting output;
without them a case is unscored. Replay completion is not task success.
Firmware gaits and sensor-driven reassessment are reported as not fully replayed,
not simulated successes. The available generic URDF is not a V2 dynamics model;
current replay does not model contact, collision, balance or recovery.

`corrections` exports a reviewer-supplied corrected program linked to its
evidence file and original failed trial. It never uses the failed output as a
positive target. Keep those cases and their source groups as regression data
after training, then draw fresh external cases for the next generalization
round. Correction export is implemented; automatic semantic grading and an
autonomous retrain-until-success controller are not implemented.

Round 0 currently exercises the old checkpoint with the new spatial contract,
so it is a migration diagnostic, not a qualified unseen-skill accuracy score.
Round 1 source groups have been reserved separately for the spatial candidate.

The first spatial epoch reproduced 7/10 frozen structured examples exactly,
but none of the eight unfamiliar HumanML requests produced a complete usable
robot program. This distinguishes a working train/export path from insufficient
semantic coverage. Results remain under `spatial-v1/epoch-1-contract-check.jsonl`
and `spatial-v1/epoch-1-semantic/`; they are not a qualification of the final epoch.

`semantic_teachers.py` authors continuous robot programs for correction and
training only. `refine_semantics.py` adds 22 teaching families, multi-action
compositions and numerical/recovery rehearsal. Every proposed target is checked
through the existing compiler and independently sampled FK. Failed teachers
remain in `audit.jsonl` and are excluded from positive targets without clipping
their requested movements. Feedback/gait examples report prefix-only evidence,
since this replay cannot simulate their sensor environment or P4 gait engine.
These offline family names are never runtime input matching or capability limits.

All eight first-round authored corrections complete kinematic replay. Seven pass
their original preliminary criteria; the salute's original excursion criterion
uses the wrong baseline after the body lowers. Its preserved failed score and
independent two-stroke trajectory review are in
`spatial-v1/round-1-corrections-v2/`. The eight source groups become training and
regression material. `external/round-2-semantic-cases.jsonl` freezes new source
groups, including guitar, bird, airplane, hammering and moonwalk requests.
Their eventual assessment must include semantic review, not only nonzero travel.

`continue_training.py` loads the preceding adapter into matching trainable LoRA
modules, verifies the loaded tensors, and starts a new optimizer on the reviewed
dataset. It preserves the pinned base revision and response-only supervision.
`export_qwen.py` retains the quantized model and export hashes, using temporary
F16/Hugging Face intermediates by default. `--quantization Q8_0` supports precision
comparisons; `--keep-intermediates` is only for an intentional export investigation.
The October 21–22 cleanup removed 14.06 GiB of obsolete exports and duplicate completed
checkpoint weights/optimizer state. Active serving files, final adapters, datasets,
metrics and trial evidence remain; the deletion record is
`artifacts/cleanup-20261021.json`.
Completed spatial-v2/v3 comparison GGUF files were removed after review; their
final adapters, export hashes and evaluation evidence remain reproducible.

The spatial-v2 continuation completed 302 steps on 1,206 training examples. Its
Q4 artifact matched 67/87 structured references and 14/16 natural feedback
references (these are synthetic correction reasoning, not recovered robots).
All 19 semantic requests finished generation in 0.405–2.932 seconds. Nine programs
completed geometric replay; independent semantic review found one match among
eight fresh external requests, zero among eight trained regression requests, and
two of three basic requests. The matching new request was a two-hand window-wiping
mime. Both-hand lifting has no demonstrated supporting contact/balance; a geometric
match is not permission to describe it as physically successful.

Seen-example reconstruction was 5/25 for both Q4 and Q8. The native adapter also missed two of three
checked semantic training examples. Q8 did not improve reconstruction and its
completed comparison model was removed; the results and export identity remain.
`native_benchmark.py` checks saved-adapter output without GGUF conversion or a
schema-constrained decoder. Detailed evidence remains in `artifacts/spatial-v2/`.
The spatial-v2 candidate has not replaced the active generator.

A CPU float32 check compared full teacher-forced forward passes with identical
prefix-only passes on three semantic examples. Their next-token logits agreed
within 0.000065. The wrong numeric decisions were already present in the native
adapter: high token accuracy did not imply a correct motion program. This check
does not establish parity with the accelerated training forward path.

The optional UI now renders job progress through Body Control's existing status
refresh and offers **Save trial data**. This export includes generation identity,
programs, receipts and before/after-operation observations. It explicitly labels
the observations as sparse, not continuous servo tracking or physical success.
Body Control was restarted through its existing launcher on October 21 and now
serves these changes. Existing per-robot Freestyle settings were restored exactly;
the robot was disconnected and no physical commands were dispatched. Seven focused
backend/API tests and the UI routing/settings/export test passed.

Spatial-v3 completed three epochs from the v2 adapter on 2,140 unique examples (2,683 weighted
training rows), with complete Wave targets replacing the old conflicting spatial
Wave targets. Additional numerical rehearsal and seven external motion families
were audited: 835 of 1,002 initial candidates replayed, with the rejected 167
preserved. Seven repaired guitar teachers then replayed after their strumming
plane moved forward into reach, preserving the vertical stroke. Cross-arms remains
uncorrected. All newly corrected source groups are retired from unseen scoring.
The first v3 epoch reconstructed only 4/25 seen programs. Independent review of
19 regression/basic requests found three semantic path matches, with no physical
qualification; most external cases in that run had already entered training.
The failed epoch-one model was stopped and removed after review. Its hashes,
generated programs, trajectories and corrected exposure labels remain in
`spatial-v3/epoch-1-semantic-regression/`.
The final v3 model reconstructed 3/25 seen references (median 1.078 seconds).
Of 32 fresh-source requests, 19 completed geometric replay; independent review of
the eight targeted semantic requests found no complete matches. Subsequent manual
review of the 24 broad-survey requests found one plausible sidearm throwing mime;
this is semantic/kinematic evidence, not physical success.
Results are retained under `spatial-v3/final-external/`.

The subsequent arithmetic audit found identical input tokens, base weight values
and adapter weight values across Unsloth and standard Transformers, but different
predictions. On the recorded numeric decision, compiled Unsloth assigned the
teacher token probability 0.9886; standard inference assigned 0.00043. Disabling
only Qwen's compiled MLP blocks restored the native decision (0.000096), as did
disabling the compiler globally. Changing FLA kernels or normalization weight
precision alone did not resolve the discrepancy. This is stronger evidence than
attributing the failed programs to quantization or insufficient data alone.

`continue_training.py` now uses eager Qwen MLP blocks inside this experimental
process while retaining the separate fused loss and linear-attention kernels.
`native_benchmark.py` applies the same arithmetic. Shared trainers and installed
packages are unchanged. Spatial-v4 continues the saved v3 adapter on the same
frozen training fold with this correction; generated-motion validation remains
in progress. The first v4 epoch reconstructs 15/25 seen reference programs,
compared with 3/25 for final v3. Its remaining errors include direction signs,
missing phases and incorrect repeat counts. This is training-example
reconstruction, not unseen-motion accuracy. Two concurrent GPU workers ran
alongside training (median 4.634 seconds), so that timing is not an idle-machine
deployment benchmark. Results are in `spatial-v4/epoch-1-seen.jsonl` and its
summary. The audit evidence and configuration hashes are in
`spatial-v3/backend-*.json` and `spatial-v4/run-plan.json`.
Sixteen new source groups and their textual semantic requirements were frozen
before v4 candidate inference in `external/round-4-broad-cases.jsonl`.
The first v4 epoch generated all 16, and 15 completed geometric replay. Independent
review against those pre-recorded requirements found one matching broad mime
(arm exercises plus squats). Failures still substitute familiar patterns or omit
requested phases: wiping without dipping, arm motion without a preceding walk,
and a right-hand reach without the final bilateral lift. Chest/head requests
often produce only a 30 mm foot lift. These 16 source groups and exact requests
had no training overlap; they remain outside the current v4 fold. Programs,
traces and per-case semantic evidence are in `spatial-v4/epoch-1-external/`.
No physical trial has been performed, and this candidate is not activated in
Body Control. The later v4 checkpoints still require evaluation.
The first checkpoint also matched 85/87 structured references but only 8/16
constructed host-event recovery references. These measure different input
conditions; neither score establishes physical recovery. The second checkpoint
matched 19/25 seen programs, yet none of the same 16 external requests fully
matched their semantic requirements (14 replayed). Improving reconstruction
has therefore not yet established open-ended motion generation.

`external_teachers.py` authors offline corrections and compositions only; the
runtime never selects one of these names. Five fourth-round corrections passed
independent path/order review: dip before wiping, a quadruped left step, a
forehand, bilateral head-height reaching, and a unilateral reach followed by a
bilateral chest-height lift. Two gait-plus-gesture proposals remain partially
replayed and were excluded from the correction training export. Another 22
mirrored paths and ordered compositions completed replay and endpoint review.
Their head-height targets reach Z=105 mm beside the head, rather than merely
lifting 30 mm from the floor; exact contact, collision and support remain unproven.

The completed `spatial-v5/dataset/` run retains the v3 training fold, adds 492
constructed host-shaped recovery inputs, and gives the 27 reviewed new motion
examples eightfold training weight. This is 3,391 training rows, not 3,391
distinct motion skills. `refine_runtime_inputs.py` records the source/evidence
hashes and retains the original 446-example evaluation fold. Preparation fits
all examples within 4,609 tokens without truncation. Sixteen new external source
groups, with semantic requirements recorded before inference, are frozen in
`external/round-5-broad-cases.jsonl`. The v5 continuation ran from the
final v4 adapter, with thinking disabled, the same process-local MLP arithmetic,
three epochs and 1,272 optimizer steps. `spatial-v5/run-plan.json` records its
inputs; `qwen-fit/training-result.json` and `training.log` record actual progress.
The prepared fold contains 2,659 distinct input queries with no conflicting
targets for identical inputs. Fresh round-five source groups and exact requests
have zero training overlap. The frozen preparation manifest's
`training_started: false` describes preparation time, not current run status.
The 27 reviewed spatial targets and 16 existing held-out host-shaped recovery
cases are combined in `spatial-v5/refinement-baseline-cases.jsonl` to compare
parent and continuation outputs. These reference checks remain separate from
the fresh external requests and their semantic/trajectory review.
The final-v4 Q8 baseline matched 0/27 new spatial references and 12/16 held-out
host-shaped recovery references: all four backoff, fall and slip examples, but
none of the four smaller-wave references. Those four generated a backoff plus
reassessment without the reduced oscillation. This describes reference matching,
not proof that a reassessment-based recovery would fail physically.
`spatial-v5/refinement-baseline-review.json` retains the programs and expected
targets. The baseline server was stopped after evaluation.

The first v5 checkpoint (step 424) is saved separately from the rotating trainer
checkpoint and exported to Q8. On the 16 fresh round-five requests, 10 programs
completed geometric replay, five failed IK, and one generation was incomplete.
Independent review matched two complete requests: an upper-body stretch and a
bilateral reach toward the face with a hold. These are held-out source requests,
not unseen semantic families; related motions occur in training. The other
requests omitted locomotion or phases, used the wrong direction, over-repeated,
or failed to finish. `spatial-v5/epoch-1-external/semantic-review.json` ties each
judgment to the frozen requirements and measured paths. No physical trials took
place. The completed 156-case reference comparison matched 24/27 new training
targets, 19/26 retained learned programs, 12/16 held-out host-shaped recovery
references, and 85/85 structured numeric references. The two legacy spatial Wave
references did not match; they use a different representation, while the complete
source Wave reference passed. Parent scores were 0/27, 26/26 and 12/16 respectively
for the first three groups. The four smaller-wave recovery references remain
incorrect. These are exact program comparisons, not physical success scores.
`epoch-1-reference-review.json` records the groups and failures. At that checkpoint,
this checkpoint has not replaced the deployed generator. Evaluation timing
includes contention with GPU training.
Four selected regressions were checked directly with the saved native adapter:
all four also failed natively. Beckoning, pulling and clapping produced exactly
the same programs as Q8; the left-step programs differed but both over-repeated.
`epoch-1-native-regression-review.json` records this limited comparison. Export
precision alone cannot explain these errors. The native check finished and its
temporary compilation cache was removed.

The parent Q8 model was also tested on the identical round-five requests. It
matched 1/16 (a forward kick), versus the new checkpoint's 2/16 (stretch and
face-region reach). Two gains and one regression do not establish broad
generalization. `epoch-1-parent-comparison.json` links this comparison to both
semantic reviews. Both temporary GPU evaluation servers were stopped after use.
The completed epoch-one GGUF was then removed to reclaim 0.76 GiB; its adapter,
export hashes and all evaluation evidence remain. The parent final Q8 and active
served model remain available.

Three more reviewed corrections were saved after the v5 training inputs were frozen:
a forward kick and a left-hand microphone hold concurrent with a right-arm
gesture in `spatial-v5/round-5-corrections/`, plus a teapot mime in
`spatial-v5/round-5-teapot-correction-v3/`. The latter moves the raised hands with
the torso during its pouring tilt instead of keeping them planted in space.
Earlier failed paths and the wrong-direction pouring proposal remain labeled as
rejected evidence. The inward folded-hands proposal still fails IK and is not
exported for training. New round-six requests and pre-inference requirements are
saved in `external/round-6-broad-cases.jsonl`; their source groups and exact
requests overlap neither v5 training nor the eight subsequently prepared
corrections from rounds four and five.

`spatial-v5/library-coverage-audit.json` found another data gap: request text has
no explicit standalone Rest, Dance, Swim, Point, Nod, Lay Down or Crouch examples;
Sit appears only inside Wave instructions. This lexical audit is not a semantic
competence score, but the current spatial fold must not be described as covering
the original motion library. Source-grounded library teaching still needs to be
restored alongside novel compositions, preserving complete phases and holds.

The v5 run completed all 1,272 optimizer steps in 4,957 seconds. Held-out
teacher-forced loss increased from 0.002048 to 0.003452. Both epoch two and the
final Q8 export reconstructed 26/26 retained programs, 27/27 newly taught
programs, 85/85 numerical references, and 12/16 host-shaped recovery references.
The same four recovery cases calculate the back-off correctly but omit the
remaining smaller-wave cycles. The two historical Wave representations still
differ; the complete source Wave reference passes. These are exact output checks,
not physical motion scores.

On the same sixteen round-five requests, epoch two and final both matched 3/16
semantic requirements: upper-body stretch, hands held near the face, and a
forward right-foot kick. Epoch two replayed 13/16 complete programs; final
replayed 11/16. On sixteen newly drawn round-six requests, final replayed 9/16
but matched **0/16** complete semantic requirements. Repeated familiar arm
sweeps often replaced unfamiliar movements; a request for very fast backward
travel selected backward gait at only 1 percent speed. Reviews, trace hashes
and frozen requirements are in `spatial-v5/final-external/semantic-review.json`
and `spatial-v5/final-round-6-external/semantic-review.json`. The new candidate
has not replaced the active compact model. All temporary evaluation servers
exited; epoch-two GGUF and the finished training cache were removed, retaining
the adapters, final Q8, provenance and evaluation evidence.

`spatial-v6/dataset/` retains all v5 training rows and adds 62 constructed
context-dependent recovery inputs, thirteen reviewed external corrections from
rounds four through six, and twelve source-posture/composition examples. New
motion examples receive eightfold weight: 3,653 rows, 2,746 distinct queries,
no conflicting identical inputs, and the unchanged 446-example evaluation fold.
The thirteen corrections include a one-hand lifting exercise, brief upper-limb
flinch, squat/T-like spread, repeated pickups into a common imaginary bin, and
an arm lowering/raising sequence while squatting. Failed proposals remain
excluded and recorded. These are kinematic mimes, not contact or balance proof.

`semantic_teachers.source_posture` adds standalone Sit, Rest and Crouch endpoint
demonstrations with their source two-second holds. Their compact joint travel
uses the contract's 50-percent default; it does **not** reproduce source easing
or establish planted-foot equivalence. Three complete seated/crouched
compositions were also reviewed; an across-body example was rejected because
its trajectory did not substantiate that wording. Multi-phase Dance, Swim,
Point and other missing library coverage remains unfinished, rather than being
silently reduced to endpoint poses.

The v6 continuation starts from the final v5 adapter with unchanged LoRA
rank, precision, learning rate and three-epoch schedule. Preparation measured
all 4,099 train/evaluation rows at at most 4,609 tokens without truncation.
`spatial-v6/run-plan.json` records its process identity and frozen inputs;
the training result and log report actual status. Sixteen new round-seven
source groups and their semantic requirements were frozen before inference in
`external/round-7-broad-cases.jsonl`, with zero source-group or exact-request
overlap against v6 training. No firmware, conventional robot behavior or active
service assignment changed for these experiments.

V6 completed all 1,371 optimizer steps and final evaluation in 4,911.6 seconds.
Held-out teacher-forced loss changed from 0.003452 to 0.003515. The Q8 export
reproduces 190/193 reference programs: all 26 retained programs, all 27 v5
targets, all 16 held-out host-shaped recovery cases, all 13 new motion targets,
all 12 new posture targets and all 12 new contextual recovery targets. Numeric
references fell from 85/85 to 84/85: one mixed-limb command lifts the rear-left
foot 15 mm instead of lowering it. The identical error occurs in native adapter
inference, so Q8 quantization alone does not explain it. The two historical Wave
representations still differ, while the complete source Wave reference passes.
Thinking was disabled and no reasoning responses were emitted.

On the same sixteen fresh round-seven requests with identical native/FK replay,
v5 matched 0/16 complete semantic requirements and v6 matched 1/16: a brief
bilateral reach beside the face. Complete geometric replays increased from
10/16 to 11/16. V6 also produced partial improvements, including the Sit prefix
in a phone mime and more recognizable dribble strokes, but still omitted later
phases or generated incorrect/unreachable targets. These partial gains are
described individually, not counted as complete successes. Both candidates had
zero source-group and exact-query overlap with the fresh requests. The paired
reviews, trace hashes and reference groups are in `spatial-v6/`; neither model
was activated. No physical trials took place. Temporary GPU evaluation servers,
training/native-check compilation caches and the native build directory were
cleaned up after completion; saved adapters, final exports and evidence remain.

The v7 data audit found inaccurate older teaching targets: drinking and saluting
stopped near body Z=50 and Z=48 mm respectively, below the 80.96 mm shoulder
reference. `semantic_teachers.demonstration` now calculates those reaches toward
the side-of-head landmark [95, +/-90, 105] mm from the supplied starting pose.
Saluting accounts for the preceding torso lowering. `repair_semantics.py` matches
exact superseded program segments from a saved catalog, never user wording, and
replays whole replacements including composed motions. Twenty-three distinct
program/state combinations were reviewed: original holds and repetitions are
preserved, unrelated actions remain identical, head holds are within 0.02 mm of
the authored landmark, and repaired segments return within 0.03 mm. Four semantic
teacher tests passed, including mirrored head reaches and repeated returns.

`spatial-v7/dataset/` replaces 94 weighted rows covering 47 distinct queries;
old datasets and reviews remain intact. It adds seven reviewed round-seven
corrections, the two native-gait walking compositions, and thirty reviewed
grounding examples: six drinking/saluting examples from changed starting poses
and twenty-four simultaneous opposite-direction foot commands. Six additional
posture examples failed IK and remain excluded. The proposed four-stride
correction was also rejected: four requested P4 loop cycles include entry and
settling, ending at native phase 8.015, so they cannot substantiate exactly four
strides. No physical gait behavior was changed to make that example pass.

The v7 fold has 4,127 weighted rows and 2,785 distinct queries, no conflicting
identical inputs, and the unchanged 446-row evaluation fold. No superseded head
program remains in its training targets. Sixteen fresh round-eight source groups
and requirements were frozen before inference, with zero source-group and exact
request overlap. Its 279 reference cases explicitly separate two superseded
historical head targets from desired outputs; historical scores are not rewritten.
All work remains inside the removable experiment and its offline artifacts.
V7 continuation is launched from the final v6 adapter, with initial weights
verified, thinking disabled, 830,315 supervised tokens and no truncated examples.
Exact native tokenization measured a maximum of 4,645 tokens. The three-epoch
rank-16 LoRA schedule and 8e-5 learning rate remain unchanged; the process and
input hashes are in `spatial-v7/run-plan.json`. Training status is recorded by
`qwen-fit/training-result.json` and `training.log`; no v7 quality result is claimed
before export and held-out evaluation.

During v7 training, `source_teachers.py` and `source_review.py` inspect complete
authored Point, Nod, Lay Down, Dance and Swim sources offline. Joint-path
simplification preserves phase boundaries and retraced motion. The spatial
candidate additionally retains curved body/foot paths within phases; endpoint
agreement alone had hidden major deviations. Ordered full-path comparisons use
discrete Frechet distance on stored polylines, densified to 0.25 degrees/mm;
this does not add source measurements or establish physical contact/stability.
Six focused tests cover reversals, phase retention and unequal sampling rates.

The revised spatial candidates replay Point, Lay Down, Dance and Swim with
maximum ordered foot-coordinate distances of 0.431, 0.277, 0.139 and 0.236 mm
respectively, including comparison sampling error. All authored phases and
holds remain represented. Nod still fails its opening crouch IK, including a
finer geometric subdivision; it is not an accepted teaching target. These
candidates remain outside the frozen v7 training fold. They also expose an
output-size problem: complete spatial Point/Dance/Swim programs require about
6,901/9,846/29,577 response tokens with the current schema. They are not ready
for fast generation merely because their geometric replays complete. Raw
candidates, source/code hashes, path reviews and token counts are retained in
`spatial-v7/source-*-review/`. No runtime or conventional motion behavior was
changed by this offline authoring work.

The owner requested a Qwen3.5-2B alternative after v7 finishes and unused-run
artifacts are cleaned up. `artifacts/spatial-2b-v1/qwen-data/` is prepared from
the same corrected fold: its 4,127 training and 446 evaluation message records
are byte-identical to v7, with a 4,645-token maximum and no truncation. The
cached 2B base is pinned to `fffbc0d8711cf87df6d1f97938c5e50ef94aadc7`.
The run plan retains rank-16 LoRA, three epochs, batch one/accumulation eight,
8e-5 learning rate, and thinking disabled. The isolated GPU run was launched
after v7 evaluation and cleanup. The first terminal-owned process disappeared
at step 55 without a checkpoint or recorded exception; its evidence is retained
under `spatial-2b-v1/interrupted-attempt-1/`. The identical configuration was
restarted as the transient user service `ainekio-freestyle-train-2b-v1`.
`spatial-2b-v1/qwen-fit/training-result.json` and `training.log` record progress;
service state must also be checked because a forcibly terminated process can
leave a stale `running` result. The transient `ainekio-freestyle-eval-2b-v1`
service waits for training completion, then exports Q8, runs the reference and
unseen-motion tests, and repeats the 0.8B unseen requests for paired latency
measurement. It stops its temporary inference servers after each comparison.
`evaluation-progress.json` and `evaluation.log` record these offline phases;
semantic review is still required after automatic replay. The same
round-eight requests and reference cases are pinned for comparison. This tests
a practical alternative: the 0.8B model has prior continuation training, whereas
the 2B model starts from its pretrained weights, so the comparison does not
isolate parameter count alone.

The 2B run completed all 1,548 optimizer steps and saved identical root/final
checkpoint adapters (SHA-256
`ee7b3d3992ea7f88879e1cf109ed76fa3b86cf13959b6f27583b24b26b3d7e3e`).
The subsequent held-out loss evaluation ran out of GPU memory after other
processes increased GPU usage. Its original error report is retained in
`post-training-loss-failure.json`; final held-out loss is unavailable. No
training was repeated for that error. The saved weights were verified, exported
and evaluated successfully in serving. Mean training-batch losses by epoch were
0.04002, 0.002836 and 0.0005257; these are not motion-success scores.

The completed comparison is in `spatial-2b-v1/comparison-summary.json`:

| Measure | 0.8B spatial-v7 | First 2B run |
| --- | ---: | ---: |
| Exact reference programs | 273/279 | 259/279 |
| Unseen requests matching frozen coarse requirements | 2/16 | 2/16 |
| Full kinematic replays in the paired run | 14/16 | 13/16 |
| Median generated-program response | 1.706 s | 1.914 s |
| p95 generated-program response | 4.810 s | 5.004 s |
| Q8 file size | 811,843,168 bytes | 2,012,012,128 bytes |

The reference suite includes training targets; it is not an independent
generalization score. Both models miss the same two superseded head targets,
two older wave representations and two posture-dependent drinking targets.
The 2B run additionally misses ten recovery references/envelopes, two pose
reference frames and two spatial-coordination directions. Several recovery
outputs reverse the required correction signs. Both reproduce the full-source
Wave reference and all 47 corrected head targets.

In the unseen set, 2B produces a small bilateral vertical greeting wave and a
20 mm squat-and-rise; 0.8B matches bilateral outward extension and an 8 mm
squat-and-rise. Both still omit major requested phases elsewhere. All semantic
scores are coarse kinematic reviews, with no physical contact, balance, recovery
or motion-recognition qualification. Three 0.8B programs varied in its repeated
greedy run: replay completion rose from 13 to 14, while the semantic score stayed
2/16. The cause of that variation was not isolated.

Latency was measured sequentially on this workstation's GPU, using Q8,
reasoning disabled and two workers, after training finished. Other workstation
services remained active. Median output lengths were 315 tokens for 0.8B and
235 for 2B, so these are end-to-end generated-program timings, not fixed-token
throughput. Q6A performance remains unmeasured. The first 2B run is not an
overall improvement; differing accumulated training histories prevent treating
this as a parameter-count-only result. Neither spatial candidate was activated.
The temporary comparison server has stopped and both jobs are finished.

The final v7 adapter completed 1,548 optimizer steps in 5,732 seconds. Held-out
loss changed from 0.003515 to 0.004528. Its Q8 export reproduces **273/279**
references, versus 264/279 at epoch one: all 47 corrected head targets, all 85
numerical references and 37/39 new targets match. Two misses are superseded
historical head targets; two are older wave representations; the remaining two
confuse posture-dependent drinking targets. Full-source Wave matches. These
reference cases include training targets, so this is retention/reproduction,
not a generalization score.

On the same sixteen frozen round-eight requests, the parent, epoch-one and final
models each match only **2/16** coarse requirements. Complete kinematic replays
are respectively 12, 10 and 13. The final model still omits sitting, turning,
wave reversals or other requested phases in most unseen compositions. Evidence
is in `spatial-v7/final-reference-review.json`,
`final-external/semantic-review.json` and `final-parent-comparison.json`.
The candidate was not activated, and no physical trials were performed.

### Direct full-weight 0.8B comparison (October 2026)

`artifacts/full-v7-vs-lora/` compares a direct full-weight fine-tune with the
v7 LoRA. Both start from the same pinned Qwen3.5-0.8B base plus the v6 adapter;
the direct run merges that adapter and updates all 752,393,024 weights. Both
use the same 4,127 training messages, three epochs, effective batch size of
eight, frozen 279 reference requests, 16 unseen requests, Q8 serving format,
and disabled thinking. Full tuning uses a lower learning rate (1e-5 versus
8e-5 for LoRA), so this is a practical comparison, not a learning-rate-matched
ablation.

| Measure | Direct full weights | v7 LoRA |
| --- | ---: | ---: |
| Exact reference programs | 270/279 | 273/279 |
| Unseen coarse motion requirements met | 3/16 | 2/16 |
| Complete native kinematic replays | 16/16 | 14/16 |
| Median generated-program response | 1.551 s | 1.674 s |
| Median output length | 279 tokens | 315 tokens |
| Q8 model size | 811,843,168 bytes | 811,843,168 bytes |

Direct tuning adds a shallow backward-step/sit/stand mime and a cross-body
throw mime on the unseen set, but loses the LoRA's bilateral outward-extension
mime. Both retain the shallow squat. It also misses three additional exact
references, including two smaller-wave jam variants that now request a
larger oscillation. These are reference regressions even though the output
still parses and replays. The small 16-case semantic difference does not
establish a reliable generalization advantage. Shorter outputs account for
some or all of the 0.12 s median response difference; the architecture and
Q8 byte size are identical.

All semantic scores are reviews of generated programs and FK/native gait
replays. There were no physical robot trials, balance/contact measurements,
or recovery demonstrations. The 279 reference requests include training
targets, so they measure retention as well as response formatting. The direct
run's training loss is not a task-success score, and posttraining held-out
loss was not measured. `comparison-summary.json`, each `semantic-review.json`,
and the complete traces record the evidence. The direct candidate was not
activated; v7 LoRA remains the baseline. The temporary inference servers
stopped, and the paused 2B service was restored after training.
The finished optimizer checkpoint was removed after confirming its model
weights exactly match the retained root weights. This reclaimed about 4 GiB;
the full model, Q8 export, source data and evaluation traces remain.

After final evaluation, the temporary server was stopped and 179 unused files
were removed, reclaiming 4,172,889,050 bytes (3.89 GiB). Cleanup includes obsolete
Q8 exports, finished optimizer checkpoints, regenerable message exports and
unused LFM/Needle serving artifacts. Source datasets, evaluation evidence,
retained adapters, current v7 export, shared pretrained caches and the active
compact service model remain. Exact file hashes and deletion results are in
`spatial-2b-v1/cleanup-result.json`.

V7 epoch one (step 516) is saved separately from rotating checkpoints and
exported as Q8 for GPU evaluation. On sixteen frozen round-eight requests,
ten complete geometric replay and two match their coarse motion requirements:
bilateral outward hand extension and a shallow 8 mm squat-and-rise. Other
requests omit phases, generate unreachable targets, or fail to finish generation.
These are not physical successes and are not a direct improvement comparison
with earlier scores on different request sets. The completed reference check
reproduces 264/279 targets, with the two superseded head targets reported
separately. It reproduces 46/47 corrected head examples, all 85 numerical
references and 32/39 new targets. Three investigated deviations include extra
boxing punches that fail IK, extra torso yaw during a stepping/forehand sequence,
and a weight-lift shrinking from 35 to 5 mm with its holds omitted. Their actual
and expected replays are in `epoch-1-reference-deviations/`; exact reproduction
and semantic success remain separate. Evidence is in
`spatial-v7/epoch-1-external/semantic-review.json`;
both evaluation and training share the GPU, so timings are not isolated inference
benchmarks. The final v7 checkpoint and 2B alternative will use the same requests.
The direct parent-v6 comparison on those same sixteen requests also matches the
same two mimes, with twelve complete geometric replays versus ten at v7 epoch
one. Thus epoch one shows no complete semantic gain on this set. The paired
reviews and hashes are in `spatial-v7/epoch-1-parent-comparison.json`. Both
temporary evaluation servers were stopped after their checks completed.

Finite gait simulation is now available through the optional `--native-gait`
argument to `challenge run` and `external_teachers`. `native_gait.c` samples the
production V2 parser and gait clock at 50 Hz without opening a robot transport.
`gait_replay.py` uses the existing command translator, including its ten-cycle
packet batching, and passes the final native joint target into subsequent
generated operations. Gait entry target jumps are recorded rather than replaced
with invented interpolation. Ongoing commands remain explicitly incomplete
because their termination needs an external command.

Build the offline sampler with the repository's native libraries:

```bash
cmake -S Slave/software/models/v2-12servo -B /tmp/freestyle-native-gait-build \
  -DCMAKE_BUILD_TYPE=Release -DPython3_EXECUTABLE=/path/to/python-with-numpy
cmake --build /tmp/freestyle-native-gait-build --target v2_walk_command -j4
cc -std=c11 -O2 -Wall -Wextra -Werror -Wpedantic \
  -I Slave/software/models/v2-12servo/include -I Slave/software/core/include \
  experiments/freestyle/native_gait.c \
  /tmp/freestyle-native-gait-build/libainekio_v2_motion.a \
  /tmp/freestyle-native-gait-build/core/libainekio_core.a -lm \
  -o /tmp/freestyle-native-gait-build/freestyle_native_gait
FREESTYLE_NATIVE_GAIT=/tmp/freestyle-native-gait-build/freestyle_native_gait \
  python -m unittest experiments.freestyle.test_native_gait
```

`artifacts/native-gait/build.json` records the tested binary and input hashes.
Nine gait/packet cases matched the existing `v2_walk_command` executable within
6.4e-10 degrees, with matching timestamps and nominal body paths. Three native
integration tests cover packet preservation, a gait followed by a hold and
relative joint movement, and incomplete ongoing motion. The existing twenty
challenge/program tests passed outside the sandbox; inside it, Python's async
runner hung during shutdown after an assertion-passing test. No production
timeouts or workarounds were added for that test-environment issue.

These traces describe **nominal targets**, using the default zero learned gait
profile. Body paths are command-relative per packet; they are not composed world
odometry. Feedback, contact forces, balance, collision clearance and physical
travel remain unverified. `native-gait/walking-corrections/` contains two reviewed
walking-plus-gesture examples previously blocked by missing gait replay: a reach
beside the head and two rightward stumbling mimes. Their training exports are
pending a later fold and do not change the running v6 inputs. The stumbling mime
does not establish actual recovery from a fall or slip.

Simulation profiling found repeated parsing/construction of the 380 KB geometry
for every sampled pose. Replay now owns one independent FK model per trial;
inverse-kinematics compilation still owns separate mutable models. Sampling,
target angles and durations are unchanged. The profiled 2,961-sample motion took
16.2 seconds instead of 29.5, and replaying all 16 saved round-four programs
produced exactly identical traces, including the three original compilation
failures. All 10 challenge/kinematics tests passed. Timing and trace-equivalence
evidence is in `spatial-v5/replay-profile-{before,after}.json` and
`spatial-v5/replay-regression.json`. No physical controller behavior changed.

While v5 runs, five more observed round-four failures have authored, replayed and
independently reviewed corrections: head-height drinking, a left chest-level
wave, shirt-removal mime, arm/squat exercise, and a seated cringe using the
existing sit endpoint. Evidence and exported examples are in
`spatial-v4/round-4-additional-corrections-v2/` and
`spatial-v4/round-4-posture-corrections/`. They are separate from the frozen v5
training inputs, and have no source-group or request overlap with fresh round
five. The direct arm-crossing proposal remains an IK failure and is excluded.
These examples describe coarse geometric mimes, not verified physical skills;
hand/head contact, balance, collisions and electrical travel remain unmeasured.

At the owner's requested pause point, v4 finished all 1,008 steps and final
evaluation in 3,859 seconds. The final adapter is saved in `spatial-v4/qwen-fit/`
(SHA-256 `77ec3f0efca1b23f039bb9ca859f20194b71fd4800f4fa83095ab38ee2bea9f7`).
At that pause it had not been exported or evaluated in serving; the resumed Q8
results below supersede that state. Final numeric evaluation loss was 0.002048;
that is not a motion-success score.

The completed epoch-two native-adapter comparison matched 3/4 checked references
(drinking, hand-circle and complete source Wave), versus 0/4 through Q4 serving.
Clapping still had an incorrect repeat count in the native output. Backend,
quantization and schema-constrained decoding differed in that initial comparison,
so it did not isolate the cause. The investigation below resolved this before
v5 training started.
At that pause, the epoch-two adapter, Q4 artifact and both outputs were retained
for that work.
The temporary spatial comparison server and unused LFM baseline server were
stopped; the deployed compact Freestyle service remained available. At that
historical pause no training or evaluation job was left running.
`spatial-v4/pause-point.json`
records the completed runs, prepared-data hashes and next actions.

The resumed precision investigation isolated Q4 damage on the same epoch-two
checkpoint. Training and serving prompt text and token IDs match exactly.
Giving llama.cpp the native token IDs directly, without JSON grammar, still
matched 0/4 references in Q4. F16 matched 3/4 both with and without JSON grammar;
all four generated programs, including the remaining clapping error, were
identical to native inference. Q8 also reproduced those four native outputs.
Across the existing 25 learned examples, F16 and Q8 produced identical programs
and matched 24/25 references, versus Q4's 19/25. This isolates precision loss in
this export; it does not establish that every future Q8 export will be identical
to native inference or that learned-example reconstruction proves generalization.

`export_qwen.py` now defaults to Q8_0. The final v4 adapter was exported with that
default and matches all 26 reconstruction cases (the 25 above plus full source
Wave). The Q8 artifact is 811,843,328 bytes, versus 1,516,744,448 for F16 and
529,297,152 for Q4. Its identity and export provenance are in
`spatial-v4/final-served/export.json`; it has not replaced the active generator.
The final native adapter and Q8 output also match on all four comparison cases,
now including the correct clap count. Median reconstruction latency was 1.623
seconds with two concurrent GPU serving slots on this machine; Q6A latency is
unmeasured. `spatial-v4/precision-investigation.json` records the controls,
results and evidence hashes.
`inference_parity.py` reproduces the raw-token and schema comparisons without
robot dispatch. The completed epoch-two comparison exports were removed after
verification; their adapters, hashes and results remain. The earlier
`pause-point.json` records historical state rather than current activation.
The final Q8 model was also evaluated against the same 16 round-four external
requests, with no source-group or exact-request training overlap. Thirteen
completed geometric replay; independent review found zero full semantic matches.
Missing walk/dip/squat phases, low hand targets and unrelated repeated motions
remain. `spatial-v4/final-q8-external/semantic-review.json` records each failure
against the pre-recorded requirements and measured foot paths. This confirms
that the precision fix preserves learned programs but does not solve novel-motion
composition. Those v4 comparison servers and evaluation processes finished;
v5 now has its own isolated checkpoint evaluation. The deployed compact service
remains unchanged.
The fresh third-round external fold remains separate from training. A component
check using Body Control-shaped event envelopes matched 13/16 recovery references;
this retains synthetic histories and does not establish real recovery ability.

## Compact-command comparison

`compact.py` defines the new instruction-to-program experiment. Its five
operations are `move`, `hold`, `gesture`, `oscillate`, and simultaneous `pose`.
For example, moving the front-right shoulder 20 degrees from home, holding for
two seconds, and returning home produces three calls instead of a table of
servo frames. `gesture` references the **complete** existing motion. This is
the original comparison contract; its results below predate the optional
compact-program executor described above.

The frozen `artifacts/compact-v1/dataset/` contains 956 training examples,
230 development examples and 506 test examples. The 60-case comparison was
selected before training: ten examples from each of six families. Test requests
use different wording and held-out movement angles. This is synthetic language
and parameter generalization, not unseen physical skills or trained recovery.
There are no measured jam/fall demonstrations in this dataset.

The three candidates use three training epochs and rank-16/alpha-32 LoRA:

- Qwen3.5-0.8B: `unsloth/Qwen3.5-0.8B`, revision
  `23c69c53358a07516b5827588b3fdb12ae78fd65`.
- LFM2.5-350M: `LiquidAI/LFM2.5-350M`, revision
  `9e6c6ccf47cd318696e137d381a7ded8fe4df09f`.
- Needle 3: `Cactus-Compute/needle3`, revision
  `d6c7d6a2e9655505e0f8e23339356dd1705900eb`, trained with `cactus-needle==3.2.8`.

`prepare_compact.py` exports identical source examples into each trainer's
native format. Qwen/LFM use the existing shared trainer with response-only
supervision, batch size 1 and eight-step gradient accumulation. Needle uses its
native quantization-aware trainer, batch size 4 and no internal split, so all
956 training examples are retained. Its measured sequence length fits the
1056-token training allocation without truncation. Native optimizers and
training numerics differ; this compares practical pipelines, not an ablation
of architecture alone.

All targets omit reasoning. Qwen/LFM inference explicitly disables thinking.
Needle has no verified reasoning-off engine switch; its targets omit reasoning,
and `benchmark_compact.py` records whether it still emits reasoning. Needle
uses its own native engine, not llama.cpp. `export_needle.py` exports both base
and trained models as W4A8 with the confidence head omitted from both, avoiding
a base-versus-candidate quantization/head mismatch. Native `--forced` mode
requests tool-call output for this offline benchmark; it does not execute tools.

`benchmark_compact.py` compares the entire ordered program, including values,
holds and return targets, against the frozen reference. A correct function name
or valid JSON alone is insufficient. CPU comparison uses four threads, resident
models, sequential requests and conversation reset between Needle cases.
Qwen/LFM use the same JSON schema for both base and trained models. Latency
includes the HTTP request and full response, excludes process/model startup,
and includes the first prompt evaluation. These workstation measurements do
not establish Q6A latency or physical robot performance.
Each comparison response has a 1024-token output allowance; incomplete or
incorrect programs count as failures. This is an offline evaluation setting,
not an inference deadline or a robot runtime change. The initial unbounded
LFM baseline was interrupted after it repeated commands instead of finishing;
its partial records remain separate from the uniform comparison.
The additional equivalence score accepts a single-joint `pose` as `move`, and
reordered joint/angle pairs within one simultaneous `pose`. It preserves action
order, values, holds and simultaneous-versus-sequential movement. This grading
does not imply physical trajectory equivalence beyond the declared operations.

### Completed comparison: 2026-10-21

All three three-epoch runs completed. Qwen and LFM overlapped on the RTX 4080;
Needle setup finished later, so this run did **not** demonstrate three simultaneous
training jobs. Original adapters, results and frozen source data remain under
`artifacts/compact-v1/`; unused serving exports were subsequently cleaned up.
Both previously active production model services were
restored and their health endpoints returned `ok`. Experimental inference
servers were stopped after testing.

The CPU was an Intel Core i9-9900K, using four inference threads. The same
60 held-out cases were evaluated before and after training:

| Model / serving format | Base exact | Trained exact | Trained equivalent | Trained median | Trained p95 | Trained reasoning |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| LFM2.5-350M, Q4_K_M + F16 adapter | 6/60 | 23/60 | 23/60 | 1.900 s | 2.318 s | 0/60 |
| Qwen3.5-0.8B, Q4_K_M + F16 adapter | 13/60 | 38/60 | 38/60 | 1.553 s | 3.368 s | 0/60 |
| Needle 3, merged W4A8 | 8/60 | 19/60 | 20/60 | 0.648 s | 7.341 s | 60/60 |

These are complete response times across correct **and incorrect** answers.
Needle's low median does not establish the fastest correct-motion pipeline;
its longer tail and low accuracy matter. Its native engine still emitted
reasoning after reasoning-free training; neither the inspected CLI nor C API
exposed a reasoning-off option. Thinking-off settings were requested for both
llama.cpp models, although the untrained LFM still emitted reasoning in 9 cases.

Qwen was strongest in this comparison, but none of these served candidates is
reliable enough to replace the motion library. Qwen scored 10/10 for individual
moves and 10/10 for move-hold-return, but 0/10 for oscillations and 0/10 for
coordinated poses. LFM and Needle were strongest on named gestures. Do not read
the small training losses as evidence of general movement understanding.

A separate four-request Qwen check using its saved adapter in Transformers
float32 produced 3/4 correct: its oscillation error persisted, while one pose
missed by the served Q4 model was correct. The served model returned that same
wrong pose both with and without JSON grammar; its GGUF chat template exactly
matched the training template. Thus both learned generalization failures and
a serving/precision discrepancy remain; this limited check does not isolate
quantization as the cause. It was performed after the latency comparison and
is not included in the timing table.

Results are in `comparison-summary.json`, with full responses and per-family
scores in `benchmark-results-v2/`, and hashes/settings in
`comparison-provenance.json`. Historical serving paths were
`qwen-fit/adapter.F16.gguf`, `lfm-fit-v2/adapter.F16.gguf`, and
`needle-fit/model.W4.cact`; these are not a current export inventory. Original
training adapters are retained. Twelve source/contract/grading
tests pass. No candidate has been activated in Body Control, MetaHuman or P4.

Source tests:

```sh
python3 -m unittest discover -s experiments/freestyle -p 'test_*.py' -v
```

## First local training result

The isolated Qwen3.5-0.8B LoRA completed three epochs on 1,551 packet examples
from 21 motion families. All 276 Wave/Swim examples were held out. Reloaded
candidate token loss decreased from 0.26615 to 0.15613. The exported F16 GGUF
adapter is 12,793,312 bytes and successfully loads in llama.cpp.

**This candidate is not ready for robot execution.** The three served first-packet
checks produced 32 frames each, but none matched its reference. “Go to sleep”
had incorrect timing and pose; Wave and Swim included impossible joint angles.
Full responses took 65.7, 84.3 and 71.7 seconds respectively on this workstation's
CPU with four threads. These are neither Q6A measurements nor whole-gesture
completion tests. Lower token loss and valid JSON did not establish correct motion.

The local candidate, frozen dataset and evaluation reports are in the ignored
`artifacts/fit-v1/` directory. It contains no measured recovery training and has
not been connected to robot execution. Both temporarily paused production
llama.cpp services were restored and their health endpoints checked; the
experimental test servers were stopped. The eight source/contract tests pass.

## Original frame-client boundary

`runtime.py` builds the model input and calls the ordinary llama.cpp
`/v1/chat/completions` endpoint. It supplies caller observations and history
without truncation. Requests may contain a jam/fall event, interrupted targets,
measured joint positions, IMU observations and their source timestamps. Missing
observations are not fabricated. There is no fixed recovery routine.

Responses use the existing `motion_plan_v2` geometry: twelve signed model
centidegrees in physical joint order, individual millisecond durations and an
ending pose. The model also reports whether the requested motion is complete.
The existing wire packet holds 32 targets. Longer motions need continuation
packets; a packet boundary is not completion of the gesture.

The caller retains robot selection, command admission and execution authority.
For one nonempty packet it can submit the existing Body Control
`POST /api/motion-plan` payload:

```json
{"robot_id":"selected-robot-id","frames":[[500,[0,0,0,0,0,0,0,0,0,0,0,0]]],"end":"hold"}
```

The zeros above illustrate encoding only, not a recommended robot pose.
Use the caller's existing authentication/CSRF and correlated receipts. The
experiment neither stores gateway credentials nor bypasses its execution owner.
It returns `execution: not_dispatched`; JSON validity does not prove geometry,
clearance, balance, physical completion or successful recovery.

Continuous multi-packet execution is **not implemented**. The P4 has no new
stream queue here. Sending packets back-to-back would replace active motions;
waiting for completion and then generating introduces gaps. This transport
question remains separate from training and must be resolved before claiming
continuous expressive execution. No delay/retry/automatic stop was added.

## Export and prepare

Run from the Ainekio repository root. Choose a new artifact directory inside
this experiment's ignored `artifacts/` or outside the repository.

```sh
python3 experiments/freestyle/dataset.py \
  --model-root Slave/software/models/v2-12servo \
  --output /tmp/ainekio-freestyle-seed \
  --evaluation-commands wave swim

python experiments/freestyle/prepare.py \
  --dataset /tmp/ainekio-freestyle-seed \
  --trainer /path/to/metahuman/docker/runpod-trainer/train_unsloth.py \
  --revision 23c69c53358a07516b5827588b3fdb12ae78fd65
```

The exporter reads the existing verified gesture compiler. It retains all
phase endpoints, joint reversals, original source duration and terminal poses.
It fits **linear** targets for the current wire format with at most 0.005 degree
error at each source sample, including target rounding. Timestamps round to
milliseconds. This does not prove continuous cubic-path equivalence or loaded
tracking. Original source timing is not the firmware's speed-retimed playback.

The 23 source motions produce synthetic language variants and packet examples,
not hundreds of distinct physical skills. All packets/paraphrases of a motion
stay in one split. The initial export holds out Wave and Swim for comparison;
this is a source-family generalization test, not measured recovery evidence.
Source hashes and qualification status accompany every example. There are
**zero measured recovery demonstrations** in this seed.

`prepare.py` uses the selected base tokenizer and the existing shared text
trainer's response-only labeling/provenance checks. It measures the complete
examples without truncation and writes training configuration/token reports.
Only preparation needs that trainer path; serving has no MetaHuman dependency.
Use an environment with the shared trainer's dependencies installed. Nothing
installs packages or starts/stops existing model services automatically.

## Train and export

After reviewing the dataset and arranging GPU capacity, the existing trainer
can fit a separate LoRA. It writes only the requested candidate directory:

```sh
python /path/to/metahuman/docker/runpod-trainer/train_unsloth.py \
  --config /tmp/ainekio-freestyle-seed/training-config.json \
  --data /tmp/ainekio-freestyle-seed/train.jsonl \
  --eval-data /tmp/ainekio-freestyle-seed/evaluation.jsonl \
  --manifest /tmp/ainekio-freestyle-seed/manifest.json \
  --output /path/to/new-freestyle-candidate --skip-gguf
```

Export the resulting adapter with a Qwen3.5-capable llama.cpp converter:

```sh
python /path/to/llama.cpp/convert_lora_to_gguf.py \
  /path/to/new-freestyle-candidate \
  --base /path/to/matching-huggingface-base-snapshot \
  --outtype f16 --outfile /path/to/freestyle-adapter.F16.gguf
```

Use the exact matching base revision for training, conversion and serving.
No production adapter is overwritten or selected by these commands.

## Serve and call

Start a separate llama.cpp process on an unused port. Set its context capacity
from measured inputs, generation size and hardware memory; this example leaves
that choice explicit rather than copying a production service configuration:

```sh
llama-server --model /path/to/matching-base.gguf \
  --lora /path/to/freestyle-adapter.F16.gguf \
  --alias ainekio-freestyle --host 127.0.0.1 --port 8092 \
  --ctx-size CONTEXT_TOKENS --jinja

python3 experiments/freestyle/runtime.py --request /path/to/request.json \
  --endpoint http://127.0.0.1:8092/v1
```

Both consumers can send the payload printed by `runtime.py --print-payload`
directly to llama.cpp. There is no extra inference server or coordinator.
The request is an evidence envelope, for example:

```json
{
  "request_id":"caller-owned-id",
  "robot_id":"selected-robot-id",
  "request":"Continue the wave with a different arm path",
  "body":{"model":"v2-12servo","joint_map":2},
  "observation":{"measured_joints_cd":null,"imu":null},
  "event":{"kind":"jam","joint_mask":64},
  "execution_history":[]
}
```

Replace nulls with available attributed observations; the example does not
establish a known pose. A recovery input contract does not mean recovery has
been trained. Dynamic recovery requires successful measured examples from
different obstructions/fall poses and separate evaluation.

## Evaluation and removal

```sh
python3 -m unittest discover -s experiments/freestyle -p 'test_*.py' -v
python3 experiments/freestyle/evaluate.py \
  --data /tmp/ainekio-freestyle-seed/evaluation.jsonl \
  --endpoint http://127.0.0.1:8092/v1 --ids wave:0:0
```

Evaluation records full response time, token usage, format validity, reference
agreement and completion labeling. It never dispatches movement. Test whole
generated continuations as well as individual teacher-context packets before
claiming sequence fidelity. Passing JSON tests is not model or hardware proof.

For removal, stop only the dedicated experimental llama.cpp process, then
remove this directory and the explicitly chosen experiment artifact directories.
The ordinary robot library, walking, Body Control and MetaHuman remain as they
were; there are no registrations to uninstall or production defaults to revert.

### Q6A corrected-motion live-test protocol

Corrected-motion test protocol

New corrected programs remain `awaiting_physical_trial` in the existing review
record and are excluded by the training export. First replay the complete
program offline: check geometry, requested side, repetitions, authored timing
and ending. Keep the original request, observations, program and correction ID.

In Body Control's Freestyle panel, use **Load saved corrections**, select the
correction, then **Test selected correction**. This runs the exact saved program
through the existing executor with fresh observations; it does not regenerate
the movement. The ordinary Stop and command replacement owners still apply.
Receipts, feedback, faults and timing remain in the existing recording database.
The model server is not needed to test a saved correction.

Watch the physical trial. Save **Performed correctly** only after observing the
intended movement, timing, repetitions and ending. Record **Partly correct** or
**Incorrect movement** with what differed when another correction is needed.
Inspect the ending after the final receipt: a later output release, reported
stall, or loss of the requested posture is part of the trial result.
Completion receipts alone do not approve a training target. Only a completed
trial with an explicit successful operator review is exported as a physically
qualified positive example; its source correction IDs remain attached.

Keep candidate programs and trial evidence on DNDIY under the existing
`experiments/freestyle/artifacts/spatial-v8/pending-motion-review/` tree. The
Q6A audience-wave batch is `q6a-20261025-audience-wave/`; its `candidates.jsonl`
is staged evidence, not an addition to `train.jsonl`. Copy consistent SQLite
backups including committed WAL data and verify transfer checksums. After the
live trial and operator assessment, export the approved trial to the pending
training set there. Preserve failed attempts; do not rewrite the frozen v8 run.
### Per-motion recovery curriculum (target-control candidate)

`library_recovery.py` derives one jam and one measured-effect fall example per
current motion-bearing training row. It excludes face-only/Stop rows and
existing recovery rows. `recovery-coverage.json` links every derived row to its
source ID and content hash, lists omissions, and counts joint coverage.
Separate probes change the sensor
values; they share source goals and do not measure unseen-motion generalization.

```sh
python -m experiments.freestyle.library_recovery \
  --source /path/to/migrated-target-dataset \
  --output /path/to/recovery-dataset \
  --native-gait /path/to/freestyle_native_gait
```

Build the native sampler against matching current headers/libraries. Its output
is nominal gait geometry, not measured robot motion. Jam prefixes retreat from
the blocked direction and shorten the affected target while continuing the other
participating joints, or reduce an oscillation's excursion. The revised programs
end with normal standing targets. Fall examples repeat or reverse a preceding
correction according to its supplied before/after IMU orientation.
Faces vary across corrections. No new slip examples or detector are added.

Jam observations retain the commanded target of every participating shaft,
separately from its measured partial progress. This lets the correction continue
the other joints without asking the model to reconstruct their inverse kinematics.
Fall corrections vary between 1, 2, 3, 4, and 6 degrees in training; probes use
intermediate magnitudes. A constant three-degree response does not demonstrate
that the model used the supplied measured correction.

Evaluate complete generated programs as well as teacher-forced loss. In the
first recovery candidate, the reviewed wiggle predicted 463/464 reference tokens
correctly with the preceding reference tokens supplied, yet free generation chose
a different face and then emitted an invalid motion. Constrained generation also
repeated motion output indefinitely in one test. Neither low loss nor grammar
conformance establishes learned motion correctness. These were offline tests;
the failed candidate was not activated and no physical trial was performed.

Recovery compression retains the last measured correction/effect and the affected
shafts' recent distinct positions. The bridge keeps unfinished actions as input
context for a real body fault. A new generated plan replaces the previous plan;
an empty response does not replay it. Correction targets therefore need not
repeat the unfinished library program merely to keep its goal available.

All new feedback is synthetic and explicitly unqualified. Prefix target/FK checks
do not establish ground contact, balance, collision clearance, or successful
righting. An initial arbitrary fallen pose with no preceding measured correction
is still an uncovered training case. Native emotes absent from the editable
training library are not covered merely because their firmware names exist.
Existing nonterminal jam observations remain the recovery trigger. Obsolete
terminal-stall error/release reporting has been removed from the candidate;
explicit Stop and actual output-driver failures remain separate.
