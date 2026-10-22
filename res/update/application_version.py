"""BGDesk stable revisions; keep ordering in sync with src/update_source.rs."""
import re


def parse_version(version):
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([1-9][0-9]*))?", version)
    if not match:
        raise ValueError(f"Invalid BGDesk version: {version}")
    parts = tuple(int(part or 0) for part in match.groups())
    if not any(parts[:3]) or any(part > 65535 for part in parts):
        raise ValueError(f"Invalid BGDesk version: {version}")
    return parts


def base_version(version):
    return '.'.join(map(str, parse_version(version)[:3]))


def package_version(version):
    """Numeric native package version (Inno/RPM/Arch/macOS), distinct from build ID."""
    return '.'.join(map(str, parse_version(version)))


def stamp_macos_bundle(plist_path, version):
    """Keep Apple's three-number marketing version and bind the full revision."""
    import plistlib
    from pathlib import Path
    path = Path(plist_path)
    info = plistlib.loads(path.read_bytes())
    info['CFBundleShortVersionString'] = base_version(version)
    info['BGDeskApplicationVersion'] = version
    path.write_bytes(plistlib.dumps(info))


if __name__ == '__main__':
    import sys
    # Also validates the input when used by shell packaging entrypoints.
    print(package_version(sys.argv[1]))
