"""Small shared artifact operations; importing inference does not import training."""
import json
from pathlib import Path
from uuid import uuid4


def save_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, indent=2, allow_nan=False))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def summarize_commands(episodes):
    """Measured progress for each requested twist, including request transitions.

    Older artifacts without command-frame measurements remain unavailable;
    world-frame displacement cannot substitute for these measurements.
    """
    grouped = {}
    for episode in episodes:
        for segment in episode.get("command_segments") or [episode]:
            required = ("command", "seconds", "command_reference_travel_m", "heading_change_rad", "reward")
            if any(key not in segment for key in required) or segment["seconds"] <= 0:
                return None
            key = tuple(segment["command"])
            row = grouped.setdefault(key, dict(command=list(key), seconds=0.,
                travel=[0.,0.], heading=0., reward=0.))
            row["seconds"] += segment["seconds"]
            for axis in range(2):
                row["travel"][axis] += segment["command_reference_travel_m"][axis]
            row["heading"] += segment["heading_change_rad"]
            row["reward"] += segment["reward"]
    return [dict(command=row["command"], seconds=row["seconds"],
                 measured_velocity_command_m_s=[value/row["seconds"] for value in row["travel"]],
                 measured_yaw_rate_rad_s=row["heading"]/row["seconds"],
                 mean_reward_per_second=row["reward"]/row["seconds"])
            for row in grouped.values()]
