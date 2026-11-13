"""The deploy artifact and verification must use the exact published runtime."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('build_site', ROOT / 'scripts/build_site.py')
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)

    def runtime_fixture(self, root):
        """A tiny genuine package, checked by the actual scripts and test loader."""
        root.mkdir()
        for name in self.builder.ASSETS:
            (root / name).write_text('fixture\n')
        files = {name: b'# packaged fixture\n' for name in (
            'source_dataset/__init__.py', 'template_dataset/__init__.py',
            'composite_dataset/__init__.py', 'math_demo/__init__.py',
            'math_demo/api.py', 'math_demo/presentation.py', 'math_demo/expression_patterns.py', 'math_demo/source_bindings.py')}
        with zipfile.ZipFile(root / 'runtime.zip', 'w') as archive:
            for name, contents in files.items():
                archive.writestr(name, contents)
        for name, contents in files.items():
            if name.startswith('math_demo/'):
                target = root / 'python' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
        raw = (root / 'runtime.zip').read_bytes()
        manifest = {'format': 'math-demo-runtime-1', 'source_commit': 'fixture',
                    'bytes': len(raw), 'sha256': sha256(raw).hexdigest(),
                    'files': {name: sha256(contents).hexdigest() for name, contents in files.items()}}
        (root / 'runtime.json').write_text(json.dumps(manifest))
        (root / 'scripts').mkdir()
        for name in ('check.py', 'build_site.py'):
            shutil.copyfile(ROOT / 'scripts' / name, root / 'scripts' / name)
        (root / 'tests').mkdir()
        shutil.copyfile(ROOT / 'tests/support.py', root / 'tests/support.py')
        (root / 'tests/test_origins.py').write_text('''import os
from pathlib import Path
import unittest
from support import ensure_runtime
ensure_runtime()
import source_dataset, template_dataset, composite_dataset
import math_demo.api
Path(__file__).with_name('probe.started').write_text('yes')
class Origins(unittest.TestCase):
    def test_imports_are_from_the_unpacked_runtime(self):
        package = Path(os.environ['PYTHONPATH'].split(os.pathsep)[-1]).resolve()
        for module in (source_dataset, template_dataset, composite_dataset):
            self.assertEqual(Path(module.__file__).resolve().parents[1], package)
        self.assertEqual(Path(math_demo.api.__file__).resolve().parents[1], package)
''')
        return manifest

    def check_fixture(self, root):
        return subprocess.run([sys.executable, '-B', str(root / 'scripts/check.py')],
                              cwd=root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                              capture_output=True, text=True, timeout=30)

    def test_static_artifact_is_self_contained_and_allowlisted(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'site'
            self.builder.build(ROOT, output)
            names = {p.name for p in output.iterdir()}
            self.assertIn('index.html', names)
            self.assertIn('runtime.zip', names)
            self.assertIn('worker.js', names)
            self.assertNotIn('tests', names)
            self.assertNotIn('python', names)
            self.assertNotIn('.git', names)
            self.assertIn('.nojekyll', names)
            for name in names - {'.nojekyll'}:
                self.assertEqual((ROOT / name).read_bytes(), (output / name).read_bytes())

    def test_check_imports_all_dataset_packages_from_the_verified_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            self.runtime_fixture(root)
            result = self.check_fixture(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((root / 'tests/probe.started').exists())

    def test_check_rejects_edited_checkout_bridge_before_running_tests(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            self.runtime_fixture(root)
            (root / 'python/math_demo/api.py').write_text('# changed since export\n')
            result = self.check_fixture(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('bridge', result.stdout + result.stderr)
            self.assertFalse((root / 'tests/probe.started').exists())

    def test_build_rejects_each_bridge_file_changed_since_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            self.runtime_fixture(root)
            for name in ('__init__.py', 'api.py', 'presentation.py', 'expression_patterns.py', 'source_bindings.py'):
                source = root / 'python/math_demo' / name
                original = source.read_bytes()
                source.write_text('# changed since export\n')
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'bridge'):
                    self.builder.build(root, Path(folder) / name)
                source.write_bytes(original)

    def test_build_rejects_per_file_hash_mismatch_even_with_matching_archive_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            manifest = self.runtime_fixture(root)
            manifest['files']['template_dataset/__init__.py'] = '0' * 64
            (root / 'runtime.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                self.builder.build(root, Path(folder) / 'site')

    def test_build_requires_exact_archive_and_manifest_file_sets(self):
        for mismatch in ('missing', 'extra', 'duplicate'):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as folder:
                root = Path(folder) / 'source'
                manifest = self.runtime_fixture(root)
                if mismatch == 'missing':
                    manifest['files'].pop('template_dataset/__init__.py')
                elif mismatch == 'extra':
                    manifest['files']['missing.py'] = '0' * 64
                else:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', UserWarning)
                        with zipfile.ZipFile(root / 'runtime.zip', 'a') as archive:
                            archive.writestr('template_dataset/__init__.py', b'# duplicate\n')
                    raw = (root / 'runtime.zip').read_bytes()
                    manifest.update(bytes=len(raw), sha256=sha256(raw).hexdigest())
                (root / 'runtime.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    self.builder.build(root, Path(folder) / 'site')

    def test_explicit_private_checkout_uses_current_public_bridge(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'
            self.runtime_fixture(root)
            private = Path(folder) / 'private'
            for name in ('source_dataset', 'template_dataset', 'composite_dataset'):
                (private / name).mkdir(parents=True)
                (private / name / '__init__.py').write_text('# private fixture\n')
            script = '''import sys
from pathlib import Path
sys.path.insert(0, 'tests')
from support import ensure_runtime
ensure_runtime()
import source_dataset, template_dataset, composite_dataset, math_demo.api
for module in (source_dataset, template_dataset, composite_dataset):
    assert Path(module.__file__).resolve().parents[1] == Path(sys.argv[1]).resolve()
assert Path(math_demo.api.__file__).resolve() == Path('python/math_demo/api.py').resolve()
'''
            result = subprocess.run([sys.executable, '-B', '-c', script,
                                     str(private)], cwd=root,
                                    env=dict(os.environ, PYTHONPATH=str(private), PYTHONDONTWRITEBYTECODE='1'),
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
