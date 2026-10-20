import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('github_release', Path(__file__).with_name('github-release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class GitHubReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.asset = self.root / 'bgdesk-cliente.dmg'
        self.asset.write_bytes(b'validated DMG')
        self.manifest = self.root / 'artifacts.json'
        self.record = dict(version='1.5.1', edition='cliente', platform='macos', arch='aarch64',
                           file_name=self.asset.name, size=self.asset.stat().st_size, sha256=release.digest(self.asset))
        self.manifest.write_text(json.dumps([self.record]))

    def test_only_the_verified_edition_is_uploaded_and_a_retry_reuses_identical_assets(self):
        target, files = release.read_edition(self.manifest)
        self.assertEqual(target, ('1.5.1', 'macos', 'aarch64', 'cliente'))
        existing = {'assets': [{'name': self.asset.name, 'size': self.asset.stat().st_size,
                               'digest': 'sha256:' + release.digest(self.asset)}]}
        with patch.object(release, 'gh') as gh:
            release.upload_files('owner/repo', 'validation', existing, files)
        gh.assert_not_called()

    def test_tampered_binaries_are_rejected_before_any_release_api_call(self):
        self.asset.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'mismatch'), patch.object(release, 'gh') as gh:
            release.read_edition(self.manifest)
        gh.assert_not_called()

    def test_existing_release_from_another_commit_is_never_overwritten(self):
        with patch.object(release, 'release', return_value={'target_commitish': 'old-commit'}), \
             patch.object(release, 'gh') as gh:
            with self.assertRaisesRegex(ValueError, 'another commit'):
                release.ensure_release('owner/repo', 'tag', 'new-commit', 'title', 'notes', draft=False)
        gh.assert_not_called()

    def test_draft_on_a_later_page_is_reused_after_the_tag_endpoint_returns_404(self):
        draft = {'id': 123, 'tag_name': 'v1.5.1', 'draft': True, 'target_commitish': 'a' * 40, 'assets': []}
        responses = [subprocess.CompletedProcess([], 1, '', 'gh: Not Found (HTTP 404)'),
                     subprocess.CompletedProcess([], 0, json.dumps([[{'tag_name': 'other'}], [draft]]), '')]
        with patch.object(release, 'gh', side_effect=responses) as gh:
            found = release.ensure_release('owner/repo', 'v1.5.1', 'a' * 40, 'title', 'notes', draft=True)
        self.assertEqual(found, draft)
        self.assertEqual(gh.call_count, 2)  # No second draft is created on resume.
        self.assertEqual(gh.call_args.args, ('api', '--paginate', '--slurp',
                                           'repos/owner/repo/releases?per_page=100'))

    def test_new_draft_is_found_without_a_published_git_tag(self):
        draft = {'target_commitish': 'a' * 40, 'draft': True, 'assets': []}
        with patch.object(release, 'release', side_effect=[None, draft]), patch.object(release, 'gh') as gh:
            self.assertEqual(release.ensure_release('owner/repo', 'tag', 'a' * 40, 'title', 'notes', draft=True), draft)
        self.assertIn('--draft', gh.call_args.args)

    def test_missing_created_release_reports_a_clear_error(self):
        with patch.object(release, 'release', return_value=None), patch.object(release, 'gh'):
            with self.assertRaisesRegex(RuntimeError, 'cannot be found'):
                release.ensure_release('owner/repo', 'tag', 'a' * 40, 'title', 'notes', draft=True)

    def test_query_errors_other_than_not_found_do_not_create_another_release(self):
        with patch.object(release, 'gh', return_value=subprocess.CompletedProcess([], 1, '', 'HTTP 403')) as gh:
            with self.assertRaisesRegex(RuntimeError, 'Cannot query'):
                release.ensure_release('owner/repo', 'tag', 'a' * 40, 'title', 'notes', draft=True)
        self.assertEqual(gh.call_count, 1)

    def test_stable_release_requires_the_entire_artifact_matrix(self):
        with patch('sys.argv', ['release', '--stable', '--version', '1.5.1', '--artifacts', str(self.root),
                                '--commit', 'a' * 40]), patch.object(release, 'gh') as gh:
            with self.assertRaisesRegex(ValueError, 'Incomplete release'):
                release.main()
        gh.assert_not_called()

    def windows_manifest(self, arch):
        records = []
        for fmt, suffix in [('exe', ''), ('inno-exe', '-setup')]:
            path = self.root / f'bgdesk-cliente-windows-{arch}{suffix}.exe'
            path.write_bytes(('signed ' + fmt).encode())
            records.append(dict(version='1.5.2', edition='cliente', platform='windows', arch=arch,
                                format=fmt, file_name=path.name, size=path.stat().st_size,
                                sha256=release.digest(path)))
        self.manifest.write_text(json.dumps(records))
        return records

    def test_windows_32_and_64_releases_expose_only_setup_and_matching_public_metadata(self):
        for arch in ('x86', 'x86_64'):
            records = self.windows_manifest(arch)
            uploads = []
            def capture(repo, tag, existing, files):
                uploads.extend(path.name for path in files)
                manifest = next(p for p in files if p.name == 'artifacts-cliente.json')
                self.assertEqual(json.loads(manifest.read_text()), [records[1]])
                checksums = next(p for p in files if p.name == 'SHA256SUMS-cliente.txt')
                self.assertEqual(checksums.read_text(), f"{records[1]['sha256']}  {records[1]['file_name']}\n")
            with patch('sys.argv', ['release', '--manifest', str(self.manifest), '--commit', 'a' * 40,
                                    '--run-id', '123']), \
                 patch.object(release, 'ensure_release', return_value={'assets': []}), \
                 patch.object(release, 'upload_files', side_effect=capture):
                release.main()
            self.assertIn(records[1]['file_name'], uploads)
            self.assertNotIn(records[0]['file_name'], uploads)
            # Filtering public downloads does not permit a corrupt internal updater.
            (self.root / records[0]['file_name']).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                release.read_edition(self.manifest)

    def test_stable_validates_all_26_packages_but_uploads_only_22_public_installers(self):
        from preflight import artifact_targets
        for platform, arch in artifact_targets():
            for edition in ('cliente', 'suporte'):
                directory = self.root / f'{platform}-{arch}-{edition}'
                directory.mkdir()
                formats = (('exe', 'inno-exe') if platform == 'windows' else ('dmg',) if platform == 'macos'
                           else ('deb', 'rpm', 'AppImage', 'pkg.tar.zst') if arch == 'x86_64'
                           else ('deb', 'rpm', 'AppImage'))
                records = []
                for fmt in formats:
                    name = f'{edition}-{platform}-{arch}-{fmt}.bin'
                    path = directory / name
                    path.write_bytes(name.encode())
                    records.append(dict(platform=platform, arch=arch, edition=edition, format=fmt,
                        version='1.5.2', file_name=name, size=path.stat().st_size, sha256=release.digest(path)))
                (directory / 'artifacts.json').write_text(json.dumps(records))
        self.manifest.unlink()
        with patch('sys.argv', ['release', '--stable', '--version', '1.5.2', '--artifacts', str(self.root),
                                '--commit', 'a' * 40]), \
             patch.object(release, 'ensure_release', return_value={'assets': []}), \
             patch.object(release, 'upload_files') as upload, patch.object(release, 'gh'):
            release.main()
        files = upload.call_args.args[-1]
        self.assertEqual(len(files), 22)
        windows = [p for p in files if '-windows-' in p.name]
        self.assertEqual(len(windows), 4)
        self.assertTrue(all('inno-exe' in p.name for p in windows))
