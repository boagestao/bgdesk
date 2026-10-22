"""Win32 must use a real PE32 runtime and retain the existing dependency lock."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


win32 = module('build-windows-x86')
pack = module('package-windows-update')
collect = module('collect-artifacts')
plan = module('preflight')


def pe(machine=0x14c, magic=0x10b):
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<H', data, 132, machine)
    struct.pack_into('<H', data, 152, magic)
    return data


def coff_archive(machine):
    body = struct.pack('<H', machine) + bytes(18)
    header = b'object.obj/     ' + b'0           ' + b'0     ' + b'0     ' + b'100644  '
    header += str(len(body)).encode().ljust(10) + b'`\n'
    return b'!<arch>\n' + header + body


class WindowsX86Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_crypto_link_override_is_scoped_to_win32_and_keeps_the_locked_library_version(self):
        package = self.root / 'registry/libsodium-sys-0.2.7'
        library = package / 'msvc/Win32/Release/v142/libsodium.lib'
        library.parent.mkdir(parents=True)
        library.write_bytes(coff_archive(0x14c))
        metadata = dict(packages=[dict(name='libsodium-sys', version='0.2.7',
                                      manifest_path=str(package / 'Cargo.toml'))])
        with patch.object(win32.subprocess, 'check_output', return_value=json.dumps(metadata)) as cargo:
            config = win32.sodium_config(self.root)
        self.assertIn('--locked', cargo.call_args.args[0])
        self.assertEqual(cargo.call_args.args[0][-1], 'i686-pc-windows-msvc')
        values = tomllib.loads(config.read_text())
        self.assertEqual(list(values['target']), ['i686-pc-windows-msvc'])
        sodium = values['target']['i686-pc-windows-msvc']['sodium']
        self.assertEqual(sodium['rustc-link-lib'], ['static=libsodium'])
        self.assertEqual(sodium['rustc-link-search'], ['native=' + str(library.parent)])
        library.write_bytes(coff_archive(0x8664))
        with patch.object(win32.subprocess, 'check_output', return_value=json.dumps(metadata)):
            with self.assertRaisesRegex(ValueError, 'non-x86'):
                win32.sodium_config(self.root)
        metadata['packages'][0]['version'] = 'other'
        with patch.object(win32.subprocess, 'check_output', return_value=json.dumps(metadata)):
            with self.assertRaisesRegex(ValueError, 'locked libsodium-sys version'):
                win32.sodium_config(self.root)

    def test_coff_archive_rejects_mixed_architectures_and_corrupt_members(self):
        path = self.root / 'sodium.lib'
        path.write_bytes(coff_archive(0x14c))
        self.assertEqual(win32.require_x86_archive(path), 1)
        for data in (coff_archive(0x14c) + coff_archive(0x8664)[8:],
                     coff_archive(0x14c)[:-3], b'!<arch>\n', b'not an archive'):
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                win32.require_x86_archive(path)

    def test_cargo_json_is_utf8_even_when_windows_uses_a_legacy_code_page(self):
        package = self.root / 'registry/ação-Ё/libsodium-sys-0.2.7'
        library = package / 'msvc/Win32/Release/v142/libsodium.lib'
        library.parent.mkdir(parents=True)
        library.write_bytes(coff_archive(0x14c))
        metadata = json.dumps(dict(packages=[dict(name='libsodium-sys', version='0.2.7',
                            manifest_path=str(package / 'Cargo.toml'))]), ensure_ascii=False).encode('utf-8')
        # U+0401 contains byte 0x81 in UTF-8, the undefined CP1252 byte seen in Actions.
        with self.assertRaises(UnicodeDecodeError):
            metadata.decode('cp1252')
        check_output = subprocess.check_output
        def cargo_json(*args, **kwargs):
            # Simulate Windows' fallback locale; the caller must explicitly override it.
            kwargs.setdefault('encoding', 'cp1252')
            return check_output([os.sys.executable, '-c',
                                 'import sys; sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))',
                                 metadata.hex()], **kwargs)
        with patch.object(win32.subprocess, 'check_output', side_effect=cargo_json):
            config = win32.sodium_config(self.root)
        sodium = tomllib.loads(config.read_text(encoding='utf-8'))['target'][win32.TARGET]['sodium']
        self.assertEqual(sodium['lib'], str(library.parent))

    def test_host_ffmpeg_does_not_satisfy_the_win32_target_dependencies(self):
        required = ('include/libavutil/attributes.h', 'include/libavutil/opt.h',
                    'include/libavcodec/avcodec.h', 'lib/avutil.lib', 'lib/avcodec.lib')
        def install(arch):
            for name in required:
                path = self.root / f'installed/{arch}-windows-static' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
        install('x64')
        with self.assertRaisesRegex(ValueError, 'host x64 libraries cannot build Win32'):
            win32.check_native_dependencies(self.root)
        install('x86')
        win32.check_native_dependencies(self.root)
        (self.root / 'installed/x86-windows-static/lib/avcodec.lib').unlink()
        with self.assertRaisesRegex(ValueError, 'avcodec.lib'):
            win32.check_native_dependencies(self.root)

    def test_runtime_and_packer_cannot_accidentally_contain_x64_or_truncated_binaries(self):
        path = self.root / 'app.exe'
        path.write_bytes(pe())
        win32.require_x86(path)
        for invalid in (pe(0x8664, 0x20b), b'MZ', pe()[:140], b'not a Windows program'):
            path.write_bytes(invalid)
            with self.assertRaises(ValueError):
                win32.require_x86(path)

    def test_both_editions_share_the_pinned_x86_binding_without_resolving_other_dependencies(self):
        repo = Path(__file__).resolve().parents[2]
        for name in ('Cargo.toml', 'Cargo.lock'):
            (self.root / name).write_bytes((repo / name).read_bytes())
        before = (self.root / 'Cargo.lock').read_text()
        win32.prepare_sciter(self.root)
        after = (self.root / 'Cargo.lock').read_text()
        old = 'git+https://github.com/rustdesk-org/rust-sciter?branch=dyn#5322f3a755a0e6bf999fbc60d1efc35246c0f821'
        new = f'git+https://github.com/rustdesk-org/rust-sciter?rev={win32.SCITER_REV}#{win32.SCITER_REV}'
        self.assertEqual(before.replace(old, new), after)
        win32.prepare_sciter(self.root)
        self.assertEqual(after, (self.root / 'Cargo.lock').read_text())
        (self.root / 'Cargo.toml').write_text('unexpected dependency')
        with self.assertRaisesRegex(ValueError, 'Unexpected Sciter'):
            win32.prepare_sciter(self.root)

    def test_cached_runtime_is_reused_only_if_checksum_and_pe_architecture_match(self):
        runtime = self.root / '.tools/sciter-win32/sciter.dll'
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(pe())
        import hashlib
        with patch.object(win32, 'SCITER_SHA256', hashlib.sha256(runtime.read_bytes()).hexdigest()), \
             patch.object(win32.urllib.request, 'urlopen') as download:
            self.assertEqual(win32.sciter_dll(self.root), runtime)
        download.assert_not_called()
        with patch.object(win32.urllib.request, 'urlopen') as download:
            download.return_value.__enter__.return_value.read.return_value = b'tampered download'
            with self.assertRaisesRegex(ValueError, 'checksum'):
                win32.sciter_dll(self.root)
        self.assertEqual(runtime.read_bytes(), pe())

    def test_native_update_packer_builds_the_i686_target_and_copies_that_output(self):
        bundle = self.root / 'build/windows-x86-cliente/extracted'
        bundle.mkdir(parents=True)
        (bundle / 'bgdesk.exe').write_bytes(pe())
        packed = self.root / 'target/i686-pc-windows-msvc/release/rustdesk-portable-packer.exe'
        packed.parent.mkdir(parents=True)
        packed.write_bytes(pe())
        with patch.object(pack, 'ROOT', self.root), patch.object(pack.subprocess, 'run') as cargo, \
             patch('sys.argv', ['package', '--edition', 'cliente', '--arch', 'x86']):
            pack.main()
        self.assertEqual(cargo.call_args.args[0][-2:], ['--target', 'i686-pc-windows-msvc'])
        self.assertEqual((bundle.parent / 'bgdesk-cliente-update-win32.exe').read_bytes(), pe())
        packed.write_bytes(pe(0x8664, 0x20b))
        with patch.object(pack, 'ROOT', self.root), patch.object(pack.subprocess, 'run'), \
             patch('sys.argv', ['package', '--edition', 'cliente', '--arch', 'x86']):
            with self.assertRaisesRegex(ValueError, 'PE32'):
                pack.main()

    def test_validation_and_all_keep_six_runners_with_both_windows_architectures_serial(self):
        jobs = plan.distribution_matrix('windows-x86')['include']
        self.assertEqual(jobs, [dict(platform='windows', arch='x86', runner='windows-2022')])
        self.assertEqual(len(plan.distribution_matrix('all')['include']), 6)
        windows = [t for t in plan.distribution_matrix('all')['include'] if t['platform'] == 'windows']
        self.assertEqual(windows, [dict(platform='windows', arch='x86_64', runner='windows-2022', win32=True)])
        self.assertEqual(list(plan.artifact_targets('windows')), [('windows', 'x86_64'), ('windows', 'x86')])
        self.assertEqual(list(plan.artifact_targets('windows-x86_64')), [('windows', 'x86_64')])
        repo = Path(__file__).resolve().parents[2]
        workflow = (repo / '.github/workflows/release.yml').read_text()
        self.assertLess(workflow.index('name: Build, sign, and save suporte'),
                        workflow.index('name: Build, sign, and save Win32 on the same Windows runner'))
        composite = (repo / '.github/actions/build-edition/action.yml').read_text()
        self.assertIn('release-artifacts/$PLATFORM-$ARCH-$EDITION', composite)
        pair = (repo / '.github/actions/build-windows-x86-pair/action.yml').read_text()
        self.assertIn('edition: cliente', pair)
        self.assertNotIn('edition: suporte', pair)
        with self.assertRaises(ValueError):
            collect.specs('windows', 'x86', 'suporte')
        for edition in ('cliente',):
            paths = collect.specs('windows', 'x86', edition)
            self.assertEqual([fmt for fmt, _ in paths], ['exe', 'inno-exe'])
            for _, path in paths:
                self.assertIn('win32.exe', path.name)
                self.assertEqual(path.parent.as_posix(), f'build/windows-x86-{edition}')

    def test_installer_receives_the_selected_architecture_and_retains_the_x64_default(self):
        repo = Path(__file__).resolve().parents[2]
        for name in ('installers/build-installer.sh', 'installers/cliente.iss', 'installers/suporte.iss',
                     'scripts/build-out-dir.sh', 'Cargo.toml', 'res/update/application_version.py'):
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repo / name, dest)
        (self.root / 'config/certs').mkdir(parents=True)
        (self.root / 'config/certs/ca.crt').write_text('public CA fixture')
        (self.root / 'scripts/sign-pe.sh').write_text('exit 0\n')
        compiler = self.root / 'compiler'
        compiler.mkdir()
        iscc = compiler / 'ISCC.exe'
        iscc.write_text('''#!/bin/bash
set -eu
# Real ISCC treats an unquoted hyphen in /D values as a new switch.
if [[ -n "${5:-}" || "$3" != /DAppVersion=\\\"*\\\" || "$4" != /DNumericVersion=\\\"*\\\" ]]; then
  printf '%s\\n' 'Usage:  iscc [options] scriptfile.iss' >&2
  exit 1
fi
edition="$(basename "$1" .iss)"
arch="${2#/DBuildArch=}"
case "$arch" in x86) suffix=win32;; x86_64) suffix=win64;; *) exit 99;; esac
touch "build/windows-$arch-$edition/bgdesk-$edition-$suffix.exe"
printf '%s\\n' "$2" "$3" "$4" > compiler-arguments
''')
        iscc.chmod(0o755)
        for arch in ('x86', 'x86_64'):
            for edition in ('cliente', 'suporte'):
                folder = self.root / f'build/windows-{arch}-{edition}/extracted'
                folder.mkdir(parents=True)
                (folder / 'bgdesk.exe').write_bytes(pe())
                arguments = [edition, arch] if arch == 'x86' else [edition]
                subprocess.run(['bash', str(self.root / 'installers/build-installer.sh'), *arguments],
                               cwd=self.root, env=dict(os.environ, INNO_SETUP_DIR=str(compiler)),
                               check=True, capture_output=True)
                self.assertEqual((self.root / 'compiler-arguments').read_text().splitlines(),
                                 ['/DBuildArch='+arch,
                                  '/DAppVersion="1.5.1-1"',
                                  '/DNumericVersion="1.5.1.1"'])


if __name__ == '__main__':
    unittest.main()
