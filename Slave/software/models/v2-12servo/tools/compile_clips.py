"""Compile retained finite gestures. Standard Python only.

Fit cubic segments to the retained 120 Hz reference, bounding continuous angle
error. Preserve extrema, holds, duration and endpoints; one runtime sampler.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gestures(root: Path) -> list[dict]:
    model = json.loads((root / "model.json").read_text())
    legs = ["FL", "FR", "RL", "RR"]
    axes = ["h_Part002", "alpha_Part006", "theta_Part005"]
    if model["model"] != "v2-12servo" or len(model["joints"]) != 12:
        raise ValueError("incompatible gesture model")
    for i, joint in enumerate(model["joints"]):
        if joint["id"] != i or joint["cad_leg"] != legs[i // 3] or joint["actuator"] != axes[i % 3]:
            raise ValueError("model joint order disagrees with the gesture source")
    family = root / "motions/gestures"
    catalog = json.loads((family / "catalog.json").read_text())
    policy_hash = digest(family / "execution-policy.json")
    geometry_id = json.loads((root / "geometry.json").read_text())["geometry_id"]
    geometry_hash = digest(root / "geometry.json")
    sole_hash = digest(root / "motions/turns/sole-hulls.npz")
    if catalog["hardware_qualified"] is not False or catalog["policy_sha256"] != policy_hash:
        raise ValueError("gesture readiness or execution policy mismatch")
    gestures = []
    for entry in catalog["commands"]:
        command = entry["command"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", command) or entry["path"] != command:
            raise ValueError("invalid gesture command/path")
        folder = family / command
        for name in ("source.json", "manifest.json", "schema.json", "execution-contract.json"):
            if digest(folder / name) != entry["sha256"][name]:
                raise ValueError(f"{command}: {name} provenance mismatch")
        manifest = json.loads((folder / "manifest.json").read_text())
        source = json.loads((folder / "source.json").read_text())
        schema = json.loads((folder / "schema.json").read_text())
        contract = json.loads((folder / "execution-contract.json").read_text())
        if "posture_sha256" in manifest:
            posture = json.loads((folder / "posture.json").read_text())
            if (digest(folder / "posture.json") != manifest["posture_sha256"]
                or digest(folder / posture["contact_hulls_file"]) != manifest["posture_hulls_sha256"]
                or posture["contact_hulls_sha256"] != manifest["posture_hulls_sha256"]
                or posture["mechanism_geometry_sha256"] != geometry_hash):
                raise ValueError(f"{command}: posture geometry provenance mismatch")
            base = posture.get("base_motion")
            if base and (digest(folder / base["source_file"]) != base["source_sha256"]
                         or digest(folder / base["posture_file"]) != base["posture_sha256"]):
                raise ValueError(f"{command}: seated motion dependency changed; regenerate this motion")
        if "reviewed_sha256" in manifest and digest(folder / "reviewed.json") != manifest["reviewed_sha256"]:
            raise ValueError(f"{command}: reviewed recording changed; regenerate the clip")
        metadata = source["metadata"]
        wire = {"t": "intent", "name": "sit"} if command == "sit" else {
            "t": "intent", "name": "emote", "asset": command}
        legs, axes = ["FL", "FR", "RL", "RR"], ["h_Part002", "alpha_Part006", "theta_Part005"]
        if (manifest["command"] != command or metadata["configuration"]["command"] != command
            or schema["command"] != command or contract["command"] != command
            or manifest["wire"] != wire or contract["wire"] != wire
            or manifest["gait_id"] != contract["gait_id"]
            or manifest["source_sha256"] != entry["sha256"]["source.json"]
            or manifest["geometry_id"] != geometry_id
            or manifest["geometry_sha256"] != geometry_hash or manifest["sole_hulls_sha256"] != sole_hash
            or contract["policy_sha256"] != policy_hash):
            raise ValueError(f"{command}: command, source or geometry mismatch")
        for document in (metadata, schema, contract):
            if document["leg_order"] != legs or document["joint_order"] != axes:
                raise ValueError(f"{command}: incompatible joint order")
        if (metadata["angle_units"] != "radian" or metadata["position_units"] != "mm"
            or metadata["time_units"] != "second"
            or contract["source_units"] != {"angle": "radian", "position": "mm", "time": "second"}):
            raise ValueError(f"{command}: incompatible units")
        binds = {record["path"]: record["sha256"] for record in contract["source_files"]}
        for name in ("source.json", "manifest.json"):
            if binds.get(f'{entry["handoff"]}/{name}') != entry["sha256"][name]:
                raise ValueError(f"{command}: timing contract bound to a different source")
        duration, hz = manifest["duration_seconds"], manifest["source_sample_hz"]
        if (hz != 120 or metadata["configuration"]["sample_hz"] != hz or schema["sample_hz"] != hz
            or contract["source_sample_hz"] != hz or not math.isfinite(duration) or not 0 < duration <= 60
            or len(source["samples"]) != round(duration * hz) + 1
            or len(source["samples"]) != manifest["sample_count"]):
            raise ValueError(f"{command}: invalid sample count or timing")
        positions = []
        for i, sample in enumerate(source["samples"]):
            if not math.isfinite(sample["time_s"]) or abs(sample["time_s"] - i / hz) > 1e-8:
                raise ValueError(f"{command}: nonuniform or reordered samples")
            angles = sample["actuator_angles_rad"]
            if len(angles) != 4 or any(len(leg) != 3 for leg in angles):
                raise ValueError(f"{command}: every sample must supply all twelve joints")
            row = [math.degrees(value) * 100 for leg in angles for value in leg]
            if not all(math.isfinite(value) for value in row):
                raise ValueError(f"{command}: nonfinite angle")
            positions.append(row)
        # Newer handoffs distinguish the command's completion from an optional
        # playlist recovery. Only the command interval belongs in firmware.
        semantic = "semantic_end_seconds" in manifest
        command_end = manifest["semantic_end_seconds"] if semantic else duration
        if (not math.isfinite(command_end) or not 0 < command_end <= duration
            or abs(command_end * hz - round(command_end * hz)) > 1e-8):
            raise ValueError(f"{command}: invalid semantic completion time")
        terminal_knot = round(command_end * hz)
        final_key = "semantic_final_actuator_angles_rad" if semantic else "final_actuator_angles_rad"
        playlist_key = "playlist_final_actuator_angles_rad" if semantic else final_key
        if semantic and (command_end != contract["completion"]["semantic_end_s"]
                         or command_end != schema["semantic_end_s"]
                         or schema["optional_demonstration_recovery"] != (command_end < duration)
                         or contract["completion"]["optional_demo_recovery_end_s"] !=
                            (duration if command_end < duration else None)):
            raise ValueError(f"{command}: semantic completion contract mismatch")
        if (source["samples"][0]["actuator_angles_rad"] != contract["entry"]["joint_angles_rad"]
            or source["samples"][terminal_knot]["actuator_angles_rad"] != contract["completion"]["joint_angles_rad"]
            or source["samples"][terminal_knot]["actuator_angles_rad"] != manifest[final_key]
            or source["samples"][-1]["actuator_angles_rad"] != manifest[playlist_key]
            or source["samples"][0]["actuator_angles_rad"] != manifest["entry_actuator_angles_rad"]):
            raise ValueError(f"{command}: recorded entry/final pose mismatch")
        phases, cursor = contract["phases"], 0.0
        demonstration = contract["timing_profiles"]["demonstration"]["duration_s"]
        if not phases or len({p["id"] for p in phases}) != len(phases) or set(demonstration) != {p["id"] for p in phases}:
            raise ValueError(f"{command}: invalid phase identifiers")
        for phase in phases:
            start, end = phase["source_interval_s"]
            if (not all(math.isfinite(v) for v in (start, end)) or abs(start-cursor) > 1e-8
                or not start < end <= duration or not math.isfinite(demonstration[phase["id"]])
                or abs(demonstration[phase["id"]] - (end-start)) > 1e-8):
                raise ValueError(f"{command}: demonstration phase timing mismatch")
            if semantic:
                role = "command" if end <= command_end else "optional_demonstration_recovery"
                if (start < command_end < end or phase["execution_role"] != role):
                    raise ValueError(f"{command}: phase crosses semantic completion or has incorrect execution role")
            cursor = end
        motion_end = manifest["source_validation"]["motion_end_s"] if semantic else manifest["motion_end_seconds"]
        if cursor != duration or not math.isfinite(motion_end) or not 0 < motion_end <= duration:
            raise ValueError(f"{command}: incomplete phase coverage")
        if (manifest["hardware_qualified"] is not False or contract["hardware_ready"] is not False
            or manifest["actuator_calibration"] is not None):
            raise ValueError("research source import cannot grant hardware readiness")
        gestures.append(dict(command=command, manifest=manifest, positions=positions[:terminal_knot+1],
                             duration_s=command_end, end_s=min(command_end, motion_end),
                             phases=[p for p in phases if p['source_interval_s'][1] <= command_end],
                             expected_up=[body_up(row['body_orientation_world_quaternion_wxyz'])
                                          for row in source['samples'][:terminal_knot+1]],
                             face_cues=[cue for cue in contract.get('face_cues', [])
                                        if cue['time_s'] <= command_end]))
    return gestures


# Error budget is 0.005 degree = 0.056 us at the nominal saved scale.
# The actual pulse error scales with each operator's us/degree calibration.
COMPRESSION_ERROR_CD = .5


def polynomial(p0, p1, m0, m1, duration):
    v0, v1 = m0*duration, m1*duration
    return (2*p0-2*p1+v0+v1, -3*p0+3*p1-2*v0-v1, v0, p0)


def evaluate(c, u):
    return ((c[0]*u+c[1])*u+c[2])*u+c[3]


def extrema(c):
    a,b,d = 3*c[0],2*c[1],c[2]
    roots=[]
    if abs(a)<1e-15:
        if abs(b)>1e-15: roots=[-d/b]
    else:
        disc=b*b-4*a*d
        if disc>=0:
            v=math.sqrt(disc);roots=[(-b-v)/(2*a),(-b+v)/(2*a)]
    return [u for u in roots if 0<u<1]


def compact(positions, required=()):
    count=len(positions);slopes=[[0.]*12 for _ in positions]
    for i in range(1,count-1):
        for j in range(12):
            a=(positions[i][j]-positions[i-1][j])*120
            b=(positions[i+1][j]-positions[i][j])*120
            slopes[i][j]=2*a*b/(a+b) if a*b>0 else 0.
    # Every extremum and every hold boundary stays exact.
    keep={0,count-1,*required}
    for i in range(1,count-1):
        if any((positions[i][j]-positions[i-1][j])*(positions[i+1][j]-positions[i][j])<=0
               and (positions[i][j]!=positions[i-1][j] or positions[i+1][j]!=positions[i][j]) for j in range(12)):keep.add(i)
    original=[[polynomial(positions[i][j],positions[i+1][j],slopes[i][j],slopes[i+1][j],1/120) for j in range(12)] for i in range(count-1)]
    pending=list(zip(sorted(keep),sorted(keep)[1:]));bound=0.
    while pending:
        lo,hi=pending.pop()
        if hi-lo<=1:continue
        width=hi-lo;curves=[polynomial(positions[lo][j],positions[hi][j],slopes[lo][j],slopes[hi][j],width/120) for j in range(12)]
        worst,split=0.,(lo+hi)//2
        # Both cubics are compared over every original interval. Their difference
        # is cubic; endpoints and derivative roots bound the ENTIRE interval.
        for i in range(lo,hi):
            offset=(i-lo)/width;scale=1/width
            for j,c in enumerate(curves):
                a,b,v,d=c
                mapped=(a*scale**3,(3*a*offset+b)*scale**2,(3*a*offset**2+2*b*offset+v)*scale,evaluate(c,offset))
                diff=tuple(x-y for x,y in zip(mapped,original[i][j]))
                error=max(abs(evaluate(diff,u)) for u in [0.,1.]+extrema(diff))
                if error>worst:worst,split=error,min(hi-1,max(lo+1,i))
        overshoot=any(any(evaluate(c,u)<min(positions[lo][j],positions[hi][j])-1e-7 or evaluate(c,u)>max(positions[lo][j],positions[hi][j])+1e-7 for u in extrema(c)) for j,c in enumerate(curves))
        if worst>COMPRESSION_ERROR_CD or overshoot:
            keep.add(split);pending.extend([(lo,split),(split,hi)])
        else:bound=max(bound,worst)
    indices=sorted(keep)
    return indices,slopes,bound


def body_up(quaternion):
    """World vertical in body coordinates; yaw is irrelevant to tipping."""
    length = math.sqrt(sum(v*v for v in quaternion))
    w, x, y, z = [v/length for v in quaternion]
    return [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]


def compact_up(rows, tolerance=1e-4):
    """Compress only notification references; joint tracks stay unchanged."""
    retained = {0, len(rows)-1}
    pending = [(0, len(rows)-1)]
    while pending:
        lo, hi = pending.pop()
        worst, split = 0., None
        for index in range(lo+1, hi):
            u = (index-lo)/(hi-lo)
            value = [(1-u)*a+u*b for a, b in zip(rows[lo], rows[hi])]
            length = math.sqrt(sum(v*v for v in value))
            error = math.sqrt(sum((v/length-target)**2 for v, target in zip(value, rows[index]))) if length else 2.
            if error > worst:
                worst, split = error, index
        if worst > tolerance:
            retained.add(split)
            pending.extend([(lo, split), (split, hi)])
    return sorted(retained)


def gesture_targets(positions, phases):
    """Authored phase ends and joint reversals, at the compiler's precision.

    The path is unchanged. These targets must reach the output before playback
    can pass them; IK roundoff below the existing 0.005-degree fit budget does
    not create artificial choreography.
    """
    targets = {0, len(positions)-1}
    for phase in phases:
        targets.update(round(t*120) for t in phase['source_interval_s'])
    for joint in range(12):
        low = high = 0
        direction = 0
        for i, row in enumerate(positions):
            if row[joint] < positions[low][joint]: low = i
            if row[joint] > positions[high][joint]: high = i
            if direction >= 0 and positions[high][joint]-row[joint] > COMPRESSION_ERROR_CD:
                if direction: targets.add(high)
                direction, low = -1, i
            elif direction <= 0 and row[joint]-positions[low][joint] > COMPRESSION_ERROR_CD:
                if direction: targets.add(low)
                direction, high = 1, i
    return sorted(targets)


def travel_clock(positions, indices, velocities, holds=()):
    """Integrate max(abs(joint travel)) along the existing cubic path.

    Between crossings of the quadratic joint derivatives one joint owns the
    clock. Its angle is an exact distance coordinate, so runtime can invert
    that cubic without imposing the recording's slow travel or easing.
    Constant-pose intervals retain their authored time separately.
    """
    rows, travel, hold = [], 0., 0.
    for segment, (lo, hi) in enumerate(zip(indices, indices[1:])):
        seconds = (hi-lo)/120
        curves = [polynomial(positions[lo][j], positions[hi][j],
                             velocities[lo][j], velocities[hi][j], seconds) for j in range(12)]
        cuts = {0., 1.}
        derivatives = [(3*a, 2*b, c) for a, b, c, _ in curves]
        # |v_i| == |v_j| exactly where v_i-v_j or v_i+v_j vanishes.
        for j, v in enumerate(derivatives):
            cuts.update(extrema(curves[j]))
            for w in derivatives[:j]:
                for sign in (-1, 1):
                    a, b, c = (v[k]+sign*w[k] for k in range(3))
                    cuts.update(extrema((a/3, b/2, c, 0.)))
        spans = []
        for start, end in zip(sorted(cuts), sorted(cuts)[1:]):
            mid = (start+end)/2
            joint = max(range(12), key=lambda j: abs(
                (derivatives[j][0]*mid+derivatives[j][1])*mid+derivatives[j][2]))
            a, b, c = derivatives[joint]
            positive = (a*mid+b)*mid+c > 0.
            if spans and spans[-1][2:] == (joint, positive):
                spans[-1] = (spans[-1][0], end, joint, positive)
            else:
                spans.append((start, end, joint, positive))
        for start, end, joint, _ in spans:
            rows.append((lo+(hi-lo)*start, travel, hold, segment, joint))
            distance = abs(evaluate(curves[joint], end)-evaluate(curves[joint], start))/100
            if (any(begin <= lo and hi <= end for begin, end in holds)
                or all(a == b == c == 0. for a, b, c, _ in curves)):
                hold += (end-start)*seconds
            else:
                travel += distance
    rows.append((indices[-1], travel, hold, len(indices)-2, 0))
    return rows


def compile_clips(root: Path, out: Path) -> None:
    clips = load_gestures(root)
    if len(clips) > 62 or len({c['command'] for c in clips}) != len(clips):
        raise ValueError("duplicate command or body declaration limit exceeded")
    out.mkdir(parents=True, exist_ok=True)
    header = '''/* Generated from retained finite motion sources; do not edit. */
#ifndef AINEKIO_V2_CLIP_DATA_H
#define AINEKIO_V2_CLIP_DATA_H
#include "ainekio/v2_motion.h"
#define V2_CLIP_SAMPLE_HZ 120U
typedef struct {
    const float (*positions)[AINEKIO_V2_JOINT_COUNT];
    const float (*velocities)[AINEKIO_V2_JOINT_COUNT];
    const uint16_t *knots;
    const float *minimum, *maximum;
    size_t count;
    uint64_t active_end_us;
} ainekio_v2_clip_track_t;
extern const ainekio_v2_clip_track_t v2_clip_tracks[];
typedef struct {
    const float (*up)[3];
    const uint16_t *knots;
    size_t count;
} ainekio_v2_clip_attitude_track_t;
extern const ainekio_v2_clip_attitude_track_t v2_clip_attitudes[];
typedef struct {
    double tick, travel_degrees, hold_seconds;
    uint16_t segment;
    uint8_t joint;
} ainekio_v2_clip_clock_knot_t;
typedef struct {
    const ainekio_v2_clip_clock_knot_t *knots;
    size_t count;
    const uint16_t *targets;
    size_t target_count;
} ainekio_v2_clip_clock_t;
extern const ainekio_v2_clip_clock_t v2_clip_clocks[];
#endif
'''
    geometry_id = json.loads((root / 'model.json').read_text())['joint_map']
    header = header.replace('#define V2_CLIP_SAMPLE_HZ', '#define V2_CLIP_GEOMETRY_ID ' + json.dumps(geometry_id) + '\n#define V2_CLIP_SAMPLE_HZ')
    code = ['/* Generated by tools/compile_clips.py. Signed CAD centidegrees. */', '#include "clip_data.h"']
    report=[]
    for i, clip in enumerate(clips):
        targets=gesture_targets(clip['positions'],clip['phases'])
        clip['targets']=targets
        indices,velocities,error=compact(clip['positions'],targets);clip['indices']=indices
        peak=0.
        for lo,hi in zip(indices,indices[1:]):
            duration=(hi-lo)/120
            for joint in range(12):
                a,b,c,_=polynomial(clip['positions'][lo][joint],clip['positions'][hi][joint],velocities[lo][joint],velocities[hi][joint],duration)
                times=[0.,1.]
                if abs(a)>1e-15 and 0<-b/(3*a)<1:times.append(-b/(3*a))
                peak=max(peak,max(abs((3*a*u+2*b)*u+c)/duration/100 for u in times))
        # Cover rounding of stored float positions, tangents and evaluation.
        clip['peak_joint_speed_degrees_s']=peak*1.00001+.01
        for name,values in [('positions',clip['positions']),('velocities',velocities)]:
            code.append(f'static const float clip_{i}_{name}[][AINEKIO_V2_JOINT_COUNT] = {{')
            code.extend('    {' + ','.join(f'{value:.9e}F' for value in values[knot]) + '},' for knot in indices)
            code.append('};')
        code.append(f'static const uint16_t clip_{i}_knots[] = '+'{'+','.join(map(str,indices))+'};')
        holds=[tuple(round(t*120) for t in p['source_interval_s']) for p in clip['phases']
               if p.get('moving_joint_indices') == [] or p['name'].startswith('hold_')]
        clock = travel_clock(clip['positions'], indices, velocities, holds)
        code.append(f'static const uint16_t clip_{i}_targets[] = '+'{'+','.join(map(str,targets))+'};')
        clip['clock_count'] = len(clock)
        code.append(f'static const ainekio_v2_clip_clock_knot_t clip_{i}_clock[] = {{')
        code.extend('    {'+','.join([*(f'{v:.17g}' for v in row[:3]), str(row[3]), str(row[4])])+'},'
                    for row in clock)
        code.append('};')
        attitude_indices = compact_up(clip['expected_up'])
        clip['attitude_indices'] = attitude_indices
        code.append(f'static const float clip_{i}_up[][3] = '+'{')
        code.extend('    {'+','.join(f'{v:.9e}F' for v in clip['expected_up'][knot])+'},'
                    for knot in attitude_indices)
        code.append('};')
        code.append(f'static const uint16_t clip_{i}_up_knots[] = '+'{'+','.join(map(str,attitude_indices))+'};')
        for name,operation in [('minimum',min),('maximum',max)]:
            code.append(f'static const float clip_{i}_{name}[] = '+'{'+','.join(f'{operation(row[j] for row in clip["positions"]):.9e}F' for j in range(12))+'};')
        report.append(dict(command=clip['command'],original_knots=len(clip['positions']),stored_knots=len(indices),continuous_error_cd=error,peak_joint_speed_degrees_s=clip['peak_joint_speed_degrees_s']))
    (out/'compression.json').write_text(json.dumps(report,indent=2)+'\n')
    for i, clip in enumerate(clips):
        if clip['face_cues']:
            code.append(f'static const ainekio_v2_face_cue_t clip_{i}_faces[] = {{')
            for cue in clip['face_cues']:
                mode = {'once': 'ONCE', 'loop': 'LOOP', 'boomerang': 'BOOMERANG'}[cue['mode']]
                code.append('    {' + json.dumps(cue['name']) +
                            f', UINT64_C({round(cue["time_s"]*1e6)}), AINEKIO_V2_FACE_{mode}' + '},')
            code.append('};')
    code.append('const ainekio_v2_clip_t ainekio_v2_clips[] = {')
    for i, clip in enumerate(clips):
        manifest = clip['manifest']
        intent = 'AINEKIO_INTENT_SIT' if manifest['wire']['name'] == 'sit' else 'AINEKIO_INTENT_EMOTE'
        code.append('    {' + ','.join((json.dumps(clip['command']), json.dumps(manifest['gait_id']), intent,
                    f'UINT64_C({round(clip["duration_s"] * 1e6)})', 'false', f'{clip["peak_joint_speed_degrees_s"]:.9e}F',
                    f'clip_{i}_faces' if clip['face_cues'] else 'NULL', str(len(clip['face_cues'])))) + '},')
    code.extend(['};', 'const size_t ainekio_v2_clip_count = sizeof(ainekio_v2_clips) / sizeof(ainekio_v2_clips[0]);',
                 'const ainekio_v2_clip_track_t v2_clip_tracks[] = {'])
    for i, clip in enumerate(clips):
        end = clip['end_s']
        code.append(f'    {{clip_{i}_positions, clip_{i}_velocities, clip_{i}_knots, clip_{i}_minimum, clip_{i}_maximum, {len(clip["indices"])}U, UINT64_C({round(end * 1e6)})}},')
    code.append('};')
    code.append('const ainekio_v2_clip_attitude_track_t v2_clip_attitudes[] = {')
    for i, clip in enumerate(clips):
        code.append(f'    {{clip_{i}_up, clip_{i}_up_knots, {len(clip["attitude_indices"])}U}},')
    code.append('};')
    code.append('const ainekio_v2_clip_clock_t v2_clip_clocks[] = {')
    for i, clip in enumerate(clips):
        code.append(f'    {{clip_{i}_clock, {clip["clock_count"]}U, clip_{i}_targets, {len(clip["targets"])}U}},')
    code.append('};')
    (out / 'clip_data.h').write_text(header)
    (out / 'clip_data.c').write_text('\n'.join(code) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    compile_clips(args.root, args.out)
