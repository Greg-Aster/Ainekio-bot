import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime import JOINTS, MAX_FRAMES, completion_request, generate, validate_packet
from dataset import export, frames_for_clip, load_compiler

REPO = Path(__file__).resolve().parents[2]
MODEL = REPO/"Slave/software/models/v2-12servo"
sys.path.insert(0, str(REPO/"Slave/software"))
from protocol.joints_v2 import JOINT_LABELS
from protocol.control_v1 import validate_control_message


class FreestyleTests(unittest.TestCase):
    def test_existing_v2_wire_contract_and_physical_joint_order(self):
        self.assertEqual(JOINTS, JOINT_LABELS)
        packet = validate_packet({"frames": [[21, [-10320, 2200, -6000]*4]],
                                  "complete": True, "end": "hold"})
        validate_control_message({"t": "motion_plan", "seq": 1, "map": 2,
                          "frames": packet["frames"], "end": packet["end"]})

    def test_feedback_and_history_reach_model_unchanged(self):
        request = {"request": "Continue waving", "event": {"kind": "jam", "joint_mask": 64},
                   "observation": {"measured_joints_cd": [1]*12, "imu": None},
                   "history": [{"sequence": n} for n in range(300)]}
        original = copy.deepcopy(request)
        payload = completion_request(request, "experimental")
        self.assertEqual(json.loads(payload["messages"][1]["content"]), original)
        self.assertEqual(request, original)
        self.assertNotIn("max_tokens", payload)

    def test_inference_only_calls_selected_model(self):
        packet = {"frames": [[500, [0]*12]], "complete": True, "end": "hold"}
        response = {"model": "test", "choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps(packet)}}], "usage": {"completion_tokens": 20}}
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as call:
            result = generate("http://localhost:8092/v1", "test", {"request": "point", "robot_id": "robot-a"})
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0].full_url, "http://localhost:8092/v1/chat/completions")
        self.assertEqual(result["execution"], "not_dispatched")
        self.assertEqual(result["packet"], packet)

    def test_evaluation_uses_frozen_messages(self):
        frozen = [{"role": "system", "content": "Frozen training contract"},
                  {"role": "user", "content": "Frozen observation"}]
        self.assertEqual(completion_request({}, "test", frozen)["messages"], frozen)

    def test_truncated_generation_is_not_presented_as_complete(self):
        result = {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(result).encode())):
            with self.assertRaisesRegex(ValueError, "did not finish"):
                generate("http://localhost:8092/v1", "test", {"request": "wave"})

    def test_packet_overflow_is_not_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, "32 frames"):
            validate_packet({"frames": [[20, [0]*12]]*33, "complete": True, "end": "hold"})

    def test_all_motion_sources_retain_duration_extrema_and_samples(self):
        compiler = load_compiler(MODEL)
        for clip in compiler.load_gestures(MODEL):
            with self.subTest(motion=clip["command"]):
                first, frames, report = frames_for_clip(clip, compiler)
                self.assertEqual(sum(f[0] for f in frames), round(clip["duration_s"]*1000))
                self.assertEqual(frames[-1][1], [round(v) for v in clip["positions"][-1]])
                endpoints = {0: first}
                t = 0
                for duration, row in frames:
                    t += duration
                    endpoints[t] = row
                for index in compiler.gesture_targets(clip["positions"], clip["phases"]):
                    self.assertEqual(endpoints[round(index*1000/120)], [round(v) for v in clip["positions"][index]])
                previous, start, n = first, 0, 0
                for index, expected in enumerate(clip["positions"]):
                    at = round(index*1000/120)
                    while at > start+frames[n][0]:
                        duration, previous = frames[n]
                        start += duration
                        n += 1
                    duration, target = frames[n]
                    u = (at-start)/duration
                    error = max(abs(previous[j]+u*(target[j]-previous[j])-expected[j]) for j in range(12))
                    self.assertLessEqual(error, .500001)

    def test_dataset_packets_reassemble_and_families_do_not_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/"dataset"
            result = export(MODEL, target, {"wave", "swim"})
            self.assertEqual(result["recovery_examples"], 0)
            rows = {split: [json.loads(s) for s in (target/(split+".jsonl")).read_text().splitlines()]
                    for split in ("train", "evaluation")}
            families = [{r["metadata"]["motion_family"] for r in part} for part in rows.values()]
            self.assertFalse(families[0] & families[1])
            wave = [r for r in rows["evaluation"] if r["id"].startswith("wave:0:")]
            source = json.loads((MODEL/"motions/gestures/wave/manifest.json").read_text())
            elapsed = 0
            for index, row in enumerate(wave):
                request = json.loads(row["messages"][1]["content"])
                packet = validate_packet(json.loads(row["messages"][2]["content"]))
                self.assertEqual(request["progress"]["reference_elapsed_ms"], elapsed)
                self.assertEqual(packet["complete"], index == len(wave)-1)
                self.assertLessEqual(len(packet["frames"]), MAX_FRAMES)
                elapsed += sum(f[0] for f in packet["frames"])
            self.assertEqual(elapsed, round(source["duration_seconds"]*1000))


if __name__ == "__main__":
    unittest.main()
