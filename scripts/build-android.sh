#!/usr/bin/env bash
# One signed universal APK with the Rust core for every advertised ABI.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source scripts/build-out-dir.sh
python3 scripts/patch-android-plugins.py
features=flutter,hwcodec
[[ "${BGDESK_CLIENTE:-0}" != 1 ]] || features+=,incoming-only
out="$(bgdesk_build_out_dir android universal)"
edition="$(bgdesk_build_mode)"
bgdesk_prepare_build_out_dir "$out"
rm -rf flutter/android/app/src/main/jniLibs
for abi in arm64-v8a armeabi-v7a x86_64; do
  case "$abi" in
    arm64-v8a) target=aarch64-linux-android; sysroot=aarch64-linux-android ;;
    armeabi-v7a) target=armv7-linux-androideabi; sysroot=arm-linux-androideabi ;;
    x86_64) target=x86_64-linux-android; sysroot=x86_64-linux-android ;;
  esac
  bash flutter/build_android_deps.sh "$abi"
  cargo ndk --platform 21 --target "$target" --bindgen build --locked --release --lib --features "$features"
  destination="flutter/android/app/src/main/jniLibs/$abi"
  mkdir -p "$destination"
  cp "target/$target/release/liblibrustdesk.so" "$destination/librustdesk.so"
  cp "$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/$ANDROID_NDK_HOST_TAG/sysroot/usr/lib/$sysroot/libc++_shared.so" "$destination/"
done
(
  cd flutter
  flutter build apk --release --target-platform android-arm64,android-arm,android-x64
)
cp flutter/build/app/outputs/flutter-apk/app-release.apk "$out/bgdesk-$edition-universal.apk"
python3 scripts/ci/verify-android.py "$out/bgdesk-$edition-universal.apk" --edition "$edition"
