# Experimental V2 Freestyle

A removable dataset, generator, and opt-in Body Control executor for a
request-driven, twelve-joint motion model. Body Control and MetaHuman can call
the same standalone generator. Ordinary motion buttons retain their existing
behavior. The generator itself has no robot transport; the explicit Body
Control execution path sends commands through the existing gateway owner.

The live standalone service still uses the earlier compact-v2-recovery model on
the GPU. The spatial-v4 continuation is training; spatial candidates remain separate
until their generated programs have been evaluated. Body Control has loaded the
optional progress/settings/trial-export integration. No physical robot trials
have occurred in this refinement. Current run evidence is under ignored
`artifacts/spatial-v4/`; the external evaluation pipeline is described below.

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
before F16 export and Q4 quantization, allowing served F16/Q4 comparisons
without a separately applied quantized-base adapter.

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
Client disconnection cancels the pending downstream model connection. A two-hop
HTTP integration test verifies that cancellation reaches the model socket,
another request can complete concurrently, and a 1.1 MB history is preserved.
On 2026-10-22 the transient API service was restarted with the existing
aiohttp-capable environment and model-file provenance; the served model and
contract were unchanged. This connection test does not establish motion quality.

On 2026-10-21 the accepted Q4 model and API were started as transient user
services `ainekio-freestyle-model` and `ainekio-freestyle-api`. They do not
start automatically after reboot. The model now offloads all layers to the GPU,
with four CPU threads, two inference slots and 16,384 total context tokens (8,192 per slot); the
benchmarks used one slot. This permits overlapping requests without changing
the trained per-request context capacity. Stop both with:

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
and a separate opt-in for responding to existing body events. Settings are
session-only. No new event thresholds, cooldowns, sensor requirements, or
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
wire duration for that initial target. `reassess` requests fresh observations
and another generation; the model chooses the correction and whether to request
more feedback. All caller history is retained in that inference context.

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
The October 21–22 cleanup removed 11.40 GiB of obsolete exports and duplicate completed
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

The proposed `spatial-v5/dataset/` retains the v3 training fold, adds 492
constructed host-shaped recovery inputs, and gives the 27 reviewed new motion
examples eightfold training weight. This is 3,391 training rows, not 3,391
distinct motion skills. `refine_runtime_inputs.py` records the source/evidence
hashes and retains the original 446-example evaluation fold. Preparation fits
all examples within 4,609 tokens without truncation. Sixteen new external source
groups, with semantic requirements recorded before inference, are frozen in
`external/round-5-broad-cases.jsonl`. The v5 training has not started.

At the owner's requested pause point, v4 finished all 1,008 steps and final
evaluation in 3,859 seconds. The final adapter is saved in `spatial-v4/qwen-fit/`
(SHA-256 `77ec3f0efca1b23f039bb9ca859f20194b71fd4800f4fa83095ab38ee2bea9f7`).
It has not been exported or evaluated in serving. Final numeric evaluation loss
was 0.002048; that is not a motion-success score.

The completed epoch-two native-adapter comparison matched 3/4 checked references
(drinking, hand-circle and complete source Wave), versus 0/4 through Q4 serving.
Clapping still had an incorrect repeat count in the native output. Backend,
quantization and schema-constrained decoding differ in this comparison, so the
cause is not isolated. Investigate that mismatch before launching v5 training.
The epoch-two adapter, Q4 artifact and both outputs are retained for that work.
The temporary spatial comparison server and unused LFM baseline server were
stopped; the deployed compact Freestyle service remains available. No training
or evaluation job is intentionally left running. `spatial-v4/pause-point.json`
records the completed runs, prepared-data hashes and next actions.
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
training jobs. The candidates and all frozen source data are retained under
`artifacts/compact-v1/`. Both previously active production model services were
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
`comparison-provenance.json`. Candidate paths are `qwen-fit/adapter.F16.gguf`,
`lfm-fit-v2/adapter.F16.gguf`, and `needle-fit/model.W4.cact`. Original training
adapters are retained alongside those exports. Twelve source/contract/grading
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
