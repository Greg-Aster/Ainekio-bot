"""Host-side, context-conditioned gait search. No robot or PWM authority.

BoTorch is imported only by propose(). Logging and ordinary movement do not
depend on PyTorch. Search coordinates describe coordinated linkage-space gait
changes; exported policies still use the existing P4 IK and feedback owner.
"""
from __future__ import annotations

import copy
import math


PRIORITIES = ("forward", "backward", "turning", "run")
# These are exploration radii around the incumbent, not actuator restrictions.
DEFAULT_RADII = {
    "duty": .03, "sweep_mm": 8., "front_lift_mm": 4., "rear_lift_mm": 4.,
    "front_landing_mm": 4., "rear_landing_mm": 4., "height_mm": 3.,
    "tilt_feedback_mm": 1.,
    "joint_response_mm": 1.,
}
DEFAULT_WEIGHTS = {
    "progress_m_s": 1., "turn_rad_s": .08, "yaw_tracking_error_rad_s": -.16,
    "lateral_m_s": -.5, "tilt_rms_rad": -.1, "angular_rms_rad_s": -.015,
    "tracking_rms_mm": -.001,
    "acceleration_deviation_rms_m_s2": -.005,
}


def context(command, gait="walk"):
    """Actual P4 interpolated command: forward, turn, lateral, stride."""
    forward, turn, lateral, stride = map(float, command)
    if gait == "run":
        return "run"
    if gait != "walk" or lateral:
        return None
    if abs(turn) > abs(forward):
        return "turning"
    return "backward" if forward < 0 else "forward"


def candidate(base, coordinates, radii):
    if len(coordinates) != len(DEFAULT_RADII) or set(radii) != set(DEFAULT_RADII):
        raise ValueError("Expected nine named exploration radii and coordinates")
    if any(not math.isfinite(x) for x in coordinates) or any(
            not math.isfinite(x) or x < 0 for x in radii.values()):
        raise ValueError("Exploration coordinates must be finite; radii nonnegative")
    model = copy.deepcopy(base)
    if model["schema"] != "gait_learning_v4":
        raise ValueError("Automatic learning requires the command-conditioned v4 policy")
    delta = dict(zip(DEFAULT_RADII, (coordinates[i]*radii[k] for i, k in enumerate(DEFAULT_RADII))))
    p = model["gait_profile"]
    p[0] += delta["duty"]
    p[1] += delta["sweep_mm"]
    # Contract order RL RR FL FR. Coordinated front/rear pairs retain the
    # existing footfall pattern, including Run's bounding pattern.
    for leg in range(4):
        pair = "rear" if leg < 2 else "front"
        p[6+leg] += delta[pair+"_lift_mm"]
        p[10+leg*2] += delta[pair+"_landing_mm"]
        # Existing feature sign convention belongs to the P4. Exploration is
        # symmetric; it does not reinterpret or reverse the calibrated IMU.
        side = 1. if leg % 2 == 0 else -1.
        fore = -1. if leg < 2 else 1.
        model["feedback_coefficients"][leg*24+16+3] += side*delta["tilt_feedback_mm"]
        model["feedback_coefficients"][leg*24+16+4] += fore*delta["tilt_feedback_mm"]
        for axis in range(3):
            model["feedback_coefficients"][leg*24+axis*8+axis] += delta["joint_response_mm"]
    p[28] += delta["height_mm"]  # body z constant term
    # Persist/hash exactly the float32 coefficients executed by the firmware.
    from .gait_training import vector, with_vector
    return with_vector(model, vector(model))


def measured_score(samples, poses, weights=None):
    """Evaluate matching measured motion, never commanded distance.

    Samples have host_monotonic_s, P4 command features, gyro and following
    error. Poses are qualified body poses from the camera measurement owner.
    All observations must share reference/calibration/epoch. Receipt-clock
    alignment uncertainty is returned separately by the recorder.
    """
    weights = weights or DEFAULT_WEIGHTS
    if set(weights) != set(DEFAULT_WEIGHTS) or not all(math.isfinite(v) for v in weights.values()):
        raise ValueError("Specify all eight finite objective weights")
    if len(samples) < 2:
        raise ValueError("Not enough joint/IMU observations")
    interval = [p for p in poses if isinstance(p.get("receivedAtMonotonic"), (int, float)) and
                samples[0]["host_monotonic_s"] <= p["receivedAtMonotonic"] <= samples[-1]["host_monotonic_s"]]
    if any(not p.get("available") for p in interval):
        raise ValueError("Camera tracking was unavailable within the observation")
    poses = sorted(interval,
                   key=lambda p: p["receivedAtMonotonic"])
    poses = list({p["frameId"]: p for p in poses}.values())
    if len(poses) < 2:
        raise ValueError("Metric camera motion unavailable; joint movement is not distance")
    identity = {(p.get("epoch"), p.get("referenceId"), p.get("calibrationId")) for p in poses}
    if len(identity) != 1 or any(v is None for v in next(iter(identity))):
        raise ValueError("Camera reference or calibration changed within the observation")
    progress = turning = yaw_error = lateral = elapsed = 0.
    for a, b in zip(poses, poses[1:]):
        dt = b["receivedAtMonotonic"]-a["receivedAtMonotonic"]
        if dt <= 0:
            continue
        sample = min(samples, key=lambda s: abs(s["host_monotonic_s"]-(a["receivedAtMonotonic"]+b["receivedAtMonotonic"])/2))
        command = sample["command"]
        f, t = command[:2]
        pa, pb = a["position"], b["position"]
        yaw = math.atan2(math.sin(math.radians(pb["headingDegrees"]-pa["headingDegrees"])),
                         math.cos(math.radians(pb["headingDegrees"]-pa["headingDegrees"])))
        heading = math.radians(pa["headingDegrees"])+yaw/2
        dx, dy = pb["xMetres"]-pa["xMetres"], pb["yMetres"]-pa["yMetres"]
        forward = dx*math.cos(heading)+dy*math.sin(heading)
        sideways = -dx*math.sin(heading)+dy*math.cos(heading)
        progress += forward*(1 if f > 0 else -1 if f < 0 else 0)
        desired = sample.get("reference_twist")
        if not desired or len(desired) != 3 or not all(math.isfinite(v) for v in desired):
            raise ValueError("Planned trajectory rate unavailable; cannot score turn tracking")
        yaw_error += abs(yaw-desired[2]*dt)
        turn_sign = 1 if t > 0 else -1 if t < 0 else 0
        # Extra spinning is not extra task success. The target is the recorded
        # planned turn, including live steering, not an arbitrary yaw maximum.
        turning += min(yaw*turn_sign, max(0., desired[2]*turn_sign*dt))
        lateral += abs(sideways)
        elapsed += dt
    if elapsed <= 0:
        raise ValueError("Camera timestamps did not advance")
    def rms(field):
        if any(not s.get(field) for s in samples):
            raise ValueError("Missing calibrated "+field+" measurements")
        values = [float(v) for s in samples for v in s[field]]
        if not values or not all(math.isfinite(v) for v in values):
            raise ValueError("Missing calibrated joint/IMU measurements")
        return math.sqrt(sum(v*v for v in values)/len(values))
    metrics = dict(progress_m_s=progress/elapsed, turn_rad_s=turning/elapsed,
                   yaw_tracking_error_rad_s=yaw_error/elapsed, lateral_m_s=lateral/elapsed,
                   tilt_rms_rad=rms("tilt"), angular_rms_rad_s=rms("angular"),
                   tracking_rms_mm=rms("error"),
                   acceleration_deviation_rms_m_s2=rms("acceleration_deviation"))
    if not all(math.isfinite(v) for v in metrics.values()):
        raise ValueError("Non-finite camera or sensor measurements")
    utility = metrics["progress_m_s"]*weights["progress_m_s"]+metrics["turn_rad_s"]*weights["turn_rad_s"]
    cost = sum(max(0., -weights[k]*metrics[k]) for k in weights if k not in ("progress_m_s", "turn_rad_s"))
    # Stillness cannot win solely by eliminating vibration/tracking costs.
    return {"score": utility/(1.+cost), "metrics": metrics,
            "duration_s": elapsed, "camera_frames": len(poses),
            "distance_m": progress, "turn_rad": turning,
            "distance_source": poses[0].get("source"),
            "distance_scale_source": poses[0].get("scaleSource", "measured-calibration"),
            "distance_accuracy_verified": poses[0].get("metricAccuracyVerified"),
            "coordinate_origin": poses[0].get("coordinateOrigin", "body"),
            "camera_context": [poses[0].get("source"), poses[0].get("scaleSource"),
                               poses[0].get("calibrationId"), poses[0].get("coordinateOrigin")],
            "energy_measured": False, "contact_measured": False}


def propose(observations, *, seed=0):
    """One Bayesian proposal in normalized exploration coordinates.

    Observations must already be separated by gait/calibration/command context.
    Repeats remain individual noisy observations. No inference deadline and no
    GPU requirement. Initial space-filling points use Torch's Sobol sequence.
    """
    import torch
    dimension = len(DEFAULT_RADII)
    torch.manual_seed(seed)
    dtype = torch.double
    if len({tuple(o["x"]) for o in observations}) < dimension+1:
        engine = torch.quasirandom.SobolEngine(dimension, scramble=True, seed=seed)
        engine.fast_forward(len(observations))
        return (engine.draw(1).double()[0]*2-1).tolist()
    from botorch.models import SingleTaskGP
    from botorch.models.transforms.input import Normalize
    from botorch.fit import fit_gpytorch_mll
    from botorch.acquisition import LogExpectedImprovement
    from botorch.optim import optimize_acqf
    from gpytorch.mlls import ExactMarginalLogLikelihood
    x = torch.tensor([o["x"] for o in observations], dtype=dtype)
    y = torch.tensor([[o["score"]] for o in observations], dtype=dtype)
    unit_x = (x+1)/2
    bounds = torch.stack((unit_x.min(dim=0).values.clamp(max=0),
                          unit_x.max(dim=0).values.clamp(min=1)))
    gp = SingleTaskGP(unit_x, y, input_transform=Normalize(dimension, bounds=bounds))
    fit_gpytorch_mll(ExactMarginalLogLikelihood(gp.likelihood, gp))
    acquisition = LogExpectedImprovement(gp, best_f=y.max())
    point, _ = optimize_acqf(acquisition, bounds=torch.tensor([[0.]*dimension, [1.]*dimension], dtype=dtype),
                            q=1, num_restarts=8, raw_samples=128)
    return (point.detach()[0]*2-1).tolist()


def compare(reference, challenger):
    """Repeated windows; uncertainty is descriptive, not an IID guarantee."""
    import statistics
    if len(reference) < 2 or len(challenger) < 2:
        return {"decision": "collecting_repeats"}
    gain = statistics.mean(challenger)-statistics.mean(reference)
    se = math.sqrt(statistics.variance(reference)/len(reference)+
                   statistics.variance(challenger)/len(challenger))
    return {"decision": "improved" if statistics.mean(challenger) > 0 and gain > 2*se else "not_demonstrated",
            "gain": gain, "standard_error": se, "reference_windows": len(reference),
            "challenger_windows": len(challenger)}


def project_candidate(base, coordinates, radii, joints, gait, conditions):
    """Fit only a proposed change using the production offline linkage solver.

    This samples the observed command conditions, not physical loads/contact.
    Existing robot motion remains independent of this host calculation.
    """
    import json
    import os
    from pathlib import Path
    import subprocess
    from .gait_training import vector
    root = Path(__file__).resolve().parents[2]
    executable = os.environ.get("AINEKIO_GAIT_PREVIEW",
                                str(root/"build/gait-native/preview_gait_learning"))
    if len(joints) != 12:
        raise ValueError("Candidate fitting needs the robot's twelve calibrated joint mappings")
    joints = sorted(joints, key=lambda j: j["id"])
    if [j["id"] for j in joints] != list(range(12)):
        raise ValueError("Candidate fitting needs each joint mapping exactly once")
    mapping = "\n".join(" ".join(str(int(j[k])) if k != "us_per_degree" else str(j[k])
                                 for k in ("channel", "invert", "home_us", "home_cd", "us_per_degree"))
                        for j in joints)
    commands = []
    for condition in sorted(set(conditions)):
        command, rate = json.loads(condition)
        f, t, lateral, stride = command
        if rate is None:
            raise ValueError("Recording lacks the requested motion rate; update trace firmware")
        commands.append(dict(t="intent", seq=1, name="walk", gait=gait, dir="fwd", steps=4,
                             forward=f*100, turn=t*100, lateral=lateral*100,
                             stride=stride*100, rate=rate))
    if not commands:
        raise ValueError("No observed command conditions to fit")

    def evaluate(scale):
        x = [v*scale for v in coordinates]
        model = candidate(base, x, radii)
        data = mapping+"\n"+" ".join(map(str, vector(model)))+"\n"+" ".join(["0"]*32)+"\n"
        data += "\n".join(f"{lo} {hi}" for lo,hi in zip(model["pulse_min_us"], model["pulse_max_us"]))+"\n"
        for command in commands:
            result = subprocess.run([executable, "1", "0", "v4", "fwd", "100", json.dumps(command)],
                                    input=data, capture_output=True, text=True, check=False)
            if result.returncode:
                if result.returncode not in (3, 4, 5, 6, 7):
                    raise RuntimeError("Linkage preview failed: "+result.stderr[-1000:])
                return None
        return model, x

    proposed = evaluate(1.)
    if proposed:
        return (*proposed, {"scale": 1., "conditions": len(commands), "sensor_input": "zero"})
    fitted = evaluate(0.)
    if not fitted:
        raise ValueError("Incumbent linkage preview fails under the recorded commands; no candidate installed")
    # Bisection resolves the learned delta to 1/4096 of its exploration radius.
    low, high = 0., 1.
    for _ in range(12):
        middle = (low+high)/2
        trial = evaluate(middle)
        if trial:
            low, fitted = middle, trial
        else:
            high = middle
    return (*fitted, {"scale": low, "conditions": len(commands), "sensor_input": "zero"})


def propose_worker(observations, *, seed=0):
    """Isolate optimizer dependencies/resources from the gateway interpreter."""
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[2]
    bundled = root/"build/gait-training-env/bin/python"
    python = os.environ.get("AINEKIO_GAIT_TRAINING_PYTHON", str(bundled) if bundled.exists() else sys.executable)
    result = subprocess.run([python, "-m", "gateway.gait_optimizer"],
                            input=json.dumps({"observations": observations, "seed": seed}),
                            text=True, capture_output=True, check=False,
                            env={**os.environ, "PYTHONPATH": str(root/"Master")+os.pathsep+os.environ.get("PYTHONPATH", "")})
    if result.returncode:
        raise RuntimeError("Optimizer worker failed: "+result.stderr[-1500:])
    return json.loads(result.stdout)


if __name__ == "__main__":
    import json
    import sys
    request = json.load(sys.stdin)
    json.dump(propose(**request), sys.stdout, allow_nan=False)
