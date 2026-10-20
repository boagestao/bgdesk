#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import config_archive


TARGETS = [
    ("macos", "aarch64", "macos-15"),
    ("macos", "x86_64", "macos-15-intel"),
    ("windows", "x86_64", "windows-2022"),
    ("linux", "x86_64", "ubuntu-24.04"),
    ("linux", "aarch64", "ubuntu-24.04-arm"),
]

def distribution_matrix(platforms):
    if platforms == 'windows-x86':
        return {'include': [dict(platform='windows', arch='x86', runner='windows-2022')]}
    return {"include": [
        dict(platform=platform, arch=arch, runner=runner,
             **({'win32': True} if platform == 'windows' and platforms in ('all', 'windows') else {}))
        for platform, arch, runner in TARGETS
        if platforms == "all" or platforms in (platform, f"{platform}-{arch}")
    ]}


def artifact_targets(platforms='all'):
    """Logical output architectures; Windows shares one runner for both."""
    for target in distribution_matrix(platforms)['include']:
        yield target['platform'], target['arch']
        if target.get('win32'):
            yield 'windows', 'x86'


def complete_build_job_names():
    return {f"{t['platform']} / {t['arch']}{' + x86' if t.get('win32') else ''} (cliente + suporte)"
            for t in distribution_matrix('all')['include']}


def matrix(platforms):
    return distribution_matrix(platforms)


def main():
    platforms = os.environ.get("BUILD_PLATFORMS", "all")
    publish = os.environ.get("PUBLISH_RELEASE") == "true"
    if publish and platforms != "all":
        raise SystemExit("Publishing requires all platforms, so an edition cannot lose artifacts.")
    if publish and os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("Publication is allowed only from main; use publish=false to validate another branch")
    active = matrix(platforms)["include"]
    if not active:
        raise SystemExit(f"No build jobs match platforms={platforms}")
    origin = os.environ.get("BGDESK_UPDATE_ORIGIN", "https://bgdesk.com")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+", origin):
        raise SystemExit("Update origin must be HTTPS, with no path or trailing slash")
    version = tomllib.loads(Path("Cargo.toml").read_text())["package"]["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise SystemExit("Cargo.toml must contain a stable MAJOR.MINOR.PATCH release version")
    flutter_version = re.search(r"^version:\s*(\S+)", Path("flutter/pubspec.yaml").read_text(), re.M)
    if not flutter_version or flutter_version[1].split("+")[0] != version:
        raise SystemExit("Cargo.toml and flutter/pubspec.yaml must have the same version")
    portable_version = tomllib.loads(Path("libs/portable/Cargo.toml").read_text())["package"]["version"]
    if portable_version != version:
        raise SystemExit("libs/portable/Cargo.toml must have the same release version")
    required = []
    config_ref = config_archive.pinned_ref(Path.cwd())
    config_source = "repository"
    if os.environ.get("BGDESK_CONFIG_ARCHIVE"):
        config_archive.validate(os.environ["BGDESK_CONFIG_ARCHIVE"], config_ref)
        config_source = "archive"
    elif not (os.environ.get("BGDESK_CONFIG_SSH_KEY") or os.environ.get("BGDESK_CONFIG_TOKEN")):
        required.append("BGDESK_CONFIG_ARCHIVE (or a read-only config token/SSH key)")
    if any(target['platform'] == 'macos' for target in active):
        required += ["MACOS_P12_BASE64", "MACOS_P12_PASSWORD", "MACOS_NOTARY_APPLE_ID", "MACOS_NOTARY_PASSWORD"]
    if publish:
        required += ["BGDESK_UPDATE_SIGNING_KEY", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                     "R2_ACCOUNT_ID", "R2_BUCKET", "R2_PUBLIC_ORIGIN"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit("Configure GitHub Secrets/Variables before building: " + ", ".join(missing))
    if publish:
        # Check the key before expensive builds, using the same source as the updater.
        sys.path.insert(0, str(Path("res/update").resolve()))
        import generate_update_metadata as signing
        key = json.loads(os.environ["BGDESK_UPDATE_SIGNING_KEY"])
        os.environ[signing.SEED_ENV] = key["seed"]
        os.environ[signing.PUBLIC_KEY_ENV] = key["public_key"]
        import argparse
        signing.command_check_key(argparse.Namespace(rust_source="src/update_metadata.rs"))
    outputs = dict(version=version, release_id=f"v{version}", config_ref=config_ref, config_source=config_source,
                   flutter_version=next(line.strip() for line in Path('scripts/flutter-stable-version').read_text().splitlines() if line.strip() and not line.startswith('#')),
                   matrix=json.dumps(matrix(platforms), separators=(",", ":")),
                   publish=str(publish).lower())
    with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")
    runners = len(matrix(platforms)['include'])
    print(f"BGDesk {version}: {runners} runners, {len(list(artifact_targets(platforms))) * 2} builds (cliente then suporte); publication={publish}")


if __name__ == "__main__":
    main()
