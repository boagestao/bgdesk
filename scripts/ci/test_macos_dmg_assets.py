#!/usr/bin/env python3
"""Validate the committed macOS DMG volume icon, background art and packager."""
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "res/macos-dmg"
PACKAGE = ROOT / "scripts/package-macos.sh"
GENERATE = ROOT / "scripts/generate-macos-dmg-assets.py"
BACKGROUND_SIZE = (800, 400)
VOLUME_SIZES = (16, 32, 64, 128, 256, 512, 1024)
LAYOUT_MARKERS = (
    "volume-icon.icns",
    "background.png",
    "background@2x.png",
    "finder-layout.dsstore",
    ".VolumeIcon.icns",
    ".DS_Store",
    ".background",
)


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    return struct.unpack(">II", data[16:24])


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


class MacOSDmgAssetTests(unittest.TestCase):
    def test_brand_svgs_use_the_bgdesk_mark(self):
        volume = (ASSETS / "volume-icon.svg").read_text()
        background = (ASSETS / "background.svg").read_text()
        for blob in (volume, background):
            self.assertIn("#027af2", blob)
            self.assertIn("#0e538c", blob)
        self.assertIn("scale(11.2)", volume)
        self.assertIn("white-drive-tahoe.png", volume)
        self.assertIn("macosicons.com/icon/white-drive-macos-tahoe", volume)
        self.assertIn("Arraste para Aplicativos", background)
        self.assertIn("(200,190)", background)
        self.assertIn("(600,190)", background)

    def test_committed_rasters_match_the_expected_geometry(self):
        self.assertEqual(png_size(ASSETS / "white-drive-tahoe.png"), (1024, 1024))
        self.assertEqual(png_size(ASSETS / "volume-icon.png"), (1024, 1024))
        self.assertEqual(png_size(ASSETS / "background.png"), BACKGROUND_SIZE)
        self.assertEqual(
            png_size(ASSETS / "background@2x.png"),
            (BACKGROUND_SIZE[0] * 2, BACKGROUND_SIZE[1] * 2),
        )
        types = icns_types(ASSETS / "volume-icon.icns")
        self.assertIn(b"ic10", types)
        self.assertIn(b"ic08", types)
        self.assertGreaterEqual(len(types), len(VOLUME_SIZES))
        layout = (ASSETS / "finder-layout.dsstore").read_bytes()
        self.assertGreater(len(layout), 100)
        self.assertTrue(layout.startswith(b"\x00\x00\x00\x01Bud1"))

    def test_packager_installs_the_volume_icon_and_finder_art(self):
        script = PACKAGE.read_text()
        for marker in LAYOUT_MARKERS:
            self.assertIn(marker, script)
        self.assertIn("assert_installer_layout", script)
        self.assertIn("SetFile -a C", script)
        self.assertIn('cp "$assets/finder-layout.dsstore" "$volume/.DS_Store"', script)
        self.assertNotIn("tell application \"Finder\"", script)
        self.assertNotIn("open -a Finder", script)
        self.assertIn(
            'hdiutil attach -readwrite -noverify -noautoopen -nobrowse -mountpoint "$volume"',
            script,
        )
        self.assertNotIn("brew install rcodesign", script)
        self.assertIn('version="0.22.0"', script)
        self.assertIn("apple-codesign-${version}-macos-universal.tar.gz", script)
        self.assertIn("install_rcodesign", script)
        self.assertIn("rcodesign staple", script)
        self.assertGreaterEqual(script.count('mount_point="$work_dir/mounted"'), 2)
        self.assertIn(
            'hdiutil attach -readonly -nobrowse -mountpoint "$mount_point"',
            script,
        )

    @unittest.skipUnless(shutil.which("rsvg-convert"), "rsvg-convert rasterizes the SVG sources")
    def test_committed_rasters_match_regenerated_svgs(self):
        with tempfile.TemporaryDirectory() as temporary:
            dest = Path(temporary)
            for name in ("volume-icon.svg", "white-drive-tahoe.png", "background.svg"):
                shutil.copyfile(ASSETS / name, dest / name)
            subprocess.run(
                [sys.executable, str(GENERATE), "--assets", str(dest)],
                check=True, cwd=str(ROOT), capture_output=True, text=True,
            )
            for name in ("volume-icon.icns", "volume-icon.png"):
                self.assertEqual(
                    (dest / name).read_bytes(), (ASSETS / name).read_bytes(), name,
                )
            self.assertEqual(png_size(dest / "background.png"), BACKGROUND_SIZE)
            self.assertEqual(
                png_size(dest / "background@2x.png"),
                (BACKGROUND_SIZE[0] * 2, BACKGROUND_SIZE[1] * 2),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
