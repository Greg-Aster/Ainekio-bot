"""Regenerate the checked-in stride/rate demonstration and its provenance."""
import argparse,hashlib,json,tempfile
from pathlib import Path
from retarget_clips import load_reference

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def generate(root):
    ref=load_reference(root);cfg=json.loads((root/'geometry.json').read_text())
    with tempfile.TemporaryDirectory(prefix='ainekio-walk-') as temporary:
        data,report=ref.generate(cfg,output_dir=Path(temporary))
    folder=root/'motions/walk';profile=json.loads((root/'servo_profile.json').read_text())
    source=dict(schema='ainekio.walk.reference.v3',leg_order=ref.LEGS,
        units=dict(angles='radians',lengths='mm',time='seconds'),
        columns={k:data[k].tolist() for k in ['time_s','phase','body','body_euler','q','feet','sole_z','states','stride_percent','motion_rate']})
    (folder/'source.json').write_text(json.dumps(source,separators=(',',':'),allow_nan=False)+'\n')
    manifest=json.loads((folder/'manifest.json').read_text());manifest.update(gait_id='stride-and-rate-'+profile['profile_id'],
        source_blend='Slave/hardware/v2-12servo/ainekio-variable-gait-Recovery.blend',
        electrical_zero_and_signs='Recommended references in servo_profile.json; per-joint measured calibration and direction remain operator settings.')
    manifest['sha256']={name:digest(folder/name) for name in ['reference.py','../../geometry.json','source.json']}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    report.update(hardware_qualified=False)
    (folder/'control-checks.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);generate(parser.parse_args().root)
