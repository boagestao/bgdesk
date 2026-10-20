#!/usr/bin/env python3
"""Publish complete signed releases to R2; announce them only after verification."""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "BGDesk-Release/1.0 (+https://bgdesk.com)"


def client():
    import boto3
    from botocore.config import Config
    account = os.environ["R2_ACCOUNT_ID"]
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account):
        raise ValueError("R2_ACCOUNT_ID must be the Cloudflare 32-character Account ID")
    return boto3.client("s3", endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
                        region_name="auto", aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                        config=Config(request_checksum_calculation="when_required",
                                      response_checksum_validation="when_required"))


def head(s3, bucket, key):
    from botocore.exceptions import ClientError
    try:
        return s3.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def upload(s3, bucket, path, key, immutable=True):
    digest = file_hash(path)
    previous = head(s3, bucket, key)
    if immutable and previous:
        if previous.get("Metadata", {}).get("sha256") != digest:
            raise ValueError(f"Immutable object already exists with different bytes: {key}; increase version")
        return
    s3.upload_file(str(path), bucket, key, ExtraArgs={
        "ContentType": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "CacheControl": "public, max-age=31536000, immutable" if immutable else "no-store, max-age=0",
        "Metadata": {"sha256": digest},
    })
    remote = head(s3, bucket, key)
    if not remote or remote["ContentLength"] != path.stat().st_size or remote.get("Metadata", {}).get("sha256") != digest:
        raise ValueError(f"R2 verification failed for {key}")


def read_records(artifacts, version):
    records = []
    seen = set()
    for manifest in artifacts.glob("*/artifacts.json"):
        for record in json.loads(manifest.read_text()):
            name = record["file_name"]
            if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in {".", ".."}:
                raise ValueError("Invalid artifact file name")
            path = manifest.parent / name
            if record["version"] != version or file_hash(path) != record["sha256"] or path.stat().st_size != record["size"]:
                raise ValueError(f"Artifact version/hash/size mismatch: {name}")
            selector = (record["edition"], record["platform"], record["arch"], record["format"])
            if selector in seen:
                raise ValueError(f"Duplicate artifact selector: {selector}")
            seen.add(selector)
            records.append((record, path))
    expected = {
        (edition, platform, arch, fmt)
        for edition in ("cliente", "suporte")
        for platform, arch, formats in (
            ("macos", "aarch64", ("dmg",)), ("macos", "x86_64", ("dmg",)),
            ("windows", "x86_64", ("exe", "inno-exe")),
            ("linux", "x86_64", ("deb", "rpm", "AppImage", "pkg.tar.zst")),
            ("linux", "aarch64", ("deb", "rpm", "AppImage")),
        ) for fmt in formats
    }
    if seen != expected:
        raise ValueError(f"Incomplete release; missing={sorted(expected - seen)}, extra={sorted(seen - expected)}")
    return records


def public_check(origin, key, path, small=False):
    request = urllib.request.Request(f"{origin}/{key}", method="GET" if small else "HEAD",
                                     headers={"Cache-Control": "no-cache", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        if small:
            if response.read(path.stat().st_size + 1) != path.read_bytes():
                raise ValueError(f"Public URL does not serve the original bytes: {key}")
        elif int(response.headers.get("Content-Length", "-1")) != path.stat().st_size:
            raise ValueError(f"Public download URL has the wrong size: {key}")


def publish(s3, bucket, site, records, origin, release_id, verify=public_check):
    # Never activate an edition while another edition still has missing objects.
    release_files = []
    for edition in ("cliente", "suporte"):
        directory = site / "updates" / edition / release_id
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                raise ValueError("Release must contain only regular files")
            key = path.relative_to(site).as_posix()
            upload(s3, bucket, path, key)
            release_files.append((key, path))
    for key, path in release_files:
        verify(origin, key, path, small=path.name in {"bgdesk-update.json", "bgdesk-update.json.sig", "index.html"})
    # Preserve the existing site's stable Windows/Linux download links.
    for record, _ in records:
        fmt, edition, arch = record["format"], record["edition"], record["arch"]
        aliases = []
        if record["platform"] == "linux":
            aliases.append(f"bgdesk-{edition}-{arch}.{fmt}")
        elif fmt == "inno-exe":
            aliases.append(f"bgdesk-{edition}-win64.exe")
        elif fmt == "dmg":
            aliases.append(f"bgdesk-{edition}-{arch}.dmg")
        path = site / "updates" / edition / release_id / record["file_name"]
        for alias in aliases:
            upload(s3, bucket, path, alias, immutable=False)
    for source_name, public_name in (("install.sh", "install-suporte.sh"), ("install-client.sh", "install.sh")):
        script = site / public_name
        script.write_text((ROOT / "installers" / source_name).read_text().replace(
            "https://download.bgdesk.com", origin))
        upload(s3, bucket, script, public_name, immutable=False)
    for edition in ("cliente", "suporte"):
        latest = site / "updates" / edition / "latest.json"
        key = latest.relative_to(site).as_posix()
        upload(s3, bucket, latest, key, immutable=False)
        verify(origin, key, latest, small=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--source-commit", help="exact commit whose successful builds produced the artifacts")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
        raise SystemExit("Invalid stable release version")
    origin = os.environ["R2_PUBLIC_ORIGIN"]
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+", origin):
        raise SystemExit("R2_PUBLIC_ORIGIN must be an HTTPS origin without a path or trailing slash")
    s3, bucket, release_id = client(), os.environ["R2_BUCKET"], f"v{args.version}"
    marker = f"updates/releases/{release_id}.json"
    published = head(s3, bucket, marker) is not None
    if args.check_only:
        with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
            handle.write(f"new_release={str(not published).lower()}\n")
        print("Version already published; builds will run without announcing it again." if published else "New version: release will be published after all builds pass.")
        return
    records = read_records(args.artifacts, args.version)
    source_commit = args.source_commit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("An exact source commit is required")
    if published:
        # A publication-only retry must never attach freshly rebuilt/different
        # bytes to an already announced version, even from the same source commit.
        for record, path in records:
            key = f"updates/{record['edition']}/{release_id}/{record['file_name']}"
            remote = head(s3, bucket, key)
            if not remote or remote['ContentLength'] != path.stat().st_size or remote.get('Metadata', {}).get('sha256') != record['sha256']:
                raise ValueError(f"Published release differs from supplied artifacts: {key}")
        print("Version already published; all supplied artifacts match its immutable objects.")
        return
    published_at = subprocess.check_output(["git", "show", "-s", "--format=%cI", source_commit], cwd=ROOT, text=True).strip()
    with tempfile.TemporaryDirectory(prefix="bgdesk-release-", dir=os.environ.get("RUNNER_TEMP")) as temp:
        private_key = Path(temp) / "signing.json"
        private_key.touch(mode=0o600)
        private_key.write_text(os.environ["BGDESK_UPDATE_SIGNING_KEY"])
        site = Path(temp) / "site"
        for edition in ("cliente", "suporte"):
            command = [sys.executable, str(ROOT / "res/update/website_release.py"), "prepare",
                       "--version", args.version, "--edition", edition,
                       "--published-at", published_at,
                       "--site-public", str(site), "--key-file", str(private_key)]
            for record, path in records:
                if record["edition"] == edition:
                    command += ["--artifact", record["platform"], record["arch"], record["format"], str(path)]
            environment = dict(os.environ, BGDESK_UPDATE_ORIGIN=origin)
            subprocess.run(command, cwd=ROOT, env=environment, check=True)
        publish(s3, bucket, site, records, origin, release_id)
        completion = Path(temp) / "release.json"
        completion.write_text(json.dumps({"version": args.version, "commit": source_commit}))
        upload(s3, bucket, completion, marker)
    print(f"BGDesk {args.version} published and verified at {origin}")


if __name__ == "__main__":
    main()
