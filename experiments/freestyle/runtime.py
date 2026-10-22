"""Isolated V2 Freestyle client. Calls llama.cpp; never contacts a robot."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

JOINTS = tuple(f"{leg}_{axis}" for leg in
               ("rear_left", "rear_right", "front_left", "front_right")
               for axis in ("shoulder", "carrier", "crank"))
MAX_FRAMES = 32  # Existing motion_plan_v2 packet capacity, not a model token cap.
SYSTEM = """You generate motion for Ainekio V2, a twelve-joint quadruped.
Use the supplied request, body description, observations and execution history.
Choose movement, coordination, timing and any recovery from that information.
Observations may describe a jam or a fall. These are evidence about the current
situation, not instructions to use a fixed recovery. Commanded positions and
authored reference positions are not measured positions. Unknown values remain
unknown. The camera is fixed to the body; there is no independent head joint.
Return only JSON with frames, complete and end. Each frame is
[duration_ms,[twelve absolute signed model angles in centidegrees]]. Joint order
is rear-left shoulder/carrier/crank, rear-right shoulder/carrier/crank,
front-left shoulder/carrier/crank, front-right shoulder/carrier/crank.
These are geometric angles, not electrical servo angles or PWM values.
The P4 interpolates linearly from the preceding target over each frame duration.
Repeated targets express intentional holds. Durations are individual positive
integer milliseconds. The existing packet holds at most 32 frames. Generate
the next packet; complete is true only when the requested movement is finished.
For a continuation, use the supplied execution progress and current observation.
end is hold, stand or neutral; use hold for an unfinished packet so that a packet
boundary does not insert a different pose. There is no instruction to shorten
a movement to fit one packet. An empty frames array represents no new movement.
"""

TARGETS_SCHEMA = {"type": "array", "minItems": 12, "maxItems": 12,
                  "items": {"type": "integer", "minimum": -(1 << 31), "maximum": (1 << 31)-1}}
OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["frames", "complete", "end"],
    "properties": {
        "frames": {"type": "array", "maxItems": MAX_FRAMES, "items": {
            "type": "array", "minItems": 2, "maxItems": 2,
            "prefixItems": [{"type": "integer", "minimum": 1, "maximum": (1 << 32)-1},
                            TARGETS_SCHEMA]}},
        "complete": {"type": "boolean"},
        "end": {"type": "string", "enum": ["hold", "stand", "neutral"]},
    },
}


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def messages(request):
    """Preserve all caller evidence. No history truncation or keyword routing."""
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": compact(request)}]


def validate_packet(value):
    """Structural/wire-format validation only; does not qualify physical motion."""
    if not isinstance(value, dict) or set(value) != {"frames", "complete", "end"}:
        raise ValueError("Expected frames, complete and end")
    if type(value["complete"]) is not bool or value["end"] not in ("hold", "stand", "neutral"):
        raise ValueError("Invalid completion or end pose")
    frames = value["frames"]
    if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
        raise ValueError("The existing V2 packet holds at most 32 frames")
    for frame in frames:
        if not isinstance(frame, list) or len(frame) != 2:
            raise ValueError("Expected [duration_ms, targets]")
        duration, targets = frame
        if type(duration) is not int or not 1 <= duration <= (1 << 32)-1:
            raise ValueError("Duration must fit the V2 uint32 millisecond field")
        if not isinstance(targets, list) or len(targets) != 12 or any(
                type(v) is not int or not -(1 << 31) <= v < (1 << 31) for v in targets):
            raise ValueError("Expected twelve signed int32 model centidegrees")
    if not value["complete"] and value["end"] != "hold":
        raise ValueError("An unfinished packet must retain its target at the packet boundary")
    return value


def completion_request(request, model, model_messages=None):
    return {"model": model, "messages": messages(request) if model_messages is None else model_messages, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "ainekio_freestyle_v2", "strict": True, "schema": OUTPUT_SCHEMA}}}


def generate(endpoint, model, request, api_key=None, model_messages=None):
    started = time.monotonic()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    payload = completion_request(request, model, model_messages)
    call = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions",
                                  data=compact(payload).encode(), headers=headers)
    # No artificial inference deadline, retries, service switching or robot I/O.
    try:
        with urllib.request.urlopen(call) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise ValueError(f"Model server HTTP {error.code}: {error.read().decode()}") from error
    choice = result["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise ValueError(f"Model did not finish its packet: {choice.get('finish_reason')}")
    packet = validate_packet(json.loads(choice["message"]["content"]))
    return {"request_id": request.get("request_id"), "robot_id": request.get("robot_id"),
            "packet": packet, "model": result.get("model", model),
            "elapsed_s": time.monotonic()-started, "usage": result.get("usage"),
            "execution": "not_dispatched"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--endpoint", help="llama.cpp API base, e.g. http://127.0.0.1:8092/v1")
    parser.add_argument("--model", default="ainekio-freestyle")
    parser.add_argument("--api-key-env", default="FREESTYLE_API_KEY")
    parser.add_argument("--print-payload", action="store_true", help="Print exact inference payload without a network call")
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    if args.print_payload:
        result = completion_request(request, args.model)
    else:
        if not args.endpoint:
            parser.error("--endpoint is required for inference")
        result = generate(args.endpoint, args.model, request, os.environ.get(args.api_key_env))
    print(compact(result))


if __name__ == "__main__":
    main()
