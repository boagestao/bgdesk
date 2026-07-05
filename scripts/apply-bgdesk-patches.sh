#!/usr/bin/env bash
# Reaplica customizações BGDesk após cópia/merge do upstream RustDesk.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log() { echo "[patch] $*"; }

# --- hbb_common ---
patch_hbb_common() {
  local hbb="$ROOT/libs/hbb_common"
  [[ -d "$hbb" ]] || return 0
  log "hbb_common: branding e servidores"

  # config.rs
  sed -i '' \
    -e 's/"RustDesk"/"BGDesk"/g' \
    -e 's/"rustdesk\.com"/"br.com.boagestao"/g' \
    -e 's|&\["rs-ny\.rustdesk\.com"\]|&["bgdesk.boagestao.net"]|g' \
    "$hbb/src/config.rs" 2>/dev/null || \
  sed -i \
    -e 's/"RustDesk"/"BGDesk"/g' \
    -e 's/"rustdesk\.com"/"br.com.boagestao"/g' \
    "$hbb/src/config.rs"

  # Fix RENDEZVOUS_SERVERS explicitly
  perl -i -pe 's/pub const RENDEZVOUS_SERVERS: &\[&str\] = &\[.*?\];/pub const RENDEZVOUS_SERVERS: \&[\&str] = \&["bgdesk.boagestao.net"];/s' "$hbb/src/config.rs" 2>/dev/null || true

  # ORG macOS — com.boagestao preserva ~/Library/Preferences/com.boagestao.BGDesk/
  perl -i -pe 's/RwLock::new\("rustdesk\.com"\.to_owned\(\)\)/RwLock::new("com.boagestao".to_owned())/g' "$hbb/src/config.rs" 2>/dev/null || true
  perl -i -pe 's/RwLock::new\("br\.com\.boagestao"\.to_owned\(\)\)/RwLock::new("com.boagestao".to_owned())/g' "$hbb/src/config.rs" 2>/dev/null || true

  # DEFAULT_SETTINGS: servidor BGDesk embutido (ID/API/key nas opções padrão)
  if ! grep -q 'fn bgdesk_default_settings' "$hbb/src/config.rs"; then
    perl -i -0pe 's/(const SERIAL: i32 = \d+;\n)/$1\nfn bgdesk_default_settings() -> HashMap<String, String> {\n    HashMap::from([\n        ("custom-rendezvous-server".to_string(), "bgdesk.boagestao.net".to_string()),\n        ("api-server".to_string(), "https:\/\/bgdesk.boagestao.net".to_string()),\n        ("key".to_string(), "hy3fp1caHX+7TRpdwMXNAlce0KMFRSmHFFAd5d0sYLI=".to_string()),\n    ])\n}\n/s' "$hbb/src/config.rs" 2>/dev/null || true
    perl -i -pe 's/pub static ref DEFAULT_SETTINGS: RwLock<HashMap<String, String>> = Default::default\(\);/pub static ref DEFAULT_SETTINGS: RwLock<HashMap<String, String>> = RwLock::new(bgdesk_default_settings());/g' "$hbb/src/config.rs" 2>/dev/null || true
  fi

  # Doc links
  perl -i -pe 's|pub const LINK_DOCS_HOME: &str = "https://rustdesk\.com/";|pub const LINK_DOCS_HOME: \&str = "https://boagestao.com.br/";|g' "$hbb/src/config.rs" 2>/dev/null || true
  perl -i -pe 's|pub const LINK_DOCS_X11_REQUIRED: &str = "https://rustdesk\.com/docs[^"]*";|pub const LINK_DOCS_X11_REQUIRED: \&str = "https://boagestao.com.br";|g' "$hbb/src/config.rs" 2>/dev/null || true

  # lib.rs version check
  sed -i '' \
    -e 's/VER_TYPE_RUSTDESK_CLIENT: &str = "rustdesk-client"/VER_TYPE_RUSTDESK_CLIENT: \&str = "bgdesk-client"/' \
    -e 's/VER_TYPE_RUSTDESK_SERVER: &str = "rustdesk-server"/VER_TYPE_RUSTDESK_SERVER: \&str = "bgdesk-server"/' \
    -e 's|https://api\.rustdesk\.com/version/latest|https://bgdesk.boagestao.net/version/latest|g' \
    "$hbb/src/lib.rs" 2>/dev/null || \
  sed -i \
    -e 's/VER_TYPE_RUSTDESK_CLIENT: &str = "rustdesk-client"/VER_TYPE_RUSTDESK_CLIENT: \&str = "bgdesk-client"/' \
    -e 's/VER_TYPE_RUSTDESK_SERVER: &str = "rustdesk-server"/VER_TYPE_RUSTDESK_SERVER: \&str = "bgdesk-server"/' \
    -e 's|https://api\.rustdesk\.com/version/latest|https://bgdesk.boagestao.net/version/latest|g' \
    "$hbb/src/lib.rs"

  # platform/mod.rs
  sed -i '' 's/"RustDesk"/"BGDesk"/g' "$hbb/src/platform/mod.rs" 2>/dev/null || \
  sed -i 's/"RustDesk"/"BGDesk"/g' "$hbb/src/platform/mod.rs"

  # message.proto scheme
  sed -i '' 's/rustdesk:\/\//bgdesk:\/\//g' "$hbb/protos/message.proto" 2>/dev/null || \
  sed -i 's/rustdesk:\/\//bgdesk:\/\//g' "$hbb/protos/message.proto"
}

# --- Cargo.toml raiz ---
patch_cargo_toml() {
  log "Cargo.toml: versão e branding"
  sed -i '' \
    -e 's/^version = ".*"/version = "1.4.8"/' \
    -e 's/description = ".*"/description = "BGDesk Remote Desktop"/' \
    "$ROOT/Cargo.toml" 2>/dev/null || \
  sed -i \
    -e 's/^version = ".*"/version = "1.4.8"/' \
    -e 's/description = ".*"/description = "BGDesk Remote Desktop"/' \
    "$ROOT/Cargo.toml"

  # metadata.bundle.name
  perl -i -0pe 's/name = "RustDesk"/name = "BGDesk"/g' "$ROOT/Cargo.toml" 2>/dev/null || true
}

# --- common.rs API server ---
patch_common_rs() {
  log "src/common.rs: API server"
  if grep -q 'bgdesk.boagestao.net' "$ROOT/src/common.rs"; then
    return 0
  fi
  perl -i -0pe 's/fn get_api_server_\(api: String, custom: String\) -> String \{.*?^\}/fn get_api_server_(api: String, custom: String) -> String {\n    "https:\/\/bgdesk.boagestao.net".to_owned()\n}/ms' "$ROOT/src/common.rs" 2>/dev/null || \
  sed -i '' 's|"https://[^"]*rustdesk[^"]*"|"https://bgdesk.boagestao.net"|g' "$ROOT/src/common.rs" 2>/dev/null || true
}

# --- auth_2fa ---
patch_auth() {
  [[ -f "$ROOT/src/auth_2fa.rs" ]] || return 0
  sed -i '' 's/const ISSUER: &str = "RustDesk"/const ISSUER: \&str = "BGDesk"/' "$ROOT/src/auth_2fa.rs" 2>/dev/null || \
  sed -i 's/const ISSUER: &str = "RustDesk"/const ISSUER: \&str = "BGDesk"/' "$ROOT/src/auth_2fa.rs"
}

# --- Traduções: RustDesk → BGDesk em strings de UI ---
patch_lang_files() {
  log "src/lang/: RustDesk → BGDesk em strings"
  find "$ROOT/src/lang" -name '*.rs' -print0 | while IFS= read -r -d '' f; do
    sed -i '' \
      -e 's/"RustDesk/"BGDesk/g' \
      -e 's/"About RustDesk"/"About BGDesk"/g' \
      -e 's/"Show RustDesk"/"Show BGDesk"/g' \
      -e 's/"Keep RustDesk background service"/"Keep BGDesk background service"/g' \
      "$f" 2>/dev/null || \
    sed -i \
      -e 's/"RustDesk/"BGDesk/g' \
      -e 's/"About RustDesk"/"About BGDesk"/g' \
      "$f"
  done
}

# --- Flutter branding ---
patch_flutter() {
  log "flutter/: branding BGDesk"

  # pubspec version
  sed -i '' 's/^version: .*/version: 1.4.8+66/' "$ROOT/flutter/pubspec.yaml" 2>/dev/null || \
  sed -i 's/^version: .*/version: 1.4.8+66/' "$ROOT/flutter/pubspec.yaml"

  # common.dart app name
  [[ -f "$ROOT/flutter/lib/common.dart" ]] && \
    sed -i '' "s/return 'RustDesk'/return 'BGDesk'/g" "$ROOT/flutter/lib/common.dart" 2>/dev/null || \
    sed -i "s/return 'RustDesk'/return 'BGDesk'/g" "$ROOT/flutter/lib/common.dart" 2>/dev/null || true

  # bridge.dart
  [[ -f "$ROOT/flutter/lib/bridge.dart" ]] && \
    sed -i '' "s/'RustDesk'/'BGDesk'/g" "$ROOT/flutter/lib/bridge.dart" 2>/dev/null || true

  # desktop_setting_page About
  [[ -f "$ROOT/flutter/lib/desktop/pages/desktop_setting_page.dart" ]] && \
    sed -i '' \
      -e 's/About RustDesk/About BGDesk/g' \
      -e 's/rustdesk\.com/bgdesk.com/g' \
      "$ROOT/flutter/lib/desktop/pages/desktop_setting_page.dart" 2>/dev/null || true

  # Android
  [[ -f "$ROOT/flutter/android/app/build.gradle" ]] && \
    perl -i -pe 's/applicationId\s+"[^"]+"/applicationId "br.com.boagestao.bgdesksuporte"/' \
      "$ROOT/flutter/android/app/build.gradle" 2>/dev/null || true

  [[ -f "$ROOT/flutter/android/app/src/main/AndroidManifest.xml" ]] && \
    sed -i '' \
      -e 's/android:label="RustDesk"/android:label="BGDesk"/' \
      -e 's/rustdesk:/bgdesk:/g' \
      "$ROOT/flutter/android/app/src/main/AndroidManifest.xml" 2>/dev/null || true

  # macOS AppInfo
  [[ -f "$ROOT/flutter/macos/Runner/Configs/AppInfo.xcconfig" ]] && \
    sed -i '' 's/PRODUCT_NAME = RustDesk/PRODUCT_NAME = BGDesk/' \
      "$ROOT/flutter/macos/Runner/Configs/AppInfo.xcconfig" 2>/dev/null || true

  # Windows main.cpp
  [[ -f "$ROOT/flutter/windows/runner/main.cpp" ]] && \
    sed -i '' 's/L"RustDesk"/L"BGDesk"/' "$ROOT/flutter/windows/runner/main.cpp" 2>/dev/null || true

  # iOS Info.plist
  [[ -f "$ROOT/flutter/ios/Runner/Info.plist" ]] && \
    sed -i '' \
      -e 's/<string>RustDesk<\/string>/<string>BGDesk<\/string>/g' \
      -e 's/<string>rustdesk<\/string>/<string>bgdesk<\/string>/g' \
      "$ROOT/flutter/ios/Runner/Info.plist" 2>/dev/null || true
}

# --- libs/portable ---
patch_portable() {
  [[ -f "$ROOT/libs/portable/Cargo.toml" ]] && \
    sed -i '' 's/^version = ".*"/version = "1.4.8"/' "$ROOT/libs/portable/Cargo.toml" 2>/dev/null || true
}

# --- lang.rs: trocar vn por vi se necessário ---
patch_lang_rs() {
  [[ -f "$ROOT/src/lang.rs" ]] || return 0
  if grep -q 'mod vn;' "$ROOT/src/lang.rs" && [[ -f "$ROOT/src/lang/vi.rs" ]]; then
    sed -i '' 's/mod vn;/mod vi;/' "$ROOT/src/lang.rs" 2>/dev/null || \
    sed -i 's/mod vn;/mod vi;/' "$ROOT/src/lang.rs"
    sed -i '' 's/"vn"/"vi"/g' "$ROOT/src/lang.rs" 2>/dev/null || true
  fi
}

patch_hbb_common
patch_cargo_toml
patch_common_rs
patch_auth
patch_lang_files
patch_lang_rs
patch_flutter
patch_portable

log "✅ Patches BGDesk aplicados"
