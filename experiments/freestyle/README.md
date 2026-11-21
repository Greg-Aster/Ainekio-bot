# Twelve-Joint Freestyle & NeuralPose Movement

`experiments/freestyle/` owns one-shot natural-language 12-joint choreography generation (`generator.py`) and 50 Hz closed-loop sensorimotor execution (`neural_pose/`) for the V2 (`v2-12servo`) Ainekio body.

## Core Design Contract (Three-Part Separation)

1. **One-shot semantic choreography (`Freestyle`, `127.0.0.1:8794/generate`):** `generator.py` translates a natural-language or cognitive motion request into a compact 12-joint program **once** and hands it to `NeuralPose`. Body events (`servo_stall`, `tipped`, `rapid_movement`, `slip`) **never** re-invoke `/generate` or run LLM movement-recalculation loops.
2. **50 Hz closed-loop neural execution (`NeuralPose`, `neural_pose/`):** `executor.py` projects Freestyle operations onto the closed 4-bar manifold (`goals.py`) and streams 50 Hz `walk_target` foot offsets (`walk_nominal_v1`) from the trained equivariant residual MLP (`policy.onnx` via `neural-pose-active`). Reading live 4th-wire shaft angles, velocities, usability flags, and IMU orientation (`contract.py`), `NeuralPose` adapts on the fly—stepping splayed stance legs clear of carpet pile (`<= 5.0°` settle band, inside firmware's `6.5°` zero-heat zone), maintaining balance on slippery floors, rising from folded boot postures, and yielding compliantly on obstructed gesture limbs. When `NeuralPose` is active, `bridge.py` disables C-side `stand_enabled` (`stand_hold_recover`) on robot connection while preserving `jam_enabled: true`. Fix movement or standing defects in `neural_pose/` training or manifold kinematics—never via host-side post-motion clamps or LLM replanning.
3. **Independent hardware thermal protection (`ESP32-P4 jam_enabled`):** Separate from Freestyle, ESP32-P4 firmware's `I²t` thermal integrator (`ainekio_p4_feedback_thermal_step`) cuts servo PWM (`outputs_released: true`) only when a servo is genuinely mechanically bound or broken with no position progress for `~9–11 s`. `bridge.py` aborts any active job cleanly on `outputs_released: true`, and `environment_adapter` forwards that terminal `servo_stall` `body_event` to Ainekio OS (`fast-body-event-mode.json`) for user notification.

## Architecture and Module Ownership

| Module | Responsibility |
| --- | --- |
| `generator.py` & `ainekio-freestyle-api.service` | HTTP inference service (`127.0.0.1:8794/generate`) serving one-shot Freestyle programs from either the shared `llama-cpp` Qwen3.5-0.8B LoRA preset or Big Brother over SSH. |
| `big_brother.py` | Remote Big Brother provider delegating `/generate` tool-call inference to an Ainekio OS host (`codex`, `claude-code`, or `gemini`) over SSH with cancellation propagation. |
| `neural_pose/` (`contract.py`, `goals.py`, `actor.py`, `executor.py`, `mdp.py`, `trainer.py`) | 50 Hz closed-loop NeuralPose observation contract, closed 4-bar geodesic manifold projection, ONNX runtime actor, `walk_nominal_v1` executor, and MuJoCo Warp PPO + equivariant DAgger trainer. |
| `bridge.py` & `recordings.py` | Body Control `/api/freestyle` coordinator, `stand_enabled: false` connection sync, terminal `outputs_released: true` abort handling, SQLite trial/receipt recording, and operator review workflow (`awaiting_physical_trial` → approved positive examples). |
| `runtime.py`, `observations.py`, `program.py`, `compact_wire.py`, & `trajectory.py` | Sensor observation enrichment, compact wire serialization (`wire.json`), `face_contract.py` validation, and legacy `motion_plan_v2` fallback compilation when `walk_nominal_v1` is absent. |
| `motion_library.py` & `motion_library.js` / `body_control.js` | Editable reference motion library and Body Control UI controls (Freestyle prompt entry, generator endpoint setting, saved-correction live trials, and manual mode selection). |
| `freestyle_curriculum.py`, `semantic_teachers.py`, & `stand_curriculum.py` | One-shot compositional choreography and Stand curriculum builders (`training-data/`, zero event-recalculation rows). |
| `prepare.py`, `train_full.py`, `continue_training.py`, & `export_qwen.py` | Dataset tokenization/provenance verification, Unsloth Qwen3.5-0.8B LoRA/full-weight training entrypoints, and F16 GGUF LoRA export. |

## Shared Inference Deployment

Local Freestyle inference runs against the host's shared `llama-cpp.service` (`http://127.0.0.1:8080/v1`) rather than launching a duplicate base-model server; see [shared `llama.cpp` hosting](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/SYSTEM_ARCHITECTURE.md#shared-llamacpp-hosting):

- Load `FREESTYLE_ADAPTER_FILE` (`adapter.F16.gguf`) on the shared unmerged BF16 Qwen3.5-0.8B base preset with global scale `0` and F16 K/V caches.
- `generator.py` resolves the loaded adapter ID by path and supplies its per-request LoRA scale on `/v1/chat/completions`, leaving other cognitive roles on the same server unaffected.
- Inspect generated programs without dispatching physical movement:
  ```python
  import asyncio
  from experiments.freestyle.generator import async_remote_generate

  result = asyncio.run(async_remote_generate("http://127.0.0.1:8794", {"request": "Please stretch"}))
  print(result["program"])
  ```

## NeuralPose Training & Promotion

Train and qualify a `NeuralPose` policy candidate outside `neural-pose-active`, then promote only after passing the 3D MuJoCo qualification suite:

```sh
PYTHONPATH=. ./build/microduck-training-env/bin/python -m experiments.freestyle.neural_pose.trainer \
  --directory /tmp/neural-pose-candidate \
  --num-envs 512 \
  --iterations 110 \
  --device cuda:0

PYTHONPATH=.:Master:Slave/software ./build/microduck-training-env/bin/python \
  experiments/freestyle/test_neural_pose.py --qualify /tmp/neural-pose-candidate/policy.onnx
```

## Freestyle LoRA Curriculum & Live-Trial Review

- **Tracked contract (`training-data/`)**: Contains `system.txt`, `tools.json`, `wire.json`, `manifest.json`, `train.jsonl`, `evaluation.jsonl`, `regression-evaluation.jsonl`, and `reference-checks.json` (`category_balance: "none"`, pure one-shot choreography).
- **Corrected-motion review gate**: Operator-edited programs in Body Control start as `awaiting_physical_trial` and are excluded from training exports until replayed on the physical robot (**Saved motion trials → Perform selected correction**) and explicitly marked **Performed correctly** after verifying movement, timing, repetitions, and post-receipt posture stability.

## Validation

Run the Python and JavaScript Freestyle and NeuralPose test suites from the repository root:

```sh
PYTHONPATH=.:experiments/freestyle:Master:Slave/software \
  python3 -m unittest discover -s experiments/freestyle -t . -p 'test_*.py' -v

PYTHONPATH=.:Master:Slave/software \
  ./build/microduck-training-env/bin/python -m unittest discover -s experiments/freestyle -t . -p 'test_neural_pose.py' -v

node --test experiments/freestyle/test_body_control.js experiments/freestyle/test_motion_library_ui.js
```
