"""The public repository owns reproducible, narrowly scoped runtime exports."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class PublicExportTests(unittest.TestCase):
    def exporter(self):
        path = ROOT / 'scripts/export_runtime.py'
        self.assertTrue(path.is_file(), 'public runtime exporter is missing')
        spec = importlib.util.spec_from_file_location('export_runtime', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self, directory):
        source, public = Path(directory) / 'source', Path(directory) / 'public'
        source.mkdir()
        public.mkdir()
        names = [
            'source_dataset/__init__.py', 'source_dataset/loader.py',
            'source_dataset/LICENSE.MATH', 'source_dataset/source.lock.json',
            'template_dataset/__init__.py', 'template_dataset/core.py',
            'template_dataset/registry.py', 'template_dataset/families/__init__.py',
            'template_dataset/families/algebra.py',
            'template_dataset/families/extensions/__init__.py',
            'template_dataset/families/extensions/example.py',
            'composite_dataset/__init__.py', 'composite_dataset/__main__.py',
            'composite_dataset/schema.py', 'composite_dataset/profiles.py',
            'composite_dataset/smart_adapters.py', 'composite_dataset/rendering.py',
            'composite_dataset/runtime.py', 'composite_dataset/diagnostics.py',
            'composite_dataset/topology.py', 'composite_dataset/patterns.py',
            'composite_dataset/operators.py', 'composite_dataset/serialization.py',
            'composite_dataset/data/profiles.json.gz',
        ]
        names += [f'source_dataset/{split}/{table}.jsonl'
                  for split in ('train', 'test') for table in ('problems', 'answers')]
        forbidden = [
            'source_dataset/reports/verification.json', 'source_dataset/tests/test_source.py',
            'template_dataset/reports/parameters.jsonl', 'template_dataset/audit.py',
            'template_dataset/__main__.py', 'template_dataset/tests/test_template.py',
            'template_dataset/families/reports/private.py',
            'composite_dataset/tests/test_runtime.py', 'composite_dataset/reports/private.json',
            'composite_dataset/audit_large.py', 'composite_dataset/tools/audit.py',
            'composite_dataset/data/private.json', 'docs/private.md',
        ]
        for name in names + forbidden:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# ' + name + '\n')
        for name in ('__init__.py', 'api.py', 'presentation.py', 'secret.txt'):
            path = public / 'python/math_demo' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# public ' + name + '\n')
        subprocess.run(['git', 'init', '-q', str(source)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(source), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Runtime Test',
                        '-c', 'user.email=runtime-test@example.invalid',
                        'commit', '-qm', 'Fixture'], check=True, capture_output=True)
        expected = set(names) | {'math_demo/' + name for name in
                                ('__init__.py', 'api.py', 'presentation.py')}
        return source, public, expected

    def test_reproducible_allowlist_and_hashes(self):
        module = self.exporter()
        with tempfile.TemporaryDirectory() as directory:
            source, public, expected = self.fixture(directory)
            first = module.export_runtime(source, public)
            payload = (public / 'runtime.zip').read_bytes()
            second = module.export_runtime(source, public)
            self.assertEqual(first, second)
            self.assertEqual(payload, (public / 'runtime.zip').read_bytes())
            self.assertEqual(json.loads((public / 'runtime.json').read_text()), first)
            self.assertEqual(first['sha256'], sha256(payload).hexdigest())
            self.assertEqual(first['bytes'], len(payload))
            commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                                             text=True).strip()
            self.assertEqual(first['source_commit'], commit)
            with zipfile.ZipFile(public / 'runtime.zip') as archive:
                self.assertEqual(set(archive.namelist()), expected)
                self.assertEqual(set(first['files']), expected)
                self.assertEqual(len(archive.namelist()), len(expected))
                for name in expected:
                    self.assertEqual(first['files'][name], sha256(archive.read(name)).hexdigest())
                    self.assertEqual(archive.getinfo(name).date_time, (1980, 1, 1, 0, 0, 0))
                    origin = (public / 'python' / name if name.startswith('math_demo/')
                              else source / name)
                    self.assertEqual(archive.read(name), origin.read_bytes())

    def test_cli_defaults_to_its_public_checkout(self):
        self.exporter()
        with tempfile.TemporaryDirectory() as directory:
            source, public, expected = self.fixture(directory)
            (public / 'scripts').mkdir()
            script = public / 'scripts/export_runtime.py'
            shutil.copyfile(ROOT / 'scripts/export_runtime.py', script)
            result = subprocess.run([sys.executable, '-B', str(script), str(source)],
                                    cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest = json.loads((public / 'runtime.json').read_text())
            self.assertEqual(set(manifest['files']), expected)


if __name__ == '__main__':
    unittest.main()
