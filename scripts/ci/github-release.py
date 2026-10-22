#!/usr/bin/env python3
"""Expose each completed edition immediately; publish a stable release only after R2."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib


def gh(*arguments, check=True):
    return subprocess.run(['gh', *arguments], check=check, text=True, capture_output=True, timeout=600)


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def is_public_package(record):
    # Native updater EXEs remain in Actions/R2, never in the public release downloads.
    return record['platform'] != 'windows' or record['format'] == 'inno-exe'


def read_edition(manifest):
    records = json.loads(manifest.read_text())
    if not records:
        raise ValueError('Empty artifact manifest')
    selectors = {(r['version'], r['platform'], r['arch'], r['edition']) for r in records}
    if len(selectors) != 1:
        raise ValueError('Expected one edition/platform/architecture per manifest')
    files = []
    seen = set()
    for record in records:
        name = record['file_name']
        if not re.fullmatch(r'[A-Za-z0-9._-]+', name) or name in {'.', '..'} or name in seen:
            raise ValueError('Invalid or duplicate asset name')
        seen.add(name)
        path = manifest.parent / name
        if not path.is_file() or path.stat().st_size != record['size'] or digest(path) != record['sha256']:
            raise ValueError(f'Asset hash/size mismatch: {name}')
        if is_public_package(record):
            files.append(path)
    if not files:
        raise ValueError('No public installer was generated')
    return next(iter(selectors)), files


def release(repository, tag):
    result = gh('api', f'repos/{repository}/releases/tags/{tag}', check=False)
    if result.returncode == 0:
        return json.loads(result.stdout)
    if '404' in result.stderr:
        # The tag endpoint only returns published releases. Authenticated lists
        # include drafts, which must be reused when resuming a stable upload.
        pages = json.loads(gh('api', '--paginate', '--slurp',
                              f'repos/{repository}/releases?per_page=100').stdout)
        matches = [item for page in pages for item in page if item['tag_name'] == tag]
        if len(matches) > 1:
            raise ValueError('Multiple releases have the same tag; refusing an ambiguous upload')
        return matches[0] if matches else None
    raise RuntimeError('Cannot query GitHub release: ' + result.stderr)


def ensure_release(repository, tag, commit, title, notes, *, draft):
    existing = release(repository, tag)
    if existing is None:
        with tempfile.TemporaryDirectory() as temp:
            body = Path(temp) / 'notes.md'
            body.write_text(notes)
            gh('release', 'create', tag, '--repo', repository, '--target', commit,
               '--title', title, '--notes-file', str(body), '--latest=false',
               '--draft' if draft else '--prerelease')
        existing = release(repository, tag)
    if existing is None:
        raise RuntimeError('Created GitHub release cannot be found; refusing to upload packages')
    if existing['target_commitish'] != commit:
        raise ValueError('Release tag belongs to another commit; refusing to mix binaries')
    return existing


def upload_files(repository, tag, existing, files):
    assets = {a['name']: a for a in existing['assets']}
    for path in files:
        previous = assets.get(path.name)
        if previous:
            expected = 'sha256:' + digest(path)
            if previous.get('digest') == expected and previous['size'] == path.stat().st_size:
                continue
            # Older assets may not expose a digest; verify the actual bytes.
            with tempfile.TemporaryDirectory() as temp:
                gh('release', 'download', tag, '--repo', repository, '--pattern', path.name, '--dir', temp)
                if digest(Path(temp) / path.name) != digest(path):
                    raise ValueError(f'Existing release asset has different bytes: {path.name}')
        else:
            gh('release', 'upload', tag, str(path), '--repo', repository)
    print(f'Packages available: https://github.com/{repository}/releases/tag/{tag}')


def reconcile_stable(repository, version, records):
    """Complete an existing version without replacing its tag or package bytes."""
    tag = f'v{version}'
    existing = release(repository, tag)
    if not existing or existing.get('draft') or existing.get('prerelease'):
        raise ValueError('Expected an existing published stable release')
    source = json.loads(gh('api', f'repos/{repository}/contents/Cargo.toml?ref={tag}').stdout)
    if tomllib.loads(base64.b64decode(source['content']).decode('utf-8'))['package']['version'] != version:
        raise ValueError('Existing stable tag belongs to another application version')
    public = {path.name: path for record, path in records if is_public_package(record)}
    internal = {path.name: path for record, path in records if not is_public_package(record)}
    assets = {asset['name']: asset for asset in existing['assets']}
    extras = assets.keys() - public.keys()
    if extras - internal.keys():
        raise ValueError('Stable release contains unexpected assets; refusing to remove unrelated files')
    # Verify ALL existing bytes before uploads/deletions, including the legacy
    # native updater assets which must leave the public Windows downloads.
    upload_files(repository, tag, existing,
                 [public.get(name, internal.get(name)) for name in assets])
    upload_files(repository, tag, existing, list(public.values()))
    for name in sorted(extras):
        gh('api', '--method', 'DELETE', f"repos/{repository}/releases/assets/{assets[name]['id']}")
    final = release(repository, tag)
    final_assets = {asset['name']: asset for asset in final['assets']}
    if final_assets.keys() != public.keys():
        raise ValueError('Stable release is missing public installers or contains extra assets')
    upload_files(repository, tag, final, list(public.values()))
    if final['target_commitish'] != existing['target_commitish']:
        raise ValueError('Existing stable target changed during synchronization')
    print(f'Stable {tag} verified: {len(public)} public packages, including the required Windows Setups. Existing tag preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--stable', action='store_true')
    parser.add_argument('--reconcile-existing', action='store_true',
                        help='complete an already published stable version without replacing existing bytes/tag')
    parser.add_argument('--artifacts', type=Path, default=Path('artifacts'))
    parser.add_argument('--version')
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', 'boagestao/bgdesk'))
    parser.add_argument('--commit', default=os.environ.get('GITHUB_SHA'))
    parser.add_argument('--run-id', default=os.environ.get('GITHUB_RUN_ID'))
    parser.add_argument('--attempt', default=os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
    args = parser.parse_args()
    if not args.commit or not re.fullmatch(r'[0-9a-f]{40}', args.commit):
        parser.error('An exact source commit is required')
    if args.stable:
        spec = importlib.util.spec_from_file_location('r2_publish', Path(__file__).with_name('r2-publish.py'))
        r2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(r2)
        records = r2.read_records(args.artifacts, args.version)
        if args.reconcile_existing:
            reconcile_stable(args.repo, args.version, records)
            return
        tag = f'v{args.version}'
        published = release(args.repo, tag)
        # GitHub state is independent of R2's completion marker. Adding Android
        # may be the first R2 publication of an existing stable GitHub version.
        if published and not published.get('draft') and not published.get('prerelease'):
            reconcile_stable(args.repo, args.version, records)
            return
        existing = ensure_release(args.repo, tag, args.commit, f'BGDesk {args.version}',
                                  'Todas as plataformas validadas e publicação R2 concluída.', draft=True)
        public_files = [path for record, path in records if is_public_package(record)]
        if {asset['name'] for asset in existing['assets']} - {path.name for path in public_files}:
            raise ValueError('Stable release contains unexpected assets; refusing to publish non-Setup Windows packages')
        upload_files(args.repo, tag, existing, public_files)
        gh('release', 'edit', tag, '--repo', args.repo, '--draft=false', '--prerelease=false', '--latest')
    else:
        if not args.manifest or not args.run_id or not args.run_id.isdigit() or not args.attempt.isdigit():
            parser.error('Edition manifest, run ID and numeric attempt are required')
        (version, platform, arch, edition), files = read_edition(args.manifest)
        tag = f'build-v{version}-{platform}-{arch}-{args.run_id}-{args.attempt}'
        notes = (f'Pacotes de {platform}/{arch} publicados assim que cada edição termina.\n\n'
                 f'Execução: https://github.com/{args.repo}/actions/runs/{args.run_id}\n\n'
                 'Pré-release de validação; a atualização automática no R2 exige a matriz completa.')
        existing = ensure_release(args.repo, tag, args.commit, f'BGDesk {version} — {platform} {arch}', notes, draft=False)
        with tempfile.TemporaryDirectory() as temp:
            manifest_copy = Path(temp) / f'artifacts-{edition}.json'
            public_records = [r for r in json.loads(args.manifest.read_text()) if is_public_package(r)]
            manifest_copy.write_text(json.dumps(public_records, indent=2) + '\n')
            checksums = Path(temp) / f'SHA256SUMS-{edition}.txt'
            checksums.write_text(''.join(f'{digest(path)}  {path.name}\n' for path in files))
            upload_files(args.repo, tag, existing, [*files, manifest_copy, checksums])


if __name__ == '__main__':
    main()
