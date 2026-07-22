#!/usr/bin/env bash
# Carrega PATH e variáveis do ambiente Windows para ./build.sh
# Gerado por scripts/setup-windows-build.sh (não editar manualmente).

win_user_home() {
  if [[ -n "${USERPROFILE:-}" ]]; then
    echo "${USERPROFILE//\\//}"
  else
    echo "${HOME//\\//}"
  fi
}

load_windows_build_env() {
  local win_home env_file
  win_home="$(win_user_home)"

  if [[ -f "$win_home/.cargo/env" ]]; then
    # shellcheck source=/dev/null
    . "$win_home/.cargo/env"
  elif [[ -d "$win_home/.cargo/bin" ]]; then
    export PATH="$win_home/.cargo/bin:$PATH"
  fi

  if [[ -f "${HOME}/.cargo/env" && "$HOME" != "$win_home" ]]; then
    # shellcheck source=/dev/null
    . "${HOME}/.cargo/env"
  fi

  local vcpkg_root="${VCPKG_ROOT:-$HOME/.bin/vcpkg}"
  if [[ -x "$vcpkg_root/vcpkg.exe" ]]; then
    export VCPKG_ROOT="$vcpkg_root"
  elif [[ -x "/c/vcpkg/vcpkg.exe" ]]; then
    export VCPKG_ROOT="/c/vcpkg"
  fi
  export VCPKG_TRIPLET="${VCPKG_TRIPLET:-x64-windows-static}"
  export VCPKG_DEFAULT_HOST_TRIPLET="${VCPKG_DEFAULT_HOST_TRIPLET:-$VCPKG_TRIPLET}"

  if [[ -n "${VCPKG_ROOT:-}" ]]; then
    local llvm_root="$VCPKG_ROOT/downloads/tools/clang/clang-15.0.6"
    local llvm_bin="$llvm_root/bin"
    if [[ -f "$llvm_bin/libclang.dll" ]]; then
      export LIBCLANG_PATH="$llvm_bin"
      export BGDESK_LLVM_ROOT="$llvm_root"
    fi
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

  local local_env
  local_env="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/windows-build-env.local.sh"
  if [[ -f "$local_env" ]]; then
    # shellcheck source=/dev/null
    source "$local_env"
  fi
}

if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* || "$(uname -s)" == CYGWIN* ]]; then
  load_windows_build_env
fi
