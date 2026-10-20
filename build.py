#!/usr/bin/env python3

import os
import glob
import contextlib
import pathlib
import platform
import zipfile
import urllib.request
import shutil
import hashlib
import re
import subprocess
import argparse
import sys
from pathlib import Path

# Captured at import, while cwd is still the repo root: before Python 3.9 the main script's __file__
# stays relative (bpo-20443), so abspath() re-resolves it against the cwd -- and the ubuntu18.04
# packaging container runs 3.6 and chdir's into flutter/ before it reaches the libdrmtap code.
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

windows = platform.platform().startswith('Windows')
osx = platform.platform().startswith(
    'Darwin') or platform.platform().startswith("macOS")
if windows:
    hbb_name = 'bgdesk.exe'
elif osx:
    hbb_name = 'rustdesk'
else:
    hbb_name = 'bgdesk'
exe_path = 'target/release/' + hbb_name


def _linux_is_arm64() -> bool:
    """Prefer DEB_ARCH from the Docker/build env; fall back to host machine."""
    deb_arch = os.environ.get('DEB_ARCH', '').lower()
    if deb_arch in ('arm64', 'aarch64'):
        return True
    if deb_arch in ('amd64', 'x86_64', 'x64'):
        return False
    machine = platform.machine().lower()
    return machine in ('aarch64', 'arm64')


if windows:
    flutter_build_dir = 'build/windows/x64/runner/Release/'
    flutter_linux_build_cmd = ''
elif osx:
    flutter_build_dir = 'build/macos/Build/Products/Release/'
    flutter_linux_build_cmd = ''
elif _linux_is_arm64():
    flutter_build_dir = 'build/linux/arm64/release/bundle/'
    flutter_linux_build_cmd = 'flutter-elinux build linux --verbose'
else:
    flutter_build_dir = 'build/linux/x64/release/bundle/'
    flutter_linux_build_cmd = 'flutter build linux --release'
flutter_build_dir_2 = f'flutter/{flutter_build_dir}'
skip_cargo = False


def ensure_cargo_on_path() -> None:
    """Make cargo available when the shell did not source ~/.cargo/env."""
    if shutil.which('cargo'):
        return
    cargo_bin = os.path.join(os.path.expanduser('~'), '.cargo', 'bin')
    cargo = os.path.join(cargo_bin, 'cargo.exe' if windows else 'cargo')
    if os.path.isfile(cargo):
        os.environ['PATH'] = cargo_bin + os.pathsep + os.environ.get('PATH', '')
        return
    sys.stderr.write(
        'cargo não encontrado. Instale o Rust (https://rustup.rs) '
        'e rode: source "$HOME/.cargo/env"\n')
    sys.exit(1)


def use_flutter_github() -> bool:
    """Clone GitHub master + engine local: apenas se BGDESK_FLUTTER_GITHUB=1."""
    return osx and os.environ.get('BGDESK_FLUTTER_GITHUB') == '1'


def use_flutter_stable() -> bool:
    """SDK Flutter stable oficial (pré-compilado) para builds manuais macOS."""
    return os.environ.get('BGDESK_FLUTTER_STABLE') == '1'


def flutter_bin() -> str:
    root = os.environ.get('FLUTTER_ROOT', '')
    if root:
        cmd = os.path.join(root, 'bin', 'flutter')
        if os.path.isfile(cmd):
            return cmd
        sys.stderr.write(f'Flutter não encontrado em {cmd}\n')
        sys.exit(1)
    return 'flutter'


def verify_flutter_root() -> None:
    cmd = flutter_bin()
    import subprocess
    result = subprocess.run([cmd, '--version'], capture_output=True, text=True)
    out = result.stdout + result.stderr
    first = out.splitlines()[0] if out.splitlines() else out
    if use_flutter_stable():
        expected = os.environ.get('FLUTTER_STABLE_VERSION', '')
        if expected and expected not in out:
            sys.stderr.write(
                f'ERRO: Flutter não é a versão stable {expected}:\n{out}\n')
            sys.exit(1)
        if 'channel stable' not in out:
            sys.stderr.write(
                'ERRO: Flutter não está no channel stable:\n' + out)
            sys.exit(1)
        sys.stderr.write(f'[build.py] {first}\n')
        sys.stderr.write(
            f'[build.py] FLUTTER_STABLE_VERSION={expected}\n')
        return
    if not use_flutter_github():
        return
    if 'github.com/flutter/flutter' not in out:
        sys.stderr.write(
            'ERRO: FLUTTER_ROOT não aponta para o clone oficial do GitHub:\n' + out)
        sys.exit(1)
    expected_commit = os.environ.get('FLUTTER_GITHUB_COMMIT', '')
    if expected_commit:
        flutter_root = os.environ.get('FLUTTER_ROOT', '')
        head = subprocess.run(
            ['git', '-C', flutter_root, 'rev-parse', 'HEAD'],
            capture_output=True, text=True)
        actual = head.stdout.strip()
        if actual != expected_commit:
            sys.stderr.write(
                f'ERRO: Flutter não está no commit fixo {expected_commit} (HEAD={actual})\n')
            sys.exit(1)
    sys.stderr.write(f'[build.py] {first}\n')
    rev = os.environ.get('FLUTTER_GITHUB_REV', '')
    pinned = os.environ.get('FLUTTER_GITHUB_COMMIT', '')
    if pinned:
        sys.stderr.write(f'[build.py] FLUTTER_GITHUB_COMMIT={pinned}\n')
    if rev:
        sys.stderr.write(f'[build.py] FLUTTER_GITHUB_REV={rev}\n')


def flutter_local_engine_flags() -> str:
    """Flags --local-engine* só com FLUTTER_USE_LOCAL_ENGINE=1 (opt-in)."""
    if not osx:
        return ''
    if os.environ.get('FLUTTER_USE_LOCAL_ENGINE') != '1':
        return ''
    root = os.environ.get('FLUTTER_ROOT', '')
    if not root:
        return ''
    local = os.environ.get('FLUTTER_LOCAL_ENGINE', '')
    host = os.environ.get('FLUTTER_LOCAL_ENGINE_HOST', local)
    engine_src = os.environ.get('FLUTTER_ENGINE', '')
    if not local:
        mac_arch = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64'
        config = f'host_release_{mac_arch}' if mac_arch == 'arm64' else 'host_release'
        out = os.path.join(root, 'engine', 'src', 'out', config)
        if os.path.isdir(out):
            local = config
            host = config
        else:
            return ''
    if not engine_src:
        engine_src = os.path.join(root, 'engine', 'src')
    if not os.path.isdir(engine_src):
        return ''
    return (
        f' --local-engine={local}'
        f' --local-engine-host={host}'
        f' --local-engine-src-path={engine_src}'
    )


def write_flutter_build_stamp() -> None:
    if not use_flutter_github() and not use_flutter_stable():
        return
    import subprocess
    cmd = flutter_bin()
    root = Path(__file__).resolve().parent
    stamp_dir = root / 'build'
    stamp_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([cmd, '--version'], capture_output=True, text=True)
    stamp = stamp_dir / 'flutter-build-stamp.txt'
    extra = ''
    if use_flutter_stable():
        extra += f'FLUTTER_STABLE_VERSION={os.environ.get("FLUTTER_STABLE_VERSION", "")}\n'
        extra += 'FLUTTER_ENGINE=prebuilt-stable\n'
    rev = os.environ.get('FLUTTER_GITHUB_REV', '')
    patch_applied = os.environ.get('FLUTTER_ENGINE_PATCH_APPLIED', '')
    local_flags = flutter_local_engine_flags()
    if patch_applied:
        extra += f'FLUTTER_ENGINE_PATCH=4332f3e-macos-occlusion-resume applied={patch_applied}\n'
    if local_flags:
        extra += f'FLUTTER_LOCAL_ENGINE_FLAGS={local_flags.strip()}\n'
    stamp.write_text(
        f'FLUTTER_ROOT={os.environ.get("FLUTTER_ROOT", "")}\n'
        f'FLUTTER_GITHUB_COMMIT={os.environ.get("FLUTTER_GITHUB_COMMIT", "")}\n'
        f'FLUTTER_GITHUB_REV={rev}\n'
        f'{extra}'
        f'{result.stdout}{result.stderr}',
        encoding='utf-8',
    )
    sys.stderr.write(f'[build.py] stamp: {stamp}\n')


def get_deb_arch() -> str:
    custom_arch = os.environ.get("DEB_ARCH")
    if custom_arch is None:
        return "amd64"
    return custom_arch

def get_deb_extra_depends() -> str:
    custom_arch = os.environ.get("DEB_ARCH")
    if custom_arch == "armhf": # for arm32v7 libsciter-gtk.so
        return ", libatomic1"
    return ""

def system2(cmd):
    exit_code = os.system(cmd)
    if exit_code != 0:
        sys.stderr.write(f"Error occurred when executing: `{cmd}`. Exiting.\n")
        sys.exit(-1)


def get_version():
    with open("Cargo.toml", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("version"):
                return line.replace("version", "").replace("=", "").replace('"', '').strip()
    return ''


def parse_rc_features(feature):
    available_features = {}
    apply_features = {}
    if not feature:
        feature = []

    def platform_check(platforms):
        if windows:
            return 'windows' in platforms
        elif osx:
            return 'osx' in platforms
        else:
            return 'linux' in platforms

    def get_all_features():
        features = []
        for (feat, feat_info) in available_features.items():
            if platform_check(feat_info['platform']):
                features.append(feat)
        return features

    if isinstance(feature, str) and feature.upper() == 'ALL':
        return get_all_features()
    elif isinstance(feature, list):
        if windows:
            # download third party is deprecated, we use github ci instead.
            # feature.append('PrivacyMode')
            pass
        for feat in feature:
            if isinstance(feat, str) and feat.upper() == 'ALL':
                return get_all_features()
            if feat in available_features:
                if platform_check(available_features[feat]['platform']):
                    apply_features[feat] = available_features[feat]
            else:
                print(f'Unrecognized feature {feat}')
        return apply_features
    else:
        raise Exception(f'Unsupported features param {feature}')


def make_parser():
    parser = argparse.ArgumentParser(description='Build script.')
    parser.add_argument(
        '-f',
        '--feature',
        dest='feature',
        metavar='N',
        type=str,
        nargs='+',
        default='',
        help='Integrate features, windows only.'
             'Available: [Not used for now]. Special value is "ALL" and empty "". Default is empty.')
    parser.add_argument('--flutter', action='store_true',
                        help='Build flutter package', default=False)
    parser.add_argument(
        '--hwcodec',
        action='store_true',
        help='Enable feature hwcodec' + (
            '' if windows or osx else ', need libva-dev.')
    )
    parser.add_argument(
        '--vram',
        action='store_true',
        help='Enable feature vram, only available on windows now.'
    )
    parser.add_argument(
        '--portable',
        action='store_true',
        help='Build windows portable'
    )
    parser.add_argument(
        '--unix-file-copy-paste',
        action='store_true',
        help='Build with unix file copy paste feature'
    )
    parser.add_argument(
        '--incoming-only',
        '--cliente',
        action='store_true',
        dest='incoming_only',
        help='Build cliente edition (incoming connections only, no outgoing)',
    )
    drm_options = parser.add_mutually_exclusive_group()
    drm_options.add_argument(
        '--drm',
        dest='drm',
        action='store_true',
        help='Linux only: build the DRM/KMS capture backend (bundles libdrmtap.so, '
             'dlopen-ed in-process by the root service). Enabled by default on Linux.'
    )
    drm_options.add_argument('--no-drm', dest='drm', action='store_false',
                             help='Build without unattended Wayland capture (portable builds).')
    parser.set_defaults(drm=not windows and not osx)
    parser.add_argument(
        '--print-features',
        action='store_true',
        help='Print the cargo feature list these flags select, and exit without building. For a '
             'caller that runs its own cargo line and then packages with --skip-cargo: it can ask '
             'for the list rather than repeat it, so the two cannot drift.'
    )
    parser.add_argument(
        '--skip-cargo',
        action='store_true',
        help='Skip cargo build process, only flutter version + Linux supported currently'
    )
    if windows:
        parser.add_argument(
            '--skip-portable-pack',
            action='store_true',
            help='Skip packing, only flutter version + Windows supported'
        )
    parser.add_argument(
        "--package",
        type=str
    )
    if osx:
        parser.add_argument(
            '--screencapturekit',
            action='store_true',
            help='Enable feature screencapturekit'
        )
    return parser


# Generate build script for docker
#
# it assumes all build dependencies are installed in environments
# Note: do not use it in bare metal, or may break build environments
def generate_build_script_for_docker():
    with open("/tmp/build.sh", "w") as f:
        f.write('''
            #!/bin/bash
            # environment
            export CPATH="$(clang -v 2>&1 | grep "Selected GCC installation: " | cut -d' ' -f4-)/include"
            # flutter
            pushd /opt
            wget https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.0.5-stable.tar.xz
            tar -xvf flutter_linux_3.0.5-stable.tar.xz
            export PATH=`pwd`/flutter/bin:$PATH
            popd
            # flutter_rust_bridge
            dart pub global activate ffigen --version 5.0.1
            pushd /tmp && git clone https://github.com/SoLongAndThanksForAllThePizza/flutter_rust_bridge --depth=1 && popd
            pushd /tmp/flutter_rust_bridge/frb_codegen && cargo install --path . && popd
            pushd flutter && flutter pub get && popd
            ~/.cargo/bin/flutter_rust_bridge_codegen --rust-input ./src/flutter_ffi.rs --dart-output ./flutter/lib/generated_bridge.dart
            # install vcpkg
            pushd /opt
            export VCPKG_ROOT=`pwd`/vcpkg
            git clone https://github.com/microsoft/vcpkg
            vcpkg/bootstrap-vcpkg.sh
            popd
            $VCPKG_ROOT/vcpkg install --x-install-root="$VCPKG_ROOT/installed"
            # build rustdesk
            ./build.py --flutter --hwcodec
        ''')
    system2("chmod +x /tmp/build.sh")
    system2("bash /tmp/build.sh")


# Downloading third party resources is deprecated.
# We can use this function in an offline build environment.
# Even in an online environment, we recommend building third-party resources yourself.
def download_extract_features(features, res_dir):
    import re

    proxy = ''

    def req(url):
        if not proxy:
            return url
        else:
            r = urllib.request.Request(url)
            r.set_proxy(proxy, 'http')
            r.set_proxy(proxy, 'https')
            return r

    for (feat, feat_info) in features.items():
        includes = feat_info['include'] if 'include' in feat_info and feat_info['include'] else []
        includes = [re.compile(p) for p in includes]
        excludes = feat_info['exclude'] if 'exclude' in feat_info and feat_info['exclude'] else []
        excludes = [re.compile(p) for p in excludes]

        print(f'{feat} download begin')
        download_filename = feat_info['zip_url'].split('/')[-1]
        checksum_md5_response = urllib.request.urlopen(
            req(feat_info['checksum_url']))
        for line in checksum_md5_response.read().decode('utf-8').splitlines():
            if line.split()[1] == download_filename:
                checksum_md5 = line.split()[0]
                filename, _headers = urllib.request.urlretrieve(feat_info['zip_url'],
                                                                download_filename)
                md5 = hashlib.md5(open(filename, 'rb').read()).hexdigest()
                if checksum_md5 != md5:
                    raise Exception(f'{feat} download failed')
                print(f'{feat} download end. extract bein')
                zip_file = zipfile.ZipFile(filename)
                zip_list = zip_file.namelist()
                for f in zip_list:
                    file_exclude = False
                    for p in excludes:
                        if p.match(f) is not None:
                            file_exclude = True
                            break
                    if file_exclude:
                        continue

                    file_include = False if includes else True
                    for p in includes:
                        if p.match(f) is not None:
                            file_include = True
                            break
                    if file_include:
                        print(f'extract file {f}')
                        zip_file.extract(f, res_dir)
                zip_file.close()
                os.remove(download_filename)
                print(f'{feat} extract end')


def external_resources(flutter, args, res_dir):
    features = parse_rc_features(args.feature)
    if not features:
        return

    print(f'Build with features {list(features.keys())}')
    if os.path.isdir(res_dir) and not os.path.islink(res_dir):
        shutil.rmtree(res_dir)
    elif os.path.exists(res_dir):
        raise Exception(f'Find file {res_dir}, not a directory')
    os.makedirs(res_dir, exist_ok=True)
    download_extract_features(features, res_dir)
    if flutter:
        os.makedirs(flutter_build_dir_2, exist_ok=True)
        for f in pathlib.Path(res_dir).iterdir():
            print(f'{f}')
            if f.is_file():
                shutil.copy2(f, flutter_build_dir_2)
            else:
                shutil.copytree(f, f'{flutter_build_dir_2}{f.stem}')


def get_features(args):
    features = ['inline'] if not args.flutter else []
    if args.hwcodec:
        features.append('hwcodec')
    if args.vram:
        features.append('vram')
    if args.flutter:
        features.append('flutter')
    if args.unix_file_copy_paste:
        features.append('unix-file-copy-paste')
    if args.drm:
        # Say so rather than quietly handing back a stock build: the backend is Linux-only, so on
        # any other host the flag cannot be honoured and the resulting binary would look like a
        # DRM build without being one.
        if windows or osx:
            raise Exception('--drm is Linux only')
        features.append('drm')
        # Native packages include the wake path for displays disabled by idle. It remains
        # switchable at runtime through OPTION_ENABLE_DRM_DISPLAY_WAKE.
        features.append('drm-wake')
    if osx:
        if args.screencapturekit:
            features.append('screencapturekit')
    if args.incoming_only:
        features.append('incoming-only')
    print("features:", features)
    return features


def generate_control_file(version):
    control_file_path = "../res/DEBIAN/control"
    system2('/bin/rm -rf %s' % control_file_path)

    content = """Package: bgdesk
Section: net
Priority: optional
Version: %s
Architecture: %s
Maintainer: bgdesk <contato@boagestao.com.br>
Homepage: https://boagestao.com.br
Depends: libgtk-3-0t64 | libgtk-3-0, libxcb-randr0, libxdo3 | libxdo4, libxfixes3, libxcb-shape0, libxcb-xfixes0, libasound2t64 | libasound2, libsystemd0, curl, libva2, libva-drm2, libva-x11-2, libgstreamer-plugins-base1.0-0, gstreamer1.0-pipewire%s
Recommends: libayatana-appindicator3-1
Description: BGDesk remote desktop software.

""" % (version, get_deb_arch(), get_deb_extra_depends())
    file = open(control_file_path, "w")
    file.write(content)
    file.close()


def ffi_bindgen_function_refactor():
    # workaround ffigen
    system2(
        'sed -i "s/ffi.NativeFunction<ffi.Bool Function(DartPort/ffi.NativeFunction<ffi.Uint8 Function(DartPort/g" flutter/lib/generated_bridge.dart')


def rename_linux_artifacts(target_triple=None):
    if windows or osx:
        return
    script = os.path.join(os.path.dirname(__file__), 'scripts', 'rename-linux-artifacts.sh')
    if target_triple:
        system2(f'bash {script} {target_triple}')
    else:
        system2(f'bash {script}')


def rename_windows_artifacts(target_triple=None):
    if not windows:
        return
    script = os.path.join(os.path.dirname(__file__), 'scripts', 'rename-windows-artifacts.ps1')
    if target_triple:
        system2(f'powershell -NoProfile -ExecutionPolicy Bypass -File {script} -TargetTriple {target_triple}')
    else:
        system2(f'powershell -NoProfile -ExecutionPolicy Bypass -File {script}')


def move_cargo_bundle_deb():
    deb_dir = Path('target/release/bundle/deb')
    candidates = sorted(deb_dir.glob('bgdesk*.deb')) + sorted(deb_dir.glob('rustdesk*.deb'))
    if not candidates:
        raise FileNotFoundError(f'No cargo bundle deb in {deb_dir}')
    shutil.move(str(candidates[0]), './bgdesk.deb')


def normalize_sciter_deb_binary():
    rustdesk_bin = Path('tmpdeb/usr/bin/rustdesk')
    bgdesk_bin = Path('tmpdeb/usr/bin/bgdesk')
    if rustdesk_bin.is_file() and not bgdesk_bin.is_file():
        rustdesk_bin.rename(bgdesk_bin)

# libdrmtap is fetched at build time from the rustdesk-org fork at a pinned
# commit — the same way rustdesk sources its other native build deps (vcpkg,
# flutter_rust_bridge, ...), rather than carrying a git submodule. It is the ONLY
# pin for the drm backend: rustdesk dlopens this .so at runtime and does not depend on
# the libdrmtap-sys crate (whose build.rs would statically link the C tree, a helper and
# libdrm/seccomp/cap). DRMTAP_REPO, DRMTAP_SHA and DRMTAP_PREBUILT_DIR override it for local testing
# or another fork, and each requires DRMTAP_ALLOW_UNPINNED=1 alongside it (see below).
# The commit is fetched directly by sha, so no branch or tag name takes part in the build: see
# build_libdrmtap_so(). This is the SINGLE source of truth for the pin, deliberately not duplicated in
# any workflow, so a bump is one edit here (plus the informational version comment in
# libs/scrap/Cargo.toml). This commit is libdrmtap v0.5.12.
LIBDRMTAP_REPO_PINNED = 'https://github.com/rustdesk-org/libdrmtap'
LIBDRMTAP_SHA_PINNED = '5936a7a88b94aa43516a3dd0eb509d2383f31e2d'
LIBDRMTAP_REPO = os.environ.get('DRMTAP_REPO', LIBDRMTAP_REPO_PINNED)
LIBDRMTAP_SHA = os.environ.get('DRMTAP_SHA', LIBDRMTAP_SHA_PINNED)
# Every way of getting a different .so than the pin needs the same explicit opt-in. Otherwise the
# claim this feature rests on -- that the privileged capture library is the reviewed object at
# LIBDRMTAP_SHA_PINNED -- would hold only as long as nobody happened to have one of these set, and a
# build that silently used something else would be indistinguishable from one that did not.
# DRMTAP_PREBUILT_DIR is in the list because it is the widest of the three: it skips both the fetch
# and the sha verification and hands over an object built from nothing this script can see.
DRMTAP_UNPINNED_OK = os.environ.get('DRMTAP_ALLOW_UNPINNED') == '1'


def _prebuilt_dir_is_the_pinned_checkout(prebuilt_dir):
    # A .so built from this repo's own third_party/libdrmtap at the pinned sha is the pinned object,
    # not an override, so it must not need the opt-in. This is how CI hands the library from a step
    # that has meson to a packaging container that does not.
    src = os.path.join(REPO_ROOT, 'third_party', 'libdrmtap')
    try:
        inside = os.path.commonpath([os.path.abspath(prebuilt_dir), src]) == src
    except ValueError:
        return False
    if not inside or not os.path.isdir(os.path.join(src, '.git')):
        return False
    try:
        head = subprocess.check_output(['git', '-C', src, 'rev-parse', 'HEAD']).decode().strip()
    except (subprocess.SubprocessError, OSError):
        return False
    return head == LIBDRMTAP_SHA


def _validate_libdrmtap_pin():
    # Called from build_libdrmtap_so(), NOT at import: a stock (non --drm) build must stay
    # byte-identical to upstream in behaviour too, and leftover DRMTAP_* variables in the
    # environment (or a malformed sha) must not be able to fail a build that never touches
    # libdrmtap.
    # `or None` so an empty value reads as unset here exactly as it does in build_libdrmtap_so(),
    # which tests it for truthiness.
    prebuilt = os.environ.get('DRMTAP_PREBUILT_DIR') or None
    if prebuilt and _prebuilt_dir_is_the_pinned_checkout(prebuilt):
        prebuilt = None
    overridden = [
        name
        for name, value, pinned in (
            ('DRMTAP_REPO', LIBDRMTAP_REPO, LIBDRMTAP_REPO_PINNED),
            ('DRMTAP_SHA', LIBDRMTAP_SHA, LIBDRMTAP_SHA_PINNED),
            ('DRMTAP_PREBUILT_DIR', prebuilt, None),
        )
        if value != pinned
    ]
    if overridden and not DRMTAP_UNPINNED_OK:
        raise Exception(
            f'{", ".join(overridden)} would build libdrmtap from something other than the pinned '
            f'{LIBDRMTAP_REPO_PINNED} at {LIBDRMTAP_SHA_PINNED}. That is supported for local work and '
            'cross-builds, but it has to be deliberate: set DRMTAP_ALLOW_UNPINNED=1 as well.')
    if overridden:
        print(f'WARNING: libdrmtap is NOT the pinned build ({", ".join(overridden)} set)')
    # Both are interpolated into shell commands below, and both are env-overridable, so validate
    # their SHAPE before they get there. This is not only about a hostile environment: a truncated
    # or abbreviated sha would otherwise reach `git fetch` and fail with something far less obvious
    # than saying so here, and an abbreviated one would defeat the point of pinning.
    if not re.fullmatch(r'[0-9a-f]{40}', LIBDRMTAP_SHA):
        raise Exception(
            f'DRMTAP_SHA must be a full 40-character commit sha, got {LIBDRMTAP_SHA!r}')
    if not re.fullmatch(r'(https://|git@)[A-Za-z0-9._~:/@-]+', LIBDRMTAP_REPO):
        raise Exception(f'DRMTAP_REPO does not look like a git remote url: {LIBDRMTAP_REPO!r}')


def _single_real_so(paths, where):
    # Return the one real libdrmtap.so.0.* object among `paths`, failing if there are zero or several.
    # glob order is arbitrary, so silently taking [0] could ship a stale or wrong-arch object left
    # over from an earlier build; a mismatch should fail the build loudly instead.
    real = sorted(p for p in paths if os.path.isfile(p) and not os.path.islink(p))
    if len(real) != 1:
        raise Exception(
            f'expected exactly one real libdrmtap.so.0.* in {where}, found {len(real)}: {real}')
    return real[0]


def build_libdrmtap_so():
    # Build libdrmtap.so from the rustdesk-org fork, fetched at the pinned LIBDRMTAP_SHA. The
    # pivot dlopen-s this .so in-process in the root service (which already holds
    # CAP_SYS_ADMIN) — no setcap helper, no privileged child. Only the shared
    # library target is built (the source also carries a helper binary we do not
    # ship). Returns the path to the built versioned .so (e.g. libdrmtap.so.0.4.x).
    _validate_libdrmtap_pin()
    # Allow a caller (e.g. CI) to build the .so ahead of time and hand it in via
    # DRMTAP_PREBUILT_DIR (must contain the real libdrmtap.so.0.* object).
    prebuilt_dir = os.environ.get('DRMTAP_PREBUILT_DIR')
    if prebuilt_dir:
        # DRMTAP_PREBUILT_DIR explicitly names the artifact source, so honor it strictly: fail
        # (rather than silently falling back to a source build) if it holds no single real .so.
        prebuilt = glob.glob(os.path.join(prebuilt_dir, 'libdrmtap.so.0.*'))
        so = _single_real_so(prebuilt, f'DRMTAP_PREBUILT_DIR={prebuilt_dir}')
        # Check the stub case HERE too, not only on the source path below. This is the widest
        # override of the three -- no fetch, no sha verification, an object built by something this
        # script cannot see -- so it is the likeliest to hand over a CPU-only build, and skipping the
        # assertion on exactly this path would leave the check guarding only the case that was
        # already trustworthy. The helper check rides along for the same reason, and it matters
        # more here than anywhere: this is the branch the packaging workflow takes.
        _assert_so_has_egl(so)
        _assert_so_has_no_helper(so)
        return so
    # Fetch the pinned source if it is not already present. third_party/libdrmtap is not a submodule
    # anymore; it is git-ignored. The commit is fetched BY SHA rather than by cloning a branch:
    # `clone --depth 1 --branch main` only ever fetches the tip, so the moment upstream pushes to
    # `main` the pinned commit is not in the shallow clone at all and the build fails on an unreachable
    # object. Fetching the sha needs no branch name, so it keeps working across every upstream push and
    # is immune to a ref being moved or repointed.
    src = os.path.join(REPO_ROOT, 'third_party', 'libdrmtap')
    if not os.path.exists(os.path.join(src, 'meson.build')):
        if os.path.isdir(src):
            shutil.rmtree(src)
        os.makedirs(src, exist_ok=True)
        system2(f'git -C "{src}" init -q')
        system2(f'git -C "{src}" remote add origin {LIBDRMTAP_REPO}')
        system2(f'git -C "{src}" fetch --depth 1 origin {LIBDRMTAP_SHA}')
        system2(f'git -C "{src}" checkout -q FETCH_HEAD')
    # Verify the pin whenever the source is a GIT checkout. A fetch by sha cannot resolve to anything
    # else, so this now guards the OTHER case: a reused checkout left by an earlier build at a
    # different pin, which is what a bump leaves behind. Reject and remove it so the next run re-fetches
    # cleanly. A NON-git tree placed here on purpose (a developer building unreleased local libdrmtap
    # source) has nothing to verify and is used as-is.
    if os.path.isdir(os.path.join(src, '.git')):
        got_sha = subprocess.check_output(
            ['git', '-C', src, 'rev-parse', 'HEAD']).decode().strip()
        if got_sha != LIBDRMTAP_SHA:
            shutil.rmtree(src, ignore_errors=True)
            raise Exception(
                f'libdrmtap at {src} is {got_sha}, expected {LIBDRMTAP_SHA} '
                f'(stale checkout from a different pin; removed, re-run to re-fetch)')
    build_dir = os.path.join(src, 'build-pkg')
    # Configure a fresh dir, or RE-configure one an earlier build left behind. Without the second
    # branch a build-pkg created before this option was added keeps its old configuration, meson
    # skips setup, and the compile produces a helper-enabled .so. The assertion below then fails
    # the build rather than shipping it, so this is a developer-build correctness fix and not a
    # security one -- but it turns a confusing failure into no failure at all.
    if not os.path.exists(os.path.join(build_dir, 'build.ninja')):
        # -Dhelper=disabled: rustdesk never uses the privileged helper. The capture context is
        # opened only in the root service (every drmtap_open lives in src/ipc/drm.rs), which
        # already has CAP_SYS_ADMIN, and the unprivileged side opens a render node instead. Without
        # this the library still carries the fallback: a fork/exec that walks six hardcoded paths,
        # two of them under /usr/local, and execs the first that passes access(X_OK) with no check
        # of its owner or mode -- inside the ROOT process. The option compiles that path out
        # entirely. Requested by the maintainer on rustdesk#16242.
        system2(f'meson setup "{build_dir}" "{src}" --buildtype=release -Dhelper=disabled')
    else:
        system2(f'meson configure "{build_dir}" -Dhelper=disabled')
    # Build only the shared library, not the bundled helper binary or the static archive. Since
    # libdrmtap 0.4.11 the project is `both_libraries` (a version-scripted .so + a static .a), so the
    # bare `drmtap` target is ambiguous ("drmtap:shared_library" vs "drmtap:static_library"); ask for
    # the shared one explicitly (rustdesk dlopens the .so and never needs the archive).
    system2(f'meson compile -C "{build_dir}" drmtap:shared_library')
    sos = glob.glob(os.path.join(build_dir, 'libdrmtap.so.0.*'))
    # keep the real object (libdrmtap.so.0.4.x), not the .so/.so.0 symlinks or meson's .p dir, and
    # require exactly one so a stale object from an earlier build is never silently picked.
    so = _single_real_so(sos, f'the libdrmtap meson build dir {build_dir}')
    _assert_so_has_egl(so)
    _assert_so_has_no_helper(so)
    return so


def _assert_so_has_no_helper(so_path):
    # Asserted on the ARTIFACT for the same reason the EGL check is: a build flag cannot notice a
    # stale object left by an earlier build, or one substituted by hand, and `-Dhelper=disabled` is
    # silently accepted by meson versions that predate the option. What the option removes is the
    # whole fork/exec path, so the produced .so imports no socketpair and carries none of the
    # helper search paths; both go to zero, measured on libdrmtap 0.5.6 (4 -> 0 and 3 -> 0).
    #
    # This matters because the object is loaded by the ROOT service. With the path compiled in, a
    # caller that ever lost CAP_SYS_ADMIN would exec whatever sits at the first of six hardcoded
    # locations that passes access(X_OK), without checking its owner or its mode.
    with open(so_path, 'rb') as f:
        blob = f.read()
    found = [m.decode() for m in (b'socketpair', b'/usr/libexec/drmtap-helper') if m in blob]
    if found:
        raise Exception(
            f'{so_path} still carries the privileged-helper fallback ({", ".join(found)}). '
            f'It must be built with -Dhelper=disabled: rustdesk captures as root and never uses '
            f'the helper, so this is a fork/exec path in the privileged process that nothing '
            f'reaches. Delete third_party/libdrmtap/build-pkg and rebuild.')


def _assert_so_has_egl(so_path):
    # libdrmtap treats egl/glesv2 as OPTIONAL dependencies: without their headers and pkg-config
    # files, meson silently builds a CPU-only stub. That stub still exports every symbol the loader
    # checks for, so nothing downstream notices -- and the split architecture depends entirely on the
    # unprivileged side EGL-detiling the scanout it receives. The result is a build where DRM capture
    # quietly degrades to PipeWire on every tiled-scanout host, which is most of them.
    #
    # Assert on the ARTIFACT rather than passing an option that demands it: `-Degl=enabled` exists
    # only in libdrmtap past 0.4.15, and checking what was actually produced also catches a stale or
    # hand-substituted object, which a build flag cannot.
    #
    # EGL is reached by lazy dlopen, on purpose, so that the privileged service never links the GPU
    # stack. That means there is no DT_NEEDED to look for and an ELF-level check reports "no EGL" on a
    # perfectly good library; the dlopen name and an extension symbol are what a CPU-only stub really
    # lacks.
    try:
        with open(so_path, 'rb') as f:
            blob = f.read()
    except OSError as err:
        raise Exception(f'cannot read the built libdrmtap at {so_path}: {err}') from err
    missing = [m for m in (b'libEGL.so.1', b'eglCreateImageKHR') if m not in blob]
    if missing:
        raise Exception(
            f'{so_path} looks like a CPU-only libdrmtap stub (missing '
            f'{", ".join(m.decode() for m in missing)}): the EGL detile path the split capture '
            'depends on is not in it, and DRM capture would silently fall back to PipeWire. '
            'Install the EGL development packages and rebuild (Debian/Ubuntu: libegl-dev '
            'libgles2-mesa-dev; Arch: mesa libglvnd).')


def assert_so_satisfies_the_runtime_abi_gate(so_path):
    """The .so we are about to ship must be one the RUNTIME will actually accept.

    `abi_accepted` in libs/scrap/src/common/drmtap_dl.rs is the only place the pinned library's
    version is ever validated, and it runs at dlopen time on the USER's machine. Nothing in the
    build or in CI compared the two, so the pin and the gate could drift apart and every existing
    assertion would still pass: the EGL check does not look at the version, the CI symbol contract
    does not call drmtap_version(), and the deb-contents regex matches any `libdrmtap.so.0.X.Y`.
    A green pipeline could therefore produce a deb in which DRM capture can never start, and the
    only symptom on the host is one log line before it falls back to the portal.

    So parse the gate out of the Rust and apply it here, to the object being staged. This is the
    same rule, not a copy of the numbers: if someone bumps the constants, this reads the new ones.
    """
    m = re.search(r'libdrmtap\.so\.(\d+)\.(\d+)\.(\d+)', os.path.basename(so_path))
    if not m:
        # Not a versioned soname (a local dev build, say). The gate cannot be evaluated, and
        # inventing a verdict would be worse than saying so.
        print(f'[drm] cannot read a version out of {so_path}; skipping the ABI-gate cross-check')
        return
    so_ver = tuple(int(g) for g in m.groups())
    # REPO_ROOT, not abspath(__file__): both callers have chdir'd into flutter/ by now.
    gate_path = os.path.join(REPO_ROOT, 'libs', 'scrap', 'src', 'common', 'drmtap_dl.rs')
    with open(gate_path) as f:
        gate_src = f.read()

    def _const(name):
        mm = re.search(rf'const {name}: c_int = (\d+);', gate_src)
        return int(mm.group(1)) if mm else None

    major, minor = _const('DRMTAP_ABI_MAJOR'), _const('DRMTAP_ABI_MINOR')
    mm = re.search(r'const DRMTAP_MIN_MINOR_PATCH: \(c_int, c_int\) = \((\d+), (\d+)\);', gate_src)
    floor = (int(mm.group(1)), int(mm.group(2))) if mm else None
    if major is None or minor is None or floor is None:
        raise Exception(
            'could not parse the libdrmtap ABI gate out of drmtap_dl.rs (DRMTAP_ABI_MAJOR / '
            'DRMTAP_ABI_MINOR / DRMTAP_MIN_MINOR_PATCH). The gate moved and this check did not; '
            'fix the check rather than removing it, or the pin and the gate can drift silently.')
    accepted = so_ver[0] == major and so_ver[1] == minor and (so_ver[1], so_ver[2]) >= floor
    if not accepted:
        raise Exception(
            f'the libdrmtap being packaged is {so_ver[0]}.{so_ver[1]}.{so_ver[2]}, which the '
            f'runtime loader would REFUSE: drmtap_dl.rs accepts exactly major {major}, minor '
            f'{minor}, patch >= {floor[1]}. Shipping it produces a deb whose DRM capture can never '
            'start. Move the build pin and the gate together, or fix whichever one is wrong.')
    print(f'[drm] libdrmtap {so_ver[0]}.{so_ver[1]}.{so_ver[2]} satisfies the runtime ABI gate '
          f'(major {major}, minor {minor}, patch >= {floor[1]})')


def validated_bundle_drmtap(payload):
    """Require an actual DRM binary and an EGL-capable library with the pinned ABI."""
    assert_staged_binary_is_drm(payload)
    so = _single_real_so(glob.glob(os.path.join(payload, 'libdrmtap.so.0.*')), payload)
    _assert_so_has_egl(so)
    _assert_so_has_no_helper(so)
    assert_so_satisfies_the_runtime_abi_gate(so)
    return so


def prepare_drm_bundle(payload):
    """Carry the library alongside the bundle so DEB, RPM and offline Arch reuse it."""
    assert_staged_binary_is_drm(payload)
    if not glob.glob(os.path.join(payload, 'libdrmtap.so.0.*')):
        so = build_libdrmtap_so()
        shutil.copy2(so, os.path.join(payload, os.path.basename(so)))
    return validated_bundle_drmtap(payload)


def stage_bundle_drmtap(payload, package_root):
    """Install at the absolute dlopen path, independent of RPM's lib/lib64 macros."""
    so = validated_bundle_drmtap(payload)
    destination = Path(package_root) / 'usr/lib/bgdesk'
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(so, str(destination / os.path.basename(so)))
    soname = destination / 'libdrmtap.so.0'
    if soname.is_symlink() or soname.exists():
        soname.unlink()
    soname.symlink_to(os.path.basename(so))
    # The bundle is an intermediate; the installed library belongs only at the private path.
    installed_payload = Path(package_root) / 'usr/share/bgdesk'
    for extra in installed_payload.glob('libdrmtap.so*'):
        extra.unlink()


def _max_glibc_minor(path):
    # Read from .dynstr rather than via objdump so packaging needs no binutils; chunked because
    # librustdesk.so is ~45 MB.
    best = 0
    with open(path, 'rb') as f:
        tail = b''
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                return best
            for m in re.finditer(rb'GLIBC_2\.(\d+)', tail + chunk):
                best = max(best, int(m.group(1)))
            tail = chunk[-16:]


def add_drm_deb_dependencies(control_path):
    """Keep the normal package name; Wayland unattended is now the native default."""
    root = str(Path(control_path).parent.parent)
    libraries = glob.glob(os.path.join(root, 'usr/lib/bgdesk/libdrmtap.so.0.*'))
    if not libraries:
        raise Exception('cannot declare DRM dependencies without the staged capture library')
    paths = libraries + [os.path.join(root, path) for path in (
        'usr/share/bgdesk/lib/libbgdesk.so', 'usr/share/bgdesk/bgdesk',
        'usr/share/bgdesk/rustdesk') if os.path.isfile(os.path.join(root, path))]
    floor = '2.%d' % max(_max_glibc_minor(path) for path in paths)
    if floor == '2.0':
        raise Exception('cannot determine the staged libdrmtap libc6 requirement')
    with open(control_path) as f:
        lines = f.readlines()
    for index, line in enumerate(lines):
        if line.startswith('Depends:'):
            lines[index] = (line.rstrip('\n') + ', libdrm2 (>= 2.4.101), libegl1, libgles2, '
                            'libc6 (>= %s)\n' % floor)
            break
    else:
        raise Exception('missing Depends field in %s' % control_path)
    with open(control_path, 'w') as f:
        f.writelines(lines)


def build_flutter_deb(version, features):
    if not skip_cargo:
        system2(f'cargo build --features {features} --lib --release')
        rename_linux_artifacts()
        ffi_bindgen_function_refactor()
    else:
        rename_linux_artifacts()
    os.chdir('flutter')
    system2(flutter_linux_build_cmd)
    system2('mkdir -p tmpdeb/usr/bin/')
    system2('mkdir -p tmpdeb/usr/share/bgdesk')
    system2('mkdir -p tmpdeb/etc/bgdesk/')
    system2('mkdir -p tmpdeb/etc/pam.d/')
    system2('mkdir -p tmpdeb/usr/share/bgdesk/files/systemd/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/256x256/apps/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/scalable/apps/')
    system2('mkdir -p tmpdeb/usr/share/applications/')
    system2('mkdir -p tmpdeb/usr/share/polkit-1/actions')
    system2('rm tmpdeb/usr/bin/bgdesk || true')
    system2(
        f'cp -r {flutter_build_dir}/* tmpdeb/usr/share/bgdesk/')
    system2(
        'cp ../res/bgdesk.service tmpdeb/usr/share/bgdesk/files/systemd/')
    system2(
        'cp ../res/128x128@2x.png tmpdeb/usr/share/icons/hicolor/256x256/apps/bgdesk.png')
    system2(
        'cp ../res/scalable.svg tmpdeb/usr/share/icons/hicolor/scalable/apps/bgdesk.svg')
    system2(
        'cp ../res/bgdesk.desktop tmpdeb/usr/share/applications/bgdesk.desktop')
    system2(
        'cp ../res/bgdesk-link.desktop tmpdeb/usr/share/applications/bgdesk-link.desktop')
    system2(
        'cp ../res/startwm.sh tmpdeb/etc/bgdesk/')
    system2(
        'cp ../res/xorg.conf tmpdeb/etc/bgdesk/')
    system2(
        'cp ../res/pam.d/bgdesk.debian tmpdeb/etc/pam.d/bgdesk')
    system2(
        "echo \"#!/bin/sh\" >> tmpdeb/usr/share/bgdesk/files/polkit && chmod a+x tmpdeb/usr/share/bgdesk/files/polkit")
    ships_so = 'drm' in features.split(',')
    if ships_so:
        prepare_drm_bundle(flutter_build_dir)
        stage_bundle_drmtap(flutter_build_dir, 'tmpdeb')

    system2('mkdir -p tmpdeb/DEBIAN')
    generate_control_file(version)
    system2('cp -a ../res/DEBIAN/* tmpdeb/DEBIAN/')
    if ships_so:
        add_drm_deb_dependencies('tmpdeb/DEBIAN/control')
    md5_file_folder("tmpdeb/")
    system2('chmod 755 tmpdeb/DEBIAN/preinst tmpdeb/DEBIAN/postinst tmpdeb/DEBIAN/prerm tmpdeb/DEBIAN/postrm 2>/dev/null || true'); system2('dpkg-deb -b tmpdeb bgdesk.deb;')

    system2('/bin/rm -rf tmpdeb/')
    system2('/bin/rm -rf ../res/DEBIAN/control')
    os.rename('bgdesk.deb', '../bgdesk-%s.deb' % version)
    os.chdir("..")


DRMTAP_DLOPEN_MARKER = b'/usr/lib/bgdesk/libdrmtap.so.0'
# Present only when `drm-wake` is compiled in: the runtime option constant is itself
# #[cfg(feature = "drm-wake")] (src/ipc/drm.rs). The dlopen marker above cannot stand in for it -
# `--features drm` alone produces a binary that carries the dlopen path and NO wake code, and that
# is exactly the deb this assertion is here to refuse.
DRMTAP_WAKE_MARKER = b'enable-drm-display-wake'


def _carries_drmtap_marker(path, marker=DRMTAP_DLOPEN_MARKER):
    # Chunked, with an overlap of len(marker)-1 so the marker cannot be missed at a chunk boundary:
    # librustdesk.so is ~45 MB and there is no reason to hold it all in memory, and the `with`
    # closes deterministically instead of relying on refcounting.
    with open(path, 'rb') as f:
        tail = b''
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                return False
            if marker in tail + chunk:
                return True
            tail = chunk[-(len(marker) - 1):]


def assert_staged_binary_is_drm(payload='tmpdeb/usr/share/bgdesk'):
    """Inspect the produced binary, including when the caller uses --skip-cargo."""
    library = os.path.join(payload, 'lib', 'libbgdesk.so')
    # Flutter's launcher does not contain Rust code. Check its library when present.
    binaries = ([library] if os.path.isfile(library) else
                [os.path.join(payload, name) for name in ('bgdesk', 'rustdesk')
                 if os.path.isfile(os.path.join(payload, name))])
    for marker in (DRMTAP_DLOPEN_MARKER, DRMTAP_WAKE_MARKER):
        if not any(_carries_drmtap_marker(p, marker) for p in binaries):
            raise Exception(
                'native Wayland package requires a binary built with drm,drm-wake; '
                'missing %s in %s. Rebuild Cargo with --features ...,drm,drm-wake '
                'before packaging with --skip-cargo.' % (marker.decode(), binaries))


def build_deb_from_folder(version, binary_folder, want_drm=True):
    binary_folder = os.path.abspath(binary_folder)
    os.chdir('flutter')
    system2('mkdir -p tmpdeb/usr/bin/')
    system2('mkdir -p tmpdeb/usr/share/bgdesk')
    system2('mkdir -p tmpdeb/usr/share/bgdesk/files/systemd/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/256x256/apps/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/scalable/apps/')
    system2('mkdir -p tmpdeb/usr/share/applications/')
    system2('mkdir -p tmpdeb/usr/share/polkit-1/actions')
    system2('rm tmpdeb/usr/bin/bgdesk || true')
    system2(
        f'cp -r "{binary_folder}"/* tmpdeb/usr/share/bgdesk/')
    system2(
        'cp ../res/bgdesk.service tmpdeb/usr/share/bgdesk/files/systemd/')
    system2(
        'cp ../res/128x128@2x.png tmpdeb/usr/share/icons/hicolor/256x256/apps/bgdesk.png')
    system2(
        'cp ../res/scalable.svg tmpdeb/usr/share/icons/hicolor/scalable/apps/bgdesk.svg')
    system2(
        'cp ../res/bgdesk.desktop tmpdeb/usr/share/applications/bgdesk.desktop')
    system2(
        'cp ../res/bgdesk-link.desktop tmpdeb/usr/share/applications/bgdesk-link.desktop')
    system2(
        "echo \"#!/bin/sh\" >> tmpdeb/usr/share/bgdesk/files/polkit && chmod a+x tmpdeb/usr/share/bgdesk/files/polkit")
    if want_drm:
        prepare_drm_bundle(binary_folder)
        stage_bundle_drmtap(binary_folder, 'tmpdeb')
    elif glob.glob('tmpdeb/usr/share/bgdesk/libdrmtap.so*'):
        raise Exception('--no-drm bundle must not carry libdrmtap')

    system2('mkdir -p tmpdeb/DEBIAN')
    generate_control_file(version)
    system2('cp -a ../res/DEBIAN/* tmpdeb/DEBIAN/')
    if want_drm:
        add_drm_deb_dependencies('tmpdeb/DEBIAN/control')
    md5_file_folder("tmpdeb/")
    system2('chmod 755 tmpdeb/DEBIAN/preinst tmpdeb/DEBIAN/postinst tmpdeb/DEBIAN/prerm tmpdeb/DEBIAN/postrm 2>/dev/null || true'); system2('dpkg-deb -b tmpdeb bgdesk.deb;')

    system2('/bin/rm -rf tmpdeb/')
    system2('/bin/rm -rf ../res/DEBIAN/control')
    os.rename('bgdesk.deb', '../bgdesk-%s.deb' % version)
    os.chdir("..")


def build_flutter_dmg(version, features):
    verify_flutter_root()
    flutter = flutter_bin()
    if not skip_cargo:
        # set minimum osx build target, now is 10.14, which is the same as the flutter xcode project
        system2(
            f'MACOSX_DEPLOYMENT_TARGET=10.14 cargo build --features {features} --release')
    # copy dylib
    system2(
        "cp target/release/liblibrustdesk.dylib target/release/librustdesk.dylib")
    os.chdir('flutter')
    mac_arch = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64'
    local_flags = flutter_local_engine_flags()
    if use_flutter_github():
        # Rebuild completo para garantir que o engine/framework venha do Flutter master atual.
        system2(f'{flutter} clean')
        system2(f'{flutter} pub get')
        if local_flags:
            sys.stderr.write(f'[build.py] engine local:{local_flags}\n')
        elif os.environ.get('FLUTTER_ENGINE_PATCH_APPLIED') == '1':
            sys.stderr.write(
                '[build.py] AVISO: patch 4332f3e (PR #188772) aplicado no source do engine, mas sem build local.\n'
                '[build.py] Rode ./scripts/build-flutter-local-engine-macos.sh para o fix entrar no app.\n')
    elif use_flutter_stable():
        system2(f'{flutter} pub get')
    system2(
        f'FLUTTER_XCODE_ARCHS={mac_arch} FLUTTER_XCODE_ONLY_ACTIVE_ARCH=YES '
        f'FLUTTER_XCODE_CODE_SIGNING_ALLOWED=NO {flutter} build macos --release{local_flags}')
    write_flutter_build_stamp()
    system2('cp -rf ../target/release/service ./build/macos/Build/Products/Release/BGDesk.app/Contents/MacOS/')
    '''
    system2(
        "create-dmg --volname \"RustDesk Installer\" --window-pos 200 120 --window-size 800 400 --icon-size 100 --app-drop-link 600 185 --icon RustDesk.app 200 190 --hide-extension RustDesk.app rustdesk.dmg ./build/macos/Build/Products/Release/RustDesk.app")
    os.rename("rustdesk.dmg", f"../rustdesk-{version}.dmg")
    '''
    os.chdir("..")


def build_flutter_arch_manjaro(version, features):
    if not skip_cargo:
        system2(f'cargo build --features {features} --lib --release')
        rename_linux_artifacts()
    ffi_bindgen_function_refactor()
    os.chdir('flutter')
    system2(flutter_linux_build_cmd)
    system2(f'strip {flutter_build_dir}/lib/libbgdesk.so')
    if 'drm' in features.split(','):
        prepare_drm_bundle(flutter_build_dir)
    os.chdir('../res')
    system2('HBB=`pwd`/.. FLUTTER=1 makepkg -f')


def build_flutter_windows(version, features, skip_portable_pack):
    if not skip_cargo:
        system2(f'cargo build --features {features} --lib --release')
        rename_windows_artifacts()
        if not os.path.exists("target/release/libbgdesk.dll"):
            print("cargo build failed, please check rust source code.")
            exit(-1)
    else:
        rename_windows_artifacts()
    os.chdir('flutter')
    system2('flutter build windows --release')
    os.chdir('..')
    shutil.copy2('target/release/deps/dylib_virtual_display.dll',
                 flutter_build_dir_2)
    if skip_portable_pack:
        return
    os.chdir('libs/portable')
    system2('pip3 install -r requirements.txt')
    system2(
        f'python3 ./generate.py -f ../../{flutter_build_dir_2} -o . -e ../../{flutter_build_dir_2}/bgdesk.exe')
    os.chdir('../..')
    if os.path.exists('./bgdesk_portable.exe'):
        os.replace('./target/release/rustdesk-portable-packer.exe',
                   './bgdesk_portable.exe')
    else:
        os.rename('./target/release/rustdesk-portable-packer.exe',
                  './bgdesk_portable.exe')
    print(
        f'output location: {os.path.abspath(os.curdir)}/bgdesk_portable.exe')
    os.rename('./bgdesk_portable.exe', f'./bgdesk-{version}-install.exe')
    print(
        f'output location: {os.path.abspath(os.curdir)}/bgdesk-{version}-install.exe')


def main():
    global skip_cargo
    parser = make_parser()
    args = parser.parse_args()

    # Before anything with a side effect: this is a query, and a caller uses it to build the very
    # binary it will then package. `get_features` stays the single definition of what a flag
    # combination means; a caller that hardcodes the list instead is one edit away from compiling
    # something other than what it ships.
    if args.print_features:
        # stdout carries the list and nothing else, so a caller can use it directly in a command
        # substitution. `get_features` prints a human-readable line of its own; send that to stderr
        # for this call rather than silencing it, which would change what every other path prints.
        with contextlib.redirect_stdout(sys.stderr):
            feats = ','.join(get_features(args))
        print(feats)
        return

    if not args.skip_cargo and not args.package:
        ensure_cargo_on_path()

    if os.path.exists(exe_path):
        os.unlink(exe_path)
    if os.path.isfile('/usr/bin/pacman'):
        system2('git checkout src/ui/common.tis')
    version = get_version()
    features = ','.join(get_features(args))
    flutter = args.flutter
    if not flutter and not args.package:
        system2('python3 res/inline-sciter.py')
    print(args.skip_cargo)
    if args.skip_cargo:
        skip_cargo = True
    portable = args.portable
    package = args.package
    if package:
        build_deb_from_folder(version, package, args.drm)
        return
    res_dir = 'resources'
    external_resources(flutter, args, res_dir)
    if windows:
        # build virtual display dynamic library
        os.chdir('libs/virtual_display/dylib')
        system2('cargo build --release')
        os.chdir('../../..')

        if flutter:
            build_flutter_windows(version, features, args.skip_portable_pack)
            return
        system2('cargo build --release --features ' + features)
        rename_windows_artifacts()
        if os.path.exists('target/release/bgdesk.exe'):
            os.replace('target/release/bgdesk.exe', 'target/release/BGDesk.exe')
        pa = os.environ.get('P')
        if pa:
            # https://certera.com/kb/tutorial-guide-for-safenet-authentication-client-for-code-signing/
            system2(
                f'signtool sign /a /v /p {pa} /debug /f .\\cert.pfx /t http://timestamp.digicert.com  '
                'target\\release\\BGDesk.exe')
        else:
            print('Not signed')
        system2(
            f'cp -rf target/release/BGDesk.exe {res_dir}')
        os.chdir('libs/portable')
        system2('pip3 install -r requirements.txt')
        system2(
            f'python3 ./generate.py -f ../../{res_dir} -o . -e ../../{res_dir}/bgdesk-{version}-win7-install.exe')
        system2('mv ../../{res_dir}/bgdesk-{version}-win7-install.exe ../..')
    elif os.path.isfile('/usr/bin/pacman'):
        # pacman -S -needed base-devel
        system2("sed -i 's/pkgver=.*/pkgver=%s/g' res/PKGBUILD" % version)
        if flutter:
            build_flutter_arch_manjaro(version, features)
        else:
            system2('cargo build --release --features ' + features)
            rename_linux_artifacts()
            system2('git checkout src/ui/common.tis')
            system2('strip target/release/bgdesk')
            if args.drm:
                prepare_drm_bundle('target/release')
            system2('ln -s res/pacman_install && ln -s res/PKGBUILD')
            system2('HBB=`pwd` makepkg -f')
        system2('mv bgdesk-%s-0-x86_64.pkg.tar.zst bgdesk-%s-manjaro-arch.pkg.tar.zst' % (
            version, version))
        # pacman -U ./bgdesk.pkg.tar.zst
    elif os.path.isfile('/usr/bin/yum'):
        system2('cargo build --release --features ' + features)
        rename_linux_artifacts()
        system2('strip target/release/bgdesk')
        if args.drm:
            prepare_drm_bundle('target/release')
        system2(
            "sed -i 's/Version:    .*/Version:    %s/g' res/rpm.spec" % version)
        system2('HBB=`pwd` rpmbuild -ba res/rpm.spec')
        system2(
            'mv $HOME/rpmbuild/RPMS/x86_64/bgdesk-%s-0.x86_64.rpm ./bgdesk-%s-fedora28-centos8.rpm' % (
                version, version))
        # yum localinstall bgdesk.rpm
    elif os.path.isfile('/usr/bin/zypper'):
        system2('cargo build --release --features ' + features)
        rename_linux_artifacts()
        system2('strip target/release/bgdesk')
        if args.drm:
            prepare_drm_bundle('target/release')
        system2(
            "sed -i 's/Version:    .*/Version:    %s/g' res/rpm-suse.spec" % version)
        system2('HBB=`pwd` rpmbuild -ba res/rpm-suse.spec')
        system2(
            'mv $HOME/rpmbuild/RPMS/x86_64/bgdesk-%s-0.x86_64.rpm ./bgdesk-%s-suse.rpm' % (
                version, version))
        # yum localinstall bgdesk.rpm
    else:
        if flutter:
            if osx:
                build_flutter_dmg(version, features)
                pass
            else:
                # system2(
                #     'mv target/release/bundle/deb/rustdesk*.deb ./flutter/rustdesk.deb')
                build_flutter_deb(version, features)
        else:
            system2('cargo bundle --release --features ' + features)
            rename_linux_artifacts()
            if osx:
                system2(
                    'strip target/release/bundle/osx/RustDesk.app/Contents/MacOS/rustdesk')
                system2(
                    'cp libsciter.dylib target/release/bundle/osx/RustDesk.app/Contents/MacOS/')
                # https://github.com/sindresorhus/create-dmg
                system2('/bin/rm -rf *.dmg')
                pa = os.environ.get('P')
                if pa:
                    system2('''
    # buggy: rcodesign sign ... path/*, have to sign one by one
    # install rcodesign via cargo install apple-codesign
    #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./target/release/bundle/osx/RustDesk.app/Contents/MacOS/rustdesk
    #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./target/release/bundle/osx/RustDesk.app/Contents/MacOS/libsciter.dylib
    #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./target/release/bundle/osx/RustDesk.app
    # goto "Keychain Access" -> "My Certificates" for below id which starts with "Developer ID Application:"
    codesign -s "Developer ID Application: {0}" --force --options runtime  ./target/release/bundle/osx/RustDesk.app/Contents/MacOS/*
    codesign -s "Developer ID Application: {0}" --force --options runtime  ./target/release/bundle/osx/RustDesk.app
    '''.format(pa))
                system2(
                    'create-dmg "RustDesk %s.dmg" "target/release/bundle/osx/RustDesk.app"' % version)
                os.rename('RustDesk %s.dmg' %
                          version, 'rustdesk-%s.dmg' % version)
                if pa:
                    system2('''
    # https://pyoxidizer.readthedocs.io/en/apple-codesign-0.14.0/apple_codesign.html
    # https://pyoxidizer.readthedocs.io/en/stable/tugger_code_signing.html
    # https://developer.apple.com/developer-id/
    # goto xcode and login with apple id, manager certificates (Developer ID Application and/or Developer ID Installer) online there (only download and double click (install) cer file can not export p12 because no private key)
    #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./rustdesk-{1}.dmg
    codesign -s "Developer ID Application: {0}" --force --options runtime ./rustdesk-{1}.dmg
    # https://appstoreconnect.apple.com/access/api
    # https://gregoryszorc.com/docs/apple-codesign/stable/apple_codesign_getting_started.html#apple-codesign-app-store-connect-api-key
    # p8 file is generated when you generate api key (can download only once)
    rcodesign notary-submit --api-key-path ../.p12/api-key.json  --staple rustdesk-{1}.dmg
    # verify:  spctl -a -t exec -v /Applications/RustDesk.app
    '''.format(pa, version))
                else:
                    print('Not signed')
            else:
                # build deb package (cargo bundle names deb/rustdesk*.deb from crate name)
                move_cargo_bundle_deb()
                system2('dpkg-deb -R bgdesk.deb tmpdeb')
                normalize_sciter_deb_binary()
                system2('mkdir -p tmpdeb/usr/share/bgdesk/files/systemd/')
                system2('mkdir -p tmpdeb/usr/share/icons/hicolor/256x256/apps/')
                system2('mkdir -p tmpdeb/usr/share/icons/hicolor/scalable/apps/')
                system2(
                    'cp res/bgdesk.service tmpdeb/usr/share/bgdesk/files/systemd/')
                system2(
                    'cp res/128x128@2x.png tmpdeb/usr/share/icons/hicolor/256x256/apps/bgdesk.png')
                system2(
                    'cp res/scalable.svg tmpdeb/usr/share/icons/hicolor/scalable/apps/bgdesk.svg')
                system2(
                    'cp res/bgdesk.desktop tmpdeb/usr/share/applications/bgdesk.desktop')
                system2(
                    'cp res/bgdesk-link.desktop tmpdeb/usr/share/applications/bgdesk-link.desktop')
                os.system('mkdir -p tmpdeb/etc/bgdesk/')
                os.system('cp -a res/startwm.sh tmpdeb/etc/bgdesk/')
                os.system('mkdir -p tmpdeb/etc/X11/bgdesk/')
                os.system('cp res/xorg.conf tmpdeb/etc/X11/bgdesk/')
                os.system('cp -a res/DEBIAN/* tmpdeb/DEBIAN/')
                os.system('mkdir -p tmpdeb/etc/pam.d/')
                os.system('cp res/pam.d/bgdesk.debian tmpdeb/etc/pam.d/bgdesk')
                system2('strip tmpdeb/usr/bin/bgdesk')
                system2('mkdir -p tmpdeb/usr/share/bgdesk')
                system2('mv tmpdeb/usr/bin/bgdesk tmpdeb/usr/share/bgdesk/')
                system2('cp libsciter-gtk.so tmpdeb/usr/share/bgdesk/')
                if args.drm:
                    prepare_drm_bundle('tmpdeb/usr/share/bgdesk')
                    stage_bundle_drmtap('tmpdeb/usr/share/bgdesk', 'tmpdeb')
                    add_drm_deb_dependencies('tmpdeb/DEBIAN/control')
                md5_file_folder("tmpdeb/")
                system2('dpkg-deb -b tmpdeb bgdesk.deb; /bin/rm -rf tmpdeb/')
                os.rename('bgdesk.deb', 'bgdesk-%s.deb' % version)


def md5_file(fn):
    with open('tmpdeb/' + fn, 'rb') as source:
        md5 = hashlib.md5(source.read()).hexdigest()
    system2('echo "%s  /%s" >> tmpdeb/DEBIAN/md5sums' % (md5, fn))

def md5_file_folder(base_dir):
    base_path = Path(base_dir)
    for file in base_path.rglob('*'):
        if file.is_file() and 'DEBIAN' not in file.parts:
            relative_path = file.relative_to(base_path)
            md5_file(str(relative_path))


if __name__ == "__main__":
    main()
