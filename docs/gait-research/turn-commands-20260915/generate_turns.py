"""Generate independently retained finite turn commands with measured four-bar IK.

Run with Python containing numpy. No Blender, network or hardware output is used.
"""
import argparse
import json
import math
from pathlib import Path
import turn_planner

P = Path(__file__).resolve().parent
COMMANDS = [f'turn_{side}_{angle}' for angle in [180,90,45,15] for side in ['right','left']]


def config(command):
    _, direction, degrees = command.split('_')
    angle = int(degrees)
    if command not in COMMANDS:
        raise ValueError(command)
    title = f'Turn {direction.title()} {angle}'
    root = f'commands/{command}'
    return dict(command=command, name=title+' - twelve-servo four-bar', direction=direction,
                yaw_degrees=angle*(-1 if direction=='right' else 1),
                turn_cycles=math.ceil(angle/30), sample_hz=120,
                cad_leg_order=['FL','RL','FR','RR'] if direction=='right' else ['FR','RR','FL','RL'],
                source_blend='Before-Turn-Family.blend',
                configuration_file=f'{root}/config.json', output_blend=f'{root}/Ainekio-{title.replace(" ","-")}.blend',
                scene_name='AINEKIO - '+title, reference_report=f'{root}/README.md',
                gait_id=command+'_fourbar_20260915', display_label=title.upper()+' | TWELVE SERVOS',
                acceptance_status='GEOMETRIC_TURN_RESEARCH_UNQUALIFIED_HARDWARE')


def write_source(command, data):
    folder = P/'commands'/command
    folder.mkdir(parents=True, exist_ok=True)
    phases={(p['kind'],p['cycle']):p for p in data['phases']}
    for row in data['samples']:
        phase=phases.get((row['phase'],row['cycle']))
        if phase:
            row['phase_fraction']=min(1.,max(0.,(row['time_s']-phase['start'])/(phase['end']-phase['start'])))
    for name,value in [('source.json',data),('config.json',data['metadata']['configuration']),('validation.json',data['validation'])]:
        (folder/name).write_text(json.dumps(value,indent=None if name=='source.json' else 2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('commands',nargs='*',default=COMMANDS)
    args=parser.parse_args()
    for command in args.commands:
        print('GENERATING',command,flush=True)
        data=turn_planner.generate(config(command))
        write_source(command,data)
        v=data['validation']
        print(json.dumps(dict(command=command,duration_s=v['duration_s'],heading_degrees=v['heading_change_degrees'],
                              minimum_support_margin_mm=v['minimum_support_margin_mm'],samples=v['samples'])),flush=True)
