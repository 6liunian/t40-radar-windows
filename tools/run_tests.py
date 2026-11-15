"""Run offline suites without starting the radar application."""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
env = dict(os.environ)
env['PYTHONPATH'] = os.pathsep.join(str(root / p) for p in ('native_windows', 'radar_client', 'desktop'))
env['MPLBACKEND'] = 'Agg'
failed = False
for folder in ('native_windows/tests', 'windows', 'web-radar'):
    print(f'Running {folder}', flush=True)
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', folder, '-p', 'test_*.py'], cwd=root, env=env)
    failed |= result.returncode != 0
sys.exit(1 if failed else 0)
