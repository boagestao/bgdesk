#!/usr/bin/env bash
# Static checks for Linux build/installer path consistency (no compile required).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail=0
ok=0

pass() { echo "  OK  $1"; ok=$((ok + 1)); }
fail_msg() { echo "  FAIL $1"; fail=$((fail + 1)); }

require_file() {
  if [[ -f "$1" ]]; then pass "$1"; else fail_msg "missing file: $1"; fi
}

require_grep() {
  local file="$1" pattern="$2" label="$3"
  if grep -qE "$pattern" "$file" 2>/dev/null; then
    pass "$label"
  else
    fail_msg "$label (expected in $file)"
  fi
}

require_not_grep() {
  local file="$1" pattern="$2" label="$3"
  if grep -qE "$pattern" "$file" 2>/dev/null; then
    fail_msg "$label (found in $file)"
  else
    pass "$label"
  fi
}

echo "=== BGDesk build path checks ==="

echo
echo "-- Required packaging files --"
for f in \
  res/bgdesk.service \
  res/bgdesk.desktop \
  res/bgdesk-link.desktop \
  res/pam.d/bgdesk.debian \
  res/pam.d/bgdesk.suse \
  res/DEBIAN/postinst \
  res/DEBIAN/preinst \
  res/rpm.spec \
  res/rpm-suse.spec \
  res/rpm-flutter.spec \
  res/PKGBUILD \
  scripts/rename-linux-artifacts.sh \
  appimage/AppImageBuilder-x86_64.yml \
  appimage/AppImageBuilder-aarch64.yml \
  flatpak/bgdesk.json; do
  require_file "$f"
done

echo
echo "-- Flutter Linux runtime --"
require_grep flutter/linux/CMakeLists.txt 'BINARY_NAME "bgdesk"' 'CMake BINARY_NAME bgdesk'
require_grep flutter/linux/CMakeLists.txt 'libbgdesk\.so' 'CMake links libbgdesk.so'
require_grep flutter/linux/main.cc 'libbgdesk\.so' 'main.cc dlopen libbgdesk.so'
require_grep flutter/lib/models/native_model.dart "libbgdesk\.so" 'native_model DynamicLibrary libbgdesk.so'

echo
echo "-- Rename script integration --"
require_grep build.py 'rename_linux_artifacts' 'build.py calls rename_linux_artifacts'
require_grep build-deb.sh 'rename-linux-artifacts' 'build-deb.sh calls rename script'
require_grep installers/build-deb.sh 'rename-linux-artifacts' 'installers/build-deb.sh calls rename script'
require_grep .github/workflows/flutter-build.yml 'rename-linux-artifacts' 'CI Linux calls rename script'

echo
echo "-- Windows Flutter runtime --"
require_file scripts/rename-windows-artifacts.ps1
require_grep flutter/windows/CMakeLists.txt 'BINARY_NAME "bgdesk"' 'Windows CMake BINARY_NAME bgdesk'
require_grep flutter/windows/CMakeLists.txt 'libbgdesk\.dll' 'Windows CMake links libbgdesk.dll'
require_grep flutter/windows/runner/main.cpp 'libbgdesk\.dll' 'main.cpp LoadLibrary libbgdesk.dll'
require_grep flutter/lib/models/native_model.dart "libbgdesk\.dll" 'native_model DynamicLibrary libbgdesk.dll'
require_grep build.py 'rename_windows_artifacts' 'build.py calls rename_windows_artifacts'
require_grep build.py "hbb_name = 'bgdesk\.exe'" 'build.py Windows hbb_name bgdesk.exe'
require_grep .github/workflows/flutter-build.yml './bgdesk' 'CI Windows staging folder bgdesk'
require_grep .github/workflows/flutter-build.yml 'bgdesk-unsigned-windows' 'CI Windows artifact name bgdesk'

echo
echo "-- Sciter deb repack (build.py) --"
require_grep build.py 'move_cargo_bundle_deb' 'build.py move_cargo_bundle_deb helper'
require_grep build.py 'normalize_sciter_deb_binary' 'build.py normalize_sciter_deb_binary'
require_grep build.py 'res/DEBIAN/\*' 'build.py uses res/DEBIAN'
require_grep build.py 'res/pam\.d/bgdesk\.debian' 'build.py uses res/pam.d'

echo
echo "-- Stale rustdesk packaging refs (should be absent in build scripts) --"
for f in build-deb.sh installers/build-deb.sh build.py res/rpm.spec res/rpm-suse.spec res/PKGBUILD; do
  require_not_grep "$f" 'res/rustdesk\.(service|desktop)' "no res/rustdesk.* in $f"
  require_not_grep "$f" 'target/release/rustdesk($|[^.\-])' "no bare target/release/rustdesk in $f"
done
for f in build.py flutter/windows/CMakeLists.txt flutter/windows/runner/main.cpp flutter/lib/models/native_model.dart; do
  require_not_grep "$f" 'librustdesk\.dll' "no librustdesk.dll runtime ref in $f"
done

echo
echo "-- AppImage / Flatpak deb name --"
require_grep appimage/AppImageBuilder-x86_64.yml 'bgdesk\.deb' 'AppImage x86_64 uses bgdesk.deb'
require_grep appimage/AppImageBuilder-aarch64.yml 'bgdesk\.deb' 'AppImage aarch64 uses bgdesk.deb'

echo
echo "-- Linux aarch64 packages (deb + rpm + AppImage) --"
require_grep docker/build-linux-aarch64.entrypoint.sh 'build_rpm' 'aarch64 entrypoint builds rpm'
require_grep docker/build-linux-aarch64.entrypoint.sh 'rpm-flutter\.spec' 'aarch64 entrypoint uses rpm-flutter.spec'
require_grep docker/build-linux-aarch64.entrypoint.sh '\$\{PKG_NAME\}-\$\{ARCH_SUFFIX\}\.rpm' 'aarch64 rpm artifact name'
require_grep scripts/docker-build-linux-aarch64.sh 'bgdesk-\*-aarch64\.rpm' 'host script collects rpm'

echo
echo "-- Linux aarch64 image prep (vcpkg baked in) --"
require_grep docker/build-linux-aarch64.dockerfile 'vcpkg.*install' 'dockerfile installs vcpkg deps'
require_grep docker/build-linux-aarch64.dockerfile 'COPY vcpkg\.json' 'dockerfile copies vcpkg manifest'
require_not_grep docker/build-linux-aarch64.entrypoint.sh 'vcpkg install' 'entrypoint does not install vcpkg'
require_not_grep scripts/docker-build-linux-aarch64.sh 'bgdesk-vcpkg-arm64' 'no vcpkg volume override'

echo
echo "-- Linux x86_64 packages (deb + rpm + AppImage) --"
require_file docker/build-linux-x86_64.dockerfile
require_file docker/build-linux-x86_64.entrypoint.sh
require_file scripts/docker-build-linux-x86_64.sh
require_grep docker/build-linux-x86_64.entrypoint.sh 'build_rpm' 'x86_64 entrypoint builds rpm'
require_grep docker/build-linux-x86_64.entrypoint.sh 'rpm-flutter\.spec' 'x86_64 entrypoint uses rpm-flutter.spec'
require_grep docker/build-linux-x86_64.entrypoint.sh '\$\{PKG_NAME\}-\$\{ARCH_SUFFIX\}\.rpm' 'x86_64 rpm artifact name'
require_grep scripts/docker-build-linux-x86_64.sh 'bgdesk-\*-x86_64\.rpm' 'host script collects x86_64 rpm'
require_grep scripts/docker-build-linux-x86_64.sh 'linux/amd64' 'x86_64 uses linux/amd64 platform'

echo
echo "-- Linux x86_64 image prep (vcpkg baked in) --"
require_grep docker/build-linux-x86_64.dockerfile 'VCPKG_TRIPLET=x64-linux' 'x86_64 dockerfile uses x64-linux triplet'
require_grep docker/build-linux-x86_64.dockerfile 'vcpkg.*install' 'x86_64 dockerfile installs vcpkg deps'
require_grep docker/build-linux-x86_64.dockerfile 'COPY vcpkg\.json' 'x86_64 dockerfile copies vcpkg manifest'
require_not_grep docker/build-linux-x86_64.entrypoint.sh 'vcpkg install' 'x86_64 entrypoint does not install vcpkg'

echo
echo "-- build.py Linux arch selection --"
require_grep build.py '_linux_is_arm64' 'build.py detects Linux arch'
require_grep build.py 'build/linux/x64/release/bundle' 'build.py supports x64 flutter bundle'
require_grep build.py 'flutter build linux --release' 'build.py uses stock flutter on x64'

echo
echo "-- Shell syntax --"
for sh in build-deb.sh installers/build-deb.sh scripts/rename-linux-artifacts.sh scripts/check-linux-build-paths.sh entrypoint.sh flutter/run.sh; do
  if bash -n "$sh" 2>/dev/null; then pass "bash -n $sh"; else fail_msg "bash -n $sh"; fi
done

echo
echo "=== Summary: $ok passed, $fail failed ==="
if [[ "$fail" -gt 0 ]]; then exit 1; fi
