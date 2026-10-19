#!/usr/bin/env python3
"""Prepare signed BGDesk releases for the static bgdesk.com website."""
import argparse
import base64
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

import generate_update_metadata as metadata

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KEY_FILE = Path.home() / ".config/bgdesk/update-signing.json"
ORIGIN = os.environ.get("BGDESK_UPDATE_ORIGIN", "https://bgdesk.com")
KEY_MARKER = "const TRUSTED_UPDATE_KEYS: &[TrustedUpdateKey] = &[];"


def load_key(key_file):
    data = json.loads(Path(key_file).read_text())
    os.environ[metadata.SEED_ENV] = data["seed"]
    os.environ[metadata.PUBLIC_KEY_ENV] = data["public_key"]


def init_key(args):
    """Keep the private seed outside both repositories; embed only its public key."""
    source_path = Path(args.rust_source)
    source = source_path.read_text()
    if source.count(KEY_MARKER) != 1:
        metadata.fail("trusted keys already configured; refusing to replace them")
    key_path = Path(args.key_file).expanduser().resolve()
    for repository in (ROOT, ROOT.parent / "bgdesk-webpage"):
        if key_path.is_relative_to(repository):
            metadata.fail("private signing key must be stored outside the repositories")
    private_key = ed25519.Ed25519PrivateKey.generate()
    seed = private_key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    data = {
        "key_id": metadata.KEY_ID,
        "seed": base64.b64encode(seed).decode("ascii"),
        "public_key": base64.b64encode(public_key).decode("ascii"),
    }
    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle)
        handle.write("\n")
    entry = (
        'const TRUSTED_UPDATE_KEYS: &[TrustedUpdateKey] = &[TrustedUpdateKey {\n'
        f'    key_id: "{metadata.KEY_ID}",\n'
        '    algorithm: "ed25519",\n'
        f'    public_key: [{", ".join(map(str, public_key))}],\n'
        '}];'
    )
    source_path.write_text(source.replace(KEY_MARKER, entry).replace(
        "// BGDesk release signing keys must be provisioned here before signed updates are enabled.\n",
        "// BGDesk release public key. The private seed is kept outside the repository.\n",
    ))
    print(f"Chave privada criada em {key_path}; faça backup seguro antes de distribuir o aplicativo.")


def validate_version(version, release_id):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        metadata.fail("version must be a stable MAJOR.MINOR.PATCH version")
    parts = [int(part) for part in version.split(".")]
    if any(part > 65535 for part in parts) or not any(parts):
        metadata.fail("version components must fit in u16 and must not all be zero")
    if release_id not in (version, f"v{version}"):
        metadata.fail("release id must equal version, optionally prefixed by v")


def release_page(version, edition, artifacts):
    links = "\n".join(
        f'<li><a href="{html.escape(item["file_name"], quote=True)}">'
        f'{html.escape(item["platform"])} / {html.escape(item["arch"])} '
        f'({html.escape(item["format"])})</a></li>'
        for item in artifacts
    )
    return (
        '<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>BGDesk {edition} {version}</title>'
        f'<h1>BGDesk {edition} — {version}</h1><ul>{links}</ul>'
        '<p><a href="https://bgdesk.com">Voltar ao site</a></p></html>\n'
    )


def prepare_release(args):
    release_id = args.release_id or f"v{args.version}"
    validate_version(args.version, release_id)
    public = Path(args.site_public).resolve()
    key_file = Path(args.key_file).expanduser().resolve()
    if key_file.is_relative_to(public):
        metadata.fail("private signing key cannot be inside the website public directory")
    load_key(key_file)
    metadata.command_check_key(argparse.Namespace(rust_source=args.rust_source))
    channel = public / "updates" / args.edition
    destination = channel / release_id
    if destination.exists():
        metadata.fail("release already exists; publish a new version instead of replacing it")
    channel.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".release-", dir=channel) as temporary:
        stage = Path(temporary) / release_id
        stage.mkdir()
        specs = []
        for platform, arch, file_format, raw_path in args.artifact:
            valid_selector = (
                platform == "macos" and arch in {"aarch64", "x86_64"} and file_format == "dmg"
            ) or (
                platform == "windows" and arch in {"x86", "x86_64", "aarch64"}
                and file_format in {"exe", "msi", "inno-exe"}
            ) or (
                platform == "linux" and arch in {"x86_64", "aarch64"}
                and file_format in {"deb", "rpm", "AppImage"}
            )
            if not valid_selector:
                metadata.fail("unsupported auto-update selector; use macos/aarch64|x86_64/dmg or windows/x86|x86_64|aarch64/exe|msi")
            path = Path(raw_path).resolve()
            extension = "exe" if file_format == "inno-exe" else file_format
            if path.suffix != f".{extension}":
                metadata.fail("artifact extension does not match its format")
            metadata.validate_or_fail(metadata.validate_artifact_file_name, path.name)
            if path.name in {"bgdesk-update.json", "bgdesk-update.json.sig", "index.html"}:
                metadata.fail("artifact name conflicts with release metadata")
            target = stage / path.name
            if target.exists():
                metadata.fail("duplicate artifact file name")
            shutil.copyfile(path, target)
            specs.append((platform, arch, file_format, str(target)))
        base_url = f"{ORIGIN}/updates/{args.edition}"
        common = dict(
            version=args.version, release_id=release_id,
            package_id=f"bgdesk-{args.edition}", release_base_url=base_url,
        )
        metadata_path = stage / "bgdesk-update.json"
        signature_path = stage / "bgdesk-update.json.sig"
        metadata.command_sign(argparse.Namespace(
            **common, artifact=specs,
            published_at=args.published_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            metadata_out=str(metadata_path), signature_out=str(signature_path),
        ))
        metadata.command_verify(argparse.Namespace(
            **common, artifact=[spec[3] for spec in specs],
            metadata=str(metadata_path), signature=str(signature_path),
        ))
        artifacts = json.loads(metadata_path.read_bytes())["artifacts"]
        (stage / "index.html").write_text(release_page(args.version, args.edition, artifacts))
        stage.rename(destination)
    # Activate only after every artifact and both signed sidecars are complete.
    with tempfile.NamedTemporaryFile(mode="w", dir=channel, delete=False) as handle:
        json.dump({"url": f"{base_url}/{release_id}/"}, handle)
        handle.write("\n")
        latest = Path(handle.name)
    latest.chmod(0o644)
    latest.replace(channel / "latest.json")
    print(f"Release verificada: {destination}")
    print(f"Publicar a pasta da release antes de {channel / 'latest.json'}")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-key")
    prepare = commands.add_parser("prepare")
    for command in (init, prepare):
        command.add_argument("--key-file", default=str(DEFAULT_KEY_FILE))
        command.add_argument("--rust-source", default=str(ROOT / "src/update_metadata.rs"))
    init.set_defaults(func=init_key)
    prepare.add_argument("--edition", choices=("cliente", "suporte"), required=True)
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--release-id")
    prepare.add_argument("--published-at", help="fixed RFC 3339 timestamp for reproducible CI retries")
    prepare.add_argument("--artifact", action="append", nargs=4, required=True,
                         metavar=("PLATFORM", "ARCH", "FORMAT", "PATH"))
    prepare.add_argument("--site-public", default=str(ROOT.parent / "bgdesk-webpage/public"))
    prepare.set_defaults(func=prepare_release)
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    args.func(args)
