"""Rebuild the three seated clips in an explicitly selected candidate model.

NumPy and SciPy are required. The baseline and candidate must be separate model
directories. This only updates offline recordings and their provenance files.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', type=Path, required=True)
parser.add_argument('--model', type=Path, required=True)
args = parser.parse_args()
scripts = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='ainekio-seated-') as work:
    env = dict(os.environ, AINEKIO_REMAP_BASE=str(args.baseline.resolve()),
               AINEKIO_REMAP_MODEL=str(args.model.resolve()),
               AINEKIO_REMAP_WORK=work)
    subprocess.run([sys.executable, str(scripts/'remap.py')], env=env, check=True)
    subprocess.run([sys.executable, '-c', 'import remap; remap.wave()'],
                   cwd=scripts, env=env, check=True)
    for name in ['build-upright.py', 'package.py']:
        subprocess.run([sys.executable, str(scripts/name)], env=env, check=True)
