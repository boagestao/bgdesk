import plistlib
from pathlib import Path
import tempfile
import unittest

from application_version import parse_version, package_version, stamp_macos_bundle
from update_metadata_policy import validate_release
from website_release import validate_version


class ApplicationVersionTests(unittest.TestCase):
    def test_ordering_and_rejection_of_equal_or_lower_revisions(self):
        versions = ['1.5.1', '1.5.1-1', '1.5.1-2', '1.5.1-10', '1.5.1-65535', '1.5.2']
        for i, installed in enumerate(versions):
            for j, candidate in enumerate(versions):
                self.assertEqual(parse_version(candidate) > parse_version(installed), j > i)
                validate_version(candidate, 'v' + candidate)
                validate_release('v' + candidate, candidate)

    def test_rejects_noncanonical_or_unbounded_versions(self):
        for version in ['1.5.1-b', '1.5.1-0', '1.5.1-01', '1.5.1-65536', '1.5.1.1',
                        '1.5.1-1+69', '01.5.1', '0.0.0', '1.5.1-1/extra']:
            with self.subTest(version=version), self.assertRaises(ValueError):
                parse_version(version)
        with self.assertRaises(ValueError):
            validate_release('v1.5.1-2', '1.5.1-1')

    def test_native_versions_preserve_revision_and_build_identity(self):
        self.assertEqual(package_version('1.5.1-10'), '1.5.1.10')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'Info.plist'
            path.write_bytes(plistlib.dumps({'CFBundleVersion': '69', 'CFBundleIdentifier': 'test.bgdesk'}))
            stamp_macos_bundle(path, '1.5.1-10')
            info = plistlib.loads(path.read_bytes())
            self.assertEqual(info['CFBundleShortVersionString'], '1.5.1')
            self.assertEqual(info['BGDeskApplicationVersion'], '1.5.1-10')
            self.assertEqual(info['CFBundleVersion'], '69')
            self.assertEqual(info['CFBundleIdentifier'], 'test.bgdesk')
