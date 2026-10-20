"""Exercise package staging and pacman's actual callback interface."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ArchPackageTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == 'darwin' and not shutil.which('ginstall'),
                     'GNU install is provided by the actual Arch packaging container')
    def test_staging_preserves_the_compiled_bundle_and_installs_owned_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            bundle = stage / 'bundle'
            (bundle / 'lib').mkdir(parents=True)
            (bundle / 'data').mkdir()
            (bundle / 'bgdesk').write_bytes(b'compiled executable')
            (bundle / 'bgdesk').chmod(0o755)
            (bundle / 'lib/libbgdesk.so').write_bytes(b'compiled library')
            (bundle / 'lib/alias.so').symlink_to('libbgdesk.so')
            (bundle / 'data/assets').write_bytes(b'Flutter assets')
            for name in ('bgdesk.service', 'bgdesk.desktop', 'bgdesk-link.desktop',
                         '128x128@2x.png', 'scalable.svg', 'startwm.sh'):
                shutil.copyfile(ROOT / 'res' / name, stage / name)
            shutil.copyfile(ROOT / 'res/arch/bgdesk.pam', stage / 'bgdesk.pam')
            for edition in ('cliente', 'suporte'):
                output = stage / edition
                result = subprocess.run(['bash', '-euc',
                    'if command -v ginstall >/dev/null; then install() { ginstall "$@"; }; sed() { gsed "$@"; }; fi; source "$1"; package; printf "%s" "$pkgname"', 'stage',
                    str(ROOT / 'res/arch/PKGBUILD')], check=True, text=True,
                    capture_output=True, env=dict(os.environ, BGDESK_EDITION=edition,
                    BGDESK_VERSION='1.5.2', startdir=str(stage), pkgdir=str(output)))
                self.assertEqual(result.stdout, f'bgdesk-{edition}')
                app = output / 'usr/share/bgdesk'
                self.assertEqual((app / 'bgdesk').read_bytes(), b'compiled executable')
                self.assertTrue(os.access(app / 'bgdesk', os.X_OK))
                self.assertEqual(os.readlink(app / 'lib/alias.so'), 'libbgdesk.so')
                self.assertEqual(os.readlink(output / 'usr/bin/bgdesk'), '/usr/share/bgdesk/bgdesk')
                service = (output / 'usr/lib/systemd/system/bgdesk.service').read_text()
                self.assertIn('ExecStart=/usr/bin/bgdesk --service', service)
                self.assertIn('ExecStop=/usr/bin/pkill ', service)
                self.assertIn('WantedBy=multi-user.target', service)
                self.assertTrue((output / 'usr/share/applications/bgdesk.desktop').is_file())
                self.assertFalse((output / 'etc/systemd/system/bgdesk.service').exists())

    def callbacks(self, live, *callbacks):
        # Simulate the systemd runtime marker; never operate the host's service.
        script = '''
          source "$1"; shift
          systemctl() { printf '%s\\n' "$*"; }
          [() {
            if [[ "$#" == 3 && "$1" == -d && "$2" == /run/systemd/system ]]; then
              [[ "$LIVE" == 1 ]]
            else builtin [ "$@"; fi
          }
          for callback in "$@"; do "$callback"; done
        '''
        return subprocess.check_output(['bash', '-euc', script, 'callbacks',
            str(ROOT / 'res/arch/bgdesk.install'), *callbacks], text=True,
            env=dict(os.environ, LIVE=str(int(live)))).splitlines()

    def test_install_enables_and_starts_unattended_service(self):
        self.assertEqual(self.callbacks(True, 'post_install'), [
            'enable bgdesk.service', 'daemon-reload', 'start bgdesk.service'])

    def test_offline_install_enables_for_next_boot_without_bus_commands(self):
        self.assertEqual(self.callbacks(False, 'post_install'), ['enable bgdesk.service'])
        self.assertEqual(self.callbacks(False, 'post_upgrade'), [])
        self.assertEqual(self.callbacks(False, 'pre_remove', 'post_remove'), ['disable bgdesk.service'])

    def test_upgrade_preserves_stopped_services_and_remove_disables(self):
        self.assertEqual(self.callbacks(True, 'post_upgrade'), [
            'daemon-reload', 'try-restart bgdesk.service'])
        self.assertEqual(self.callbacks(True, 'pre_remove', 'post_remove'), [
            'stop bgdesk.service', 'disable bgdesk.service', 'daemon-reload'])


if __name__ == '__main__':
    unittest.main()
