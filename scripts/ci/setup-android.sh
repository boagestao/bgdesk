#!/usr/bin/env bash
set -euo pipefail
# Validate the existing private key before installing/compiling native dependencies.
export JAVA_HOME="$JAVA_HOME_17_X64"
export PATH="$JAVA_HOME/bin:$PATH"
echo "JAVA_HOME=$JAVA_HOME" >> "$GITHUB_ENV"
echo "$JAVA_HOME/bin" >> "$GITHUB_PATH"
python scripts/ci/android_signing.py
sudo apt-get update
sudo apt-get install -y autoconf automake build-essential clang cmake libclang-dev libtool llvm nasm ninja-build pkg-config unzip zip
rustup toolchain install "$RUST_VERSION" --profile minimal --component rustfmt
rustup default "$RUST_VERSION"
rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android
cargo install cargo-ndk --version 3.1.2 --locked
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" 'platforms;android-36' 'build-tools;36.0.0' 'ndk;28.2.13676358'
export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/28.2.13676358"
export ANDROID_NDK_ROOT="$ANDROID_NDK_HOME"
export ANDROID_NDK_HOST_TAG=linux-x86_64
export VCPKG_ROOT="$HOME/.bin/vcpkg"
export LIBCLANG_PATH
LIBCLANG_PATH="$(llvm-config --libdir)"
for name in ANDROID_NDK_HOME ANDROID_NDK_ROOT ANDROID_NDK_HOST_TAG VCPKG_ROOT LIBCLANG_PATH; do
  echo "$name=${!name}" >> "$GITHUB_ENV"
done
git clone --filter=blob:none https://github.com/microsoft/vcpkg.git "$VCPKG_ROOT"
git -C "$VCPKG_ROOT" checkout --detach "$VCPKG_COMMIT_ID"
"$VCPKG_ROOT/bootstrap-vcpkg.sh" -disableMetrics
bash .github/patches/apply_flutter_3.44_source_patches.sh
