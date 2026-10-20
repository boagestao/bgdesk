#!/usr/bin/env python3
"""Send local signing credentials to GitHub Secrets without printing their values."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit

import config_archive
import android_signing

ROOT = Path(__file__).resolve().parents[2]


def dotenv(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    values.update(os.environ)
    # Accept the existing storage fields used by the project's local .env.
    for old, new in (("STORAGE_ACCESS_KEY", "R2_ACCESS_KEY_ID"), ("STORAGE_SECRET", "R2_SECRET_ACCESS_KEY")):
        if not values.get(new) and values.get(old):
            values[new] = values[old]
    storage = urlsplit(values.get("STORAGE_URL", ""))
    if storage.hostname and storage.hostname.endswith(".r2.cloudflarestorage.com"):
        if storage.scheme != "https" or storage.username or storage.password or storage.query or storage.fragment:
            raise SystemExit("STORAGE_URL must be an HTTPS R2 endpoint without credentials/query")
        account = storage.hostname.split(".")[0]
        bucket = storage.path.strip("/")
        if bucket and "/" in bucket:
            raise SystemExit("STORAGE_URL must end with the bucket name, without an object path")
        values.setdefault("R2_ACCOUNT_ID", account)
        if bucket:
            values.setdefault("R2_BUCKET", bucket)
        values.setdefault("R2_PUBLIC_ORIGIN", "https://download.bgdesk.com")
    return values


def collect(values, update_key):
    secrets = {}
    for name in ("MACOS_P12_PASSWORD", "MACOS_CODESIGN_IDENTITY", "MACOS_TEAM_ID",
                 "MACOS_NOTARY_APPLE_ID", "MACOS_NOTARY_PASSWORD",
                 "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "BGDESK_CONFIG_TOKEN"):
        if values.get(name):
            secrets[name] = values[name]
    p12 = values.get("MACOS_P12_FILE")
    if p12:
        secrets["MACOS_P12_BASE64"] = base64.b64encode(Path(p12).expanduser().read_bytes()).decode()
    if update_key.exists():
        secrets["BGDESK_UPDATE_SIGNING_KEY"] = update_key.read_text()
    return secrets


def config_key(repo, config_repo, key_path, apply):
    if not apply:
        print("BGDESK_CONFIG_SSH_KEY: será criada/reutilizada uma deploy key de leitura do config")
        return None
    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not key_path.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
                        "BGDesk Actions config (read only)", "-f", str(key_path)], check=True)
    public = Path(str(key_path) + ".pub").read_text().strip()
    keys = json.loads(subprocess.check_output(["gh", "api", f"repos/{config_repo}/keys"]))
    if not any(item["key"].split()[:2] == public.split()[:2] for item in keys):
        body = json.dumps({"title": "BGDesk Actions config", "key": public, "read_only": True})
        subprocess.run(["gh", "api", f"repos/{config_repo}/keys", "--method", "POST",
                        "--input", "-"], input=body, text=True, check=True, stdout=subprocess.DEVNULL)
    return key_path.read_text()


def desktop_archive(args):
    commit = config_archive.pinned_ref(ROOT)
    if args.checkout_config:
        with tempfile.TemporaryDirectory(prefix="bgdesk-private-config-") as temporary:
            checkout = Path(temporary) / "config"
            subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                            f"git@github.com:{args.config_repo}.git", str(checkout)], check=True)
            subprocess.run(["git", "-C", str(checkout), "checkout", "--quiet", "--detach", commit], check=True)
            value = config_archive.export(checkout, commit)
    else:
        value = config_archive.export(ROOT / "config", commit)
    print(f"Configuração desktop verificada no commit {commit[:12]} ({len(config_archive.FILES)} arquivos).")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="boagestao/bgdesk")
    parser.add_argument("--config-repo", default="boagestao/bgdesk-config")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--update-key", type=Path, default=Path.home() / ".config/bgdesk/update-signing.json")
    parser.add_argument("--config-key", type=Path, default=Path.home() / ".config/bgdesk/actions-config")
    parser.add_argument("--apply", action="store_true", help="upload; without this flag only names are shown")
    parser.add_argument('--android-only', action='store_true', help='validate and upload only the existing Android signing identity')
    parser.add_argument("--register-config-key", action="store_true",
                        help="optional SSH deploy key; requires deploy keys to be allowed by repository policy")
    parser.add_argument("--checkout-config", action="store_true",
                        help="clone the private repository into a temporary checkout and export its pinned desktop files")
    parser.add_argument("--skip-config-archive", action="store_true",
                        help="use an existing repository token/SSH key instead of a configuration snapshot Secret")
    args = parser.parse_args()
    if args.android_only:
        secrets = android_signing.local_secrets(ROOT)
        with tempfile.TemporaryDirectory(prefix='bgdesk-android-validate-') as temporary:
            android_signing.validate(secrets, Path(temporary))
        for name, value in secrets.items():
            if len(value.encode()) > 48 * 1024:
                raise SystemExit(f'{name}: exceeds GitHub secret size limit')
            if args.apply:
                subprocess.run(['gh', 'secret', 'set', name, '--repo', args.repo], input=value,
                               text=True, check=True, stdout=subprocess.DEVNULL)
            print(f'{name}: {"salvo no GitHub" if args.apply else "validado para envio"}')
        return
    values = dotenv(args.env_file)
    secrets = collect(values, args.update_key.expanduser())
    if not args.skip_config_archive:
        secrets["BGDESK_CONFIG_ARCHIVE"] = desktop_archive(args)
    if args.register_config_key:
        key = config_key(args.repo, args.config_repo, args.config_key.expanduser(), args.apply)
        if key:
            secrets["BGDESK_CONFIG_SSH_KEY"] = key
    for name, value in sorted(secrets.items()):
        if len(value.encode()) > 48 * 1024:
            raise SystemExit(f"{name}: exceeds GitHub's 48 KiB secret limit")
        if args.apply:
            subprocess.run(["gh", "secret", "set", name, "--repo", args.repo],
                           input=value, text=True, check=True, stdout=subprocess.DEVNULL)
        print(f"{name}: {'salvo no GitHub' if args.apply else 'disponível para envio'}")
    for name in ("R2_ACCOUNT_ID", "R2_BUCKET", "R2_PUBLIC_ORIGIN"):
        value = values.get(name)
        if value:
            if args.apply:
                subprocess.run(["gh", "variable", "set", name, "--repo", args.repo],
                               input=value, text=True, check=True, stdout=subprocess.DEVNULL)
            print(f"{name}: {'variável salva' if args.apply else 'variável disponível'}")
    required = ("MACOS_P12_BASE64", "MACOS_P12_PASSWORD", "MACOS_NOTARY_APPLE_ID",
                "MACOS_NOTARY_PASSWORD", "BGDESK_UPDATE_SIGNING_KEY",
                "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
    missing = [name for name in required if name not in secrets]
    if not any(name in secrets for name in ("BGDESK_CONFIG_ARCHIVE", "BGDESK_CONFIG_TOKEN", "BGDESK_CONFIG_SSH_KEY")):
        missing.append("BGDESK_CONFIG_ARCHIVE (ou token/SSH de leitura)")
    if missing:
        print("Ainda não encontrados no .env/ambiente: " + ", ".join(missing))
    print("Valores de Secrets não são impressos. O perfil local de Keychain não é exportado.")


if __name__ == "__main__":
    main()
