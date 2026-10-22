from distribution import editions_for_target
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import base64
import gzip
import tarfile
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import config_archive

from botocore.exceptions import ClientError


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


r2 = module("r2-publish")
setup = module("setup-github-secrets")
plan = module("preflight")
collect = module("collect-artifacts")


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.writes = []

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return self.objects[Key]

    def upload_file(self, filename, bucket, key, ExtraArgs):
        self.writes.append(key)
        self.objects[key] = dict(ContentLength=Path(filename).stat().st_size,
                                 Metadata=ExtraArgs["Metadata"], cache=ExtraArgs["CacheControl"],
                                 body=Path(filename).read_bytes())


class ReleaseToolsTests(unittest.TestCase):
    def root_packages(self):
        site = self.site()
        records = []
        for platform, arch in plan.artifact_targets():
            for edition in editions_for_target(platform, arch):
                for fmt, _ in collect.specs(platform, arch, edition):
                    record = dict(edition=edition, platform=platform, arch=arch, format=fmt)
                    name = r2.root_artifact_name(edition, platform, arch, fmt)
                    path = site / 'updates' / edition / 'v1.5.2' / name
                    path.write_bytes(('package-' + name).encode())
                    record.update(file_name='versioned-' + name, size=path.stat().st_size,
                                  sha256=r2.file_hash(path))
                    records.append((record, path))
                (site / 'updates' / edition / 'v1.5.2' / 'bgdesk.dmg').unlink(missing_ok=True)
        return site, records

    def test_packages_are_uploaded_once_at_root_before_metadata_or_latest(self):
        site, records = self.root_packages()
        s3, verified = FakeS3(), []
        def verify(origin, key, path, small=False):
            if len(verified) < 26:
                self.assertEqual(len(s3.writes), 26)
                self.assertNotIn('/', key)
            verified.append(key)
        r2.publish(s3, 'bucket', site, records, 'https://bgdesk.com', 'v1.5.2',
                   verify=verify, root_artifacts=True)
        packages = [key for key in s3.writes if key.endswith(('.exe', '.dmg', '.deb', '.rpm', '.AppImage', '.pkg.tar.zst', '.apk'))]
        self.assertEqual(len(packages), 26)
        self.assertTrue(all('/' not in key for key in packages))
        self.assertTrue(all(s3.objects[key]['cache'] == 'no-store, max-age=0' for key in packages))
        self.assertEqual(set(packages), set(verified[:26]))
        self.assertEqual(s3.writes[-2:], ['updates/cliente/latest.json', 'updates/suporte/latest.json'])
        writes = len(s3.writes)
        r2.publish(s3, 'bucket', site, records, 'https://bgdesk.com', 'v1.5.2',
                   verify=lambda *a, **kw: None, root_artifacts=True)
        self.assertEqual(len(s3.writes), writes)

    def test_root_verification_failure_never_activates_metadata_or_feed(self):
        site, records = self.root_packages()
        s3 = FakeS3()
        def fail(*args, **kwargs):
            raise ValueError('Root download unavailable')
        with self.assertRaisesRegex(ValueError, 'Root download'):
            r2.publish(s3, 'bucket', site, records, 'https://bgdesk.com', 'v1.5.2',
                       verify=fail, root_artifacts=True)
        self.assertTrue(all('/' not in key for key in s3.writes))
        records[-1][1].write_bytes(b'tampered')
        s3 = FakeS3()
        with self.assertRaisesRegex(ValueError, 'differs from the build'):
            r2.publish(s3, 'bucket', site, records, 'https://bgdesk.com', 'v1.5.2', root_artifacts=True)
        self.assertEqual(s3.writes, [])

    def test_root_names_are_unique_including_the_four_future_win32_packages(self):
        _, records = self.root_packages()
        names = {r2.root_artifact_name(r['edition'], r['platform'], r['arch'], r['format']) for r, _ in records}
        for edition in ('cliente',):
            names.add(r2.root_artifact_name(edition, 'windows', 'x86', 'exe'))
            names.add(r2.root_artifact_name(edition, 'windows', 'x86', 'inno-exe'))
        self.assertEqual(len(names), 26)
        self.assertIn('bgdesk-cliente-win32.exe', names)
        self.assertIn('bgdesk-cliente-update-win32.exe', names)

    def test_native_builds_use_the_manifest_vcpkg_baseline(self):
        root = Path(__file__).resolve().parents[2]
        baseline = json.loads((root / 'vcpkg.json').read_text())['vcpkg-configuration']['default-registry']['baseline']
        for name in ('.github/workflows/release.yml', 'build.sh', 'scripts/setup-windows-build.sh',
                     'docker/build-linux-x86_64.dockerfile', 'docker/build-linux-aarch64.dockerfile'):
            with self.subTest(file=name):
                pins = re.findall(r'(?:VCPKG_COMMIT_ID|vcpkg_commit)[^\n]*?([0-9a-f]{40})',
                                  (root / name).read_text())
                self.assertEqual(pins, [baseline])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def site(self):
        for edition in ("cliente", "suporte"):
            channel = self.root / "updates" / edition
            release = channel / "v1.5.2"
            release.mkdir(parents=True)
            (release / "bgdesk.dmg").write_bytes(b"installer")
            (release / "bgdesk-update.json").write_bytes(b"signed metadata")
            (release / "bgdesk-update.json.sig").write_bytes(b"signature")
            (channel / "latest.json").write_text('{"url":"release"}')
        return self.root

    def test_both_editions_are_uploaded_and_publicly_verified_before_any_announcement(self):
        s3 = FakeS3()
        verified = []
        def verify(origin, key, path, small=False):
            if not key.endswith("latest.json"):
                self.assertEqual(len(s3.writes), 6)
                self.assertFalse(any(item.endswith('latest.json') for item in s3.writes))
            verified.append(key)
        r2.publish(s3, "bucket", self.site(), [], "https://bgdesk.com", "v1.5.2", verify)
        self.assertEqual(s3.writes[-2:], ["updates/cliente/latest.json", "updates/suporte/latest.json"])
        self.assertEqual(len(verified), 8)
        self.assertEqual(s3.objects[s3.writes[-1]]["cache"], "no-store, max-age=0")
        self.assertIn("immutable", s3.objects[s3.writes[0]]["cache"])

    def test_failed_public_verification_preserves_all_previous_announcements(self):
        s3 = FakeS3()
        def fail(*args, **kwargs):
            raise ValueError("SPA fallback or inaccessible public URL")
        with self.assertRaises(ValueError):
            r2.publish(s3, "bucket", self.site(), [], "https://bgdesk.com", "v1.5.2", fail)
        self.assertFalse(any(key.endswith("latest.json") for key in s3.writes))

    def test_immutable_objects_can_be_retried_but_never_changed(self):
        s3 = FakeS3()
        path = self.root / "app.dmg"
        path.write_bytes(b"first release")
        r2.upload(s3, "bucket", path, "updates/v1/app.dmg")
        r2.upload(s3, "bucket", path, "updates/v1/app.dmg")
        self.assertEqual(len(s3.writes), 1)
        path.write_bytes(b"different release")
        with self.assertRaisesRegex(ValueError, "Immutable"):
            r2.upload(s3, "bucket", path, "updates/v1/app.dmg")

    def test_public_verification_identifies_bgdesk_and_checks_actual_bytes_and_sizes(self):
        payload = b'public package'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.respond(True)
            def do_HEAD(self):
                self.respond(False)
            def respond(self, body):
                # Reproduce the origin's rejection of urllib's default identity.
                allowed = self.headers.get('User-Agent', '').startswith('BGDesk-Release/')
                self.send_response(200 if allowed else 403)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                if body:
                    self.wfile.write(payload)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        path = self.root / 'package'
        path.write_bytes(payload)
        origin = f'http://127.0.0.1:{server.server_port}'
        try:
            r2.public_check(origin, 'package', path, small=True)
            r2.public_check(origin, 'package', path)
            path.write_bytes(b'tampered bytes')
            with self.assertRaisesRegex(ValueError, 'original bytes'):
                r2.public_check(origin, 'package', path, small=True)
            path.write_bytes(b'wrong size')
            with self.assertRaisesRegex(ValueError, 'wrong size'):
                r2.public_check(origin, 'package', path)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_publication_retry_keeps_the_build_commit_and_original_timestamp(self):
        s3 = FakeS3()
        source_commit = 'a' * 40
        stamp = '2026-10-20T01:02:03-03:00'
        environment = dict(R2_PUBLIC_ORIGIN='https://download.bgdesk.com', R2_BUCKET='bucket',
                           BGDESK_UPDATE_SIGNING_KEY='test-key', GITHUB_SHA='b' * 40)
        with patch.dict(os.environ, environment), \
             patch('sys.argv', ['publish', '--version', '1.5.2', '--source-commit', source_commit]), \
             patch.object(r2, 'client', return_value=s3), patch.object(r2, 'read_records', return_value=[]), \
             patch.object(r2.subprocess, 'check_output', return_value=stamp) as git, \
             patch.object(r2.subprocess, 'run') as prepare, patch.object(r2, 'publish'):
            r2.main()
        self.assertEqual(git.call_args.args[0][-1], source_commit)
        for call in prepare.call_args_list:
            command = call.args[0]
            self.assertEqual(command[command.index('--published-at') + 1], stamp)
            self.assertIn('--root-artifacts', command)
        marker = json.loads(s3.objects['updates/releases/v1.5.2.json']['body'])
        self.assertEqual(marker['commit'], source_commit)
        self.assertEqual(marker['artifact_layout'], 'root')

    def test_published_root_layout_retries_check_the_existing_root_without_reuploading(self):
        s3 = FakeS3()
        path = self.root / 'package.exe'
        path.write_bytes(b'original')
        marker = self.root / 'marker.json'
        marker.write_text('{}')
        record = dict(edition='cliente', platform='windows', arch='x86_64', format='exe',
                      file_name='versioned-app.exe', sha256=r2.file_hash(path))
        r2.upload(s3, 'bucket', marker, 'updates/releases/v1.5.2.json', metadata={'artifact-layout': 'root'})
        r2.upload(s3, 'bucket', path, 'bgdesk-cliente-update-win64.exe', immutable=False)
        with patch.dict(os.environ, {'R2_PUBLIC_ORIGIN': 'https://download.bgdesk.com', 'R2_BUCKET': 'bucket'}), \
             patch('sys.argv', ['publish', '--version', '1.5.2', '--source-commit', 'a' * 40]), \
             patch.object(r2, 'client', return_value=s3), patch.object(r2, 'read_records', return_value=[(record, path)]):
            r2.main()
            path.write_bytes(b'changed!')
            record['sha256'] = r2.file_hash(path)
            with self.assertRaisesRegex(ValueError, 'Published release differs'):
                r2.main()
        self.assertEqual(len(s3.writes), 2)

    def test_already_published_retry_requires_identical_immutable_packages(self):
        s3 = FakeS3()
        path = self.root / 'app.dmg'
        path.write_bytes(b'original')
        marker = self.root / 'marker.json'
        marker.write_text('{}')
        r2.upload(s3, 'bucket', marker, 'updates/releases/v1.5.2.json')
        r2.upload(s3, 'bucket', path, 'updates/cliente/v1.5.2/app.dmg')
        record = dict(edition='cliente', file_name='app.dmg', sha256=r2.file_hash(path))
        with patch.dict(os.environ, {'R2_PUBLIC_ORIGIN': 'https://download.bgdesk.com', 'R2_BUCKET': 'bucket'}), \
             patch('sys.argv', ['publish', '--version', '1.5.2', '--source-commit', 'a' * 40]), \
             patch.object(r2, 'client', return_value=s3), patch.object(r2, 'read_records', return_value=[(record, path)]):
            r2.main()
            path.write_bytes(b'changed!')
            record['sha256'] = r2.file_hash(path)
            with self.assertRaisesRegex(ValueError, 'Published release differs'):
                r2.main()
        self.assertEqual(len(s3.writes), 2)

    def test_complete_artifact_matrix_and_hashes_are_required(self):
        entries = [dict(platform=platform, arch=arch, edition=edition)
                   for platform, arch in plan.artifact_targets()
                   for edition in editions_for_target(platform, arch)]
        for entry in entries:
            directory = self.root / f"{entry['platform']}-{entry['arch']}-{entry['edition']}"
            directory.mkdir()
            records = []
            for fmt, _ in collect.specs(entry["platform"], entry["arch"], entry["edition"]):
                name = f"app.{fmt}"
                path = directory / name
                path.write_bytes(b"test build")
                records.append(dict(platform=entry["platform"], arch=entry["arch"], edition=entry["edition"],
                                    format=fmt, version="1.5.2", file_name=name, size=10,
                                    sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            (directory / "artifacts.json").write_text(json.dumps(records))
        self.assertEqual(len(r2.read_records(self.root, "1.5.2")), 26)
        chosen = next(self.root.glob("*/artifacts.json"))
        saved = chosen.read_bytes()
        chosen.unlink()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            r2.read_records(self.root, "1.5.2")
        chosen.write_bytes(saved)
        first = json.loads(saved)[0]
        (chosen.parent / first["file_name"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            r2.read_records(self.root, "1.5.2")

    def test_dotenv_is_data_and_environment_has_priority(self):
        path = self.root / ".env"
        path.write_text('SECRET="literal$(never-run)"\nexport ANOTHER=original\n# ignored\n')
        with patch.dict(os.environ, {"ANOTHER": "environment"}):
            values = setup.dotenv(path)
        self.assertEqual(values["SECRET"], "literal$(never-run)")
        self.assertEqual(values["ANOTHER"], "environment")

    def test_no_secret_values_are_shown_during_setup(self):
        path = self.root / ".env"
        path.write_text("MACOS_P12_PASSWORD=private-sentinel\n")
        with patch("sys.argv", ["setup", "--env-file", str(path), "--update-key", str(self.root / "absent"), "--skip-config-archive"]), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            setup.main()
        self.assertNotIn("private-sentinel", output.getvalue())
        self.assertIn("MACOS_P12_PASSWORD", output.getvalue())

    def test_existing_storage_fields_map_to_r2_without_executing_dotenv(self):
        path = self.root / ".env"
        path.write_text('STORAGE_URL="https://' + 'a' * 32 + '.r2.cloudflarestorage.com/bgdesk"\n'
                        'STORAGE_ACCESS_KEY=access-sentinel\nSTORAGE_SECRET=secret-sentinel\n')
        with patch.dict(os.environ, {}, clear=True):
            values = setup.dotenv(path)
        self.assertEqual(values['R2_ACCOUNT_ID'], 'a' * 32)
        self.assertEqual(values['R2_BUCKET'], 'bgdesk')
        self.assertEqual(values['R2_PUBLIC_ORIGIN'], 'https://download.bgdesk.com')
        self.assertEqual(values['R2_ACCESS_KEY_ID'], 'access-sentinel')
        self.assertEqual(values['R2_SECRET_ACCESS_KEY'], 'secret-sentinel')

    def test_preflight_allows_validation_without_publishing_credentials(self):
        output = self.root / 'outputs'
        with patch.dict(os.environ, {'BUILD_PLATFORMS':'macos', 'PUBLISH_RELEASE':'false',
                                    'BGDESK_CONFIG_TOKEN':'test-config-token',
                                    'MACOS_P12_BASE64':'cert', 'MACOS_P12_PASSWORD':'pw',
                                    'MACOS_NOTARY_APPLE_ID':'apple', 'MACOS_NOTARY_PASSWORD':'app-pw',
                                    'GITHUB_OUTPUT':str(output)}, clear=True):
            with patch('sys.stdout', new_callable=io.StringIO):
                plan.main()
        values = dict(line.split('=',1) for line in output.read_text().splitlines())
        self.assertEqual(values['publish'], 'false')
        selected = json.loads(values['matrix'])['include']
        self.assertEqual({(item['platform'], item['arch']) for item in selected},
                         {('macos', 'aarch64'), ('macos', 'x86_64')})
        self.assertNotIn('test-config-token', output.read_text())

    def test_build_plan_allocates_one_runner_for_each_platform_and_architecture(self):
        targets = plan.distribution_matrix('all')['include']
        self.assertEqual({(target['platform'], target['arch']) for target in targets}, {
            ('macos', 'aarch64'), ('macos', 'x86_64'), ('windows', 'x86_64'),
            ('linux', 'aarch64'), ('linux', 'x86_64'), ('android', 'universal'),
        })
        self.assertEqual(len(targets), 6)
        self.assertTrue(all('edition' not in target for target in targets))
        for platform, count in (('macos', 2), ('windows', 1), ('linux', 2), ('android', 1)):
            with self.subTest(platform=platform):
                selected = plan.distribution_matrix(platform)['include']
                self.assertEqual(len(selected), count)
                self.assertTrue(all(target['platform'] == platform for target in selected))
        self.assertEqual(plan.matrix('all')['include'], targets)

    def test_targeted_validation_allocates_only_one_machine_and_keeps_both_editions(self):
        for platform, arch, runner in plan.TARGETS:
            selected = plan.matrix(f'{platform}-{arch}')['include']
            self.assertEqual(selected, [dict(platform=platform, arch=arch, runner=runner)])
            self.assertNotIn('edition', selected[0])

    def test_serial_editions_keep_independent_artifacts_for_publication(self):
        repository = Path(__file__).resolve().parents[2]
        (self.root / 'Cargo.toml').write_text('[package]\nversion = "1.5.2"\n')
        artifacts = self.root / 'artifacts'
        for platform, arch in plan.artifact_targets():
            for edition in editions_for_target(platform, arch):
                mode = '1' if edition == 'cliente' else '0'
                local_platform = 'macOS' if platform == 'macos' else platform
                local_arch = 'arm64' if platform == 'macos' and arch == 'aarch64' else arch
                out = subprocess.check_output([
                    'bash', '-c', 'source "$1"; export BGDESK_CLIENTE="$2"; bgdesk_build_out_dir "$3" "$4"',
                    'build-path', str(repository / 'scripts/build-out-dir.sh'), mode, local_platform, local_arch,
                ], text=True).strip()
                for fmt, path in collect.specs(platform, arch, edition):
                    self.assertEqual(path.parent.as_posix(), out)
                    source = self.root / path
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(f'{platform}/{arch}/{edition}/{fmt}'.encode())
                subprocess.run([
                    sys.executable, str(repository / 'scripts/ci/collect-artifacts.py'),
                    platform, arch, edition, '--output',
                    str(artifacts / f'build-{platform}-{arch}-{edition}'),
                ], cwd=self.root, check=True)
        records = r2.read_records(artifacts, '1.5.2')
        self.assertEqual(len(records), 26)
        for record, path in records:
            self.assertEqual(path.read_bytes(),
                             f"{record['platform']}/{record['arch']}/{record['edition']}/{record['format']}".encode())

    def test_preflight_rejects_partial_or_non_main_publication(self):
        for platforms, ref in (('windows','refs/heads/main'), ('all','refs/heads/test')):
            with patch.dict(os.environ, {'BUILD_PLATFORMS':platforms, 'PUBLISH_RELEASE':'true',
                                        'GITHUB_REF':ref}, clear=True):
                with self.assertRaises(SystemExit):
                    plan.main()

    def configuration_repository(self):
        repository = self.root / 'private-config'
        repository.mkdir()
        subprocess.run(['git', 'init', '--quiet', str(repository)], check=True)
        for name in config_archive.FILES:
            path = repository / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'test configuration, not a real secret')
        (repository / 'certs/ca.key').write_bytes(b'root key must not be exported')
        (repository / 'android-key.jks').write_bytes(b'android is outside the desktop build')
        subprocess.run(['git', '-C', str(repository), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(repository), '-c', 'user.name=CI test', '-c',
                        'user.email=ci@example.test', 'commit', '--quiet', '-m', 'test config'], check=True)
        commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
        return repository, commit

    def test_configuration_snapshot_is_pinned_and_only_contains_desktop_files(self):
        repository, commit = self.configuration_repository()
        encoded = config_archive.export(repository, commit)
        self.assertEqual(encoded, config_archive.export(repository, commit))
        self.assertLess(len(encoded), 48 * 1024)
        self.assertEqual(set(config_archive.validate(encoded, commit)), config_archive.FILES)
        with self.assertRaisesRegex(ValueError, 'pinned submodule commit'):
            config_archive.validate(encoded, '0' * 40)
        restored = self.root / 'restored'
        config_archive.restore(encoded, commit, restored)
        for name in config_archive.FILES:
            self.assertEqual((restored / name).read_bytes(), (repository / name).read_bytes())
            if os.name != 'nt':
                self.assertEqual((restored / name).stat().st_mode & 0o777, 0o600)
        self.assertFalse((restored / 'certs/ca.key').exists())
        self.assertFalse((restored / 'android-key.jks').exists())
        with self.assertRaisesRegex(ValueError, 'empty regular directory'):
            config_archive.restore(encoded, commit, restored)

    def test_configuration_snapshot_rejects_links_and_paths_outside_allowlist(self):
        for name, kind in (('../outside', tarfile.REGTYPE), ('certs/sign.key', tarfile.SYMTYPE)):
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT,
                              pax_headers={'comment':'1' * 40}) as archive:
                entry = tarfile.TarInfo(name)
                entry.type = kind
                if kind == tarfile.SYMTYPE:
                    entry.linkname = '/outside'
                archive.addfile(entry)
            encoded = base64.b64encode(gzip.compress(buffer.getvalue())).decode()
            with self.assertRaisesRegex(ValueError, 'Unexpected path'):
                config_archive.validate(encoded, '1' * 40)


if __name__ == "__main__":
    unittest.main()
