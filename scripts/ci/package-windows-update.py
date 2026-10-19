#!/usr/bin/env python3
"""Bundle the signed Windows app in the native executable that supports --update."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=("cliente", "suporte"), required=True)
    args = parser.parse_args()
    output = ROOT / f"build/windows-x86_64-{args.edition}"
    bundle = output / "extracted"
    if not (bundle / "bgdesk.exe").is_file():
        raise SystemExit("Build and sign extracted/bgdesk.exe first")
    subprocess.run([
        sys.executable, str(ROOT / "libs/portable/generate.py"),
        "-f", str(bundle), "-o", str(ROOT / "libs/portable"),
        "-e", str(bundle / "bgdesk.exe"),
    ], cwd=ROOT, check=True)
    packed = ROOT / "target/release/rustdesk-portable-packer.exe"
    if not packed.is_file():
        raise SystemExit("Portable updater executable was not generated")
    shutil.copyfile(packed, output / f"bgdesk-{args.edition}-update-win64.exe")


if __name__ == "__main__":
    main()
