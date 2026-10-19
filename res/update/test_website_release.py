import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import generate_update_metadata as metadata
import website_release as website


class WebsiteReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "update_metadata.rs"
        self.source.write_text(website.KEY_MARKER)
        self.key = self.root / "private.json"
        self.public = self.root / "public"
        self.run_cli("init-key")
        self.artifact = self.root / "bgdesk-1.5.2-aarch64.dmg"
        self.artifact.write_bytes(b"test installer")

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *args, success=True):
        result = subprocess.run([
            sys.executable, str(Path(website.__file__)), *args,
            "--key-file", str(self.key), "--rust-source", str(self.source),
        ], text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def prepare(self, edition="suporte", *, version="1.5.2", extra=(), success=True):
        return self.run_cli(
            "prepare", "--edition", edition, "--version", version,
            "--site-public", str(self.public),
            "--artifact", "macos", "aarch64", "dmg", str(self.artifact),
            *extra, success=success,
        )

    def test_prepares_both_editions_with_valid_signatures_and_hashes(self):
        for edition in ("cliente", "suporte"):
            self.prepare(edition)
            channel = self.public / "updates" / edition
            release = channel / "v1.5.2"
            feed = json.loads((channel / "latest.json").read_text())
            self.assertEqual(os.stat(channel / "latest.json").st_mode & 0o777, 0o644)
            self.assertEqual(feed["url"], f"{website.ORIGIN}/updates/{edition}/v1.5.2/")
            data = json.loads((release / "bgdesk-update.json").read_text())
            self.assertEqual(data["package_id"], f"bgdesk-{edition}")
            self.assertEqual(data["artifacts"][0]["url"], feed["url"] + self.artifact.name)
            self.assertEqual((release / self.artifact.name).read_bytes(), self.artifact.read_bytes())
            self.assertIn(self.artifact.name, (release / "index.html").read_text())
            website.load_key(self.key)
            args = argparse.Namespace(
                metadata=release / "bgdesk-update.json", signature=release / "bgdesk-update.json.sig",
                artifact=[str(release / self.artifact.name)], version="1.5.2", release_id="v1.5.2",
                package_id=f"bgdesk-{edition}", release_base_url=f"{website.ORIGIN}/updates/{edition}",
            )
            metadata.command_verify(args)
            (release / self.artifact.name).write_bytes(b"tampered")
            with self.assertRaises(SystemExit):
                metadata.command_verify(args)
        self.assertEqual(os.stat(self.key).st_mode & 0o777, 0o600)
        self.assertEqual(list(self.public.rglob("private.json")), [])

    def test_failed_release_preserves_latest_and_existing_releases(self):
        self.prepare()
        latest = self.public / "updates/suporte/latest.json"
        original = latest.read_bytes()
        self.prepare(success=False)
        self.prepare(version="1.5.3", extra=("--release-id", "v9.0.0"), success=False)
        self.prepare(version="1.5.3-rc1", success=False)
        self.prepare(version="1.5.3", extra=(
            "--artifact", "macos", "aarch64", "dmg", str(self.artifact),
        ), success=False)
        self.assertEqual(latest.read_bytes(), original)
        self.assertFalse((latest.parent / "v1.5.3").exists())
        self.assertEqual(list(latest.parent.glob(".release-*")), [])

    def test_rejects_wrong_signing_key_and_key_replacement(self):
        self.run_cli("init-key", success=False)
        self.source.write_text(self.source.read_text().replace("public_key:", "wrong_key:"))
        self.prepare(success=False)
        self.assertFalse((self.public / "updates/suporte/latest.json").exists())

    def test_windows_exe_and_msi_selectors_are_kept_separate(self):
        exe = self.root / "bgdesk.exe"
        msi = self.root / "bgdesk.msi"
        exe.write_bytes(b"exe")
        msi.write_bytes(b"msi")
        self.prepare(extra=(
            "--artifact", "windows", "x86_64", "exe", str(exe),
            "--artifact", "windows", "x86_64", "msi", str(msi),
        ))
        data = json.loads((self.public / "updates/suporte/v1.5.2/bgdesk-update.json").read_text())
        self.assertEqual({item["format"] for item in data["artifacts"]}, {"exe", "msi", "dmg"})


if __name__ == "__main__":
    unittest.main()
