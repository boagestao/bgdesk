import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from botocore.exceptions import ClientError

import android_signing


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


verify = module('verify-android')
publish = module('publish-android')
patch_spec = importlib.util.spec_from_file_location('patch_android_plugins', Path(__file__).parents[1] / 'patch-android-plugins.py')
patch_plugins = importlib.util.module_from_spec(patch_spec)
patch_spec.loader.exec_module(patch_plugins)


class FakeS3:
    def __init__(self):
        self.objects = {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': '404'}}, 'HeadObject')
        return {'ContentLength': len(self.objects[Key])}

    def get_object(self, Bucket, Key):
        return {'Body': io.BytesIO(self.objects[Key])}


class AndroidTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_properties_escape_password_characters_and_unicode(self):
        self.assertEqual(android_signing.escape_property(' a\\b:=#!\nç'), r'\ a\\b\:\=\#\!\n\u00e7')

    def test_legacy_registration_patch_preserves_v2_handlers_and_is_idempotent(self):
        v2 = 'implements FlutterPlugin, ActivityAware, PluginRegistry.NewIntentListener {\n' + 'void onAttachedToEngine() {}\nvoid onAttachedToActivity() {}\nvoid onNewIntent() {}\n'
        source = v2 + patch_plugins.LEGACY + '}\n'
        patched = patch_plugins.patch_source(source)
        self.assertEqual(patched, v2 + '}\n')
        self.assertEqual(patch_plugins.patch_source(patched), patched)
        with self.assertRaisesRegex(ValueError, 'legacy registration changed'):
            patch_plugins.patch_source(source.replace('registrar.activity() == null', 'registrar.activity() != null'))

    def test_failed_private_key_validation_is_sanitized(self):
        values = dict(zip(android_signing.NAMES, (base64.b64encode(b'fake').decode(), 'alias', 'store-secret', 'key-secret')))
        with patch.object(android_signing.subprocess, 'run') as run:
            run.return_value.returncode = 1
            run.return_value.stderr = b'private failure data'
            with self.assertRaisesRegex(ValueError, 'failed validation') as error:
                android_signing.validate(values, self.root)
        self.assertNotIn('secret', str(error.exception))
        self.assertEqual((self.root / 'android-key.jks').stat().st_mode & 0o777, 0o600)
        command = run.call_args.args[0]
        self.assertNotIn('store-secret', command)
        self.assertNotIn('key-secret', command)

    def test_universal_apk_missing_a_rust_core_is_rejected(self):
        apk = self.root / 'incomplete.apk'
        with zipfile.ZipFile(apk, 'w') as archive:
            archive.writestr('lib/arm64-v8a/librustdesk.so', b'core')
        with self.assertRaisesRegex(ValueError, 'all three Rust cores'), patch.object(verify.subprocess, 'check_output') as call:
            verify.verify(apk, 'cliente', '1.5.1', '68', self.root, self.root / 'key.jks', 'alias')
        call.assert_not_called()

    def test_apk_signed_with_a_different_certificate_is_rejected(self):
        apk = self.root / 'universal.apk'
        with zipfile.ZipFile(apk, 'w') as archive:
            for abi in ('arm64-v8a', 'armeabi-v7a', 'x86_64'):
                for lib in ('librustdesk.so', 'libflutter.so', 'libapp.so', 'libc++_shared.so'):
                    archive.writestr(f'lib/{abi}/{lib}', b'library')
        responses = ["package: name='br.com.boagestao.bgdeskcliente' versionCode='68' versionName='1.5.1'", 'Signer #1 certificate SHA-256 digest: ' + '0' * 64]
        with patch.object(verify.subprocess, 'check_output', side_effect=responses), patch.object(verify.subprocess, 'run') as call:
            call.return_value.stdout = b'expected certificate'
            with self.assertRaisesRegex(ValueError, 'signer differs'):
                verify.verify(apk, 'cliente', '1.5.1', '68', self.root, self.root / 'key.jks', 'alias')

    def test_signed_android_retry_preserves_existing_metadata_and_rejects_different_apks(self):
        private = ed25519.Ed25519PrivateKey.generate()
        key = self.root / 'key.json'
        key.write_text(json.dumps(dict(seed=base64.b64encode(private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode(),
                                      public_key=base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())))
        records = []
        for edition in ('cliente', 'suporte'):
            path = self.root / f'{edition}.apk'
            path.write_bytes(edition.encode())
            records.append((dict(platform='android', edition=edition, size=path.stat().st_size,
                                 sha256=hashlib.sha256(path.read_bytes()).hexdigest()), path))
        s3 = FakeS3()
        def prepare(name):
            stage = self.root / name
            stage.mkdir()
            with patch.object(publish.metadata, 'command_check_key'), patch.object(publish.subprocess, 'check_output', return_value='2026-10-20T12:00:00Z'):
                return publish.prepare(s3, 'bucket', records, '1.5.1', 'https://download.bgdesk.com', stage, key)
        packages, sidecars = prepare('first')
        self.assertEqual({name for name, _ in packages}, {'bgdesk-cliente-universal.apk', 'bgdesk-suporte-universal.apk'})
        for name, path in sidecars:
            self.assertTrue(name.startswith('updates/android/'))
            s3.objects[name] = path.read_bytes()
        original = dict(s3.objects)
        _, retried = prepare('retry')
        self.assertEqual({name: path.read_bytes() for name, path in retried}, original)
        records[1][1].write_bytes(b'different APK')
        records[1][0].update(size=records[1][1].stat().st_size, sha256=hashlib.sha256(records[1][1].read_bytes()).hexdigest())
        with self.assertRaises(SystemExit):
            prepare('changed')
        self.assertEqual(s3.objects, original)


if __name__ == '__main__':
    unittest.main()
