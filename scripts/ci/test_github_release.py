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
