"""Exercise native capture staging and the portable X11 boundary without a GPU."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('bgdesk_build', ROOT / 'build.py')
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class LinuxWaylandPackageTests(unittest.TestCase):
    def features(self, flags=(), windows=False, osx=False):
        with patch.multiple(build, windows=windows, osx=osx), contextlib.redirect_stdout(io.StringIO()):
            return build.get_features(build.make_parser().parse_args(list(flags)))

    def test_native_default_and_other_platforms(self):
        for flutter in ([], ['--flutter']):
            for edition in ([], ['--incoming-only']):
                features = self.features(flutter + edition)
                self.assertTrue({'drm', 'drm-wake'}.issubset(features))
        self.assertNotIn('drm', self.features(['--no-drm']))
        self.assertNotIn('drm', self.features(windows=True))
        self.assertNotIn('drm', self.features(osx=True))

    def bundle(self, directory):
        payload = directory / 'compiled bundle'
        (payload / 'lib').mkdir(parents=True)
        (payload / 'data').mkdir()
        (payload / 'bgdesk').write_bytes(b'Flutter launcher')
        (payload / 'lib/libbgdesk.so').write_bytes(
            b'\0'.join([build.DRMTAP_DLOPEN_MARKER, build.DRMTAP_WAKE_MARKER, b'GLIBC_2.38']))
        (payload / 'libdrmtap.so.0.5.12').write_bytes(
            b'libEGL.so.1\0eglCreateImageKHR\0GLIBC_2.34\0GLIBC_2.3')
        return payload

    def project(self, directory):
        project = directory / 'source'
        project.mkdir()
        for name in ('build.py', 'Cargo.toml', 'scripts/stage-linux-drm.py',
                     'libs/scrap/src/common/drmtap_dl.rs', 'res/bgdesk.service',
                     'res/bgdesk.desktop', 'res/bgdesk-link.desktop', 'res/128x128@2x.png',
                     'res/scalable.svg', 'res/arch/PKGBUILD', 'res/arch/bgdesk.install',
                     'res/startwm.sh', 'res/xorg.conf', 'res/pam.d/bgdesk.debian',
                     'res/update/application_version.py'):
            destination = project / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        shutil.copytree(ROOT / 'res/DEBIAN', project / 'res/DEBIAN')
        payload = self.bundle(directory)
        bundle = project / 'flutter/build/linux/x64/release/bundle'
        shutil.copytree(payload, bundle)
        native = project / 'target/release'
        native.mkdir(parents=True)
        shutil.copy2(payload / 'lib/libbgdesk.so', native / 'bgdesk')
        shutil.copy2(payload / 'libdrmtap.so.0.5.12', native / 'libdrmtap.so.0.5.12')
        (project / 'libsciter-gtk.so').write_bytes(b'Sciter runtime')
        return project, bundle

    def test_isolated_packaging_tree_can_import_build_and_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, _ = self.project(Path(temporary))
            for command in (['python3', '-c', 'import build'],
                            ['python3', 'scripts/stage-linux-drm.py', '--help']):
                result = subprocess.run(command, cwd=project, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'Linux DEB tools required')
    def test_deb_folder_packaging_includes_capture_under_normal_package_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, bundle = self.project(Path(temporary))
            result = subprocess.run(['python3', 'build.py', '--package', str(bundle)],
                                    cwd=project, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            packages = list(project.glob('bgdesk-*.deb'))
            self.assertEqual(len(packages), 1)
            metadata = subprocess.check_output(['dpkg-deb', '-f', str(packages[0])], text=True)
            self.assertIn('Package: bgdesk\n', metadata)
            self.assertIn('libdrm2 (>= 2.4.101), libegl1, libgles2', metadata)
            extracted = project / 'extracted'
            subprocess.run(['dpkg-deb', '-x', str(packages[0]), str(extracted)], check=True)
            self.assertTrue((extracted / 'usr/lib/bgdesk/libdrmtap.so.0').is_file())

    @unittest.skipUnless(shutil.which('rpmbuild'), 'RPM build tools required')
    def test_rpm_specs_include_capture_and_runtime_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            project, bundle = self.project(directory)
            for name in ('rpm-flutter', 'rpm-flutter-suse', 'rpm', 'rpm-suse'):
                with self.subTest(spec=name):
                    topdir = directory / name
                    result = subprocess.run(['rpmbuild', '-bb', '--nodeps', '--define',
                        '_topdir %s' % topdir, str(ROOT / ('res/%s.spec' % name))],
                        env=dict(os.environ, HBB=str(project)), capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    packages = list((topdir / 'RPMS').rglob('*.rpm'))
                    self.assertEqual(len(packages), 1)
                    files = subprocess.check_output(['rpm', '-qlp', str(packages[0])], text=True)
                    self.assertIn('/usr/lib/bgdesk/libdrmtap.so.0\n', files)
                    self.assertNotIn('/usr/share/bgdesk/libdrmtap', files)
                    dependencies = subprocess.check_output(['rpm', '-qp', '--requires', str(packages[0])], text=True)
                    self.assertIn('libdrm2 >= 2.4.101' if 'suse' in name else 'libdrm >= 2.4.101', dependencies)
                    self.assertIn('libEGL.so.1()(64bit)', dependencies)
                    self.assertIn('libGLESv2.so.2()(64bit)', dependencies)

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'Linux DEB tools required')
    def test_flutter_deb_leaves_capture_in_bundle_for_rpm_and_arch(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, bundle = self.project(Path(temporary))
            prebuilt = project / 'libdrmtap.so.0.5.12'
            (bundle / prebuilt.name).rename(prebuilt)
            original_cwd = Path.cwd()
            try:
                os.chdir(project)
                with patch.multiple(build, skip_cargo=True, flutter_linux_build_cmd='true',
                        flutter_build_dir='build/linux/x64/release/bundle'), \
                        patch.object(build, 'rename_linux_artifacts'), \
                        patch.object(build, 'build_libdrmtap_so', return_value=str(prebuilt)), \
                        contextlib.redirect_stdout(io.StringIO()):
                    build.build_flutter_deb('1.5.2', 'flutter,drm,drm-wake')
            finally:
                os.chdir(original_cwd)
            self.assertTrue((bundle / prebuilt.name).is_file())
            package = project / 'bgdesk-1.5.2.deb'
            self.assertTrue(package.is_file())
            extracted = project / 'extracted'
            subprocess.run(['dpkg-deb', '-x', str(package), str(extracted)], check=True)
            self.assertTrue((extracted / 'usr/lib/bgdesk/libdrmtap.so.0').is_file())
            self.assertFalse(list((extracted / 'usr/share/bgdesk').glob('libdrmtap*')))

    def test_native_staging_keeps_soname_at_absolute_loader_path_and_measures_glibc(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            payload = self.bundle(directory)
            stage = directory / 'package root'
            shutil.copytree(payload, stage / 'usr/share/bgdesk')
            with contextlib.redirect_stdout(io.StringIO()):
                build.stage_bundle_drmtap(str(payload), str(stage))
            capture = stage / 'usr/lib/bgdesk/libdrmtap.so.0'
            self.assertEqual(capture.read_bytes(), (payload / 'libdrmtap.so.0.5.12').read_bytes())
            self.assertEqual(os.readlink(capture), 'libdrmtap.so.0.5.12')
            self.assertFalse(list((stage / 'usr/share/bgdesk').glob('libdrmtap*')))
            control = stage / 'DEBIAN/control'
            control.parent.mkdir()
            control.write_text('Package: bgdesk\nDepends: libgtk-3-0\nDescription: BGDesk\n')
            build.add_drm_deb_dependencies(str(control))
            metadata = control.read_text()
            self.assertIn('Package: bgdesk\n', metadata)
            self.assertIn('libdrm2 (>= 2.4.101), libegl1, libgles2', metadata)
            self.assertIn('libc6 (>= 2.38)', metadata)

    def test_stale_binary_missing_wake_and_incompatible_libraries_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = self.bundle(Path(temporary))
            binary = payload / 'lib/libbgdesk.so'
            for content in (b'old X11 build', build.DRMTAP_DLOPEN_MARKER):
                binary.write_bytes(content)
                with self.assertRaisesRegex(Exception, 'drm,drm-wake'):
                    build.validated_bundle_drmtap(str(payload))
            binary.write_bytes(build.DRMTAP_DLOPEN_MARKER + build.DRMTAP_WAKE_MARKER)
            so = payload / 'libdrmtap.so.0.5.12'
            for content, message in ((b'CPU only', 'CPU-only'),
                    (b'libEGL.so.1 eglCreateImageKHR socketpair', 'privileged-helper')):
                so.write_bytes(content)
                with self.assertRaisesRegex(Exception, message):
                    build.validated_bundle_drmtap(str(payload))
            so.write_bytes(b'libEGL.so.1 eglCreateImageKHR')
            so.rename(payload / 'libdrmtap.so.0.0.1')
            with self.assertRaisesRegex(Exception, 'REFUSE'):
                build.validated_bundle_drmtap(str(payload))

    def test_prepare_builds_library_once_and_cli_handles_spaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            payload = self.bundle(directory)
            so = payload / 'libdrmtap.so.0.5.12'
            prebuilt = directory / so.name
            so.rename(prebuilt)
            with patch.object(build, 'build_libdrmtap_so', return_value=str(prebuilt)) as compile_library:
                with contextlib.redirect_stdout(io.StringIO()):
                    build.prepare_drm_bundle(str(payload))
                    build.prepare_drm_bundle(str(payload))
                compile_library.assert_called_once()
            stage = directory / 'RPM build root'
            result = subprocess.run(['python3', str(ROOT / 'scripts/stage-linux-drm.py'),
                str(payload), '--root', str(stage)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((stage / 'usr/lib/bgdesk/libdrmtap.so.0').is_file())

    @unittest.skipUnless(shutil.which('dpkg-deb') and shutil.which('bsdtar'),
                         'Linux DEB and libarchive tools required')
    def test_appimage_gets_original_feature_set_without_mutating_native_deb(self):
        spec = importlib.util.spec_from_file_location('bgdesk_portable', ROOT / 'scripts/prepare-appimage-deb.py')
        portable = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(portable)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            payload = self.bundle(directory)
            stage = directory / 'native'
            shutil.copytree(payload, stage / 'usr/share/bgdesk')
            with contextlib.redirect_stdout(io.StringIO()):
                build.stage_bundle_drmtap(str(payload), str(stage))
            control = stage / 'DEBIAN/control'
            control.parent.mkdir()
            control.write_text('Package: bgdesk\nVersion: 1.5.2\nArchitecture: all\n'
                               'Maintainer: BGDesk <test@example.com>\nDepends: libgtk-3-0\nDescription: BGDesk\n')
            build.add_drm_deb_dependencies(str(control))
            native = directory / 'native.deb'
            subprocess.run(['dpkg-deb', '-Zzstd', '-b', str(stage), str(native)],
                           check=True, capture_output=True)
            source_bytes = native.read_bytes()
            portable_library = directory / 'portable library.so'
            portable_library.write_bytes(b'original non-DRM feature set')
            image_deb = directory / 'portable.deb'
            portable.prepare(str(native), str(portable_library), str(image_deb))
            extracted = directory / 'portable root'
            subprocess.run(['dpkg-deb', '-R', str(image_deb), str(extracted)], check=True)
            self.assertEqual((extracted / 'usr/share/bgdesk/lib/libbgdesk.so').read_bytes(),
                             portable_library.read_bytes())
            self.assertFalse((extracted / 'usr/lib/bgdesk').exists())
            metadata = (extracted / 'DEBIAN/control').read_text()
            self.assertIn('Depends: libgtk-3-0\n', metadata)
            self.assertEqual(native.read_bytes(), source_bytes)
            portable_library.write_bytes(build.DRMTAP_DLOPEN_MARKER)
            with self.assertRaisesRegex(ValueError, '--no-drm'):
                portable.prepare(str(native), str(portable_library), str(image_deb))
            # Run the unchanged recipes against the actual portable DEB.
            resources = directory / 'res'
            resources.mkdir()
            for icon in ('32x32.png', '64x64.png', '128x128.png', 'scalable.svg'):
                (resources / icon).write_text('icon')
            for arch in ('x86_64', 'aarch64'):
                with self.subTest(arch=arch):
                    work = directory / arch
                    work.mkdir()
                    shutil.copy2(image_deb, work / 'bgdesk.deb')
                    recipe = (ROOT / 'appimage' / ('AppImageBuilder-%s.yml' % arch)).read_text()
                    script = '\n'.join(line[3:] for line in recipe.split('script:\n', 1)[1].split('AppDir:', 1)[0].splitlines()
                                       if line.startswith(' - '))
                    result = subprocess.run(['bash', '-euc', script], cwd=work, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    appdir = work / 'AppDir'
                    self.assertTrue((appdir / 'usr/share/bgdesk/lib/libbgdesk.so').is_file())
                    self.assertFalse((appdir / 'usr/lib/bgdesk').exists())
                    self.assertIn('GDK_BACKEND: x11', recipe)


if __name__ == '__main__':
    unittest.main()
