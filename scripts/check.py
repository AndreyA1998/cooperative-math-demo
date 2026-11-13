"""Test the actual bundled runtime, independent of a private research checkout."""
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from build_site import verify_runtime

ROOT = Path(__file__).resolve().parents[1]
verified_archive = verify_runtime(ROOT)
scratch = ROOT / '.cache/tmp'
scratch.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('TMPDIR', str(scratch))
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.cache/ms-playwright'))
with tempfile.TemporaryDirectory(prefix='math-demo-check-') as folder:
    with zipfile.ZipFile(BytesIO(verified_archive)) as archive:
        archive.extractall(folder)
    env = dict(os.environ, PYTHONPATH=folder,
               PYTHONDONTWRITEBYTECODE='1', MATH_DEMO_REQUIRE_BROWSER='1')
    command = [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(ROOT / 'tests'), '-v']
    raise SystemExit(subprocess.call(command, cwd=ROOT, env=env))
