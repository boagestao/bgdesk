import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('sign_windows', Path(__file__).with_name('sign-windows.py'))
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


class WindowsSigningTests(unittest.TestCase):
    def test_hung_command_is_terminated_and_reports_the_phase(self):
        with patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaisesRegex(RuntimeError, 'timestamp: timed out'):
                signing.run_phase('timestamp', [sys.executable, '-c', 'import time; time.sleep(10)'], timeout=0.1)

    def test_commands_receive_closed_stdin_and_never_echo_password_arguments(self):
        result = subprocess.CompletedProcess([], 1, 'private-sentinel', 'failed')
        with patch.object(signing.subprocess, 'run', return_value=result) as command, \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            with self.assertRaisesRegex(RuntimeError, 'Export certificate: failed') as error:
                signing.run_phase('Export certificate', ['openssl', 'private-sentinel'],
                                  environment={'BGDESK_PFX_PASSWORD': 'private-sentinel'})
        self.assertEqual(command.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertNotIn('private-sentinel', output.getvalue() + str(error.exception))

    def test_temporary_pfx_is_removed_after_a_failed_signing_phase(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            tool = base / 'Windows Kits/10/bin/10.0/x64/signtool.exe'
            tool.parent.mkdir(parents=True)
            tool.touch()
            app = base / 'app.exe'
            app.touch()
            pfx = []
            def phase(label, command, **kwargs):
                if label == 'Export certificate':
                    path = Path(command[command.index('-out') + 1])
                    path.write_bytes(b'temporary key container')
                    pfx.append(path)
                    self.assertIn('-passin', command)
                elif label == 'Sign executable':
                    self.assertNotIn('/tr', command)
                    raise RuntimeError('signing failed')
            with patch.dict(os.environ, {'ProgramFiles(x86)': str(base), 'RUNNER_TEMP': str(base)}), \
                 patch.object(signing.shutil, 'which', return_value='openssl'), \
                 patch.object(signing, 'run_phase', side_effect=phase):
                with self.assertRaisesRegex(RuntimeError, 'signing failed'):
                    signing.sign(app)
            self.assertEqual(len(pfx), 1)
            self.assertFalse(pfx[0].exists())
