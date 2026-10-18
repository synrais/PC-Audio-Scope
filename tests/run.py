"""runs every test script and prints a summary:  python tests/run.py   (takes about a minute; the app is driven in a hidden window, nothing is played)"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = ['dsp.py', 'clips.py', 'findings.py', 'functional.py', 'flat_buttons.py', 'live_compare.py', 'window_fit.py', 'beam.py', 'eqapo.py']

bad = []
for name in SCRIPTS:
    print('=' * 20, name)
    r = subprocess.run([sys.executable, os.path.join(HERE, name)], cwd=HERE)
    if r.returncode != 0:
        bad.append(name)
print('=' * 20)
print('FAILED: ' + ', '.join(bad) if bad else 'all test scripts passed')
sys.exit(1 if bad else 0)
