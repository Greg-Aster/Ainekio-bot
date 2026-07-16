# Local Ainekio microWakeWord Workflow

The robot uses the open microWakeWord/TensorFlow Lite Micro format. Model sample
generation, training, evaluation, packaging, and inference must run on owner
hardware. Do not upload voice recordings, generated samples, feature sets, or
trained weights to an outside training service.

The firmware engine is implemented, but this repository intentionally contains
no pretend or unvalidated `Ainekio` model. First boot therefore remains
`wake_enabled=false`, and firmware reports `wake_ready=false` until a valid local
package is present in LittleFS.

## 0. Frozen pronunciation target

The owner-selected reference is `01-ay-neck-ee-oh.wav`. Piper maps the
continuous generator spelling `Ay-neck-ee-oh` to the approximate IPA target
`/aɪ nɛk iː oʊ/`: `eye`, `neck`, long E, long O. Keep that phoneme sequence
fixed across positive sample generation. Do not mix in the `/eɪ/` long-A,
`ah-nek-ee-oh`, or `uh-nek-ee-oh` variants.

The accepted listening reference and comparison checks are outside the
repository at:

```text
/home/greggles/ainekio-wake-training/pronunciation-check/
  01-ay-neck-ee-oh.wav                 # accepted reference
  target-a-nek-io-lessac.wav
  target-a-nek-io-amy.wav
  target-a-nek-io-joe.wav
```

The three `target-a-nek-io-*` files use the rejected `/eɪ/` variant and must not
be included as positives. The first synthetic corpus should favor medium male
English samples because that resembles the owner's voice, while retaining
other English voices to avoid overfitting. Owner recordings are now present in
the pilot train, validation, and test splits, but the independent held-out sets
remain too small to accept a production model.

### Local seed corpus checkpoint

The first positive seed set is stored outside the repository at
`/home/greggles/ainekio-wake-training/positive-corpus/v1`. It contains 96
unique English Piper samples using only the accepted `Ay-neck-ee-oh` phoneme
target:

- 48 Joe medium samples;
- 24 Ryan samples;
- 12 Lessac medium samples;
- 12 Amy medium samples.

This makes the seed set 75 percent male-voice samples while retaining a small
cross-voice check. Speaking length, synthesis noise, and phoneme-width values
vary in the filenames. Validation confirmed 96 unique mono 16-bit WAV files,
durations from 0.704 to 1.400 seconds, and valid 40-channel microWakeWord
features after 16 kHz resampling. This is a pipeline seed, not enough data to
train or accept the production model.

## 1. Keep training data outside the repository

Use a separate workspace with enough free disk. Training audio, generated
features, downloaded negative datasets, notebooks with outputs, and checkpoints
do not belong in this repository.

```sh
mkdir -p /home/greggles/ainekio-wake-training
cd /home/greggles/ainekio-wake-training
git clone https://github.com/OHF-Voice/micro-wake-word.git
cd micro-wake-word
git checkout 4665173cd35f1cff9a61e06fc427f124766c488e
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install jupyter tensorboard
```

Commit `4665173cd35f1cff9a61e06fc427f124766c488e` is the upstream revision reviewed
for this integration. Re-review its model contract before deliberately moving to
a newer revision. The upstream basic notebook contains the remaining pinned
Python dependencies and is the maintained starting point:

```sh
jupyter lab notebooks/basic_training_notebook.ipynb
```

On the current Linux host, the isolated Python 3.10 environment lives at
`/home/greggles/ainekio-wake-training/.venv`. TensorFlow's pip-provided CUDA
libraries are not in the process loader path by default on this machine. Run
training commands through the repository launcher so it selects that virtual
environment and exposes only its local NVIDIA libraries:

```sh
Slave/software/tools/run_local_wake_word.sh python -c \
  "import tensorflow as tf; print(tf.config.list_physical_devices('GPU'))"
```

Set `AINEKIO_WAKE_TRAINING_ROOT` only if the external workspace is moved. The
launcher does not download data, start training, or stop other GPU workloads.

Downloading open-source code, a local Piper voice, or a properly licensed
negative corpus is not an outside training service; the processing still occurs
locally. Record every source, version, URL, and license in a local dataset ledger.
Do not assume that a convenient mixed training corpus can be redistributed with
the final model.

### Owner recordings and `pilot-v1` checkpoint

The 13 owner recordings remain outside the repository at
`/home/greggles/ainekio-wake-training/owner-recordings/raw`. Inspection found
that every file was already 16 kHz, mono, signed 16-bit PCM, with durations from
0.714 to 1.166 seconds. The originals were not modified.

Because the recordings sounded slightly high, a second pool was generated at
`/home/greggles/ainekio-wake-training/owner-recordings/corrected-speed-0p91875`
using SoX `speed 0.91875` followed by high-quality resampling to 16 kHz. This is
the exact 44.1/48 replay-speed ratio: it lowers both pitch and tempo. Validation
of all 13 pairs measured a median duration ratio of 1.08842 and median pitch
ratio of 0.91751. All 26 files produced valid 40-channel features.

The repository preparation tool builds a reproducible local pilot workspace:

```sh
Slave/software/tools/run_local_wake_word.sh \
  python Slave/software/tools/prepare_local_wake_word_pilot.py
```

It refuses to overwrite an existing run and records paths, counts, hashes, and
split membership in the external run's `provenance.json`. Each original and its
speed-corrected derivative stay in the same split so a derivative cannot leak
from training into validation or testing.

The completed external `pilot-v1` run used:

- 72/12/12 synthetic positives for training/validation/testing;
- 18/4/4 owner-positive files, representing 9/2/2 independent original pairs;
- 64/16/16 locally generated similar-speech negatives;
- 32 generated training-noise clips; and
- four 10-second generated ambient clips for each of validation and testing.

The 2,000-step GPU run selected the step-1,800 weights. Its nonstreaming
validation result was AUC 0.96421, 87.50 percent accuracy, 81.25 percent recall,
92.86 percent precision, and 93.75 percent recall at a cutoff with no accepts in
the short validation ambient set. The step-2,000 result was similar: AUC
0.96396. The quantized streaming test detected all 16 held-out positive files at
the evaluator's approximately 0.66 cutoff. Its reported AUC of 0.00000 describes
the two-point, false-rejection-versus-capped-FAPH curve; it is not evidence of a
bad conversion or a production-quality false-accept rate.

The companion quantized test scores both the 16 held-out positives and 16
held-out similar-speech negatives at its fixed 0.5 cutoff. It measured 81.25
percent accuracy, 75.00 percent recall, 85.71 percent precision, a 12.50 percent
false-positive rate, and a 25.00 percent false-negative rate. In concrete terms,
it detected 12 of 16 positives, missed four, rejected 14 of 16 hard negatives,
and falsely accepted two. This result confirms that `pilot-v1` is useful for
testing the complete local pipeline but does not meet a production acceptance
bar.

The evaluation artifact is:

```text
/home/greggles/ainekio-wake-training/runs/pilot-v1/model/
  tflite_stream_state_internal_quant/stream_state_internal_quant.tflite
```

It is 62,304 bytes with SHA-256
`d544fe90823654e6512c8379ab1ae383b3bfc75bfb5c6acdfc57a919aed4d0d3`.
Host inspection confirmed an int8 `[1,3,40]` input and uint8 `[1,1]` output,
matching the firmware service contract. This pilot is deliberately not copied
to the firmware seed assets: the corrected files are derivatives, the held-out
owner set contains only two independent recordings, and 40 seconds of generated
ambient audio cannot validate false accepts per hour on the real robot.

## 2. Freeze the pronunciation before generating samples

The owner-selected pronunciation is frozen in section 0. Before deliberately
changing that target or generating a replacement corpus, test the notebook's
`target_word` or phonetic spelling by generating one sample and listening to it.
Do not start a large run until the sample sounds like the intended name.

Generate positive samples locally with Piper, include varied voices, speeds,
pitches, noise levels, and distances. Retain owner recordings only under the
owner's explicit local retention rules. Build hard negatives that include
similar-sounding phrases, normal conversation, robot speaker output, music,
television, fan noise, and the actual room background.

The current upstream notebook starts with 1,000 synthetic positives. That is a
pipeline check, not an acceptance target. A usable model normally requires more
data and repeated tuning.

## 3. Train and export the quantized streaming model

Use 16 kHz mono signed-16-bit input and preserve the upstream frontend contract:
40 features, a 30 ms analysis window, and a 10 ms feature step. Complete the
notebook's augmentation, feature generation, training, and streaming evaluation.
The firmware consumes the final quantized artifact:

```text
trained_models/wakeword/tflite_stream_state_internal_quant/
  stream_state_internal_quant.tflite
```

Do not accept a model only because training accuracy is high. Measure at least:

- false accepts per hour over long local ambient recordings;
- successful detection across multiple speakers, volumes, distances, and angles;
- similar-sounding hard negatives;
- microphone gain/noise on the real INMP441 installation;
- coexistence with WiFi, camera capture, servo movement, and robot speaker audio.

Keep the final probability cutoff, sliding-window size, and tensor-arena value
with the evaluation record. The defaults below are packaging starting points,
not validated Ainekio thresholds.

## 4. Build the Ainekio model package

From the Ainekio repository root, package only the locally trained `.tflite`
file. Replace the example provenance values with the real dataset/model record:

```sh
python3 Slave/software/tools/package_micro_wake_word.py \
  --model /home/greggles/ainekio-wake-training/micro-wake-word/trained_models/wakeword/tflite_stream_state_internal_quant/stream_state_internal_quant.tflite \
  --output-dir Slave/software/assets/seed/wake/ainekio \
  --id ainekio \
  --wake-word Ainekio \
  --author "Ainekio local training" \
  --license "REPLACE-WITH-VERIFIED-MODEL-LICENSE" \
  --training-revision "REPLACE-WITH-LOCAL-REVISION" \
  --trained-language en \
  --probability-cutoff 0.97 \
  --feature-step-size 10 \
  --sliding-window-size 5 \
  --tensor-arena-size 26080
```

The tool refuses accidental replacement unless `--replace` is supplied. It
copies the model unchanged and writes `manifest.json` using schema
`ainekio-microwakeword-v1`, including the model SHA-256 and required provenance.

At boot, firmware accepts the package only after checking the bounded manifest,
SHA-256, TFLite FlatBuffer, supported operator set, quantized tensor contract,
and runtime arena allocation. Only then does status report `wake_ready=true`.

## 5. Install and validate

The current preparation path builds the package into the LittleFS image. The
LittleFS partition can be rebuilt and flashed without replacing either OTA
application slot:

```sh
cd Slave/firmware/esp32s3
source /home/greggles/esp/esp-idf-v5.5.4/export.sh
idf.py build
idf.py littlefs-flash
```

After reboot, confirm `wake_ready=true` while `wake_enabled` remains false. Enable
the model through the authenticated gateway/dashboard, then issue microphone
mode `gate=wake`. In this mode, PCM stays local until detection. A detection
emits the wake event and opens bounded VAD forwarding; about 700 ms of silence
closes the utterance and rearms the detector after its warm-up interval.

An authenticated network model upload/activation/rollback protocol is still a
separate pending feature. Until that exists, changing model bytes does not
require rebuilding the application, but it does require updating LittleFS.
