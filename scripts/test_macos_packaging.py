#!/usr/bin/env python3
"""macOS packaging regressions using real ad hoc signing and a small Mach-O app.

Run: python3 scripts/test_macos_packaging.py
Notarization orchestration uses fake Apple responses; signature/DMG roundtrips
use real codesign, hdiutil and ditto. No notarization upload is required.
"""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "scripts/package-macos.sh"
SIGN = ROOT / ".github/scripts/sign-macos-app.sh"
RELEASE_ENTITLEMENTS = ROOT / "flutter/macos/Runner/Release.entitlements"


@unittest.skipUnless(sys.platform == "darwin", "Requires macOS signing tools")
class MacOSPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bgdesk-packaging-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        dotenv = self.base / "empty.env"
        dotenv.write_text("")
        self.env = dict(
            os.environ, MACOS_CODESIGN_IDENTITY="-", MACOS_TEAM_ID="3Z7C3Q7NMT",
            BGDESK_DOTENV_FILE=str(dotenv),
        )
        for key in ("MACOS_P12_FILE", "MACOS_P12_PASSWORD",
                    "MACOS_NOTARY_APPLE_ID", "MACOS_NOTARY_PASSWORD",
                    "MACOS_CODESIGN_KEYCHAIN"):
            self.env.pop(key, None)
        self.bin = self.base / "bin"
        self.bin.mkdir()

    def run_command(self, args, *, env=None, ok=True):
        result = subprocess.run(
            [str(arg) for arg in args], env=env or self.env,
            capture_output=True, text=True,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def fake_tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
        path.chmod(0o755)
        return dict(self.env, PATH=str(self.bin) + os.pathsep + os.environ["PATH"])

    def make_app(self):
        app = self.base / "BGDesk.app"
        contents = app / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        (contents / "Resources").mkdir()
        info = {
            "CFBundleExecutable": "BGDesk", "CFBundleIdentifier": "br.com.boagestao.bgdesk",
            "CFBundleName": "BGDesk", "CFBundlePackageType": "APPL", "CFBundleVersion": "1",
        }
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        source = self.base / "main.c"
        source.write_text("int main(void) { return 0; }\n")
        self.run_command(["xcrun", "clang", source, "-o", contents / "MacOS/BGDesk"])
        shutil.copy2(contents / "MacOS/BGDesk", contents / "MacOS/service")
        (contents / "Resources/flutter-build-stamp.txt").write_text("test stamp\n")

        framework = contents / "Frameworks/Test.framework"
        version = framework / "Versions/A"
        (version / "Resources").mkdir(parents=True)
        library = self.base / "library.c"
        library.write_text("int bgdesk_test(void) { return 42; }\n")
        self.run_command(["xcrun", "clang", "-dynamiclib", library, "-o", version / "Test"])
        info.update(CFBundleExecutable="Test", CFBundleIdentifier="br.com.boagestao.test",
                    CFBundlePackageType="FMWK", CFBundleName="Test")
        (version / "Resources/Info.plist").write_bytes(plistlib.dumps(info))
        (framework / "Versions/Current").symlink_to("A")
        (framework / "Test").symlink_to("Versions/Current/Test")
        (framework / "Resources").symlink_to("Versions/Current/Resources")
        return app

    def mount_image(self, image):
        mount = self.base / "mounted"
        mount.mkdir()
        self.run_command(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", mount, image])
        self.addCleanup(self.run_command, ["hdiutil", "detach", mount, "-quiet"])
        return mount

    def test_signed_dmg_roundtrip_and_tampering_detection(self):
        app = self.make_app()
        archive = self.base / "bgdesk-local.dmg"
        self.run_command(["bash", PACKAGE, "--local", app, archive])
        self.run_command(["hdiutil", "verify", archive])
        self.run_command(["codesign", "--verify", "--strict", archive])
        mount = self.mount_image(archive)
        self.assertTrue(os.statvfs(mount).f_flag & os.ST_RDONLY)
        self.assertEqual(os.readlink(mount / "Applications"), "/Applications")
        extracted = self.base / "extracted"
        delivered = extracted / "BGDesk.app"
        self.run_command(["ditto", mount / "BGDesk.app", delivered])
        for relative in ("Versions/Current", "Test", "Resources"):
            self.assertTrue((delivered / "Contents/Frameworks/Test.framework" / relative).is_symlink())
        self.run_command(["codesign", "--verify", "--deep", "--strict", delivered])
        self.run_command(["codesign", "--verify", "--strict", delivered / "Contents/MacOS/service"])
        entitlements = self.run_command(["codesign", "-d", "--entitlements", "-", "--xml", delivered])
        actual = plistlib.loads(entitlements.stdout.encode())
        self.assertTrue(actual["com.apple.security.device.audio-input"])
        self.assertFalse(actual.get("com.apple.security.get-task-allow", False))
        (delivered / "Contents/Resources/flutter-build-stamp.txt").write_text("changed\n")
        self.run_command(["codesign", "--verify", "--deep", "--strict", delivered], ok=False)

    def test_distribution_rejects_development_certificate(self):
        env = self.fake_tool("security", '''cat <<'EOF'
  1) 1111111111111111111111111111111111111111 "Apple Development: Test (PERSONALID)"
     1 valid identities found
EOF''')
        env["MACOS_CODESIGN_IDENTITY"] = "1111111111111111111111111111111111111111"
        result = self.run_command(["bash", PACKAGE, "--check"], env=env, ok=False)
        self.assertIn("Developer ID Application", result.stderr)

    def test_distribution_rejects_wrong_team(self):
        env = self.fake_tool("security", '''cat <<'EOF'
  1) 1111111111111111111111111111111111111111 "Developer ID Application: Test (OTHERTTEAM)"
     1 valid identities found
EOF''')
        env.pop("MACOS_CODESIGN_IDENTITY")
        result = self.run_command(["bash", PACKAGE, "--check"], env=env, ok=False)
        self.assertIn("3Z7C3Q7NMT", result.stderr)

    def test_missing_notary_profile_preserves_existing_archive(self):
        env = self.fake_tool("security", '''cat <<'EOF'
  1) 1111111111111111111111111111111111111111 "Developer ID Application: Test (3Z7C3Q7NMT)"
     1 valid identities found
EOF''')
        self.fake_tool("xcrun", 'if [[ "$1" == "--find" ]]; then exit 0; fi\nexit 1')
        env.pop("MACOS_CODESIGN_IDENTITY")
        env["MACOS_NOTARY_PROFILE"] = "bgdesk-test-missing-profile"
        archive = self.base / "release.dmg"
        archive.write_bytes(b"previous release")
        result = self.run_command(["bash", PACKAGE, self.base / "Missing.app", archive], env=env, ok=False)
        self.assertIn("bgdesk-test-missing-profile", result.stderr)
        self.assertEqual(archive.read_bytes(), b"previous release")

    def test_dotenv_notary_profile_name_is_used(self):
        env = self.fake_tool("security", '''cat <<'EOF'
  1) 1111111111111111111111111111111111111111 "Developer ID Application: Test (3Z7C3Q7NMT)"
     1 valid identities found
EOF''')
        self.fake_tool("xcrun", 'if [[ "$1" == "--find" ]]; then exit 0; fi\nexit 1')
        env.pop("MACOS_CODESIGN_IDENTITY", None)
        env.pop("MACOS_NOTARY_PROFILE", None)
        dotenv = self.base / "notary.env"
        dotenv.write_text("MACOS_NOTARY_PROFILE=perfil-do-dotenv\n")
        env["BGDESK_DOTENV_FILE"] = str(dotenv)
        result = self.run_command(["bash", PACKAGE, "--check"], env=env, ok=False)
        self.assertIn("perfil-do-dotenv", result.stderr)
        self.assertNotIn("bgdesk-notary", result.stderr)

    def test_environment_notary_profile_overrides_dotenv(self):
        env = self.fake_tool("security", '''cat <<'EOF'
  1) 1111111111111111111111111111111111111111 "Developer ID Application: Test (3Z7C3Q7NMT)"
     1 valid identities found
EOF''')
        self.fake_tool("xcrun", 'if [[ "$1" == "--find" ]]; then exit 0; fi\nexit 1')
        env.pop("MACOS_CODESIGN_IDENTITY", None)
        dotenv = self.base / "notary.env"
        dotenv.write_text("MACOS_NOTARY_PROFILE=perfil-do-dotenv\n")
        env["BGDESK_DOTENV_FILE"] = str(dotenv)
        env["MACOS_NOTARY_PROFILE"] = "perfil-do-ambiente"
        result = self.run_command(["bash", PACKAGE, "--check"], env=env, ok=False)
        self.assertIn("perfil-do-ambiente", result.stderr)
        self.assertNotIn("perfil-do-dotenv", result.stderr)

    def test_local_archive_requires_distinct_filename(self):
        app = self.base / "BGDesk.app"
        (app / "Contents/MacOS").mkdir(parents=True)
        result = self.run_command(["bash", PACKAGE, "--local", app, self.base / "release.dmg"], ok=False)
        self.assertIn("-local.dmg", result.stderr)

    def test_debug_entitlement_is_rejected(self):
        app = self.make_app()
        entitlements = plistlib.loads(RELEASE_ENTITLEMENTS.read_bytes())
        entitlements["com.apple.security.get-task-allow"] = True
        debug = self.base / "debug.plist"
        debug.write_bytes(plistlib.dumps(entitlements))
        result = self.run_command(["bash", SIGN, app, "-", debug], ok=False)
        self.assertIn("must not contain com.apple.security.get-task-allow", result.stderr)

    def mock_distribution_services(self):
        """Test publication gates independently of Apple's external services."""
        env = self.fake_tool("security", '''cat <<'EOF'
  1) 1111111111111111111111111111111111111111 "Developer ID Application: Test (3Z7C3Q7NMT)"
     1 valid identities found
EOF''')
        self.fake_tool("codesign", '''
if [[ "$1" == "-d" ]]; then cat "$TEST_ENTITLEMENTS"; fi
# Parse explicit certificate requirements with Apple's real parser.
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "-R" ]]; then
    /usr/bin/csreq -r "$2" -t >/dev/null
    shift
  fi
  shift
done
''')
        self.fake_tool("xcrun", '''
if [[ "$1" == "--find" ]]; then exit 0; fi
printf '%s %s\n' "$1" "$2" >>"$TEST_EVENTS"
case "$1 $2" in
  'notarytool history') echo '{"history": []}' ;;
  'notarytool submit')
    printf '{"id":"test-submission","status":"%s"}\n' "$TEST_NOTARY_STATUS" ;;
  'notarytool log') echo '{"issues": []}' >"${@: -1}" ;;
  'stapler staple'|'stapler validate')
    attempt_file="$TEST_EVENTS.$2.attempts"
    attempts=0
    [[ ! -f "$attempt_file" ]] || attempts=$(cat "$attempt_file")
    attempts=$((attempts + 1))
    echo "$attempts" > "$attempt_file"
    failures="${TEST_STAPLE_FAILURES:-0}"
    [[ "$2" == staple ]] || failures="${TEST_VALIDATE_FAILURES:-0}"
    if [[ "$attempts" -le "$failures" ]]; then
      echo 'NSURLErrorDomain Code=-1005: The network connection was lost.' >&2
      exit "${TEST_STAPLER_EXIT:-68}"
    fi
    if [[ "$2" == staple ]]; then
      xattr -w com.bgdesk.test-notary-ticket accepted "$3"
    else
      xattr -p com.bgdesk.test-notary-ticket "$3" >/dev/null
    fi ;;
  *) exit 99 ;;
esac
''')
        self.fake_tool("spctl", '''
echo gatekeeper >>"$TEST_EVENTS"
exit "$TEST_GATEKEEPER_EXIT"
''')
        env.pop("MACOS_CODESIGN_IDENTITY")
        env.update(TEST_ENTITLEMENTS=str(RELEASE_ENTITLEMENTS),
                   TEST_EVENTS=str(self.base / "events"),
                   TEST_NOTARY_STATUS="Accepted", TEST_GATEKEEPER_EXIT="0")
        app = self.base / "BGDesk.app"
        (app / "Contents/MacOS").mkdir(parents=True)
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "br.com.boagestao.bgdesk",
        }))
        archive = self.base / "release.dmg"
        archive.write_bytes(b"previous release")
        return env, app, archive

    def test_rejected_notarization_does_not_publish(self):
        env, app, archive = self.mock_distribution_services()
        env["TEST_NOTARY_STATUS"] = "Invalid"
        self.run_command(["bash", PACKAGE, app, archive], env=env, ok=False)
        self.assertEqual(archive.read_bytes(), b"previous release")
        self.assertTrue((self.base / "release.notary-log.json").exists())
        self.assertNotIn("stapler staple", (self.base / "events").read_text())

    def test_gatekeeper_rejection_does_not_publish(self):
        env, app, archive = self.mock_distribution_services()
        env["TEST_GATEKEEPER_EXIT"] = "3"
        self.run_command(["bash", PACKAGE, app, archive], env=env, ok=False)
        self.assertEqual(archive.read_bytes(), b"previous release")
        self.assertIn("gatekeeper", (self.base / "events").read_text())

    def test_accepted_ticket_is_on_final_dmg(self):
        env, app, archive = self.mock_distribution_services()
        self.run_command(["bash", PACKAGE, app, archive], env=env)
        ticket = self.run_command(["xattr", "-p", "com.bgdesk.test-notary-ticket", archive])
        self.assertEqual(ticket.stdout.strip(), "accepted")
        mount = self.mount_image(archive)
        self.assertTrue((mount / "BGDesk.app").is_dir())
        self.assertEqual(os.readlink(mount / "Applications"), "/Applications")
        events = (self.base / "events").read_text().splitlines()
        self.assertEqual(events, ["notarytool history", "notarytool submit", "stapler staple",
                                  "stapler validate", "gatekeeper", "gatekeeper"])

    def test_stapler_recovers_from_network_loss_without_resubmitting_notarization(self):
        env, app, archive = self.mock_distribution_services()
        env.update(TEST_STAPLE_FAILURES='1', TEST_VALIDATE_FAILURES='1')
        self.fake_tool('sleep', 'echo "$1" >> "$TEST_EVENTS.sleeps"')
        self.run_command(["bash", PACKAGE, app, archive], env=env)
        events = (self.base / 'events').read_text().splitlines()
        self.assertEqual(events.count('notarytool submit'), 1)
        self.assertEqual(events.count('stapler staple'), 2)
        self.assertEqual(events.count('stapler validate'), 2)
        self.assertEqual((self.base / 'events.sleeps').read_text().splitlines(), ['5', '5'])
        ticket = self.run_command(['xattr', '-p', 'com.bgdesk.test-notary-ticket', archive])
        self.assertEqual(ticket.stdout.strip(), 'accepted')

    def test_persistent_stapler_network_failure_is_bounded_and_preserves_previous_dmg(self):
        env, app, archive = self.mock_distribution_services()
        env['TEST_STAPLE_FAILURES'] = '99'
        self.fake_tool('sleep', 'echo "$1" >> "$TEST_EVENTS.sleeps"')
        result = self.run_command(["bash", PACKAGE, app, archive], env=env, ok=False)
        self.assertEqual(result.returncode, 68)
        self.assertEqual(archive.read_bytes(), b'previous release')
        events = (self.base / 'events').read_text().splitlines()
        self.assertEqual(events.count('stapler staple'), 5)
        self.assertEqual(events.count('notarytool submit'), 1)
        self.assertNotIn('gatekeeper', events)
        self.assertEqual((self.base / 'events.sleeps').read_text().splitlines(), ['5', '10', '20', '40'])

    def test_revoked_ticket_is_not_retried_or_published(self):
        env, app, archive = self.mock_distribution_services()
        env.update(TEST_STAPLE_FAILURES='99', TEST_STAPLER_EXIT='77')
        self.fake_tool('sleep', 'echo "$1" >> "$TEST_EVENTS.sleeps"')
        result = self.run_command(["bash", PACKAGE, app, archive], env=env, ok=False)
        self.assertEqual(result.returncode, 77)
        self.assertEqual(archive.read_bytes(), b'previous release')
        events = (self.base / 'events').read_text().splitlines()
        self.assertEqual(events.count('stapler staple'), 1)
        self.assertNotIn('gatekeeper', events)
        self.assertFalse((self.base / 'events.sleeps').exists())

    def test_installers_reject_invalid_image_before_installing(self):
        env = self.fake_tool("curl", '''
printf '%s\n' "$*" >"$TEST_DOWNLOAD"
touch "${@: -1}"
''')
        self.fake_tool("codesign", "exit 1")
        self.fake_tool("sudo", 'touch "$TEST_INSTALLED"; exit 99')
        self.fake_tool("hdiutil", 'touch "$TEST_MOUNTED"; exit 99')
        self.fake_tool("uname", 'if [[ "$1" == "-m" ]]; then echo "$TEST_ARCH"; else echo Darwin; fi')
        env.update(TEST_DOWNLOAD=str(self.base / "download"),
                   TEST_INSTALLED=str(self.base / "installed"),
                   TEST_MOUNTED=str(self.base / "mount-called"), TMPDIR=str(self.base))
        for arch, download_arch in (("arm64", "aarch64"), ("x86_64", "x86_64")):
            env["TEST_ARCH"] = arch
            for script, mode in (("install.sh", "suporte"), ("install-client.sh", "cliente")):
                with self.subTest(script=script, arch=arch):
                    self.run_command(["bash", ROOT / "installers" / script], env=env, ok=False)
                    self.assertIn(f"bgdesk-{mode}-{download_arch}.dmg", (self.base / "download").read_text())
                    self.assertFalse((self.base / "installed").exists())
                    self.assertFalse((self.base / "mount-called").exists())

    def test_dotenv_is_gitignored(self):
        result = self.run_command(["git", "-C", ROOT, "check-ignore", "-q", ".env"])
        self.assertEqual(result.returncode, 0)

    def test_certificate_inside_repository_is_rejected(self):
        env = dict(self.env)
        env.pop("MACOS_CODESIGN_IDENTITY")
        env["MACOS_P12_FILE"] = str(ROOT / "DeveloperId.p12")
        env["MACOS_P12_PASSWORD"] = "senha-de-teste"
        result = self.run_command(["bash", PACKAGE, "--check"], env=env, ok=False)
        self.assertIn("dentro do projeto", result.stderr)
        self.assertNotIn("senha-de-teste", result.stdout + result.stderr)
        self.assertFalse((ROOT / "DeveloperId.p12").exists())

    def test_missing_p12_password_names_dotenv(self):
        certificate_dir = self.base / "Certificados"
        certificate_dir.mkdir()
        (certificate_dir / "DeveloperId.p12").write_bytes(b"fora-do-repositorio")
        env = dict(self.env)
        env.pop("MACOS_CODESIGN_IDENTITY")
        env["MACOS_P12_FILE"] = str(certificate_dir / "DeveloperId.p12")
        result = self.run_command(["bash", PACKAGE, "--check"], env=env, ok=False)
        self.assertIn(".env", result.stderr)
        self.assertEqual((certificate_dir / "DeveloperId.p12").read_bytes(), b"fora-do-repositorio")

    def test_dotenv_reads_certificate_in_place_without_printing_password(self):
        certificate_dir = self.base / "Certificados Locais"
        certificate_dir.mkdir()
        p12 = certificate_dir / "DeveloperId.p12"
        p12.write_bytes(b"arquivo-original")
        dotenv = self.base / "signing.env"
        dotenv.write_text(
            'MACOS_P12_FILE="' + str(p12) + '"\n'
            "MACOS_P12_PASSWORD='senha-que-nao-pode-aparecer'\n"
        )
        env = self.fake_tool("security", '''
printf '%s\\n' "$*" >> "$TEST_SECURITY_LOG"
if [[ "$1" == "list-keychains" && "$#" == 3 ]]; then
  echo '    "/original keychains/login.keychain-db"'
  echo '    "/original/system.keychain-db"'
fi
if [[ "$1" == "find-identity" ]]; then
  echo '  1) 1111111111111111111111111111111111111111 "Developer ID Application: Test (3Z7C3Q7NMT)"'
fi
exit 0
''')
        self.fake_tool("xcrun", '''
if [[ "$1" == "--find" || "$1 $2" == "notarytool history" ]]; then
  [[ "$1" == "--find" ]] && exit 0
  echo '{"history":[]}'
  exit 0
fi
exit 0
''')
        self.fake_tool("codesign", 'exit "${TEST_SIGNATURE_PROBE_EXIT:-0}"')
        env.pop("MACOS_CODESIGN_IDENTITY")
        env["BGDESK_DOTENV_FILE"] = str(dotenv)
        env["TEST_SECURITY_LOG"] = str(self.base / "security.log")
        result = self.run_command(["bash", PACKAGE, "--check"], env=env)
        self.assertNotIn("senha-que-nao-pode-aparecer", result.stdout + result.stderr)
        self.assertIn(str(p12), result.stdout)
        log = (self.base / "security.log").read_text()
        self.assertIn("import " + os.path.realpath(p12), log)
        restore = 'list-keychains -d user -s /original keychains/login.keychain-db /original/system.keychain-db'
        self.assertIn(restore, log)
        self.assertIn('Assinatura de teste validada', result.stdout)
        self.assertEqual(p12.read_bytes(), b"arquivo-original")
        # A private-key access failure must also restore the original search list.
        env['TEST_SIGNATURE_PROBE_EXIT'] = '42'
        self.run_command(["bash", PACKAGE, "--check"], env=env, ok=False)
        self.assertEqual((self.base / "security.log").read_text().count(restore), 2)

    def test_imported_distribution_certificate_is_rejected(self):
        certificate_dir = self.base / "Certificados"
        certificate_dir.mkdir()
        (certificate_dir / "DeveloperId.p12").write_bytes(b"distribution")
        env = self.fake_tool("security", '''
if [[ "$1" == "find-identity" ]]; then
  echo '  1) 1111111111111111111111111111111111111111 "Apple Distribution: Test (3Z7C3Q7NMT)"'
fi
exit 0
''')
        env.pop("MACOS_CODESIGN_IDENTITY")
        env["MACOS_P12_FILE"] = str(certificate_dir / "DeveloperId.p12")
        env["MACOS_P12_PASSWORD"] = "senha-de-teste"
        result = self.run_command(["bash", PACKAGE, "--check"], env=env, ok=False)
        self.assertIn("Apple Distribution", result.stderr)
        self.assertNotIn("senha-de-teste", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
