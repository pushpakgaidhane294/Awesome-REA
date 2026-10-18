"""A rebuilt deployment replaces old output without sacrificing the last good build."""
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_site
from build_manifest import read_build_manifest


def file_bytes(directory):
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in directory.rglob('*') if path.is_file()}


class StagedSiteBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.output = self.root / 'site', self.root / 'dist'
        # Real renderers/assets, but only one resource and one paper; no scan snapshot.
        shutil.copytree(ROOT / 'site', self.source)
        data = self.root / 'data'
        data.mkdir()
        for filename in ('rea-resources.json', 'papers.json'):
            records = json.loads((ROOT / 'data' / filename).read_text())[:1]
            (data / filename).write_text(json.dumps(records))
        (data / 'tool-resources.json').write_text('[]')
        self.unowned = self.root / 'keep.txt'
        self.unowned.write_bytes(b'Not deployment output\n')
        stack = self.enterContext(ExitStack())
        for name, value in [('ROOT', self.root), ('SOURCE', self.source), ('OUTPUT', self.output)]:
            stack.enter_context(patch.object(build_site, name, value))

    def build(self, **kwargs):
        result = build_site.build_staged_site(**kwargs)
        self.assertEqual(result[:2], (1, 1))
        manifest = read_build_manifest(self.output)
        self.assertTrue(manifest['files']['index.html']['html_sha256'])
        self.assertNotIn(str(self.root), json.dumps(manifest))
        self.assertEqual(self.unowned.read_bytes(), b'Not deployment output\n')
        self.assertEqual(list((self.root / '.cache').glob('site-build-*')), [])
        return manifest

    def test_deleted_assets_and_nested_files_do_not_survive_rebuild(self):
        (self.source / 'legacy.css').write_text('old css')
        (self.source / 'old').mkdir()
        (self.source / 'old' / 'data.txt').write_text('old nested data')
        first = self.build()
        self.assertIn('legacy.css', first['files'])
        self.assertIn('old/data.txt', first['files'])
        (self.source / 'legacy.css').unlink()
        shutil.rmtree(self.source / 'old')
        second = self.build()
        for path in ('legacy.css', 'old/data.txt'):
            self.assertFalse((self.output / path).exists())
            self.assertNotIn(path, second['files'])
        # A normal repeated build has identical bytes, including its manifest.
        expected = file_bytes(self.output)
        self.build()
        self.assertEqual(file_bytes(self.output), expected)

    def test_late_generation_failure_preserves_prior_valid_output(self):
        self.build()
        expected = file_bytes(self.output)
        (self.source / 'app.js').write_text((self.source / 'app.js').read_text() + '\n// changed asset\n')
        with patch.object(build_site, 'write_build_manifest', side_effect=ValueError('late manifest failure')):
            with self.assertRaisesRegex(ValueError, 'late manifest failure'):
                build_site.build_staged_site()
        self.assertEqual(file_bytes(self.output), expected)
        read_build_manifest(self.output)
        self.assertEqual(list((self.root / '.cache').glob('site-build-*')), [])
        self.assertEqual(self.unowned.read_bytes(), b'Not deployment output\n')

    def test_failed_replacement_restores_prior_valid_output(self):
        self.build()
        expected = file_bytes(self.output)
        rename = Path.rename

        def fail_next(path, target):
            if path.name == 'next':
                raise OSError('replacement failed')
            return rename(path, target)

        with patch.object(Path, 'rename', fail_next):
            with self.assertRaisesRegex(OSError, 'replacement failed'):
                build_site.build_staged_site()
        self.assertEqual(file_bytes(self.output), expected)
        read_build_manifest(self.output)
        self.assertEqual(list((self.root / '.cache').glob('site-build-*')), [])

    def test_failed_rollback_keeps_recoverable_previous_output(self):
        self.build()
        expected = file_bytes(self.output)
        rename = Path.rename

        def fail_next_and_restore(path, target):
            if path.name in {'next', 'previous'}:
                raise OSError('rename failed')
            return rename(path, target)

        with patch.object(Path, 'rename', fail_next_and_restore):
            with self.assertRaisesRegex(RuntimeError, 'prior deployment.*preserved'):
                build_site.build_staged_site()
        preserved = list((self.root / '.cache').glob('site-build-*/previous'))
        self.assertEqual(len(preserved), 1)
        self.assertEqual(file_bytes(preserved[0]), expected)
        read_build_manifest(preserved[0])
        self.assertEqual(self.unowned.read_bytes(), b'Not deployment output\n')

    def test_output_symlink_and_file_are_rejected_without_touching_target(self):
        external = self.root / 'other'
        external.mkdir()
        (external / 'keep.txt').write_text('preserve me')
        self.output.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink or file'):
            build_site.build_staged_site()
        self.assertEqual(file_bytes(external), {'keep.txt': b'preserve me'})
        self.output.unlink()
        self.output.write_text('unrelated file')
        with self.assertRaisesRegex(ValueError, 'symlink or file'):
            build_site.build_staged_site()
        self.assertEqual(self.output.read_text(), 'unrelated file')
        self.assertFalse((self.root / '.cache').exists())

    def test_cache_symlink_is_rejected_without_touching_target(self):
        external = self.root / 'other'
        external.mkdir()
        (external / 'keep.txt').write_text('preserve me')
        (self.root / '.cache').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink or file'):
            build_site.build_staged_site()
        self.assertEqual(file_bytes(external), {'keep.txt': b'preserve me'})
        self.assertFalse(self.output.exists())

    def test_synthetic_font_package_stays_separate_across_all_modes(self):
        # Fabricated fixtures only: no licensed font data enters the test sources.
        package = self.root / 'synthetic-icons'
        (package / 'css').mkdir(parents=True)
        (package / 'webfonts').mkdir()
        css = '\n'.join('.fa-' + name + '{--fa:"\\f001";}'
                        for name in set(build_site.FONT_AWESOME_ICONS.values()))
        for name in ('fontawesome.css', 'brands.css', 'light.css'):
            (package / 'css' / name).write_text(css)
        fonts = ('fa-light-300.woff2', 'fa-brands-400.woff2')
        for name in fonts:
            (package / 'webfonts' / name).write_bytes(b'synthetic test bytes, not a font')
        input_before = file_bytes(package)
        source_before = file_bytes(self.source)
        manifest = self.build(fontawesome_dir=package)
        self.assertIn('fontawesome.css', manifest['files'])
        for name in fonts:
            self.assertEqual((self.output / 'fonts' / name).read_bytes(), input_before['webfonts/' + name])
            self.assertNotIn('fonts/' + name, manifest['files'])
        self.assertIn('data-icon-set="fontawesome"', (self.output / 'index.html').read_text())
        self.build(fontawesome_assets_url='https://example.org/icons')
        self.assertIn('https://example.org/icons/fontawesome.css', (self.output / 'index.html').read_text())
        self.assertFalse((self.output / 'fontawesome.css').exists())
        self.assertFalse((self.output / 'fonts').exists())
        self.build()
        html = (self.output / 'index.html').read_text()
        self.assertNotIn('fontawesome.css', html)
        self.assertNotIn('data-icon-set="fontawesome"', html)
        self.assertIn('class="symbol-bank"', html)
        self.assertFalse((self.output / 'fontawesome.css').exists())
        self.assertFalse((self.output / 'fonts').exists())
        self.assertEqual(file_bytes(package), input_before)
        self.assertEqual(file_bytes(self.source), source_before)

    def test_invalid_font_input_preserves_prior_output(self):
        self.build()
        expected = file_bytes(self.output)
        with self.assertRaisesRegex(ValueError, 'Font Awesome input'):
            build_site.build_staged_site(fontawesome_dir=self.root / 'missing-icons')
        self.assertEqual(file_bytes(self.output), expected)
        read_build_manifest(self.output)
        self.assertEqual(list((self.root / '.cache').glob('site-build-*')), [])


if __name__ == '__main__':
    unittest.main()
