"""Generate firmware/model constants from the one V2 servo profile."""
import argparse,json,math
from pathlib import Path
def generate(root,out):
    p=json.loads((root/"servo_profile.json").read_text());out.mkdir(parents=True,exist_ok=True)
    speed=p['gait_max_joint_speed_degrees_s']
    if not math.isfinite(speed) or speed<=0:raise ValueError('Gait joint speed must be finite and positive')
    ratio=p['servo_speed_excess_flag_ratio']
    if not math.isfinite(ratio) or ratio<1:raise ValueError('Servo excess flag ratio must be finite and at least one')
    def array(v):return '{'+','.join(array(x) if isinstance(x,list) else format(x,'.17g') for x in v)+'}'
    h=['/* Generated from servo_profile.json; do not edit. */','#ifndef AINEKIO_V2_SERVO_DATA_H','#define AINEKIO_V2_SERVO_DATA_H',
       'extern const double v2_joint_center_degrees[3];','extern const unsigned v2_joint_reference_us[3];',
       f'#define V2_SERVO_PULSE_MIDPOINT_US ({sum(p["pulse_range_us"])/2:.17g})',
       f'#define V2_SERVO_US_PER_DEGREE ({p["us_per_degree"]:.17g})',
       f'#define V2_GAIT_MAX_JOINT_SPEED_DEGREES_S ({speed:.17g})',
       f'#define V2_SERVO_SPEED_EXCESS_FLAG_RATIO ({p["servo_speed_excess_flag_ratio"]:.17g})',
       f'#define V2_SERVO_PROFILE_ID {json.dumps(p["profile_id"])}','#endif']
    c=['#include "servo_data.h"',f'const double v2_joint_center_degrees[3]={array(p["center_degrees"])};',f'const unsigned v2_joint_reference_us[3]={array(p["pulse_reference_us"])};']
    (out/'servo_data.h').write_text('\n'.join(h)+'\n');(out/'servo_data.c').write_text('\n'.join(c)+'\n')
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();generate(a.root,a.out)
