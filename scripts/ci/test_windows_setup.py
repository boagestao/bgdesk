"""Exercise SDK reuse and installation without requiring a Windows compiler."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


SETUP = Path(__file__).resolve().parents[1] / 'setup-windows-build.sh'
LAUNCHER = '''#!/bin/bash
if [[ "$1" == --version ]]; then
  echo 'Preparing Flutter tools...'
  echo 'Flutter 3.47.2 • channel stable'
else
  printf '%s\\n' "$*" >> "$TEST_FLUTTER_EVENTS"
fi
'''


class WindowsSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sdk = self.root / 'hosted toolcache' / 'flutter'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, BGDESK_SETUP_SCRIPT=str(SETUP),
                        FLUTTER_DIR=str(self.sdk), FLUTTER_VERSION='3.47.2',
                        TEMP_DIR=str(self.root / 'temp'),
                        TEST_FLUTTER_EVENTS=str(self.root / 'events'),
                        TEST_CURL_LOG=str(self.root / 'downloads'),
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'])
        curl = self.bin / 'curl'
        curl.write_text('''#!/bin/bash
echo download >> "$TEST_CURL_LOG"
[[ -n "${TEST_FLUTTER_ZIP:-}" ]] || exit 99
while [[ $# -gt 0 ]]; do
  if [[ "$1" == -o ]]; then cp "$TEST_FLUTTER_ZIP" "$2"; exit; fi
  shift
done
exit 98
''')
        curl.chmod(0o755)

    def run_install(self):
        return subprocess.run(['bash', '-c', 'source "$BGDESK_SETUP_SCRIPT"; '
                               'REINSTALL_FLUTTER="${TEST_FORCE_FLUTTER:-0}"; install_flutter'],
                              env=self.env, text=True, capture_output=True)

    def installed_sdk(self):
        (self.sdk / 'bin').mkdir(parents=True)
        (self.sdk / 'bin/flutter.bat').write_text('@echo off\n')
        (self.sdk / 'bin/flutter').write_text(LAUNCHER)
        for path in (self.sdk / 'bin').iterdir():
            path.chmod(0o644)

    def test_existing_sdk_with_non_executable_batch_and_bootstrap_output_is_reused(self):
        self.installed_sdk()
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / 'downloads').exists())
        self.assertEqual((self.root / 'events').read_text().splitlines(),
                         ['config --no-analytics', 'precache --windows'])

    def test_windows_sdk_zip_is_installed_at_custom_path_and_download_removed(self):
        archive = self.root / 'sdk.zip'
        with zipfile.ZipFile(archive, 'w') as handle:
            handle.writestr('flutter/bin/flutter', LAUNCHER)
            handle.writestr('flutter/bin/flutter.bat', '@echo off\n')
        self.env['TEST_FLUTTER_ZIP'] = str(archive)
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.sdk / 'bin/flutter.bat').is_file())
        self.assertEqual(list((self.root / 'temp').iterdir()), [])

    def test_invalid_download_preserves_existing_sdk(self):
        self.installed_sdk()
        original = (self.sdk / 'bin/flutter').read_bytes()
        archive = self.root / 'bad-sdk.zip'
        with zipfile.ZipFile(archive, 'w') as handle:
            handle.writestr('flutter/README', 'incomplete SDK')
        self.env.update(TEST_FLUTTER_ZIP=str(archive), TEST_FORCE_FLUTTER='1')
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SDK Flutter Windows completo', result.stderr)
        self.assertEqual((self.sdk / 'bin/flutter').read_bytes(), original)

    def test_ci_reconciles_all_x64_dependencies_even_if_host_ffmpeg_is_cached(self):
        vcpkg = self.root / 'vcpkg'
        header = vcpkg / 'installed/x64-windows-static/include/libavutil/attributes.h'
        header.parent.mkdir(parents=True)
        header.touch()
        bash = self.bin / 'bash'
        bash.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_CURL_LOG"\n')
        bash.chmod(0o755)
        env = dict(self.env, VCPKG_ROOT=str(vcpkg))
        def reconcile():
            return subprocess.run(['/bin/bash', '-c',
                'source "$BGDESK_SETUP_SCRIPT"; install_vcpkg_dependencies'],
                env=env, text=True, capture_output=True)
        self.assertEqual(reconcile().returncode, 0)
        self.assertFalse((self.root / 'downloads').exists())
        env['BGDESK_VERIFY_VCPKG_MANIFEST'] = '1'
        result = reconcile()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('install-vcpkg.sh', (self.root / 'downloads').read_text())


if __name__ == '__main__':
    unittest.main()
