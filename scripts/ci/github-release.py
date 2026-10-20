#!/usr/bin/env python3
"""Expose each completed edition immediately; publish a stable release only after R2."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def gh(*arguments, check=True):
    return subprocess.run(['gh', *arguments], check=check, text=True, capture_output=True, timeout=600)


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


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
        files.append(path)
    return next(iter(selectors)), files


def release(repository, tag):
    result = gh('api', f'repos/{repository}/releases/tags/{tag}', check=False)
    if result.returncode == 0:
        return json.loads(result.stdout)
    if '404' in result.stderr:
        return None
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--stable', action='store_true')
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
        tag = f'v{args.version}'
        existing = ensure_release(args.repo, tag, args.commit, f'BGDesk {args.version}',
                                  'Todas as plataformas validadas e publicação R2 concluída.', draft=True)
        upload_files(args.repo, tag, existing, [path for _, path in records])
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
            manifest_copy.write_bytes(args.manifest.read_bytes())
            checksums = Path(temp) / f'SHA256SUMS-{edition}.txt'
            checksums.write_text(''.join(f'{digest(path)}  {path.name}\n' for path in files))
            upload_files(args.repo, tag, existing, [*files, manifest_copy, checksums])


if __name__ == '__main__':
    main()
