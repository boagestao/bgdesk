#!/bin/bash
set -euo pipefail

OS=$(uname -s)
ARCH=$(uname -m)

MAC="Darwin"
WINDOWS="NT"
LINUX="Linux"

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* || "$(uname -s)" == CYGWIN* ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/scripts/windows-build-env.sh"
fi

win_user_home() {
  if [[ -n "${USERPROFILE:-}" ]]; then
    echo "${USERPROFILE//\\//}"
  else
    echo "${HOME//\\//}"
  fi
}

ensure_cargo() {
  if command -v cargo >/dev/null 2>&1; then
    return 0
  fi
  local win_home="${WIN_HOME:-$(win_user_home)}"
  local env_file
  for env_file in "$win_home/.cargo/env" "${HOME}/.cargo/env"; do
    if [[ -f "$env_file" ]]; then
      # shellcheck source=/dev/null
      . "$env_file"
      command -v cargo >/dev/null 2>&1 && return 0
    fi
  done
  if [[ -x "$win_home/.cargo/bin/cargo.exe" ]]; then
    export PATH="$win_home/.cargo/bin:$PATH"
    return 0
  fi
  if ! command -v cargo >/dev/null 2>&1; then
    echo "[build] ERRO: cargo não encontrado."
    echo "[build] Instale o Rust: https://rustup.rs"
    echo "[build] Ou rode: ./scripts/setup-windows-build.sh"
    exit 1
  fi
}

usage() {
  cat <<'EOF'
Uso: ./build.sh [plataforma] [opções]

Plataformas:
  mac                 Build macOS (padrão no Darwin)
  windows             Build Windows (padrão no Windows)
  linux               Build Linux via Docker (arch do host)
  linux-x86_64        Build Linux amd64 via Docker
  linux-aarch64       Build Linux arm64 via Docker
  android             Build APK Android

Modos:
  cliente             Build somente conexões recebidas (feature incoming-only).
                      Artefatos: bgdesk-cliente-*.{deb,rpm,AppImage,darwin.zip,win64.exe}
  (padrão)            Build completo (suporte).
                      Artefatos: bgdesk-suporte-*.{deb,rpm,AppImage,darwin.zip,win64.exe}

Opções:
  --build-bridges     Regenera o flutter-rust-bridge.
                      Sozinho: só regenera e sai.
                      Com plataforma: regenera e depois compila.
                      Sem esta flag, o bridge só é gerado se não existir.
  --force, -f, force  Recompilação completa (Linux: limpa target/release,
                      flutter build e pacotes). Não regenera o bridge.
  --rebuild-image     Reconstrói a imagem Docker do build Linux.
  --flutter           Atualiza/usa engine Flutter local (macOS).
  --help, -h, help    Mostra esta ajuda.

Exemplos:
  ./build.sh
  ./build.sh mac
  ./build.sh cliente mac
  ./build.sh linux-aarch64
  ./build.sh cliente linux-aarch64
  ./build.sh linux --force
  ./build.sh --build-bridges
  ./build.sh mac --build-bridges
  ./build.sh linux-x86_64 --rebuild-image

Notas:
  - Sem --force, o cargo build sempre roda de forma incremental.
  - No Linux, o cache Cargo (target/) fica em volume Docker nativo
    (bgdesk-target-aarch64 / bgdesk-target-x86_64), não no bind-mount do host.
  - Bridge só é recriado com --build-bridges ou se os arquivos não existirem.
  - Artefatos ficam em build/.
  - Windows: gera instalador Inno Setup (bgdesk-suporte-win64.exe /
    bgdesk-cliente-win64.exe) se ISCC estiver instalado.
EOF
}

UPDATE_FLUTTER=0
BGDESK_CLIENTE=0
FORCE_REBUILD=0
REBUILD_IMAGE=0
BUILD_BRIDGES=0
SHOW_HELP=0
REMAINING_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --help|-h|help) SHOW_HELP=1 ;;
    --flutter) UPDATE_FLUTTER=1 ;;
    cliente) BGDESK_CLIENTE=1 ;;
    --force|-f|force) FORCE_REBUILD=1 ;;
    --rebuild-image) REBUILD_IMAGE=1 ;;
    --build-bridges) BUILD_BRIDGES=1 ;;
    *) REMAINING_ARGS+=("$arg") ;;
  esac
done

if [[ "$SHOW_HELP" == "1" ]]; then
  usage
  exit 0
fi

export FLUTTER_UPDATE="$UPDATE_FLUTTER"
export BGDESK_CLIENTE
export FORCE_REBUILD
export REBUILD_IMAGE
export BUILD_BRIDGES

# vcpkg: VCPKG_ROOT é definido em buildMac / setup_windows_build_env

BUILD_PATH="${BUILD_PATH:-$ARCH}"
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  PYTHON=python3
fi

FORCED_PLATFORM=${REMAINING_ARGS[0]:-}

# Só limpa build/ em builds de plataforma (não em --build-bridges sozinho)
if [[ -n "$FORCED_PLATFORM" || "$BGDESK_CLIENTE" == "1" || "$BUILD_BRIDGES" != "1" ]]; then
  rm -rf build
  mkdir -p build
fi

ANDROID_NDK_HOME=/Users/belizario/Library/Android/sdk/ndk/27.2.12479018

log_flutter_for_build() {
  echo "[build] Flutter: $(flutter --version 2>/dev/null | head -1)"
  echo "[build] FLUTTER_ROOT=$FLUTTER_ROOT"
  echo "[build] FLUTTER_GITHUB_REV=${FLUTTER_GITHUB_REV:-?}"
  echo "[build] which flutter: $(command -v flutter)"
}

generate_bridge_windows() {
  local llvm_bin="${VCPKG_ROOT}/downloads/tools/clang/clang-15.0.6/bin"
  if [[ ! -f "$llvm_bin/libclang.dll" ]]; then
    echo "[build] ERRO: libclang não encontrado em $llvm_bin"
    echo "[build] Instale as dependências vcpkg do projeto ou defina LIBCLANG_PATH."
    exit 1
  fi
  export LIBCLANG_PATH="$llvm_bin"
  if ! command -v flutter_rust_bridge_codegen >/dev/null 2>&1; then
    echo "[build] instalando flutter_rust_bridge_codegen..."
    cargo install flutter_rust_bridge_codegen --version 1.80.1 --features "uuid" --locked
  fi
  pushd flutter >/dev/null
  flutter pub get
  popd >/dev/null
  flutter_rust_bridge_codegen --llvm-path "$llvm_bin" \
    --rust-input ./src/flutter_ffi.rs \
    --dart-output ./flutter/lib/generated_bridge.dart \
    --c-output ./flutter/macos/Runner/bridge_generated.h
  cp ./flutter/macos/Runner/bridge_generated.h ./flutter/ios/Runner/bridge_generated.h
  pushd flutter >/dev/null
  dart run build_runner build --delete-conflicting-outputs
  popd >/dev/null
}

bridge_exists() {
  [[ -f flutter/lib/generated_bridge.dart \
    && -f flutter/lib/generated_bridge.freezed.dart \
    && -f src/bridge_generated.rs ]]
}

generate_bridge() {
  if [[ $(uname -s) == *"$WINDOWS"* ]]; then
    generate_bridge_windows
  else
    "$ROOT/scripts/generate-bridge.sh"
  fi
}

ensure_bridge() {
  if [[ "${BUILD_BRIDGES}" != "1" ]] && bridge_exists; then
    echo "[build] bridge já existe — pulando geração (use --build-bridges para recriar)"
    pushd flutter >/dev/null
    flutter pub get
    popd >/dev/null
    return
  fi
  if [[ "${BUILD_BRIDGES}" == "1" ]]; then
    echo "[build] --build-bridges: regenerando bridge..."
  else
    echo "[build] bridge ausente — gerando..."
  fi
  generate_bridge
}

setup_windows_build_env() {
  if [[ -n "${VCPKG_ROOT:-}" && ( -x "${VCPKG_ROOT}/vcpkg.exe" || -x "${VCPKG_ROOT}/vcpkg" ) ]]; then
    :
  elif [[ -x "/c/vcpkg/vcpkg.exe" ]]; then
    export VCPKG_ROOT="/c/vcpkg"
  else
    export VCPKG_ROOT="${VCPKG_ROOT:-$HOME/.bin/vcpkg}"
  fi
  export VCPKG_DEFAULT_HOST_TRIPLET="${VCPKG_DEFAULT_HOST_TRIPLET:-x64-windows-static}"
  export VCPKG_TRIPLET="${VCPKG_TRIPLET:-x64-windows-static}"

  local llvm_bin="${VCPKG_ROOT}/downloads/tools/clang/clang-15.0.6/bin"
  if [[ -f "$llvm_bin/libclang.dll" ]]; then
    export LIBCLANG_PATH="$llvm_bin"
  fi

  if [[ -z "${FLUTTER_ROOT:-}" ]]; then
    local candidate
    for candidate in \
      /c/flutter \
      "$HOME/flutter" \
      "$HOME/flutter344/flutter" \
      "${LOCALAPPDATA:-}/flutter"; do
      if [[ -x "$candidate/bin/flutter.bat" || -x "$candidate/bin/flutter" ]]; then
        export FLUTTER_ROOT="$candidate"
        break
      fi
    done
  fi
  if [[ -n "${FLUTTER_ROOT:-}" ]]; then
    export PATH="$FLUTTER_ROOT/bin:$PATH"
  fi

  if [[ ! -x "${VCPKG_ROOT}/vcpkg.exe" && ! -x "${VCPKG_ROOT}/vcpkg" ]]; then
    echo "[build] ERRO: vcpkg não encontrado em VCPKG_ROOT=$VCPKG_ROOT"
    echo "[build] Rode: ./scripts/setup-windows-build.sh"
    exit 1
  fi
  if ! command -v flutter >/dev/null 2>&1; then
    echo "[build] ERRO: flutter não está no PATH"
    echo "[build] Defina FLUTTER_ROOT ou rode: ./scripts/setup-windows-build.sh"
    exit 1
  fi
  if [[ -z "${LIBCLANG_PATH:-}" ]]; then
    echo "[build] ERRO: LIBCLANG_PATH não definido e libclang não encontrado em vcpkg"
    exit 1
  fi
}

buildWindows()
{
    ensure_cargo
    setup_windows_build_env
    ensure_bridge
    local WIN_OUT_DIR="build/windows-suporte"
    local BUILD_ARGS=(--flutter --skip-portable-pack)
    if [[ "$BGDESK_CLIENTE" == "1" ]]; then
      WIN_OUT_DIR="build/windows-cliente"
      BUILD_ARGS+=(--incoming-only)
      echo "[build] modo cliente (somente conexões recebidas)"
    else
      echo "[build] modo suporte"
    fi
    echo "[build] Flutter: $(flutter --version 2>/dev/null | head -1)"
    echo "[build] VCPKG_ROOT=$VCPKG_ROOT"
    echo "[build] LIBCLANG_PATH=$LIBCLANG_PATH"
    $PYTHON build.py "${BUILD_ARGS[@]}"
    rm -rf "$WIN_OUT_DIR"
    mkdir -p "$WIN_OUT_DIR"
    cp -r flutter/build/windows/x64/runner/Release/. "$WIN_OUT_DIR"/.
    if [[ -f "$WIN_OUT_DIR/rustdesk.exe" ]]; then
      cp "$WIN_OUT_DIR/rustdesk.exe" "$WIN_OUT_DIR/bgdesk.exe"
      rm -f "$WIN_OUT_DIR/rustdesk.exe"
    fi
    bash "$ROOT/scripts/sign-pe.sh" "$ROOT/$WIN_OUT_DIR/bgdesk.exe"
    local INSTALLER_MODE="suporte"
    if [[ "$BGDESK_CLIENTE" == "1" ]]; then
      INSTALLER_MODE="cliente"
    fi
    bash "$ROOT/installers/build-installer.sh" "$INSTALLER_MODE"
    echo ""
    echo "=== Build Windows concluído ==="
    echo "Pasta: $ROOT/$WIN_OUT_DIR/"
    ls -la "$WIN_OUT_DIR/bgdesk.exe" 2>/dev/null || true
    if [[ -f "$ROOT/build/bgdesk-${INSTALLER_MODE}-win64.exe" ]]; then
      ls -la "$ROOT/build/bgdesk-${INSTALLER_MODE}-win64.exe"
    fi
}

ensure_local_flutter_engine() {
  [[ "$FLUTTER_UPDATE" == "1" ]] || return 0
  local engine_out="$FLUTTER_ROOT/engine/src/out/host_release_arm64/FlutterMacOS.framework"
  [[ "${FLUTTER_ENGINE_PATCH_APPLIED:-}" == "1" ]] || return 0
  [[ -f "$engine_out/Versions/A/FlutterMacOS" ]] && return 0
  echo "[build] engine local não encontrado; compilando (pode demorar)..."
  "$ROOT/scripts/build-flutter-local-engine-macos.sh"
}

setup_macos_flutter_github() {
  export BGDESK_FLUTTER_GITHUB=1
  # Flutter do GitHub (branch master) — somente build manual macOS; ver scripts/setup-flutter-github.sh
  # shellcheck source=/dev/null
  source "$ROOT/scripts/setup-flutter-github.sh"
}

ensure_macos_vcpkg() {
  export VCPKG_ROOT="${VCPKG_ROOT:-$HOME/.bin/vcpkg}"
  local vcpkg_commit="120deac3062162151622ca4860575a33844ba10b"
  if [[ ! -x "$VCPKG_ROOT/vcpkg" ]]; then
    echo "[build] instalando vcpkg em $VCPKG_ROOT..."
    mkdir -p "$(dirname "$VCPKG_ROOT")"
    git clone https://github.com/microsoft/vcpkg.git "$VCPKG_ROOT"
    git -C "$VCPKG_ROOT" checkout "$vcpkg_commit"
    "$VCPKG_ROOT/bootstrap-vcpkg.sh" -disableMetrics
  fi
  local ffmpeg_hdr="$VCPKG_ROOT/installed/$VCPKG_TRIPLET/include/libavutil/attributes.h"
  if [[ ! -f "$ffmpeg_hdr" ]]; then
    echo "[build] instalando dependências vcpkg ($VCPKG_TRIPLET)..."
    "$ROOT/install-vcpkg.sh"
  fi
}

buildMac()
{
    ensure_cargo
    export VCPKG_ROOT="${VCPKG_ROOT:-$HOME/.bin/vcpkg}"
    if [[ "$ARCH" == "arm64" ]]; then
      export VCPKG_TRIPLET="${VCPKG_TRIPLET:-arm64-osx}"
    else
      export VCPKG_TRIPLET="${VCPKG_TRIPLET:-x64-osx}"
    fi
    ensure_macos_vcpkg
    setup_macos_flutter_github
    # Flutter master precisa dos renames DialogTheme/TabBarTheme e deps novas.
    bash "$ROOT/.github/patches/apply_flutter_3.44_source_patches.sh"
    ensure_local_flutter_engine
    ensure_bridge
    log_flutter_for_build
    local BUILD_ARGS=(--flutter --hwcodec --unix-file-copy-paste)
    if [[ "$BGDESK_CLIENTE" == "1" ]]; then
      BUILD_ARGS+=(--incoming-only)
      echo "[build] modo cliente (somente conexões recebidas)"
    fi
    $PYTHON build.py "${BUILD_ARGS[@]}"
    STAMP_SRC="build/flutter-build-stamp.txt"
    [[ -f "$STAMP_SRC" ]] || STAMP_SRC="flutter/build/flutter-build-stamp.txt"
    if [[ -f "$STAMP_SRC" ]]; then
      mkdir -p flutter/build/macos/Build/Products/Release/BGDesk.app/Contents/Resources
      cp "$STAMP_SRC" \
        flutter/build/macos/Build/Products/Release/BGDesk.app/Contents/Resources/flutter-build-stamp.txt
    fi
    mv flutter/build/macos/Build/Products/Release/BGDesk.app ./build/BGDesk.app
    if [[ -f "$STAMP_SRC" ]]; then
      mkdir -p ./build/BGDesk.app/Contents/Resources
      cp "$STAMP_SRC" ./build/BGDesk.app/Contents/Resources/flutter-build-stamp.txt
      if [[ "$(cd "$(dirname "$STAMP_SRC")" && pwd)/$(basename "$STAMP_SRC")" != "$(pwd)/build/flutter-build-stamp.txt" ]]; then
        cp "$STAMP_SRC" ./build/flutter-build-stamp.txt
      fi
    fi
    local ZIP_NAME
    if [[ "$BGDESK_CLIENTE" == "1" ]]; then
      ZIP_NAME="bgdesk-cliente-darwin.zip"
    else
      ZIP_NAME="bgdesk-suporte-darwin.zip"
    fi
    (
      cd build
      zip -vr "$ZIP_NAME" BGDesk.app
    )
    echo ""
    echo "=== Flutter usado neste build ==="
    cat build/flutter-build-stamp.txt 2>/dev/null || true
}

buildLinux_x86_64()
{
    echo "Building Linux-x86_64 (.deb + .rpm + AppImage via Docker)"
    local args=()
    if [[ "${BGDESK_CLIENTE}" == "1" ]]; then
      echo "[build] modo cliente (somente conexões recebidas)"
      args+=(cliente)
    else
      echo "[build] modo suporte"
    fi
    if [[ "${FORCE_REBUILD}" == "1" ]]; then
      echo "[build] FORCE_REBUILD=1 — recompilação completa"
      args+=(--force)
    fi
    if [[ "${REBUILD_IMAGE}" == "1" ]]; then
      args+=(--rebuild-image)
    fi
    if [[ "${BUILD_BRIDGES}" == "1" ]]; then
      echo "[build] BUILD_BRIDGES=1 — regenerando bridge"
      args+=(--build-bridges)
    fi
    # ${args[@]+...} evita "unbound variable" com set -u e array vazio (bash 3.2/macOS)
    bash ./scripts/docker-build-linux-x86_64.sh ${args[@]+"${args[@]}"}
}

buildLinux_aarch64()
{
    echo "Building Linux-aarch64 (.deb + .rpm + AppImage via Docker)"
    local args=()
    if [[ "${BGDESK_CLIENTE}" == "1" ]]; then
      echo "[build] modo cliente (somente conexões recebidas)"
      args+=(cliente)
    else
      echo "[build] modo suporte"
    fi
    if [[ "${FORCE_REBUILD}" == "1" ]]; then
      echo "[build] FORCE_REBUILD=1 — recompilação completa"
      args+=(--force)
    fi
    if [[ "${REBUILD_IMAGE}" == "1" ]]; then
      args+=(--rebuild-image)
    fi
    if [[ "${BUILD_BRIDGES}" == "1" ]]; then
      echo "[build] BUILD_BRIDGES=1 — regenerando bridge"
      args+=(--build-bridges)
    fi
    # ${args[@]+...} evita "unbound variable" com set -u e array vazio (bash 3.2/macOS)
    bash ./scripts/docker-build-linux-aarch64.sh ${args[@]+"${args[@]}"}
}

# ./build.sh linux — em qualquer plataforma, compila Linux via Docker
# (arch do host: arm64/aarch64 → aarch64; x86_64 → amd64)
buildLinux()
{
    local arch
    arch="$(uname -m)"
    case "$arch" in
      aarch64|arm64)
        buildLinux_aarch64
        ;;
      x86_64|amd64)
        buildLinux_x86_64
        ;;
      *)
        echo "Arquitetura não suportada para build Linux via Docker: $arch"
        echo "Use: ./build.sh linux-x86_64 ou ./build.sh linux-aarch64"
        exit 1
        ;;
    esac
}

buildAndroid()
{
    ensure_cargo
    TARGET=aarch64-linux-android
    echo "Building Android"
    ./flutter/ndk_arm64.sh
    mkdir -p ./flutter/android/app/src/main/jniLibs/arm64-v8a
    cp ./target/aarch64-linux-android/release/liblibrustdesk.so ./flutter/android/app/src/main/jniLibs/arm64-v8a/librustdesk.so

    sed -i '' "s/signingConfigs.release/signingConfigs.debug/g" ./flutter/android/app/build.gradle

    cp "$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so" ./flutter/android/app/src/main/jniLibs/arm64-v8a/
    cp "./target/$TARGET/release/liblibrustdesk.so" ./flutter/android/app/src/main/jniLibs/arm64-v8a/librustdesk.so
    pushd flutter >/dev/null
    flutter build apk "--release" --target-platform android-arm64 --split-per-abi
    mv build/app/outputs/flutter-apk/app-arm64-v8a-release.apk ../bgdesk.apk
    popd >/dev/null
    mkdir -p signed-apk
    mv bgdesk.apk signed-apk/
}

# ./build.sh --build-bridges — só regenera o bridge (sem build de plataforma)
if [[ "$BUILD_BRIDGES" == "1" && -z "$FORCED_PLATFORM" && "$BGDESK_CLIENTE" != "1" ]]; then
  ensure_cargo
  if [[ $OS == *$WINDOWS* ]]; then
    setup_windows_build_env
  fi
  echo "[build] --build-bridges: regenerando bridge..."
  generate_bridge
  exit 0
fi

if [[ $FORCED_PLATFORM == "windows" ]]; then
   buildWindows
   exit 0
fi
if [[ $FORCED_PLATFORM == "mac" ]]; then
   buildMac
   exit 0
fi
if [[ $FORCED_PLATFORM == "linux" ]]; then
   buildLinux
   exit 0
fi
if [[ $FORCED_PLATFORM == "linux-x86_64" ]]; then
   buildLinux_x86_64
   exit 0
fi
if [[ $FORCED_PLATFORM == "linux-aarch64" ]]; then
   buildLinux_aarch64
   exit 0
fi
if [[ $FORCED_PLATFORM == "android" ]]; then
   buildAndroid
   exit 0
fi

if [[ $OS == *$WINDOWS* ]]; then
   buildWindows
   exit 0
fi

if [[ $OS == *$MAC* ]]; then
   buildMac
   exit 0
fi

if [[ $OS == *$LINUX* ]]; then
   echo "Use: ./build.sh linux, ./build.sh linux-x86_64 ou ./build.sh linux-aarch64"
   echo "Veja: ./build.sh --help"
   exit 1
fi
