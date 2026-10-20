import hashlib
import base64
import copy
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

    def test_stable_validates_all_28_packages_but_uploads_only_24_public_packages(self):
        from preflight import artifact_targets
        for platform, arch in artifact_targets():
            for edition in ('cliente', 'suporte'):
                directory = self.root / f'{platform}-{arch}-{edition}'
                directory.mkdir()
                formats = (('apk',) if platform == 'android' else ('exe', 'inno-exe') if platform == 'windows' else ('dmg',) if platform == 'macos'
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
        self.assertEqual(len(files), 24)
        windows = [p for p in files if '-windows-' in p.name]
        self.assertEqual(len(windows), 4)
        self.assertTrue(all('inno-exe' in p.name for p in windows))

    def existing_stable_fixture(self, missing):
        records, assets = [], []
        for arch in ('x86', 'x86_64'):
            for edition in ('cliente', 'suporte'):
                for fmt, suffix in [('exe', ''), ('inno-exe', '-setup')]:
                    path = self.root / f'bgdesk-{edition}-1.5.1-windows-{arch}{suffix}.exe'
                    path.write_bytes(path.name.encode())
                    record = dict(platform='windows', arch=arch, edition=edition, format=fmt,
                                  file_name=path.name, sha256=release.digest(path), size=path.stat().st_size)
                    records.append((record, path))
                    # The old stable contains native x64 packages, but not native Win32.
                    if (arch, edition) not in missing and (fmt == 'inno-exe' or arch == 'x86_64'):
                        assets.append(dict(id=len(assets)+1, name=path.name, size=path.stat().st_size,
                                           digest='sha256:' + record['sha256']))
        stable = dict(target_commitish='c' * 40, draft=False, prerelease=False, assets=assets)
        mutations = []
        def gh(*args, **kwargs):
            if args[:2] == ('api', 'repos/owner/repo/contents/Cargo.toml?ref=v1.5.1'):
                content = base64.b64encode(b'[package]\nversion="1.5.1"\n').decode()
                return subprocess.CompletedProcess([], 0, json.dumps(dict(content=content)), '')
            if args[:2] == ('release', 'upload'):
                path = Path(args[3])
                stable['assets'].append(dict(id=100+len(stable['assets']), name=path.name,
                    size=path.stat().st_size, digest='sha256:'+release.digest(path)))
            elif args[:3] == ('api', '--method', 'DELETE'):
                asset_id = int(args[3].split('/')[-1])
                stable['assets'] = [a for a in stable['assets'] if a['id'] != asset_id]
            elif args[:2] == ('release', 'download'):
                directory = Path(args[args.index('--dir')+1])
                (directory / args[args.index('--pattern')+1]).write_bytes(b'wrong bytes')
                return subprocess.CompletedProcess([], 0, '', '')
            else:
                raise AssertionError(f'Unexpected mutation: {args}')
            mutations.append(args)
            return subprocess.CompletedProcess([], 0, '', '')
        return records, stable, mutations, gh

    def test_existing_version_still_uploads_missing_win32_setups_for_both_editions(self):
        for missing in ({('x86', 'cliente'), ('x86', 'suporte')}, {('x86', 'suporte')}):
            with self.subTest(missing=missing):
                records, stable, mutations, gh = self.existing_stable_fixture(missing)
                with patch.object(release, 'release', side_effect=lambda *a: copy.deepcopy(stable)), \
                     patch.object(release, 'gh', side_effect=gh):
                    release.reconcile_stable('owner/repo', '1.5.1', records)
                uploads = [Path(call[3]).name for call in mutations if call[:2] == ('release', 'upload')]
                self.assertEqual(set(uploads), {f'bgdesk-{e}-1.5.1-windows-{a}-setup.exe' for a,e in missing})
                self.assertEqual(len(stable['assets']), 4)
                self.assertTrue(all(a['name'].endswith('-setup.exe') for a in stable['assets']))
                self.assertEqual(stable['target_commitish'], 'c' * 40)

    def test_existing_stable_different_bytes_are_rejected_before_any_upload_or_deletion(self):
        records, stable, mutations, gh = self.existing_stable_fixture({('x86', 'suporte')})
        stable['assets'][0]['digest'] = 'sha256:' + '0' * 64
        with patch.object(release, 'release', return_value=stable), patch.object(release, 'gh', side_effect=gh):
            with self.assertRaisesRegex(ValueError, 'different bytes'):
                release.reconcile_stable('owner/repo', '1.5.1', records)
        self.assertEqual(mutations, [])
