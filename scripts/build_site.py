"""Build the static Pages artifact without exposing tests or development files."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ('index.html', 'styles.css', 'composite.css', 'app.js', 'composite.js',
          'main.js', 'math-renderer.js', 'rpc.js', 'transport.js', 'worker.js',
          'runtime.json', 'runtime.zip', 'THIRD_PARTY.md')


def verify_runtime(source):
    """Return the verified package bytes, including the current public bridge."""
    source = Path(source)
    manifest = json.loads((source / 'runtime.json').read_text())
    archive = (source / 'runtime.zip').read_bytes()
    if (manifest.get('format') != 'math-demo-runtime-1'
            or len(archive) != manifest.get('bytes')
            or sha256(archive).hexdigest() != manifest.get('sha256')):
        raise ValueError('Runtime archive does not match its manifest')
    hashes = manifest.get('files')
    with zipfile.ZipFile(BytesIO(archive)) as package:
        names = package.namelist()
        if (not isinstance(hashes, dict) or len(names) != len(set(names))
                or set(names) != set(hashes)):
            raise ValueError('Runtime archive file list differs from its manifest')
        for name in names:
            if sha256(package.read(name)).hexdigest() != hashes[name]:
                raise ValueError('Runtime file differs from its manifest: ' + name)
        for name in ('__init__.py', 'api.py', 'presentation.py'):
            bundled = 'math_demo/' + name
            current = source / 'python' / bundled
            if (bundled not in hashes or not current.is_file()
                    or package.read(bundled) != current.read_bytes()):
                raise ValueError('Public bridge differs from runtime; re-export before publishing: ' + name)
    return archive


def build(source, output):
    source, output = Path(source), Path(output)
    verify_runtime(source)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be empty')
    output.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        shutil.copyfile(source / name, output / name)
    (output / '.nojekyll').touch()
    return output


if __name__ == '__main__':
    print(build(ROOT, Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'dist'))
