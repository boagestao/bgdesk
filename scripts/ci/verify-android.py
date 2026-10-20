#!/usr/bin/env python3
"""Verify APK ABI coverage, package/version, and the release signing certificate."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tomllib
import zipfile


def verify(path, edition, version, version_code, sdk, keystore, alias):
    with zipfile.ZipFile(path) as archive:
        abis = {name.split('/')[1] for name in archive.namelist() if name.startswith('lib/') and name.endswith('/librustdesk.so')}
        if abis != {'arm64-v8a', 'armeabi-v7a', 'x86_64'}:
            raise ValueError('Universal APK does not contain all three Rust cores')
        for abi in abis:
            for library in ('librustdesk.so', 'libflutter.so', 'libapp.so', 'libc++_shared.so'):
                if archive.getinfo(f'lib/{abi}/{library}').file_size == 0:
                    raise ValueError('APK contains an empty native library')
    tools = sdk / 'build-tools' / '36.0.0'
    badging = subprocess.check_output([str(tools / 'aapt'), 'dump', 'badging', str(path)], text=True)
    package = f'br.com.boagestao.bgdesk{edition}'
    if not re.search(rf"package: name='{re.escape(package)}' versionCode='{version_code}' versionName='{re.escape(version)}'", badging):
        raise ValueError('APK application ID, version or versionCode mismatch')
    result = subprocess.check_output([str(tools / 'apksigner'), 'verify', '--verbose', '--print-certs', str(path)], text=True)
    expected = subprocess.run(['keytool', '-exportcert', '-keystore', str(keystore), '-alias', alias,
                               '-storepass:env', 'ANDROID_KEY_STORE_PASSWORD'], capture_output=True, check=True).stdout
    fingerprint = hashlib.sha256(expected).hexdigest()
    signers = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)$', result, re.M)
    if signers != [fingerprint]:
        raise ValueError('APK signer differs from the configured release certificate')
    print(f'Verified {package} {version}+{version_code}: 3 ABIs and release certificate SHA-256 {fingerprint}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('--edition', required=True, choices=('cliente', 'suporte'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    version = tomllib.loads((root / 'Cargo.toml').read_text())['package']['version']
    code = re.search(r'^version:\s*[^+]+\+(\d+)', (root / 'flutter/pubspec.yaml').read_text(), re.M)[1]
    if os.environ.get('ANDROID_SIGNING_KEY'):
        keystore = Path(os.environ['RUNNER_TEMP']) / 'bgdesk-android-signing/android-key.jks'
        alias = os.environ['ANDROID_ALIAS']
    else:
        import android_signing
        values = android_signing.local_secrets(root)
        os.environ['ANDROID_KEY_STORE_PASSWORD'] = values['ANDROID_KEY_STORE_PASSWORD']
        keystore = root / 'config/android-key.jks'
        alias = values['ANDROID_ALIAS']
    verify(args.apk, args.edition, version, code, Path(os.environ['ANDROID_HOME']), keystore, alias)


if __name__ == '__main__':
    main()
