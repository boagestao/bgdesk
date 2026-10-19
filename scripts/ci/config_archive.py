#!/usr/bin/env python3
"""Export/restore the pinned desktop configuration through GitHub Secrets."""
import base64
import gzip
import io
import os
from pathlib import Path
import subprocess
import tarfile

FILES = frozenset(("settings.toml", "certs/ca.crt", "certs/sign.crt", "certs/sign.key"))
MAX_SECRET_BYTES = 48 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024


def pinned_ref(root):
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD:config"], text=True).strip()


def export(repository, expected_ref):
    data = subprocess.check_output([
        "git", "-C", str(repository), "archive", "--format=tar", expected_ref, *sorted(FILES),
    ])
    encoded = base64.b64encode(gzip.compress(data, mtime=0)).decode("ascii")
    if len(encoded) > MAX_SECRET_BYTES:
        raise ValueError("Configuration archive exceeds GitHub's 48 KiB secret limit")
    validate(encoded, expected_ref)
    return encoded


def validate(encoded, expected_ref):
    if len(encoded) > MAX_SECRET_BYTES:
        raise ValueError("Configuration secret exceeds maximum size")
    compressed = base64.b64decode(encoded, validate=True)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        data = stream.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("Configuration archive exceeds maximum expanded size")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        if archive.pax_headers.get("comment") != expected_ref:
            raise ValueError("Configuration Secret does not match the pinned submodule commit; refresh it with setup-github-secrets.py --checkout-config --apply")
        for member in archive:
            if member.isdir() and member.name.rstrip("/") == "certs":
                continue
            if not member.isfile() or member.name not in FILES or member.name in files:
                raise ValueError("Unexpected path, link, or duplicate in configuration archive")
            with archive.extractfile(member) as handle:
                files[member.name] = handle.read()
    if files.keys() != FILES:
        raise ValueError("Configuration archive is missing a required desktop build file")
    return files


def restore(encoded, expected_ref, destination):
    files = validate(encoded, expected_ref)
    destination = Path(destination)
    if destination.is_symlink() or (destination.exists() and any(destination.iterdir())):
        raise ValueError("Configuration destination must be an empty regular directory")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    for name, data in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    commit = pinned_ref(root)
    restore(os.environ["BGDESK_CONFIG_ARCHIVE"], commit, root / "config")
    print(f"Desktop configuration restored from Secret for commit {commit[:12]}.")
