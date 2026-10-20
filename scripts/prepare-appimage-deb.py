#!/usr/bin/env python3
"""Create the original portable payload from a native DEB and a non-DRM Rust build."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build


def prepare(native_deb, portable_library, destination):
    portable_library = Path(portable_library).resolve()
    # Catch accidentally reusing the native library before giving it to the unchanged recipes.
    for marker in (build.DRMTAP_DLOPEN_MARKER, build.DRMTAP_WAKE_MARKER):
        if build._carries_drmtap_marker(str(portable_library), marker):
            raise ValueError('AppImage requires a Rust library compiled with --no-drm')
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bgdesk-appimage-deb-') as temporary:
        root = Path(temporary) / 'package'
        subprocess.run(['dpkg-deb', '-R', str(Path(native_deb).resolve()), str(root)], check=True)
        shutil.copy2(str(portable_library), str(root / 'usr/share/bgdesk/lib/libbgdesk.so'))
        shutil.rmtree(str(root / 'usr/lib/bgdesk'), ignore_errors=True)
        for extra in (root / 'usr/share/bgdesk').glob('libdrmtap.so*'):
            extra.unlink()
        control = root / 'DEBIAN/control'
        lines = control.read_text().splitlines(True)
        for index, line in enumerate(lines):
            if line.startswith('Depends:'):
                dependencies = line[len('Depends:'):].strip().split(',')
                # These entries were added by the native DRM packaging step.
                dependencies = [dependency.strip() for dependency in dependencies
                                if dependency.strip().split(' ', 1)[0]
                                not in ('libdrm2', 'libegl1', 'libgles2', 'libc6')]
                lines[index] = 'Depends: ' + ', '.join(dependencies) + '\n'
        control.write_text(''.join(lines))
        # The installed library changed; don't carry the native package's checksums into this DEB.
        md5sums = root / 'DEBIAN/md5sums'
        if md5sums.exists():
            md5sums.unlink()
        subprocess.run(['dpkg-deb', '-Zzstd', '-b', str(root), str(destination)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('native_deb')
    parser.add_argument('portable_library')
    parser.add_argument('destination')
    args = parser.parse_args()
    prepare(args.native_deb, args.portable_library, args.destination)


if __name__ == '__main__':
    main()
