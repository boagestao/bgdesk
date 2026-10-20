#!/usr/bin/env python3
"""Publish root APKs with a separate signed channel, preserving desktop metadata."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'res/update'))
import generate_update_metadata as metadata
import website_release

spec = importlib.util.spec_from_file_location('r2', Path(__file__).with_name('r2-publish.py'))
r2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r2)


def prepare(s3, bucket, records, version, origin, stage, key, source_commit='HEAD'):
    """Validate both editions, including any existing signed bytes, before uploading."""
    website_release.load_key(key)
    metadata.command_check_key(argparse.Namespace(rust_source=str(ROOT / 'src/update_metadata.rs')))
    stamp = subprocess.check_output(['git', 'show', '-s', '--format=%cI', source_commit], cwd=ROOT, text=True).strip()
    packages, sidecars = [], []
    for edition in ('cliente', 'suporte'):
        record, path = next((r, p) for r, p in records if r['platform'] == 'android' and r['edition'] == edition)
        name = r2.root_artifact_name(edition, 'android', 'universal', 'apk')
        directory = stage / edition
        directory.mkdir()
        target = directory / name
        # Signing reads the validated source bytes, not an unchecked copy.
        target.write_bytes(path.read_bytes())
        if r2.file_hash(target) != record['sha256'] or target.stat().st_size != record['size']:
            raise ValueError('Android artifact changed before publication')
        base = f'updates/android/{edition}'
        prefix = f'{base}/v{version}'
        data, signature = directory / 'bgdesk-update.json', directory / 'bgdesk-update.json.sig'
        common = dict(version=version, release_id=f'v{version}', package_id=f'bgdesk-{edition}',
                      release_base_url=f'{origin}/{base}', artifact_base_url=origin)
        exists = [r2.head(s3, bucket, f'{prefix}/{p.name}') is not None for p in (data, signature)]
        if any(exists) and not all(exists):
            raise ValueError('Incomplete existing Android metadata; refusing to replace signed bytes')
        if all(exists):
            for local in (data, signature):
                local.write_bytes(s3.get_object(Bucket=bucket, Key=f'{prefix}/{local.name}')['Body'].read())
        else:
            metadata.command_sign(argparse.Namespace(**common, artifact=[('android', 'universal', 'apk', str(target))],
                                  published_at=stamp, metadata_out=str(data), signature_out=str(signature)))
        metadata.command_verify(argparse.Namespace(**common, artifact=[str(target)], metadata=str(data), signature=str(signature)))
        document = json.loads(data.read_bytes())
        artifacts = document['artifacts']
        if len(artifacts) != 1 or any(artifacts[0].get(k) != v for k, v in dict(
                platform='android', arch='universal', format='apk', file_name=name,
                url=f'{origin}/{name}', size=record['size'], sha256=record['sha256']).items()):
            raise ValueError('Existing Android metadata differs from the supplied APK')
        packages.append((name, target))
        sidecars += [(f'{prefix}/{p.name}', p) for p in (data, signature)]
    return packages, sidecars


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--artifacts', type=Path, default=Path('artifacts'))
    parser.add_argument('--source-commit', default='HEAD')
    args = parser.parse_args()
    records = r2.read_records(args.artifacts, args.version)
    if not any(r['platform'] == 'android' for r, _ in records):
        print('Historical desktop-only run: no Android publication requested.')
        return
    s3, bucket, origin = r2.client(), os.environ['R2_BUCKET'], os.environ['R2_PUBLIC_ORIGIN']
    metadata.validate_or_fail(metadata.validate_release_base_url, origin)
    with tempfile.TemporaryDirectory(prefix='bgdesk-android-publish-') as temporary:
        stage = Path(temporary)
        key = stage / 'signing.json'
        key.touch(mode=0o600)
        key.write_text(os.environ['BGDESK_UPDATE_SIGNING_KEY'])
        packages, sidecars = prepare(s3, bucket, records, args.version, origin, stage, key, args.source_commit)
        for name, path in packages:
            r2.upload(s3, bucket, path, name, immutable=False)
        for name, path in packages:
            r2.public_check(origin, name, path, small=True)
        for name, path in sidecars:
            r2.upload(s3, bucket, path, name)
            r2.public_check(origin, name, path, small=True)
        # Activate only after both packages and all signed sidecars were verified.
        for edition in ('cliente', 'suporte'):
            latest = stage / edition / 'latest.json'
            latest.write_text(json.dumps({'url': f'{origin}/updates/android/{edition}/v{args.version}/'}) + '\n')
            name = f'updates/android/{edition}/latest.json'
            r2.upload(s3, bucket, latest, name, immutable=False)
            r2.public_check(origin, name, latest, small=True)


if __name__ == '__main__':
    main()
