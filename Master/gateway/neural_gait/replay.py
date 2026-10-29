"""Immutable checkpoint clips and cumulative, comparable learning videos."""
import argparse
from dataclasses import replace
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import zipfile

os.environ.setdefault('MUJOCO_GL', 'egl')
import mujoco
from PIL import Image, ImageDraw, ImageFont
import torch

from .environment import EnvironmentConfig, make_environment, ENVIRONMENT_VERSION, POLICY_ENVIRONMENT_VERSIONS, representation_identity
from .contract import SCHEMA, SCHEMAS
from .training import load_policy, request_interval_steps, save_json

WIDTH, HEIGHT, RENDER_VERSION = 1280, 720, 3


def versions(directory, progress, *, comparison=False):
    if progress:
        rows = json.loads((directory/'checkpoints.json').read_text())
        if not rows:
            raise ValueError('No checkpoint evaluations yet')
        if comparison:
            final = versions(directory, False)[0]
            return [rows[0]] if rows[0]['id'] == final['id'] else [rows[0], final]
        return rows
    result = json.loads((directory/'progress.json').read_text())
    evaluation = json.loads((directory/'evaluation.json').read_text())['candidate']
    selection = directory/'selection.json'
    if selection.exists():
        return [dict(json.loads(selection.read_text()), policy='policy.zip', evaluation=evaluation)]
    return [dict(id=result.get('selected_checkpoint_id', f"{result['steps']:09d}"),
                 steps=result['steps'], imitation_updates=result.get('imitation_updates', 0),
                 policy='policy.zip', evaluation=evaluation)]


def labelled(frame, lines):
    result = Image.fromarray(frame)
    draw = ImageDraw.Draw(result)
    font = ImageFont.load_default(size=23)
    draw.rectangle((0,0,WIDTH,110), fill='#101820')
    for index,line in enumerate(lines):
        draw.text((16,9+index*32), line, font=font, fill='white')
    return result


def encoder(path, fps):
    return subprocess.Popen([
        'ffmpeg','-nostdin','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24',
        '-s',f'{WIDTH}x{HEIGHT}','-r',str(fps),'-i','-','-an','-c:v','libx264',
        '-preset','fast','-crf','18','-threads','2','-pix_fmt','yuv420p',
        '-movflags','+faststart',str(path)], stdin=subprocess.PIPE)


def clip(directory, config, checkpoint, seed, *, model=None, episode=None):
    """Render once; later progress updates concatenate the existing clips."""
    folder = directory/'clips'
    folder.mkdir(exist_ok=True)
    checkpoint_id = checkpoint.get('id', f'{checkpoint["steps"]:09d}')
    if episode is None:
        episode = next(row for row in checkpoint['evaluation']['episodes'] if row['seed'] == seed)
    config = replace(config, command=list(episode.get('command', config.command)))
    command_index = episode.get('command_index')
    command_segments = episode.get('command_segments', [])
    command_suffix = f'-command{command_index+1}' if command_index is not None else ''
    scenario_suffix = f'-scenario{episode["scenario_index"]+1}' if 'scenario_index' in episode else ''
    manifest_path = directory/'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    training_version = manifest.get('environment_version', ENVIRONMENT_VERSION)
    rollout_suffix = f'-rollout-v{ENVIRONMENT_VERSION}' if training_version != ENVIRONMENT_VERSION else ''
    stem = f'{checkpoint_id}{command_suffix}{scenario_suffix}-trial{seed-999}{rollout_suffix}'
    metadata_path = folder/(stem+'.json')
    if metadata_path.exists():
        previous = json.loads(metadata_path.read_text())
        if (previous.get('renderer_version') == RENDER_VERSION
                and previous.get('rollout_environment_version') == ENVIRONMENT_VERSION):
            if previous.get('command_segments', []) == command_segments:
                return previous
    if model is None:
        model = load_policy(directory, checkpoint['policy'], device='cpu')
    imitation_path = directory/'imitation.json'
    imitation = json.loads(imitation_path.read_text()) if imitation_path.exists() else None
    updates = checkpoint.get('imitation_updates', imitation['updates'] if imitation else 0)
    training_label = (f'{updates:,} imitation updates + ' if updates else '') + f'{checkpoint["steps"]:,} RL steps'
    if manifest.get('initialization'):
        inherited = manifest['initialization']['source_rl_steps']
        training_label = f'Transferred {inherited:,} prior RL steps + {checkpoint["steps"]:,} new steps'
    if training_version != ENVIRONMENT_VERSION:
        training_label += f' | Trained env {training_version}, replay env {ENVIRONMENT_VERSION}'
    if checkpoint.get('training_method'):
        training_label = checkpoint['training_method'] + ' | ' + training_label
    if checkpoint.get('aggregation_round') is not None:
        training_label += f' | DAgger round {checkpoint["aggregation_round"]}'
    replay_commands = [row["command"] for row in command_segments] or [config.command]
    env = make_environment(config, commands=replay_commands)
    env.model.vis.global_.offwidth = WIDTH
    env.model.vis.global_.offheight = HEIGHT
    renderer = mujoco.Renderer(env.model, height=HEIGHT, width=WIDTH)
    camera = mujoco.MjvCamera()
    camera.distance, camera.azimuth, camera.elevation = .55, 135, -22
    fps = min(25, config.control_hz)
    names = [stem+'.mp4', stem+'-clean.mp4']
    temporary = [folder/(name+'.tmp.mp4') for name in names]
    processes = [encoder(path, fps) for path in temporary]
    try:
        options = {"command": config.command}
        if 'scenario_id' in episode:
            options['scenario'] = episode['scenario_id']
        obs,_ = env.reset(seed=seed, options=options)
        origin = env.data.qpos[:2].copy()
        next_frame = 0.
        schedule = {row['start_step']: row['command'] for row in command_segments}
        frames = 0
        def write_frame(step, outcome):
            camera.lookat[:] = env.data.qpos[:3]
            renderer.update_scene(env.data, camera=camera)
            raw = renderer.render()
            overlay = labelled(raw, [
                f'SIMULATION | {training_label} | {episode.get("scenario_id", "flat")} | Fixed trial {seed-999}',
                f'Request ({env.config.command[0]:+.3f}, {env.config.command[1]:+.3f}) m/s, yaw {env.config.command[2]:+.2f} rad/s | Trial {episode["forward_m_s"]:+.3f} m/s forward',
                f't={step/config.control_hz:.2f}s | Travel ({env.data.qpos[0]-origin[0]:+.3f}, {env.data.qpos[1]-origin[1]:+.3f}) m | Yaw {math.degrees(env.world_heading_delta):+.1f} deg | {outcome}'])
            processes[0].stdin.write(overlay.tobytes())
            processes[1].stdin.write(raw.tobytes())
            return overlay
        for step in range(round(config.episode_seconds*config.control_hz)):
            if step in schedule:
                obs = env.set_command(schedule[step])
                if episode.get('command_switch_range') is not None:
                    # Collection draws an interval here from the same RNG used
                    # by sensor noise. Preserve that stream while replaying the
                    # recorded boundary, rather than changing the request.
                    request_interval_steps(config, command_switch_range=episode['command_switch_range'],
                                           rng=env.np_random)
            if step/config.control_hz >= next_frame:
                first = write_frame(step, 'Running')
                if step == 0:
                    image_path = directory/f'environment-{os.getpid()}.png'
                    first.save(image_path)
                    image_path.replace(directory/'environment.png')
                frames += 1
                next_frame += 1/fps
            action,_ = model.predict(obs, deterministic=True)
            obs,_,terminated,truncated,info = env.step(action)
            if terminated or truncated:
                if info.get('producer_failure'):
                    outcome = 'POLICY PRODUCER FAILED'
                elif info.get('body_rejection'):
                    outcome = 'BODY REJECTED TARGET'
                elif info.get('body_terminal'):
                    outcome = 'BODY ' + str(info['body_terminal'].get('t', 'terminated')).upper()
                else:
                    outcome = 'FELL' if info['fallen'] else 'Trial duration reached'
                # Video presentation only: no extra time in the physics rollout.
                for _ in range(fps):
                    write_frame(step+1, outcome+' | Final pose held for review')
                    frames += 1
                break
        for process in processes:
            process.stdin.close()
            if process.wait() != 0:
                raise RuntimeError('Video encoder failed')
        for path,name in zip(temporary,names):
            path.replace(folder/name)
        metadata = dict(renderer_version=RENDER_VERSION, checkpoint_id=checkpoint_id,
            rollout_environment_version=ENVIRONMENT_VERSION, training_environment_version=training_version,
            aggregation_round=checkpoint.get('aggregation_round'), steps=checkpoint['steps'], seed=seed,
            labelled='clips/'+names[0], clean='clips/'+names[1], duration_s=frames/fps,
            simulated_seconds=(step+1)/config.control_hz, final_pose_display_hold_s=1,
            forward_displacement_m=float(env.data.qpos[0]-origin[0]), fallen=info['fallen'],
            command=config.command, command_index=command_index,
            scenario_id=episode.get('scenario_id', 'flat'),
            ground_displacement_m=(env.data.qpos[:2]-origin).tolist(),
            heading_change_rad=env.world_heading_delta,
            **({'command_segments': command_segments} if command_segments else {}),
            command_switch_range=episode.get('command_switch_range'),
            execution_backend=config.execution_backend,
            body_terminal=info.get('body_terminal'), body_rejection=info.get('body_rejection'),
            producer_failure=info.get('producer_failure'),
            imitation_updates=updates,
            physical_execution=False, width=WIDTH, height=HEIGHT, fps=fps)
        save_json(metadata_path, metadata)
        return metadata
    finally:
        for process in processes:
            if process.poll() is None:
                process.stdin.close()
                process.wait()
        renderer.close()
        env.close()


def write_footage(directory, destination):
    """Build a download snapshot without retaining another copy of the videos."""
    directory = Path(directory)
    with (directory/'render.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        # Footage only, never the optimizer replay buffer or model weights.
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED) as archive:
            for path in sorted((directory/'clips').glob('*')):
                if path.is_file() and path.suffix in ('.mp4', '.json') and '.tmp.' not in path.name:
                    archive.write(path, path.relative_to(directory))
            for filename in ('manifest.json', 'imitation.json', 'aggregation.json', 'selection.json',
                             'checkpoints.json', 'evaluation.json', 'progress-video.mp4',
                             'progress-video.json', 'replay.mp4', 'replay.json'):
                path = directory/filename
                if path.exists():
                    archive.write(path, filename)


def _publish_video(directory, name, manifest, checkpoints, episodes, clips, *, comparison=False):
    """Publish only completed checkpoint footage; retain the old video on failure."""
    playlist = directory/(name+'.concat.txt')
    playlist.write_text(''.join(f"file '{row['labelled']}'\n" for row in clips))
    output = directory/(name+'.tmp.mp4')
    try:
        subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-f','concat',
            '-safe','0','-i',str(playlist),'-c','copy','-movflags','+faststart',str(output)], check=True)
        output.replace(directory/(name+'.mp4'))
    finally:
        playlist.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
    metadata = dict(footage_scope="initial_final_matched_trial" if comparison else "detailed_replay",
        checkpoint_ids=[row.get('id', f"{row['steps']:09d}") for row in checkpoints],
        training_environment_version=manifest['environment_version'],
        renderer_environment_version=ENVIRONMENT_VERSION,
        renderer_version=RENDER_VERSION,
        training_steps=[row['steps'] for row in checkpoints],
        displayed_seeds=sorted({episode['seed'] for _, episode in episodes}),
        displayed_commands=[list(command) for command in dict.fromkeys(
            tuple(episode.get('command',manifest['environment']['command'])) for _,episode in episodes)],
        evaluation_seeds=[row['seed'] for row in checkpoints[-1]['evaluation']['episodes']],
        simulated_speed=1., final_pose_display_hold_s=1, physical_execution=False, clips=clips)
    save_json(directory/(name+'.json'),metadata)


def render(directory, *, progress=False, comparison=False):
    directory = Path(directory)
    # Manual rendering and automatic training rendering share artifact ownership.
    # Coalesce a duplicate request; never queue competing encoders for one run.
    with (directory/'render.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return
        manifest = json.loads((directory/'manifest.json').read_text())
        if (manifest.get('schema') not in SCHEMAS or
                manifest.get('environment_version') not in POLICY_ENVIRONMENT_VERSIONS or
                manifest.get('representation') != representation_identity()):
            raise ValueError('Replay requires the original observation and robot representation')
        config = EnvironmentConfig(**manifest['environment'])
        checkpoints = versions(directory, progress, comparison=True) if comparison else versions(directory, progress)
        torch.set_num_threads(1)
        name = 'progress-video' if progress else 'replay'
        metadata_path = directory/(name+'.json')
        previous = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        published = (previous.get('checkpoint_ids', []) if previous.get('renderer_version') == RENDER_VERSION
                     and previous.get('renderer_environment_version') == ENVIRONMENT_VERSION
                     and previous.get('footage_scope') == ('initial_final_matched_trial' if comparison else 'detailed_replay')
                     and (directory/(name+'.mp4')).exists() else [])
        episodes, clips, completed = [], [], []
        matched = checkpoints[0]['evaluation']['episodes'][0] if comparison else None
        for checkpoint in checkpoints:
            counts = {}
            trials = checkpoint['evaluation']['episodes']
            if comparison:
                trials = [next(episode for episode in trials if
                    episode['seed'] == matched['seed'] and
                    episode.get('command', config.command) == matched.get('command', config.command) and
                    episode.get('scenario_id') == matched.get('scenario_id'))]
            for episode in trials:
                command = (tuple(episode.get('command', config.command)), episode.get('scenario_id'))
                if progress and counts.get(command, 0) >= 2:
                    continue
                counts[command] = counts.get(command, 0)+1
                episodes.append((checkpoint, episode))
                clips.append(clip(directory,config,checkpoint,episode['seed'],episode=episode))
            completed.append(checkpoint)
            identities = [row.get('id', f"{row['steps']:09d}") for row in completed]
            # Publish each newly finished checkpoint instead of withholding all
            # footage until a growing batch finishes. Cached prefixes stay put.
            if identities != published[:len(identities)]:
                _publish_video(directory, name, manifest, completed, episodes, clips, comparison=comparison)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--progress', action='store_true')
    parser.add_argument('--comparison', action='store_true',
        help='Initial/final published weights, one matched trial each; requires --progress')
    args = parser.parse_args()
    if args.comparison and not args.progress:
        parser.error('--comparison requires --progress')
    render(args.directory, progress=args.progress, comparison=args.comparison)
