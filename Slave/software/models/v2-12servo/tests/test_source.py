"""Compare the compiled C sampler against the independently retained source."""
import json
import math
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
source = json.loads((root / "motions/walk/source.json").read_text())
samples = source["samples"]
times = list(range(0, 32400001, 25000))  # three cycles reconstruct the full source clip
times += [12200000,16200000,20200000,24200000,32400000]
result = subprocess.run([sys.argv[1]], input="".join(f"3 {t}\n" for t in times),
                        capture_output=True,text=True,check=True)
rows = [json.loads(line) for line in result.stdout.splitlines()]
assert len(rows)==len(times)
maximum_error = 0
for t, actual in zip(times, rows):
    expected = [math.degrees(v)*100 for leg in samples[round(t*120/1e6)]["actuator_angles_rad"] for v in leg]
    assert len(actual)==12
    maximum_error = max(maximum_error,max(abs(a-b) for a,b in zip(actual,expected)))
assert maximum_error < .002, maximum_error  # 0.00002 degree tolerance at source knots
print(f"Compiled C sampler matches all 12 source joints at {len(times)} times; max error {maximum_error/100:.9g} degrees.")
