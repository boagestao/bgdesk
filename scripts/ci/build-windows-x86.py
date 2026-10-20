#!/usr/bin/env python3
"""Build the existing Sciter UI for Win32, without Flutter or bridge generation."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SCITER_REV = '674e07d3066ca9a92ced3816203ab6b652629d1e'
SCITER_SDK_REV = 'f33df075d9eb2f8d252cb88f1b2c8096e56197ed'
SCITER_SHA256 = '285f3e6a051a7c61845cd7e4d2120781b6bdf411239f70a85c65b38a52d38f28'
TARGET = 'i686-pc-windows-msvc'


def check_native_dependencies(vcpkg_root):
    prefix = Path(vcpkg_root) / 'installed/x86-windows-static'
    required = ('include/libavutil/attributes.h', 'include/libavutil/opt.h',
                'include/libavcodec/avcodec.h', 'lib/avutil.lib', 'lib/avcodec.lib')
    missing = [name for name in required if not (prefix / name).is_file()]
    if missing:
        raise ValueError('FFmpeg target dependencies missing from x86-windows-static '
                         '(host x64 libraries cannot build Win32): ' + ', '.join(missing))


def require_x86(path):
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError(f'Not a PE executable: {path.name}')
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    if offset + 26 > len(data) or data[offset:offset + 4] != b'PE\0\0':
        raise ValueError(f'Invalid PE header: {path.name}')
    machine = struct.unpack_from('<H', data, offset + 4)[0]
    optional = struct.unpack_from('<H', data, offset + 24)[0]
    if machine != 0x14c or optional != 0x10b:
        raise ValueError(f'Expected an x86 PE32 binary: {path.name}')


def prepare_sciter(root):
    # Only the isolated Win32 runner uses upstream's x86 video calling convention.
    # Preserve every other locked dependency; never resolve a fresh dependency set.
    original = 'sciter-rs = { git = "https://github.com/rustdesk-org/rust-sciter", branch = "dyn" }'
    pinned = original.replace('branch = "dyn"', f'rev = "{SCITER_REV}"')
    old_source = 'git+https://github.com/rustdesk-org/rust-sciter?branch=dyn#5322f3a755a0e6bf999fbc60d1efc35246c0f821'
    new_source = f'git+https://github.com/rustdesk-org/rust-sciter?rev={SCITER_REV}#{SCITER_REV}'
    manifest, lock = root / 'Cargo.toml', root / 'Cargo.lock'
    contents, locked = manifest.read_text(encoding='utf-8'), lock.read_text(encoding='utf-8')
    if pinned in contents and new_source in locked:
        return  # Cliente and suporte share one checkout/toolchain.
    if contents.count(original) != 1 or locked.count(old_source) != 1:
        raise ValueError('Unexpected Sciter dependency pin; review Win32 compatibility before building')
    manifest.write_text(contents.replace(original, pinned), encoding='utf-8')
    lock.write_text(locked.replace(old_source, new_source), encoding='utf-8')


def sciter_dll(root):
    target = root / '.tools/sciter-win32/sciter.dll'
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != SCITER_SHA256:
        url = f'https://raw.githubusercontent.com/c-smile/sciter-sdk/{SCITER_SDK_REV}/bin.win/x32/sciter.dll'
        request = urllib.request.Request(url, headers={'User-Agent': 'BGDesk-Release/1.0 (+https://bgdesk.com)'})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != SCITER_SHA256:
            raise ValueError('Sciter x86 runtime checksum mismatch')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    require_x86(target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', choices=('cliente', 'suporte'), required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Win32 compilation requires a Windows MSVC runner')
    check_native_dependencies(os.environ['VCPKG_ROOT'])
    prepare_sciter(ROOT)
    subprocess.run(['python', 'res/inline-sciter.py'], cwd=ROOT, check=True,
                   env=dict(os.environ, PYTHONUTF8='1'))
    features = 'inline,hwcodec,vram' + (',incoming-only' if args.edition == 'cliente' else '')
    subprocess.run(['cargo', 'build', '--locked', '--release', '--target', TARGET,
                    '--features', features, '--bin', 'rustdesk'], cwd=ROOT, check=True)
    source = ROOT / f'target/{TARGET}/release/rustdesk.exe'
    require_x86(source)
    bundle = ROOT / f'build/windows-x86-{args.edition}/extracted'
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    shutil.copyfile(source, bundle / 'bgdesk.exe')
    shutil.copyfile(sciter_dll(ROOT), bundle / 'sciter.dll')
    print(f'Win32 {args.edition} app and pinned Sciter runtime verified as PE32')


if __name__ == '__main__':
    main()
