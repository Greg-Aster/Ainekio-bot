"""Regenerate the checked-in stride/rate demonstration and its provenance."""
import argparse,hashlib,json,tempfile
from pathlib import Path
import numpy as np
from retarget_clips import load_reference

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def generate(root):
    ref=load_reference(root);cfg=json.loads((root/'geometry.json').read_text())
    cfg['body_translation_z_mm']=json.loads((root/'motions/locomotion/config.json').read_text())['walk']['body_z_mm']
    with tempfile.TemporaryDirectory(prefix='ainekio-walk-') as temporary:
        data,report=ref.generate(cfg,output_dir=Path(temporary))
    folder=root/'motions/walk';profile=json.loads((root/'servo_profile.json').read_text())
    original_time=data['time_s'].copy();dt=np.diff(original_time)
    steps=np.rad2deg(abs(np.diff(data['q'],axis=0)))
    demand=float(np.max(steps/dt[:,None,None]));rated=profile['gait_max_joint_speed_degrees_s']
    flagged=demand>=rated*profile['servo_speed_excess_flag_ratio']
    if flagged:
        intervals=np.maximum(dt,steps.max(axis=(1,2))/rated)
        data['time_s']=np.r_[original_time[0],original_time[0]+np.cumsum(intervals)]
        report['duration_s']=float(data['time_s'][-1]-data['time_s'][0])
        velocity=np.gradient(data['q'],data['time_s'],axis=0)
        report['peak_joint_speed_deg_s']=np.rad2deg(abs(velocity)).max(axis=0).tolist()
        report['peak_joint_acceleration_deg_s2']=np.rad2deg(abs(np.gradient(velocity,data['time_s'],axis=0))).max(axis=0).tolist()
        speed=np.diff(data['body'][:,0])/intervals;frequency=np.diff(data['phase'])/intervals
        report['body_speed_mm_s_range']=[float(speed.min()),float(speed.max())]
        report['cycle_frequency_hz_range']=[float(frequency.min()),float(frequency.max())]
        report['effective_sample_hz_range']=[float(1/intervals.max()),float(1/intervals.min())]
        for event in report['timeline']:event['time_s']=float(np.interp(event['phase'],data['phase'],data['time_s']))
    report['speed_retiming']=dict(rated_degrees_s=rated,flag_threshold_degrees_s=rated*profile['servo_speed_excess_flag_ratio'],
        original_peak_degrees_s=demand,flagged=flagged,original_duration_s=float(original_time[-1]-original_time[0]),
        final_peak_degrees_s=float(np.max(steps/np.diff(data['time_s'])[:,None,None])),joint_and_body_paths_preserved=True)
    source=dict(schema='ainekio.walk.reference.v3',leg_order=ref.LEGS,
        units=dict(angles='radians',lengths='mm',time='seconds'),
        columns={k:data[k].tolist() for k in ['time_s','phase','body','body_euler','q','feet','sole_z','states','stride_percent','motion_rate']})
    (folder/'source.json').write_text(json.dumps(source,separators=(',',':'),allow_nan=False)+'\n')
    manifest=json.loads((folder/'manifest.json').read_text());manifest.update(gait_id='stride-and-rate-'+profile['profile_id'],geometry_id=cfg['geometry_id'],
        source_blend='Slave/hardware/v2-12servo/ainekio-variable-gait-Recovery.blend',
        electrical_zero_and_signs='Recommended references in servo_profile.json; per-joint measured calibration and direction remain operator settings.')
    manifest['sha256']={name:digest(folder/name) for name in ['reference.py','../../geometry.json','../locomotion/config.json','source.json']}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    report.update(hardware_qualified=False)
    (folder/'control-checks.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);generate(parser.parse_args().root)
