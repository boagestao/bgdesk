from distribution import editions_for_target
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

    def test_existing_version_release_is_reused_even_from_another_commit(self):
        existing = {'id': 1, 'target_commitish': 'old-commit', 'draft': False, 'assets': []}
        with patch.object(release, 'release', return_value=existing), patch.object(release, 'gh') as gh:
            self.assertEqual(release.ensure_release(
                'owner/repo', 'v1.5.1-1', 'new-commit', 'title', 'notes', draft=True), existing)
        gh.assert_not_called()

    def test_draft_is_loaded_by_id_after_the_tag_endpoint_returns_404(self):
        draft = {'id': 123, 'tag_name': 'v1.5.1-1', 'draft': True, 'target_commitish': 'a' * 40, 'assets': []}
        graphql = {'data': {'repository': {'release': {'databaseId': 123}}}}
        responses = [subprocess.CompletedProcess([], 1, '', 'gh: Not Found (HTTP 404)'),
                     subprocess.CompletedProcess([], 0, json.dumps(graphql), ''),
                     subprocess.CompletedProcess([], 0, json.dumps(draft), '')]
        with patch.object(release, 'gh', side_effect=responses) as gh:
            found = release.ensure_release('owner/repo', 'v1.5.1-1', 'a' * 40, 'title', 'notes', draft=True)
        self.assertEqual(found, draft)
        self.assertEqual(gh.call_count, 3)  # No second draft is created on resume.
        self.assertEqual(gh.call_args_list[1].args[:2], ('api', 'graphql'))
        self.assertIn('tagName=v1.5.1-1', gh.call_args_list[1].args)
        self.assertEqual(gh.call_args.args, ('api', 'repos/owner/repo/releases/123'))

    def test_new_draft_uses_the_create_response_instead_of_requerying(self):
        created = {'id': 9, 'target_commitish': 'a' * 40, 'draft': True, 'assets': []}
        captured = []
        def create(*args, **kwargs):
            captured.append(json.loads(Path(args[args.index('--input') + 1]).read_text()))
            return subprocess.CompletedProcess([], 0, json.dumps(created), '')
        with patch.object(release, 'release', return_value=None), patch.object(release, 'gh', side_effect=create) as gh:
            self.assertEqual(release.ensure_release('owner/repo', 'v1.5.1-1', 'a' * 40, 'title', 'notes', draft=True), created)
        self.assertEqual(gh.call_count, 1)
        self.assertEqual(gh.call_args.args[:3], ('api', '--method', 'POST'))
        self.assertEqual(captured, [{'tag_name': 'v1.5.1-1', 'target_commitish': 'a' * 40,
                                     'name': 'title', 'body': 'notes', 'draft': True,
                                     'prerelease': False, 'make_latest': 'false'}])

    def test_concurrent_create_reuses_the_release_after_http_422(self):
        existing = {'id': 4, 'tag_name': 'v1.5.1-1', 'draft': True, 'assets': []}
        responses = [subprocess.CompletedProcess([], 1, '', 'gh: Validation Failed (HTTP 422)'),
                     subprocess.CompletedProcess([], 0, json.dumps(existing), '')]
        with patch.object(release, 'release', side_effect=[None, existing]), \
             patch.object(release, 'gh', side_effect=responses):
            self.assertEqual(release.ensure_release(
                'owner/repo', 'v1.5.1-1', 'a' * 40, 'title', 'notes', draft=True), existing)

    def test_empty_draft_is_completed_even_when_the_current_commit_differs(self):
        draft = {'id': 1, 'draft': True, 'target_commitish': 'b' * 40, 'assets': []}
        with patch.object(release, 'release', return_value=draft), patch.object(release, 'gh') as gh:
            self.assertEqual(release.ensure_release('owner/repo', 'v1.5.1-1', 'a' * 40, 'title', 'notes', draft=True), draft)
        gh.assert_not_called()

    def test_missing_created_release_reports_a_clear_error(self):
        with patch.object(release, 'release', return_value=None), \
             patch.object(release, 'gh', return_value=subprocess.CompletedProcess([], 0, '{}', '')):
            with self.assertRaisesRegex(RuntimeError, 'cannot be found'):
                release.ensure_release('owner/repo', 'tag', 'a' * 40, 'title', 'notes', draft=True)

    def test_upload_retries_when_the_new_draft_is_not_visible_yet(self):
        responses = [subprocess.CompletedProcess([], 1, '', 'release not found'),
                     subprocess.CompletedProcess([], 0, '', '')]
        with patch.object(release, 'gh', side_effect=responses) as gh, patch.object(release.time, 'sleep') as sleep:
            release.upload_asset('owner/repo', 'v1.5.1-1', self.asset)
        self.assertEqual(gh.call_count, 2)
        sleep.assert_called_once_with(1)

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

    def test_windows_32_and_64_editions_upload_only_setup_to_the_version_release(self):
        for arch in ('x86', 'x86_64'):
            records = self.windows_manifest(arch)
            uploads = []
            def capture(repo, tag, existing, files):
                self.assertEqual(tag, 'v1.5.2')
                uploads.extend(path.name for path in files)
            with patch('sys.argv', ['release', '--manifest', str(self.manifest), '--commit', 'a' * 40]), \
                 patch.object(release, 'ensure_release', return_value={'assets': []}) as ensure, \
                 patch.object(release, 'upload_files', side_effect=capture), \
                 patch.object(release, 'delete_validation_prereleases') as cleanup:
                release.main()
            self.assertEqual(ensure.call_args.args[1], 'v1.5.2')
            self.assertTrue(ensure.call_args.kwargs['draft'])
            self.assertEqual(uploads, [records[1]['file_name']])
            cleanup.assert_not_called()
            # Filtering public downloads does not permit a corrupt internal updater.
            (self.root / records[0]['file_name']).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                release.read_edition(self.manifest)

    def test_stable_validates_all_26_packages_but_uploads_only_23_public_packages(self):
        from preflight import artifact_targets
        for platform, arch in artifact_targets():
            for edition in editions_for_target(platform, arch):
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
             patch.object(release, 'upload_files') as upload, patch.object(release, 'gh'), \
             patch.object(release, 'release', return_value=None), \
             patch.object(release, 'delete_validation_prereleases') as cleanup:
            release.main()
        files = upload.call_args.args[-1]
        self.assertEqual(len(files), 23)
        windows = [p for p in files if '-windows-' in p.name]
        self.assertEqual(len(windows), 3)
        self.assertTrue(all('inno-exe' in p.name for p in windows))
        cleanup.assert_called_once_with('boagestao/bgdesk')

        # Existing stable GitHub releases must preserve their original tag even
        # when R2's completion marker is absent.
        with patch('sys.argv', ['release', '--stable', '--version', '1.5.2', '--artifacts', str(self.root),
                                '--commit', 'a' * 40]), \
             patch.object(release, 'release', return_value={'draft': False, 'prerelease': False,
                                                          'target_commitish': 'b' * 40}), \
             patch.object(release, 'reconcile_stable') as reconcile, \
             patch.object(release, 'ensure_release') as create, \
             patch.object(release, 'delete_validation_prereleases') as cleanup:
            release.main()
        create.assert_not_called()
        self.assertEqual(reconcile.call_args.args[:2], ('boagestao/bgdesk', '1.5.2'))
        self.assertEqual(len(reconcile.call_args.args[2]), 26)
        cleanup.assert_called_once_with('boagestao/bgdesk')

    def test_stable_publish_deletes_only_validation_prereleases(self):
        pages = [[
            dict(tag_name='v1.5.1-1', prerelease=False, draft=False),
            dict(tag_name='v1.5.1', prerelease=False, draft=False),
            dict(tag_name='build-v1.5.1-1-windows-x86-1-1', prerelease=True, draft=False),
            dict(tag_name='build-v1.5.1-linux-x86_64-2-1', prerelease=True, draft=False),
        ]]
        deleted = []
        def gh(*args, **kwargs):
            if args[:2] == ('api', '--paginate'):
                return subprocess.CompletedProcess([], 0, json.dumps(pages), '')
            if args[:2] == ('release', 'delete'):
                self.assertEqual(args[3:], ('--repo', 'owner/repo', '--yes', '--cleanup-tag'))
                deleted.append(args[2])
                return subprocess.CompletedProcess([], 0, '', '')
            raise AssertionError(args)
        with patch.object(release, 'gh', side_effect=gh):
            self.assertEqual(release.delete_validation_prereleases('owner/repo'),
                             ['build-v1.5.1-1-windows-x86-1-1', 'build-v1.5.1-linux-x86_64-2-1'])
        self.assertEqual(deleted, ['build-v1.5.1-1-windows-x86-1-1', 'build-v1.5.1-linux-x86_64-2-1'])

    def test_per_edition_upload_skips_identical_files_already_on_the_version_release(self):
        existing = {'id': 7, 'draft': False, 'prerelease': False, 'assets': [
            {'name': self.asset.name, 'size': self.asset.stat().st_size,
             'digest': 'sha256:' + release.digest(self.asset)}]}
        with patch('sys.argv', ['release', '--manifest', str(self.manifest), '--commit', 'a' * 40]), \
             patch.object(release, 'ensure_release', return_value=existing) as ensure, \
             patch.object(release, 'gh') as gh:
            release.main()
        self.assertEqual(ensure.call_args.args[1], 'v1.5.1')
        gh.assert_not_called()

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
