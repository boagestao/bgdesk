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
    parser.add_argument("--arch", choices=("x86", "x86_64"), default="x86_64")
    args = parser.parse_args()
    output = ROOT / f"build/windows-{args.arch}-{args.edition}"
    bundle = output / "extracted"
    if not (bundle / "bgdesk.exe").is_file():
        raise SystemExit("Build and sign extracted/bgdesk.exe first")
    command = [
        sys.executable, str(ROOT / "libs/portable/generate.py"),
        "-f", str(bundle), "-o", str(ROOT / "libs/portable"),
        "-e", str(bundle / "bgdesk.exe"),
    ]
    if args.arch == 'x86':
        command += ['--target', 'i686-pc-windows-msvc']
    subprocess.run(command, cwd=ROOT, check=True)
    target_dir = 'i686-pc-windows-msvc/release' if args.arch == 'x86' else 'release'
    packed = ROOT / f"target/{target_dir}/rustdesk-portable-packer.exe"
    if not packed.is_file():
        raise SystemExit("Portable updater executable was not generated")
    if args.arch == 'x86':
        import importlib.util
        spec = importlib.util.spec_from_file_location('win32', Path(__file__).with_name('build-windows-x86.py'))
        win32 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(win32)
        win32.require_x86(packed)
    suffix = 'win32' if args.arch == 'x86' else 'win64'
    shutil.copyfile(packed, output / f"bgdesk-{args.edition}-update-{suffix}.exe")


if __name__ == "__main__":
    main()
