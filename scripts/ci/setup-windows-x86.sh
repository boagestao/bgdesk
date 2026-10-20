#!/usr/bin/env bash
# Target x86 dependencies share the existing runner's host x64 tools and cache.
set -euo pipefail
export VCPKG_ROOT="$HOME/.bin/vcpkg"
export VCPKG_TRIPLET=x86-windows-static
export BGDESK_LLVM_ROOT="$(cygpath -u "$RUNNER_TEMP")/bgdesk-llvm"
export LIBCLANG_PATH="$BGDESK_LLVM_ROOT/bin"
source scripts/setup-windows-build.sh
export VCPKG_DEFAULT_HOST_TRIPLET=x64-windows-static
install_vcpkg
"$VCPKG_ROOT/vcpkg.exe" install --triplet "$VCPKG_TRIPLET" --host-triplet "$VCPKG_DEFAULT_HOST_TRIPLET" --x-install-root="$VCPKG_ROOT/installed" --clean-after-build
{
  echo "VCPKG_ROOT=$(cygpath -w "$VCPKG_ROOT")"
  echo "VCPKG_TRIPLET=$VCPKG_TRIPLET"
  echo "VCPKG_DEFAULT_HOST_TRIPLET=$VCPKG_DEFAULT_HOST_TRIPLET"
  echo "LIBCLANG_PATH=$(cygpath -w "$LIBCLANG_PATH")"
} >> "$GITHUB_ENV"
