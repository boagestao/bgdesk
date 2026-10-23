import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import generate_update_metadata as metadata
import website_release as website


class WebsiteReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "update_metadata.rs"
        self.source.write_text(website.KEY_MARKER)
        self.key = self.root / "private.json"
        self.public = self.root / "public"
        self.run_cli("init-key")
        self.artifact = self.root / "bgdesk-1.5.2-aarch64.dmg"
        self.artifact.write_bytes(b"test installer")

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *args, success=True):
        result = subprocess.run([
            sys.executable, str(Path(website.__file__)), *args,
            "--key-file", str(self.key), "--rust-source", str(self.source),
        ], text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def prepare(self, edition="suporte", *, version="1.5.2", extra=(), success=True):
        return self.run_cli(
            "prepare", "--edition", edition, "--version", version,
            "--site-public", str(self.public),
            "--artifact", "macos", "aarch64", "dmg", str(self.artifact),
            *extra, success=success,
        )

    def verify_latest(self, edition='suporte', version='1.5.2'):
        website.load_key(self.key)
        latest = self.public / 'updates' / edition / 'latest.json'
        document = json.loads(latest.read_bytes())
        args = argparse.Namespace(metadata=latest, version=version, release_id=f'v{version}',
            package_id=f'bgdesk-{edition}', release_base_url=f'{website.ORIGIN}/updates/{edition}',
            artifact_base_url=website.ORIGIN,
            artifact=[str(self.public / item['file_name']) for item in document['artifacts']])
        metadata.command_verify_latest(args)
        return latest, document, args

    def test_prepares_self_contained_signed_feeds_and_stores_packages_once_at_root(self):
        for edition in ('cliente', 'suporte'):
            channel = self.public / 'updates' / edition
            channel.mkdir(parents=True)
            (channel / 'latest.json').write_text('{"url":"https://bgdesk.com/old/"}')
            self.prepare(edition)
            latest, document, _ = self.verify_latest(edition)
            self.assertEqual(document['version'], '1.5.2')
            self.assertEqual(document['package_id'], f'bgdesk-{edition}')
            self.assertNotIn('url', document)
            self.assertIn('signature', document)
            self.assertEqual(list(latest.parent.iterdir()), [latest])
            self.assertEqual(os.stat(latest).st_mode & 0o777, 0o644)
            item = document['artifacts'][0]
            self.assertEqual(item['url'], f'{website.ORIGIN}/bgdesk-{edition}-aarch64.dmg')
            self.assertEqual((self.public / item['file_name']).read_bytes(), self.artifact.read_bytes())
        self.assertEqual(len(list(self.public.rglob('*.dmg'))), 2)
        self.assertEqual(list(self.public.rglob('*.sig')), [])
        self.assertEqual(list(self.public.rglob('index.html')), [])
        self.assertEqual(list(self.public.rglob('private.json')), [])
        self.assertEqual(os.stat(self.key).st_mode & 0o777, 0o600)

    def test_failed_release_preserves_latest_and_packages(self):
        self.prepare()
        latest = self.public / 'updates/suporte/latest.json'
        original = latest.read_bytes()
        package = self.public / 'bgdesk-suporte-aarch64.dmg'
        self.artifact.write_bytes(b'changed')
        self.prepare(success=False)
        self.prepare(version='1.5.1', success=False)
        self.prepare(version='1.5.3', extra=('--release-id', 'v9.0.0'), success=False)
        self.prepare(version='1.5.3-rc1', success=False)
        self.prepare(version='1.5.3', extra=(
            '--artifact', 'macos', 'aarch64', 'dmg', str(self.artifact)), success=False)
        self.assertEqual(latest.read_bytes(), original)
        self.assertEqual(package.read_bytes(), b'test installer')
        self.assertEqual(list(latest.parent.glob('.release-*')), [])

    def test_new_version_replaces_latest_without_creating_version_directories(self):
        self.prepare()
        self.artifact.write_bytes(b'new installer')
        self.prepare(version='1.5.3')
        _, document, _ = self.verify_latest(version='1.5.3')
        self.assertEqual(document['artifacts'][0]['size'], len(b'new installer'))
        self.assertEqual(list((self.public / 'updates/suporte').iterdir()),
                         [self.public / 'updates/suporte/latest.json'])

    def test_rejects_changed_version_hash_signature_and_installer_bytes(self):
        self.prepare()
        latest, document, args = self.verify_latest()
        original = latest.read_bytes()
        for field in ('version', 'package_id'):
            changed = json.loads(original)
            changed[field] = 'changed'
            latest.write_bytes(metadata.stable_json(changed))
            with self.assertRaises(SystemExit):
                metadata.command_verify_latest(args)
        for field in ('sha256', 'url', 'size'):
            changed = json.loads(original)
            changed['artifacts'][0][field] = 'changed'
            latest.write_bytes(metadata.stable_json(changed))
            with self.assertRaises(SystemExit):
                metadata.command_verify_latest(args)
        latest.write_bytes(original)
        # Layout/whitespace are not part of the canonical signed content.
        latest.write_text(json.dumps(document, indent=2))
        metadata.command_verify_latest(args)
        (self.public / document['artifacts'][0]['file_name']).write_bytes(b'tampered')
        with self.assertRaises(SystemExit):
            metadata.command_verify_latest(args)

    def test_rejects_wrong_signing_key_and_key_replacement(self):
        self.run_cli('init-key', success=False)
        self.source.write_text(self.source.read_text().replace('public_key:', 'wrong_key:'))
        self.prepare(success=False)
        self.assertFalse((self.public / 'updates/suporte/latest.json').exists())

    def test_windows_native_updater_setup_and_msi_keep_distinct_signed_selectors(self):
        exe, setup, msi = [self.root / name for name in ('update.exe', 'setup.exe', 'app.msi')]
        for path in (exe, setup, msi):
            path.write_bytes(path.name.encode())
        self.prepare('cliente', extra=('--artifact', 'windows', 'x86_64', 'exe', str(exe),
            '--artifact', 'windows', 'x86_64', 'inno-exe', str(setup),
            '--artifact', 'windows', 'x86_64', 'msi', str(msi),
            '--artifact', 'windows', 'x86', 'exe', str(exe),
            '--artifact', 'windows', 'x86', 'inno-exe', str(setup)))
        _, document, _ = self.verify_latest('cliente')
        self.assertEqual({a['format'] for a in document['artifacts']}, {'exe', 'inno-exe', 'msi', 'dmg'})
        self.assertEqual({a['file_name'] for a in document['artifacts'] if a['platform'] == 'windows'},
                         {'bgdesk-cliente-update-win64.exe', 'bgdesk-cliente-win64.exe', 'bgdesk-cliente-win64.msi',
                          'bgdesk-cliente-update-win32.exe', 'bgdesk-cliente-win32.exe'})
        win32 = next(a for a in document['artifacts']
                     if (a['platform'], a['arch'], a['format']) == ('windows', 'x86', 'exe'))
        self.assertEqual(win32['url'], f'{website.ORIGIN}/bgdesk-cliente-update-win32.exe')

    def test_arch_compound_extension_is_signed_and_wrong_extension_rejected(self):
        package = self.root / 'bgdesk-suporte-x86_64.pkg.tar.zst'
        package.write_bytes(b'Arch package')
        self.prepare(extra=('--artifact', 'linux', 'x86_64', 'pkg.tar.zst', str(package)))
        self.verify_latest()
        wrong = self.root / 'bgdesk.zst'
        wrong.write_bytes(b'wrong extension')
        self.prepare('cliente', extra=('--artifact', 'linux', 'x86_64', 'pkg.tar.zst', str(wrong)), success=False)
        self.prepare('cliente', extra=('--artifact', 'linux', 'aarch64', 'pkg.tar.zst', str(package)), success=False)


if __name__ == '__main__':
    unittest.main()
