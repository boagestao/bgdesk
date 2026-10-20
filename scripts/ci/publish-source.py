#!/usr/bin/env python3
"""Verify a completed main release run before reusing its already built packages."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

from preflight import TARGETS


def validate(run, jobs, repository):
    if (run.get('status') != 'completed' or run.get('conclusion') not in {'success', 'failure'}
            or run.get('head_branch') != 'main' or run.get('path') != '.github/workflows/release.yml'
            or run.get('head_repository', {}).get('full_name') != repository):
        raise ValueError('Source must be a completed main release run from this repository')
    expected = {f'{platform} / {arch} (cliente + suporte)' for platform, arch, _ in TARGETS}
    expected |= {'preflight', 'flutter bridge'}
    selected = [job for job in jobs if job['name'] != 'publish']
    if len(selected) != len(expected) or {job['name'] for job in selected} != expected:
        raise ValueError('Source run does not contain the complete build matrix')
    if any(job['status'] != 'completed' or job['conclusion'] != 'success' for job in selected):
        raise ValueError('Every source build must have completed successfully')
    commit = run.get('head_sha', '')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid source commit')
    return commit


def api(path, *, paginate=False):
    command = ['gh', 'api', path]
    if paginate:
        command += ['--paginate', '--slurp']
    return json.loads(subprocess.check_output(command, text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id')
    args = parser.parse_args()
    if not args.run_id.isdigit():
        parser.error('A numeric source run ID is required')
    repository = os.environ['GITHUB_REPOSITORY']
    run = api(f'repos/{repository}/actions/runs/{args.run_id}')
    pages = api(f'repos/{repository}/actions/runs/{args.run_id}/jobs?filter=latest&per_page=100', paginate=True)
    commit = validate(run, [job for page in pages for job in page['jobs']], repository)
    # Fetch only the original commit; keep the corrected publication tools at HEAD.
    subprocess.run(['git', 'fetch', '--no-tags', '--depth=1', 'origin', commit], check=True)
    source = subprocess.check_output(['git', 'show', f'{commit}:Cargo.toml'], text=True)
    version = tomllib.loads(source)['package']['version']
    if version != tomllib.loads(Path('Cargo.toml').read_text())['package']['version']:
        raise ValueError('Source version differs from the current publication tools; refusing to mix releases')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
        handle.write(f'commit={commit}\nversion={version}\n')
    print(f'All five source builds passed; reusing BGDesk {version} from {commit[:12]}')


if __name__ == '__main__':
    main()
