"""Generation-only evaluation against frozen examples; never dispatches actions."""
import argparse
import json
import math
import os
from pathlib import Path

from runtime import compact, generate, validate_packet


def comparison(expected, actual):
    """Reference agreement is descriptive, not a physical success verdict."""
    expected_frames, actual_frames = expected["frames"], actual["frames"]
    final_error = None
    if expected_frames and actual_frames:
        final_error = math.sqrt(sum(((a-b)/100)**2 for a, b in
                                   zip(expected_frames[-1][1], actual_frames[-1][1]))/12)
    return {"exact_reference_packet": expected == actual,
            "expected_frames": len(expected_frames), "generated_frames": len(actual_frames),
            "expected_duration_ms": sum(f[0] for f in expected_frames),
            "generated_duration_ms": sum(f[0] for f in actual_frames),
            "final_reference_error_rms_deg": final_error,
            "completion_agreement": expected["complete"] == actual["complete"],
            "physical_success": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", default="ainekio-freestyle")
    parser.add_argument("--ids", nargs="+", help="Explicit subset; omitted means all records")
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    chosen = set(args.ids) if args.ids else {r["id"] for r in rows}
    if chosen - {r["id"] for r in rows}:
        parser.error("Unknown record id")
    for row in rows:
        if row["id"] not in chosen:
            continue
        request = json.loads(row["messages"][-2]["content"])
        expected = validate_packet(json.loads(row["messages"][-1]["content"]))
        try:
            generated = generate(args.endpoint, args.model, request, os.environ.get("FREESTYLE_API_KEY"),
                                 model_messages=row["messages"][:-1])
            print(compact({"id": row["id"], "valid_packet": True, **generated,
                           "comparison": comparison(expected, generated["packet"])}), flush=True)
        except (ValueError, KeyError) as error:
            print(compact({"id": row["id"], "valid_packet": False, "error": str(error),
                           "execution": "not_dispatched"}), flush=True)
