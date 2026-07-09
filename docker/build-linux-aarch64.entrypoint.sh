#!/bin/bash
# Compile-only entrypoint. Toolchain, vcpkg, Flutter and packaging tools are
# baked into the image (see docker/build-linux-aarch64.dockerfile).
set -euo pipefail

cd /root/bgdesk

# shellcheck source=scripts/build-out-dir.sh
source /root/bgdesk/scripts/build-out-dir.sh

VERSION="$(grep '^version' Cargo.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')"
FORCE_REBUILD="${FORCE_REBUILD:-0}"
BUILD_BRIDGES="${BUILD_BRIDGES:-0}"
BGDESK_CLIENTE="${BGDESK_CLIENTE:-0}"
ARCH_SUFFIX=aarch64
if [[ "${BGDESK_CLIENTE}" == "1" ]]; then
  PKG_NAME="bgdesk-cliente"
else
  PKG_NAME="bgdesk-suporte"
fi
export DEB_ARCH="${DEB_ARCH:-arm64}"
export VCPKG_ROOT="${VCPKG_ROOT:-/vcpkg}"
export VCPKG_TRIPLET="${VCPKG_TRIPLET:-arm64-linux}"
export CARGO_INCREMENTAL="${CARGO_INCREMENTAL:-1}"
export PUB_CACHE="${PUB_CACHE:-/root/.pub-cache}"
export PATH="/opt/flutter-elinux/bin:/opt/flutter-elinux/flutter/bin:/root/.cargo/bin:${PATH}"
BGDESK_BUILD_OUT_DIR="${BGDESK_BUILD_OUT_DIR:-$(bgdesk_build_out_dir linux "${ARCH_SUFFIX}")}"

log() { echo "[build-linux-aarch64] $*"; }

# google_fonts ^8.1.0 needs Dart ^3.9 / Flutter >=3.35; flutter-elinux ships 3.29.x (Dart 3.7).
# Override only inside Docker so x86_64 and other targets keep the committed pubspec.
ensure_aarch64_pubspec_compat() {
  cat > flutter/pubspec_overrides.yaml <<'EOF'
dependency_overrides:
  google_fonts: 6.2.1
  intl: ^0.19.0
  flutter_plugin_android_lifecycle: 2.0.17
EOF
  log "pubspec_overrides.yaml: overrides aarch64 (google_fonts + intl + flutter_plugin_android_lifecycle)"
}

cleanup_aarch64_pubspec_compat() {
  rm -f flutter/pubspec_overrides.yaml
}

trap cleanup_aarch64_pubspec_compat EXIT

# Bind-mounted source may not be covered by the image's git safe.directory.
git config --global --add safe.directory /root/bgdesk >/dev/null 2>&1 || true

if [[ ! -d "${VCPKG_ROOT}/installed/${VCPKG_TRIPLET}" ]]; then
  log "ERROR: vcpkg ${VCPKG_TRIPLET} missing from image (expected ${VCPKG_ROOT}/installed/${VCPKG_TRIPLET})"
  log "Rebuild the image: ./build.sh linux --rebuild-image"
  exit 1
fi

clean_for_force_rebuild() {
  if [[ "${FORCE_REBUILD}" != "1" ]]; then
    return
  fi
  log "FORCE_REBUILD=1 — removing previous outputs for full rebuild..."
  rm -rf target/release
  rm -rf flutter/build/linux flutter/.dart_tool
  rm -f bgdesk-*.deb bgdesk-*-aarch64.deb bgdesk-*.rpm bgdesk-*-aarch64.rpm
  rm -f appimage/*.AppImage "${BGDESK_BUILD_OUT_DIR}"/*.deb "${BGDESK_BUILD_OUT_DIR}"/*.AppImage "${BGDESK_BUILD_OUT_DIR}"/*.rpm
  rm -f appimage/*.zst appimage/debian-binary appimage/bgdesk.deb \
    appimage/control.tar.* appimage/data.tar.* ./*.zst 2>/dev/null || true
}

ensure_bridge() {
  if [[ "${BUILD_BRIDGES}" != "1" \
      && -f flutter/lib/generated_bridge.dart \
      && -f flutter/lib/generated_bridge.freezed.dart \
      && -f src/bridge_generated.rs ]]; then
    log "bridge já existe — pulando geração (use --build-bridges para recriar)"
    return
  fi

  if [[ "${BUILD_BRIDGES}" == "1" ]]; then
    log "--build-bridges: regenerando flutter-rust-bridge..."
  else
    log "bridge ausente — gerando flutter-rust-bridge artifacts..."
  fi
  pushd flutter >/dev/null
  flutter-elinux pub get
  popd >/dev/null

  flutter_rust_bridge_codegen \
    --rust-input ./src/flutter_ffi.rs \
    --dart-output ./flutter/lib/generated_bridge.dart \
    --c-output ./flutter/macos/Runner/bridge_generated.h
  cp ./flutter/macos/Runner/bridge_generated.h ./flutter/ios/Runner/bridge_generated.h
}

build_rust() {
  # Sempre roda cargo build: sem --force o Cargo recompila só o que mudou.
  # --force limpa target/release antes (clean_for_force_rebuild).
  # target/ vive em volume Docker (não no bind-mount do host) para fingerprints estáveis.
  local features="hwcodec,flutter,unix-file-copy-paste"
  if [[ "${BGDESK_CLIENTE}" == "1" ]]; then
    features="${features},incoming-only"
    log "features: ${features} (modo cliente)"
  else
    log "features: ${features} (modo suporte)"
  fi
  if [[ -d target/release/deps ]]; then
    log "building Rust library (incremental cache hit; use --force for full rebuild)..."
  else
    log "building Rust library (cold cache; próximo build será incremental)..."
  fi
  # Single job avoids OOM on Docker Desktop/Colima with limited RAM.
  cargo build --locked --lib --jobs 1 \
    --features "${features}" \
    --release
  bash ./scripts/rename-linux-artifacts.sh
}

prepare_flutter() {
  log "preparing Flutter dependencies..."
  pushd flutter >/dev/null
  rm -rf .dart_tool build/linux
  flutter-elinux pub get
  popd >/dev/null
}

build_deb() {
  local out="${PKG_NAME}-${ARCH_SUFFIX}.deb"
  local py_args=(--flutter --skip-cargo)
  if [[ "${BGDESK_CLIENTE}" == "1" ]]; then
    py_args+=(--incoming-only)
  fi
  if [[ "${FORCE_REBUILD}" != "1" ]] && \
     { [[ -f "${out}" ]] || [[ -f "${BGDESK_BUILD_OUT_DIR}/${out}" ]]; }; then
    log "${out} already exists, skipping deb build (use --force to rebuild)"
    if [[ ! -f "${out}" && -f "${BGDESK_BUILD_OUT_DIR}/${out}" ]]; then
      cp -f "${BGDESK_BUILD_OUT_DIR}/${out}" "${out}"
    fi
    return
  fi
  log "building .deb package..."
  prepare_flutter
  chmod -R 755 res/DEBIAN
  python3 ./build.py "${py_args[@]}"

  local deb_name="bgdesk-${VERSION}.deb"
  if [[ -f "${deb_name}" ]]; then
    mv "${deb_name}" "${out}"
    log "created ${out}"
  else
    log "ERROR: expected ${deb_name} not found"
    ls -la *.deb 2>/dev/null || true
    exit 1
  fi
}

build_rpm() {
  local rpm_out="${PKG_NAME}-${ARCH_SUFFIX}.rpm"
  if [[ "${FORCE_REBUILD}" != "1" ]] && \
     { [[ -f "${rpm_out}" ]] || [[ -f "${BGDESK_BUILD_OUT_DIR}/${rpm_out}" ]]; }; then
    log "${rpm_out} already exists, skipping rpm build (use --force to rebuild)"
    if [[ ! -f "${rpm_out}" && -f "${BGDESK_BUILD_OUT_DIR}/${rpm_out}" ]]; then
      cp -f "${BGDESK_BUILD_OUT_DIR}/${rpm_out}" "${rpm_out}"
    fi
    return
  fi

  local bundle=""
  for candidate in \
    flutter/build/linux/arm64/release/bundle \
    flutter/build/linux/x64/release/bundle; do
    if [[ -d "${candidate}" ]]; then
      bundle="${candidate}"
      break
    fi
  done
  [[ -n "${bundle}" ]] || {
    log "ERROR: flutter release bundle not found (run deb build first)"
    exit 1
  }

  log "building .rpm package from ${bundle}..."
  # Work on a temp copy so we do not mutate the bind-mounted sources.
  local work="/tmp/bgdesk-rpm"
  rm -rf "${work}"
  mkdir -p "${work}"
  local spec="${work}/bgdesk.spec"
  cp res/rpm-flutter.spec "${spec}"
  sed -i "s/^Version:.*/Version:    ${VERSION}/" "${spec}"
  if [[ "${bundle}" == *"/arm64/"* ]]; then
    sed -i 's|linux/x64|linux/arm64|g' "${spec}"
  fi

  rm -rf "${HOME}/rpmbuild/RPMS"
  HBB="$(pwd)" rpmbuild -bb "${spec}"

  local built=""
  built="$(find "${HOME}/rpmbuild/RPMS" -name 'bgdesk-*.rpm' -type f 2>/dev/null | head -1 || true)"
  if [[ -z "${built}" ]]; then
    log "ERROR: rpm not found under ${HOME}/rpmbuild/RPMS"
    find "${HOME}/rpmbuild" -type f 2>/dev/null || true
    exit 1
  fi
  cp -f "${built}" "${rpm_out}"
  log "created ${rpm_out} (from ${built##*/})"
}

build_appimage() {
  local deb="${PKG_NAME}-${ARCH_SUFFIX}.deb"
  local appimage_out="${PKG_NAME}-${ARCH_SUFFIX}.AppImage"
  if [[ ! -f "${deb}" && -f "${BGDESK_BUILD_OUT_DIR}/${deb}" ]]; then
    cp -f "${BGDESK_BUILD_OUT_DIR}/${deb}" "${deb}"
  fi

  if [[ "${FORCE_REBUILD}" != "1" ]] && \
     { [[ -f "appimage/${appimage_out}" ]] || \
       [[ -f "${BGDESK_BUILD_OUT_DIR}/${appimage_out}" ]]; }; then
    log "${appimage_out} already exists, skipping (use --force to rebuild)"
    if [[ ! -f "appimage/${appimage_out}" && -f "${BGDESK_BUILD_OUT_DIR}/${appimage_out}" ]]; then
      mkdir -p appimage
      cp -f "${BGDESK_BUILD_OUT_DIR}/${appimage_out}" appimage/
    fi
    return
  fi

  log "building AppImage..."
  [[ -f "${deb}" ]] || { log "missing ${deb}"; exit 1; }

  # Build outside the macOS bind mount to avoid permission errors from appimage-builder.
  local work="/tmp/bgdesk-appimage"
  rm -rf "${work}"
  mkdir -p "${work}/appimage" "${work}/res"
  cp "${deb}" "${work}/appimage/bgdesk.deb"
  cp appimage/AppImageBuilder-aarch64.yml "${work}/appimage/"
  cp res/{32x32,64x64,128x128}.png res/scalable.svg "${work}/res/" 2>/dev/null || cp -r res/* "${work}/res/"

  pushd "${work}/appimage" >/dev/null
  appimage-builder --skip-tests --recipe ./AppImageBuilder-aarch64.yml
  shopt -s nullglob
  local artifacts=(bgdesk-*.AppImage BGDesk-*.AppImage)
  if ((${#artifacts[@]} == 0)); then
    log "ERROR: AppImage not found in ${work}/appimage/"
    ls -la
    exit 1
  fi
  mkdir -p /root/bgdesk/appimage
  cp -f "${artifacts[0]}" "/root/bgdesk/appimage/${appimage_out}"
  popd >/dev/null
  rm -rf "${work}"

  log "created /root/bgdesk/appimage/${appimage_out}"
}

collect_artifacts() {
  log "moving artifacts to ${BGDESK_BUILD_OUT_DIR}/ and cleaning intermediates..."
  mkdir -p "${BGDESK_BUILD_OUT_DIR}"

  shopt -s nullglob
  local deb="${PKG_NAME}-${ARCH_SUFFIX}.deb"
  if [[ -f "${deb}" ]]; then
    mv -f "${deb}" "${BGDESK_BUILD_OUT_DIR}/"
  fi

  local rpm="${PKG_NAME}-${ARCH_SUFFIX}.rpm"
  if [[ -f "${rpm}" ]]; then
    mv -f "${rpm}" "${BGDESK_BUILD_OUT_DIR}/"
  fi

  local appimage_out="${PKG_NAME}-${ARCH_SUFFIX}.AppImage"
  if [[ -f "appimage/${appimage_out}" ]]; then
    mv -f "appimage/${appimage_out}" "${BGDESK_BUILD_OUT_DIR}/"
  fi

  rm -f appimage/*.zst appimage/debian-binary appimage/bgdesk.deb \
    appimage/control.tar.* appimage/data.tar.* 2>/dev/null || true
  rm -f ./*.zst 2>/dev/null || true

  log "done — artifacts in ${BGDESK_BUILD_OUT_DIR}/:"
  ls -lh "${BGDESK_BUILD_OUT_DIR}"/*.deb "${BGDESK_BUILD_OUT_DIR}"/*.rpm "${BGDESK_BUILD_OUT_DIR}"/*.AppImage 2>/dev/null || true
}

log "BGDesk Linux aarch64 compile starting (version ${VERSION}, FORCE_REBUILD=${FORCE_REBUILD}, BGDESK_CLIENTE=${BGDESK_CLIENTE})"
cleanup_aarch64_pubspec_compat
clean_for_force_rebuild
ensure_aarch64_pubspec_compat
ensure_bridge
build_rust
build_deb
build_rpm
build_appimage
collect_artifacts
