#!/usr/bin/env python3
"""Validate and stage unattended Wayland capture for every native Linux package."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', help='Compiled Flutter bundle or native executable directory')
    parser.add_argument('--prepare', action='store_true', help='Build the pinned library if missing')
    parser.add_argument('--root', help='Package staging root')
    parser.add_argument('--control', help='Debian control file to add runtime dependencies to')
    args = parser.parse_args()
    if args.control and not args.root:
        parser.error('--control requires --root')
    payload = str(Path(args.bundle).resolve())
    if args.prepare:
        build.prepare_drm_bundle(payload)
    else:
        build.validated_bundle_drmtap(payload)
    if args.root:
        build.stage_bundle_drmtap(payload, args.root)
    if args.control:
        build.add_drm_deb_dependencies(args.control)


if __name__ == '__main__':
    main()
