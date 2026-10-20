#!/usr/bin/env python3
"""Collect exactly the expected build outputs, with unique names and hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tomllib


def specs(platform, arch, edition):
    if platform == "macos":
        return [("dmg", Path(f"build/macOS-{arch}-{edition}/bgdesk-{edition}-darwin.dmg"))]
    if platform == "windows":
        directory = Path(f"build/windows-x86_64-{edition}")
        return [("exe", directory / f"bgdesk-{edition}-update-win64.exe"),
                ("inno-exe", directory / f"bgdesk-{edition}-win64.exe")]
    directory = Path(f"build/linux-{arch}-{edition}")
    formats = ("deb", "rpm", "AppImage") + (("pkg.tar.zst",) if arch == "x86_64" else ())
    return [(fmt, directory / f"bgdesk-{edition}-{arch}.{fmt}") for fmt in formats]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=("macos", "windows", "linux"))
    parser.add_argument("arch", choices=("aarch64", "x86_64"))
    parser.add_argument("edition", choices=("cliente", "suporte"))
    parser.add_argument("--output", type=Path, default=Path("release-artifacts"))
    args = parser.parse_args()
    version = tomllib.loads(Path("Cargo.toml").read_text())["package"]["version"]
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for file_format, source in specs(args.platform, args.arch, args.edition):
        if not source.is_file() or not source.stat().st_size:
            raise SystemExit(f"Required {file_format} was not generated: {source}")
        extension = "exe" if file_format == "inno-exe" else file_format
        suffix = "-setup" if file_format == "inno-exe" else ""
        name = f"bgdesk-{args.edition}-{version}-{args.platform}-{args.arch}{suffix}.{extension}"
        target = args.output / name
        shutil.copyfile(source, target)
        with target.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        records.append(dict(platform=args.platform, arch=args.arch, format=file_format,
                            edition=args.edition, version=version, file_name=name,
                            size=target.stat().st_size,
                            sha256=digest))
    (args.output / "artifacts.json").write_text(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    main()
