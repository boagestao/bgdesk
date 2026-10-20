import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('publish_source', Path(__file__).with_name('publish-source.py'))
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class PublishSourceTests(unittest.TestCase):
    def setUp(self):
        self.run = dict(status='completed', conclusion='failure', head_branch='main',
                        path='.github/workflows/release.yml', head_sha='a' * 40,
                        head_repository={'full_name': 'boagestao/bgdesk'})
        names = ['preflight', 'flutter bridge'] + [
            f'{platform} / {arch} (cliente + suporte)' for platform, arch, _ in source.TARGETS]
        self.jobs = [dict(name=name, status='completed', conclusion='success') for name in names]
        self.jobs.append(dict(name='publish', status='completed', conclusion='failure'))

    def test_failed_publication_with_all_builds_passed_can_reuse_the_exact_commit(self):
        self.assertEqual(source.validate(self.run, self.jobs, 'boagestao/bgdesk'), 'a' * 40)

    def test_active_cancelled_fork_or_other_workflow_sources_are_rejected(self):
        for change in (dict(status='in_progress'), dict(conclusion='cancelled'), dict(head_branch='other'),
                       dict(head_repository={'full_name': 'fork/bgdesk'}), dict(path='other.yml')):
            run = dict(self.run, **change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                source.validate(run, self.jobs, 'boagestao/bgdesk')

    def test_failed_or_missing_build_cannot_publish_a_partial_matrix(self):
        jobs = copy.deepcopy(self.jobs)
        jobs[2]['conclusion'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'Every source build'):
            source.validate(self.run, jobs, 'boagestao/bgdesk')
        with self.assertRaisesRegex(ValueError, 'complete build matrix'):
            source.validate(self.run, self.jobs[1:], 'boagestao/bgdesk')
