import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('reuse', Path(__file__).with_name('reuse-builds.py'))
reuse = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reuse)
REPO = 'boagestao/bgdesk'


class ReuseBuildTests(unittest.TestCase):
    def setUp(self):
        self.run = dict(id=123, status='completed', conclusion='failure', head_branch='main',
                        path='.github/workflows/release.yml', head_sha='a' * 40,
                        head_repository={'full_name': REPO})
        self.jobs = [dict(name='windows / x86_64 + x86 (cliente + suporte)', status='completed', conclusion='success')]
        self.artifacts = [dict(name=f'build-windows-{arch}-{edition}', expired=False)
                          for arch in ('x86_64', 'x86') for edition in reuse.editions_for_target('windows', arch)]
        self.version = '1.5.1'

    def query(self, path, **kwargs):
        if '/contents/Cargo.toml' in path:
            return dict(content=base64.b64encode(f'[package]\nversion="{self.version}"\n'.encode()).decode())
        if '/jobs?' in path:
            return [dict(jobs=self.jobs)]
        if '/artifacts?' in path:
            return [dict(artifacts=self.artifacts)]
        return dict(workflow_runs=[self.run])

    def plan(self):
        return reuse.make_plan(dict(include=[dict(platform='windows', arch='x86_64', win32=True)]),
                               '1.5.1', REPO, self.query, lambda *args: True)['include'][0]

    def test_same_version_reuses_both_architectures_even_from_another_commit_and_failed_run(self):
        target = self.plan()
        self.assertEqual(target['reuse_run'], '123')
        self.assertEqual(target['win32_reuse_run'], '123')
        self.assertEqual(target['reuse_commit'], 'a' * 40)
        self.assertFalse(target['needs_build'])

    def test_other_version_does_not_reuse(self):
        self.version = '1.5.2'
        target = self.plan()
        self.assertEqual(target['reuse_run'], '')
        self.assertTrue(target['needs_build'])

    def test_revision_is_part_of_the_reuse_identity(self):
        matrix = dict(include=[dict(platform='windows', arch='x86_64')])
        for version in ('1.5.1', '1.5.1-2'):
            self.version = version
            result = reuse.make_plan(matrix, '1.5.1-1', REPO, self.query, lambda *args: True)
            self.assertTrue(result['include'][0]['needs_build'])
        self.version = '1.5.1-1'
        result = reuse.make_plan(matrix, '1.5.1-1', REPO, self.query, lambda *args: True)
        self.assertFalse(result['include'][0]['needs_build'])

    def test_expired_or_missing_edition_requires_only_that_architecture(self):
        for expired in (True, False):
            with self.subTest(expired=expired):
                artifacts = copy.deepcopy(self.artifacts)
                artifacts[0]['expired'] = expired
                self.artifacts = artifacts if expired else artifacts[1:]
                target = self.plan()
                self.assertEqual(target['reuse_run'], '')
                self.assertEqual(target['win32_reuse_run'], '123')
                self.assertTrue(target['needs_build'])

    def test_failed_target_is_not_reused(self):
        self.jobs[0]['conclusion'] = 'failure'
        self.assertEqual(self.plan()['reuse_run'], '')

    def test_untrusted_or_unfinished_run_is_not_reused(self):
        original = copy.deepcopy(self.run)
        for change in (dict(status='in_progress'), dict(conclusion='cancelled'),
                       dict(head_branch='other'), dict(head_repository={'full_name': 'fork/bgdesk'}),
                       dict(path='.github/workflows/other.yml')):
            self.run = dict(original, **change)
            with self.subTest(change=change):
                self.assertEqual(self.plan()['reuse_run'], '')

    def test_isolated_windows_x64_cannot_satisfy_win32(self):
        self.jobs[0]['name'] = 'windows / x86_64 (cliente + suporte)'
        self.assertEqual(self.plan()['win32_reuse_run'], '')

    def directory(self, root, edition='cliente'):
        records = []
        for fmt in ('exe', 'inno-exe'):
            path = root / f'{fmt}.exe'
            path.write_bytes(b'MZ\0Inno Setup Setup Data' if fmt == 'inno-exe' else fmt.encode())
            records.append(dict(platform='windows', arch='x86', edition=edition,
                                version='1.5.1', format=fmt, file_name=path.name,
                                size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        (root / 'artifacts.json').write_text(json.dumps(records))
        return records

    def test_restored_native_updater_and_setup_both_have_hashes_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.directory(root)
            self.assertEqual(len(reuse.validate_directory(root, '1.5.1', 'windows', 'x86', 'cliente')), 2)
            (root / 'exe.exe').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'hash/size'):
                reuse.validate_directory(root, '1.5.1', 'windows', 'x86', 'cliente')

    def test_incomplete_or_wrong_version_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = self.directory(root)
            with self.assertRaisesRegex(ValueError, 'version or target'):
                reuse.validate_directory(root, '1.5.2', 'windows', 'x86', 'cliente')
            (root / 'artifacts.json').write_text(json.dumps(records[:1]))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                reuse.validate_directory(root, '1.5.1', 'windows', 'x86', 'cliente')

    def test_candidate_requires_actual_setup_for_both_editions_before_skipping_build(self):
        def download(repository, run, platform, arch, edition, directory):
            directory.mkdir()
            self.directory(directory, edition)
            if edition == 'cliente':
                (directory / 'inno-exe.exe').unlink()
        with patch.object(reuse, 'download_edition', side_effect=download):
            self.assertFalse(reuse.validate_candidate(REPO, '123', '1.5.1', 'windows', 'x86'))
        matrix = dict(include=[dict(platform='windows', arch='x86')])
        with patch.object(reuse, 'download_edition', side_effect=download):
            target = reuse.make_plan(matrix, '1.5.1', REPO, self.query)['include'][0]
        self.assertTrue(target['needs_build'])
        self.assertEqual(target['reuse_run'], '')

    def test_bare_app_mislabeled_as_setup_is_rejected_even_with_correct_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = self.directory(root)
            app = root / 'inno-exe.exe'
            app.write_bytes(b'MZ bare application')
            records[1].update(size=app.stat().st_size, sha256=hashlib.sha256(app.read_bytes()).hexdigest())
            (root / 'artifacts.json').write_text(json.dumps(records))
            with self.assertRaisesRegex(ValueError, 'not an Inno Setup'):
                reuse.validate_directory(root, '1.5.1', 'windows', 'x86', 'cliente')
