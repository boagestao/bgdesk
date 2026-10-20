#!/usr/bin/env python3
"""Reuse approved main builds by application version and target, not source diff."""
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


EDITIONS = ('cliente', 'suporte')


def api(path, *, paginate=False):
    command = ['gh', 'api', path]
    if paginate:
        command += ['--paginate', '--slurp']
    result = subprocess.run(command, check=True, capture_output=True, text=True,
                            encoding='utf-8', timeout=120)
    return json.loads(result.stdout)


def trusted_run(run, repository):
    return (run.get('status') == 'completed' and run.get('conclusion') in ('success', 'failure')
            and run.get('head_branch') == 'main'
            and run.get('path') == '.github/workflows/release.yml'
            and run.get('head_repository', {}).get('full_name') == repository
            and re.fullmatch('[0-9a-f]{40}', run.get('head_sha', '')) is not None)


def approved_target(jobs, artifacts, platform, arch):
    names = {f'{platform} / {arch} (cliente + suporte)'}
    if platform == 'windows':
        names.add('windows / x86_64 + x86 (cliente + suporte)')
    passed = any(job.get('name') in names and job.get('status') == 'completed'
                 and job.get('conclusion') == 'success' for job in jobs)
    available = {a['name'] for a in artifacts if not a.get('expired', True)}
    return passed and all(f'build-{platform}-{arch}-{edition}' in available for edition in EDITIONS)


def make_plan(matrix, version, repository, query=api, validate=None):
    validate = validate or validate_candidate
    wanted = {(t['platform'], t['arch']) for t in matrix['include']}
    if any(t.get('win32') for t in matrix['include']):
        wanted.add(('windows', 'x86'))
    found, versions = {}, {}
    runs = query(f'repos/{repository}/actions/workflows/release.yml/runs?branch=main&status=completed&per_page=100')['workflow_runs']
    for run in runs:
        if not trusted_run(run, repository):
            continue
        commit = run['head_sha']
        if commit not in versions:
            cargo = query(f'repos/{repository}/contents/Cargo.toml?ref={commit}')
            versions[commit] = tomllib.loads(base64.b64decode(cargo['content']).decode('utf-8'))['package']['version']
        if versions[commit] != version:
            continue
        run_id = run['id']
        jobs = [job for page in query(f'repos/{repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100', paginate=True) for job in page['jobs']]
        artifacts = [a for page in query(f'repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100', paginate=True) for a in page['artifacts']]
        for target in wanted - found.keys():
            if (approved_target(jobs, artifacts, *target)
                    and validate(repository, str(run_id), version, *target)):
                found[target] = dict(run=str(run_id), commit=commit)
        if wanted == found.keys():
            break
    for target in matrix['include']:
        reuse = found.get((target['platform'], target['arch']), {})
        target.update(reuse_run=reuse.get('run', ''), reuse_commit=reuse.get('commit', ''))
        win32 = found.get(('windows', 'x86'), {}) if target.get('win32') else {}
        target.update(win32_reuse_run=win32.get('run', ''), win32_reuse_commit=win32.get('commit', ''))
        target['needs_build'] = not reuse or (target.get('win32', False) and not win32)
    return matrix


def validate_directory(directory, version, platform, arch, edition):
    spec = importlib.util.spec_from_file_location('collect', Path(__file__).with_name('collect-artifacts.py'))
    collect = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collect)
    records = json.loads((directory / 'artifacts.json').read_text(encoding='utf-8'))
    expected = {fmt for fmt, _ in collect.specs(platform, arch, edition)}
    if len(records) != len(expected) or {r['format'] for r in records} != expected:
        raise ValueError('Reused edition has an incomplete package set')
    for record in records:
        if (record['version'], record['platform'], record['arch'], record['edition']) != (version, platform, arch, edition):
            raise ValueError('Reused package version or target differs')
        name = record['file_name']
        if not re.fullmatch('[A-Za-z0-9._-]+', name) or name in ('.', '..'):
            raise ValueError('Invalid reused artifact name')
        path = directory / name
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        if path.stat().st_size != record['size'] or digest != record['sha256']:
            raise ValueError('Reused artifact hash/size mismatch')
        if platform == 'windows' and record['format'] == 'inno-exe':
            data = path.read_bytes()
            if not data.startswith(b'MZ') or b'Inno Setup Setup Data' not in data:
                raise ValueError('Reused Windows package is not an Inno Setup installer')
    return records


def download_edition(repository, run_id, platform, arch, edition, directory):
    directory.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(['gh', 'run', 'download', run_id, '--repo', repository,
                             '--name', f'build-{platform}-{arch}-{edition}', '--dir', str(directory)],
                            capture_output=True, text=True, encoding='utf-8', timeout=600)
    if result.returncode:
        # gh may include a signed download URL in stderr; never print it.
        raise RuntimeError('Cannot download the approved build artifacts')


def validate_candidate(repository, run_id, version, platform, arch):
    # Artifact names alone do not prove that the required installers exist.
    # Validate both editions before deciding to skip their compilation.
    with tempfile.TemporaryDirectory(prefix='bgdesk-reuse-check-') as temporary:
        try:
            for edition in EDITIONS:
                directory = Path(temporary) / edition
                download_edition(repository, run_id, platform, arch, edition, directory)
                validate_directory(directory, version, platform, arch, edition)
        except (ValueError, OSError, RuntimeError, KeyError, TypeError):
            print(f'Rejecting incomplete/invalid {platform}/{arch} packages from run {run_id}.')
            return False
    return True


def restore(repository, run_id, commit, version, platform, arch):
    if not run_id.isdigit() or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Invalid reuse source')
    run = api(f'repos/{repository}/actions/runs/{run_id}')
    if not trusted_run(run, repository) or run['head_sha'] != commit:
        raise ValueError('Reuse source changed or is not a completed trusted run')
    jobs = [job for page in api(f'repos/{repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100', paginate=True) for job in page['jobs']]
    artifacts = [a for page in api(f'repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100', paginate=True) for a in page['artifacts']]
    if not approved_target(jobs, artifacts, platform, arch):
        raise ValueError('Source target did not pass or its artifacts expired')
    for edition in EDITIONS:
        directory = Path(f'release-artifacts/{platform}-{arch}-{edition}')
        download_edition(repository, run_id, platform, arch, edition, directory)
        validate_directory(directory, version, platform, arch, edition)
        provenance_path = directory / 'build-source.json'
        provenance = dict(
            repository=repository, run_id=run_id, commit=commit,
            version=version, platform=platform, arch=arch, edition=edition)
        if provenance_path.exists():
            original = json.loads(provenance_path.read_text(encoding='utf-8'))
            if (any(original.get(key) != provenance[key] for key in
                    ('repository', 'version', 'platform', 'arch', 'edition'))
                    or not re.fullmatch('[0-9a-f]{40}', original.get('commit', ''))
                    or not str(original.get('run_id', '')).isdigit()):
                raise ValueError('Invalid original build provenance')
            original['restored_from'] = dict(run_id=run_id, commit=commit)
            provenance = original
        provenance_path.write_text(json.dumps(provenance, indent=2) + '\n')
    print(f'Reusing approved BGDesk {version} {platform}/{arch} from run {run_id}; hashes and sizes verified.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--platform', choices=('linux', 'macos', 'windows'))
    parser.add_argument('--arch', choices=('x86', 'x86_64', 'aarch64'))
    parser.add_argument('--run')
    parser.add_argument('--commit')
    args = parser.parse_args()
    repository = os.environ['GITHUB_REPOSITORY']
    version = os.environ['BGDESK_VERSION']
    if args.plan:
        matrix = make_plan(json.loads(os.environ['BUILD_MATRIX']), version, repository)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            handle.write('matrix=' + json.dumps(matrix, separators=(',', ':')) + '\n')
            handle.write('needs_build=' + str(any(t['needs_build'] for t in matrix['include'])).lower() + '\n')
        for target in matrix['include']:
            print(f"{target['platform']}/{target['arch']}: " + (f"reuse run {target['reuse_run']}" if target['reuse_run'] else 'build required'))
            if target.get('win32'):
                print('windows/x86: ' + (f"reuse run {target['win32_reuse_run']}" if target['win32_reuse_run'] else 'build required'))
    else:
        if not all((args.platform, args.arch, args.run, args.commit)):
            parser.error('Target, source run and commit are required')
        restore(repository, args.run, args.commit, version, args.platform, args.arch)


if __name__ == '__main__':
    main()
