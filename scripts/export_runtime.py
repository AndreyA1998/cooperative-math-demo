"""Export a dataset checkout and this public bridge into the browser runtime."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def export_runtime(source, public=ROOT):
    source, public = Path(source), Path(public)
    paths = [source / 'source_dataset' / name for name in (
        '__init__.py', 'loader.py', 'LICENSE.MATH', 'source.lock.json')]
    paths.extend(source / 'source_dataset' / split / (table + '.jsonl')
                 for split in ('train', 'test') for table in ('problems', 'answers'))
    paths.extend(source / 'template_dataset' / name for name in (
        '__init__.py', 'core.py', 'registry.py'))
    families = source / 'template_dataset/families'
    paths.extend(path for path in sorted(families.rglob('*.py'))
                 if not {'tests', 'reports', 'tools', 'docs'}.intersection(
                     path.relative_to(families).parts))
    paths.extend(source / 'composite_dataset' / name for name in (
        '__init__.py', '__main__.py', 'schema.py', 'profiles.py', 'smart_adapters.py',
        'rendering.py', 'runtime.py', 'diagnostics.py', 'topology.py', 'patterns.py',
        'operators.py', 'serialization.py', 'data/profiles.json.gz'))
    entries = {path.relative_to(source).as_posix(): path.read_bytes() for path in paths}
    for name in ('__init__.py', 'api.py', 'presentation.py'):
        entries['math_demo/' + name] = (public / 'python/math_demo' / name).read_bytes()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    archive_path = public / 'runtime.zip'
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, contents in sorted(entries.items()):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, contents, compresslevel=9)
    manifest = {
        'format': 'math-demo-runtime-1', 'source_commit': commit,
        'sha256': sha256(archive_path.read_bytes()).hexdigest(),
        'bytes': archive_path.stat().st_size,
        'files': {name: sha256(contents).hexdigest() for name, contents in sorted(entries.items())},
    }
    (public / 'runtime.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_checkout', type=Path)
    parser.add_argument('public_checkout', type=Path, nargs='?', default=ROOT)
    args = parser.parse_args()
    manifest = export_runtime(args.source_checkout, args.public_checkout)
    print(f"Exported {len(manifest['files'])} files, {manifest['bytes']} bytes; SHA256 {manifest['sha256']}")


if __name__ == '__main__':
    main()
