#!/usr/bin/env python3
"""Rasterize the committed macOS DMG SVGs into PNG and ICNS files."""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "res/macos-dmg"
VOLUME_SVG = ASSETS / "volume-icon.svg"
BACKGROUND_SVG = ASSETS / "background.svg"
ICNS_TYPES = (
    (b"icp4", 16),
    (b"icp5", 32),
    (b"icp6", 64),
    (b"ic07", 128),
    (b"ic08", 256),
    (b"ic09", 512),
    (b"ic10", 1024),
    (b"ic11", 32),
    (b"ic12", 64),
    (b"ic13", 256),
    (b"ic14", 512),
)
BACKGROUND_SIZE = (800, 400)
WINDOW_BOUNDS = (200, 120, 800, 400)
ICON_SIZE = 128
APP_ICON_POSITION = (200, 190)
APPLICATIONS_ICON_POSITION = (600, 190)


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def icns_types(path: Path) -> list[bytes]:
    data = path.read_bytes()
    if data[:4] != b"icns":
        raise ValueError(f"{path} is not an ICNS")
    declared = struct.unpack(">I", data[4:8])[0]
    if declared != len(data):
        raise ValueError(f"{path} has a truncated ICNS header")
    offset = 8
    found = []
    while offset + 8 <= len(data):
        ostype = data[offset:offset + 4]
        size = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        if size < 8 or offset + size > len(data):
            raise ValueError(f"{path} has a truncated ICNS entry")
        found.append(ostype)
        offset += size
    if offset != len(data):
        raise ValueError(f"{path} has leftover ICNS bytes")
    return found


def write_icns(png_by_size: dict[int, bytes], destination: Path) -> None:
    entries = []
    for ostype, size in ICNS_TYPES:
        png = png_by_size[size]
        entries.append(ostype + struct.pack(">I", 8 + len(png)) + png)
    body = b"".join(entries)
    destination.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def rsvg_convert(svg: Path, png: Path, width: int, height: int, *, transparent: bool) -> None:
    command = [
        "rsvg-convert", "--width", str(width), "--height", str(height),
        "--output", str(png), str(svg),
    ]
    if transparent:
        command[1:1] = ["--background-color", "none"]
    subprocess.run(command, check=True)
    if png_size(png) != (width, height):
        raise RuntimeError(f"{png} was written with the wrong size")


def generate(assets: Path = ASSETS) -> dict[str, Path]:
    volume_svg = assets / VOLUME_SVG.name
    background_svg = assets / BACKGROUND_SVG.name
    png_by_size = {}
    preview = assets / "volume-icon.png"
    for size in sorted({item[1] for item in ICNS_TYPES}):
        png = preview if size == 1024 else assets / f"volume-icon-{size}.png"
        rsvg_convert(volume_svg, png, size, size, transparent=True)
        png_by_size[size] = png.read_bytes()
        if png != preview:
            png.unlink()
    icns = assets / "volume-icon.icns"
    write_icns(png_by_size, icns)

    background = assets / "background.png"
    background_2x = assets / "background@2x.png"
    rsvg_convert(background_svg, background, *BACKGROUND_SIZE, transparent=False)
    rsvg_convert(
        background_svg, background_2x,
        BACKGROUND_SIZE[0] * 2, BACKGROUND_SIZE[1] * 2, transparent=False,
    )
    return {
        "volume_icon": icns,
        "volume_preview": assets / "volume-icon.png",
        "background": background,
        "background_2x": background_2x,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ASSETS)
    args = parser.parse_args()
    written = generate(args.assets)
    for path in written.values():
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
