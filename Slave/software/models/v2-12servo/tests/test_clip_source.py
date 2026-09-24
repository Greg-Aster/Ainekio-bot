"""Compare compiled C positions and derivatives to the supplied independent reference."""
import importlib.util
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

family = Path(__file__).resolve().parents[1] / "motions/gestures"
catalog = json.loads((family / "catalog.json").read_text())
retained = catalog["timing_reference"]
timing_path = family / retained["path"]
assert hashlib.sha256(timing_path.read_bytes()).hexdigest() == retained["sha256"]
spec = importlib.util.spec_from_file_location("timing_reference", timing_path)
timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)
maximum = {"position": 0, "velocity": 0, "acceleration": 0}
count = 0
for item in catalog["commands"]:
    folder = family / item["path"]
    reference_path = folder / "sample_reference.py"
    spec = importlib.util.spec_from_file_location("source_reference", reference_path)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    motion = reference.Motion(folder)
    # Every original knot, plus an off-grid sample in every interval, entry and
    # exit joins, terminal hold and an arbitrarily late call (no wrap/overflow).
    times = {round(i * 1000000 / motion.hz) for i in range(len(motion.positions))}
    times.update(round((i + 0.371) * 1000000 / motion.hz) for i in range(len(motion.positions) - 1))
    contract_path = folder / "execution-contract.json"
    contract = json.loads(contract_path.read_text())
    schedule = timing.build_schedule(contract)
    command_duration_us = round(schedule["duration_s"] * 1000000)
    boundaries = [
        round(value * 1000000) for phase in json.loads(contract_path.read_text())["phases"] for value in phase["source_interval_s"]]
    for boundary in boundaries:
        times.update(t for t in (boundary - 1, boundary, boundary + 1) if t >= 0)
    times.add(2**64 - 1)
    times = sorted(times)
    result = subprocess.run([sys.argv[1]], input="".join(f'{item["command"]} {t}\n' for t in times),
                            capture_output=True, text=True, check=True)
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == len(times)
    for t, actual in zip(times, rows):
        expected = motion.sample(min(t, command_duration_us))
        if t >= command_duration_us:
            expected.update(complete=True, velocity=[0.0]*12, acceleration=[0.0]*12)
        assert actual["complete"] == expected["complete"]
        for key in maximum:
            assert len(actual[key]) == 12 and all(math.isfinite(v) for v in actual[key])
            maximum[key] = max(maximum[key], max(abs(a-b) for a, b in zip(actual[key], expected[key])))
    count += len(times)
# Certified fitting budget plus float32 arithmetic, in CAD centidegrees.
# Derivatives are metadata; PCA output consumes positions. Bound their numerical
# change too without claiming unchanged acceleration or physical tracking.
assert maximum["position"] < 0.502, maximum
assert maximum["velocity"] < 400 and maximum["acceleration"] < 200000, maximum

print(f"gestures: all twelve joints at {count} times; maximum numeric errors: {maximum}")
