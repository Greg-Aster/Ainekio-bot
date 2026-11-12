# Twelve-Joint Freestyle Movement

`experiments/freestyle/` owns natural-language 12-joint choreography generation, closed-chain IK validation, compact wire compilation, event-triggered recovery, and training data preparation for the V2 (`v2-12servo`) Ainekio body.

## Architecture and Module Ownership

| Module | Responsibility |
| --- | --- |
| `generator.py` & `ainekio-freestyle-api.service` | HTTP inference service (`127.0.0.1:8794/generate`) serving Freestyle programs from either the shared `llama-cpp` Qwen LoRA preset or Big Brother over SSH. |
| `big_brother.py` | Remote Big Brother provider delegating `/generate` tool-call inference to an Ainekio OS host (`codex`, `claude-code`, or `gemini`) over SSH with cancellation propagation. |
| `runtime.py` & `observations.py` | Prompt/observation assembly (`feedback_range_deg`, `arrival_tolerance_deg`, `feedback_usable`, `feedback_faults`, IMU state, and `motion_goal` recovery context) without silent truncation. |
| `program.py`, `compact_wire.py`, & `trajectory.py` | Compact wire operation parsing, linear/cubic trajectory compilation into `motion_plan_v2` (`map: 2`, 1–32 frames of `[duration_ms, [12 centidegree targets]]`), and `face_contract.py` validation. |
| `kinematics.py`, `stand_geometry.c`, & `native_gait.c` | Closed-chain 4-bar linkage feasibility checks, foot-space kinematics, and native C geometry samplers. |
| `bridge.py` & `recordings.py` | Body Control `/api/freestyle` execution coordinator, SQLite trial/receipt recording, operator review workflow (`awaiting_physical_trial` → approved positive examples), and job cancellation. |
| `motion_library.py` & `motion_library.js` / `body_control.js` | Editable reference motion library and Body Control UI controls (Freestyle prompt entry, saved-correction live trials, and manual mode selection). |
| `freestyle_curriculum.py`, `semantic_teachers.py`, `stand_curriculum.py`, & `library_recovery.py` | Consolidated curriculum builders for semantic poses/gestures, Stand transitions, and synthetic jam/repeated-jam/fall recovery lessons (`training-data/`). |
| `prepare.py`, `train_full.py`, `continue_training.py`, & `export_qwen.py` | Dataset tokenization/provenance verification, Unsloth Qwen3.5-0.8B LoRA/full-weight training entrypoints, and F16 GGUF LoRA export. |

## Shared Inference Deployment

Local Freestyle inference runs against the host's shared `llama-cpp.service` (`http://127.0.0.1:8080/v1`) rather than launching a duplicate base-model server; see [shared `llama.cpp` hosting](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/SYSTEM_ARCHITECTURE.md#shared-llamacpp-hosting):

- Load the `FREESTYLE_ADAPTER_FILE` (`adapter.F16.gguf`) on the shared unmerged BF16 Qwen3.5-0.8B base preset with global scale `0` and F16 K/V caches.
- `generator.py` resolves the loaded adapter ID by path and supplies its per-request LoRA scale on `/v1/chat/completions`, leaving other cognitive roles on the same server unaffected.
- Inspect generated programs without dispatching physical movement:
  ```python
  import asyncio
  from experiments.freestyle.generator import async_remote_generate

  result = asyncio.run(async_remote_generate("http://127.0.0.1:8794", {"request": "Please stretch"}))
  print(result["program"])
  ```

## Big Brother inference

`generator.py` can also route `/generate` requests through an Ainekio OS installation's Big Brother provider over SSH while keeping the identical Body Control execution boundary:

```sh
python3 -m experiments.freestyle.generator \
  --big-brother-ssh <ainekio-os-host> --metahuman-root /path/to/ainekio-os \
  --profile Ainekio --model gpt-5.4 \
  --contract experiments/freestyle/training-data
```

- Uses an existing SSH key and verified `known_hosts` entry (`--ssh-option HostName=...` when needed) and stores no browser session cookies.
- Sends the canonical tool schema, `training-data/system.txt`, live joint/IMU observations, and recovery history with reasoning disabled for low latency.
- Client cancellation propagates across SSH to the Big Brother session; provider errors fail explicitly without substituting a scripted fallback motion.

## Execution, 4th-Wire Arrival, and Event-Triggered Recovery

- **Single execution owner**: Body Control (`bridge.py` + `Master/gateway/server/service.py`) owns robot selection, sequence admission, and `motion_plan_v2` dispatch. A generated program runs once; P4 firmware verifies measured 4th-wire potentiometer arrival at each resolved target (`position_verified` and `target_adjusted_joints` on `done`).
- **Cancellation & Stop**: `POST /api/freestyle` with `{"operation": "cancel", "robot_id": "...", "job_id": "..."}` cancels an active Freestyle job while preserving prior receipts. `stop` / `release` settle on gateway command acknowledgement without invoking Freestyle.
- **Recovery-first jam, fault, & fall handling**: Non-releasing `servo_stall` (`outputs_released: false`), `servo_feedback_fault`, `tipped`, and slip events trigger opt-in Freestyle recovery while the active hold or command remains energized. Recovery context preserves the original `motion_goal` alongside `program_state`, `interrupted_action` / `failed_action`, `completed_action`, and measured shaft progress so corrective motions do not overwrite the user's original intent.

## Curriculum Preparation, Training, and Live-Trial Review

- **Tracked contract (`training-data/`)**: Contains `system.txt`, `tools.json`, `wire.json`, `manifest.json`, `train.jsonl`, `evaluation.jsonl`, `regression-evaluation.jsonl`, `recovery-probe.jsonl`, and `recovery-coverage.json`.
- **Training & GGUF export**:
  ```sh
  # Build synthetic jam/fall recovery rows against the native gait geometry sampler
  python3 -m experiments.freestyle.library_recovery \
    --source experiments/freestyle/training-data \
    --output /tmp/freestyle-recovery \
    --native-gait /path/to/freestyle_native_gait

  # Fit or continue training a Qwen3.5-0.8B candidate outside tracked source
  python3 -m experiments.freestyle.continue_training --help
  python3 -m experiments.freestyle.export_qwen --help
  ```
- **Corrected-motion review gate**: Operator-edited programs in Body Control start as `awaiting_physical_trial` and are excluded from training exports until replayed on the physical robot (**Load saved corrections → Test selected correction**) and explicitly marked **Performed correctly** after verifying movement, timing, repetitions, and post-receipt posture stability.

## Validation

Run the Python and JavaScript Freestyle test suites from the repository root:

```sh
PYTHONPATH=.:experiments/freestyle:Master:Slave/software \
  python3 -m unittest discover -s experiments/freestyle -t . -p 'test_*.py' -v

node --test experiments/freestyle/test_body_control.js experiments/freestyle/test_motion_library_ui.js
```
