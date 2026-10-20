#!/usr/bin/env python3
"""Sign, timestamp, and verify with bounded, noninteractive native commands."""
import argparse
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def run_phase(label, command, *, environment=None, timeout=120):
    print(f'[sign-windows] {label}: starting (limit {timeout}s)', flush=True)
    start = time.monotonic()
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=timeout, env=environment)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f'{label}: timed out after {timeout}s; process terminated') from None
    # Never print the command line (it may include a temporary PFX password).
    output = result.stdout + result.stderr
    password = (environment or {}).get('BGDESK_PFX_PASSWORD')
    if password:
        output = output.replace(password, '***')
    if output.strip():
        print(output.strip(), flush=True)
    if result.returncode:
        raise RuntimeError(f'{label}: failed with exit code {result.returncode}')
    print(f'[sign-windows] {label}: completed in {time.monotonic() - start:.1f}s', flush=True)


def sign(path):
    if not path.is_file():
        raise ValueError('Windows executable to sign was not found')
    tools = sorted((Path(os.environ['ProgramFiles(x86)']) / 'Windows Kits/10/bin').glob('*/x64/signtool.exe'))
    if not tools:
        raise ValueError('Windows SDK signtool.exe not found')
    tool = str(tools[-1])
    openssl = shutil.which('openssl')
    if not openssl:
        raise ValueError('OpenSSL not found')
    environment = dict(os.environ, BGDESK_PFX_PASSWORD=secrets.token_hex(32),
                       BGDESK_CA_FILE=str(ROOT / 'config/certs/ca.crt'))
    with tempfile.TemporaryDirectory(prefix='bgdesk-sign-', dir=os.environ.get('RUNNER_TEMP')) as temporary:
        pfx = str(Path(temporary) / 'signing.pfx')
        run_phase('Export certificate', [openssl, 'pkcs12', '-export', '-in',
                  str(ROOT / 'config/certs/sign.crt'), '-inkey', str(ROOT / 'config/certs/sign.key'),
                  '-passin', 'pass:', '-out', pfx, '-passout', 'env:BGDESK_PFX_PASSWORD'], environment=environment, timeout=30)
        run_phase('Trust private CA on disposable runner', ['pwsh', '-NoLogo', '-NoProfile', '-NonInteractive',
                  '-Command', 'Import-Certificate -FilePath $env:BGDESK_CA_FILE -CertStoreLocation Cert:/CurrentUser/Root -ErrorAction Stop | Out-Null'],
                  environment=environment, timeout=30)
        run_phase('Sign executable', [tool, 'sign', '/v', '/fd', 'SHA256', '/f', pfx,
                  '/p', environment['BGDESK_PFX_PASSWORD'], str(path)], environment=environment)
        # Keep timestamping separate so a stalled TSA is distinguishable from
        # certificate export or private-key access. Timestamping remains required.
        run_phase('RFC3161 timestamp', [tool, 'timestamp', '/v', '/tr',
                  'http://timestamp.digicert.com', '/td', 'SHA256', str(path)], environment=environment)
        run_phase('Verify Authenticode and timestamp', [tool, 'verify', '/pa', '/all', '/tw', '/v', str(path)],
                  environment=environment)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    try:
        sign(args.path.resolve())
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from None


if __name__ == '__main__':
    main()
