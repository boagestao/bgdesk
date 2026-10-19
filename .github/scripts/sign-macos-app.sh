#!/usr/bin/env bash

set -euo pipefail

app_path=${1:?Usage: sign-macos-app.sh app identity entitlements}
identity=${2:?Missing signing identity}
entitlements=${3:?Missing entitlements plist}

[[ -d "$app_path/Contents/MacOS" && -f "$entitlements" ]]

sign_args=(--force --options runtime --sign "$identity")
if [[ -n "${MACOS_CODESIGN_KEYCHAIN:-}" ]]; then
  sign_args+=(--keychain "$MACOS_CODESIGN_KEYCHAIN")
fi
if [[ "$identity" != "-" ]]; then
  sign_args+=(--timestamp)
fi

frameworks_path="$app_path/Contents/Frameworks"
if [[ -d "$frameworks_path" ]]; then
  while IFS= read -r -d '' code; do
    if file -b "$code" | grep -q 'Mach-O'; then
      codesign "${sign_args[@]}" "$code"
    fi
  done < <(find "$frameworks_path" -type f -print0)

  while IFS= read -r -d '' framework; do
    codesign "${sign_args[@]}" "$framework"
  done < <(find "$frameworks_path" -depth -type d -name '*.framework' -print0)
fi

# Sign helper executables as well as the main executable before sealing the app.
while IFS= read -r -d '' code; do
  if file -b "$code" | grep -q 'Mach-O'; then
    codesign "${sign_args[@]}" "$code"
  fi
done < <(find "$app_path/Contents/MacOS" -type f -print0)

codesign "${sign_args[@]}" --generate-entitlement-der \
  --entitlements "$entitlements" "$app_path"
codesign --verify --deep --strict --verbose=2 "$app_path"

actual_entitlements=$(codesign -d --entitlements - --xml "$app_path" 2>/dev/null)
audio_input=$(plutil -extract 'com\.apple\.security\.device\.audio-input' raw - \
  <<<"$actual_entitlements")
if [[ "$audio_input" != "true" ]]; then
  echo "Missing com.apple.security.device.audio-input entitlement" >&2
  exit 1
fi

debug_allowed=$(plutil -extract 'com\.apple\.security\.get-task-allow' raw - \
  <<<"$actual_entitlements" 2>/dev/null || true)
if [[ "$debug_allowed" == "true" ]]; then
  echo "Release signature must not contain com.apple.security.get-task-allow" >&2
  exit 1
fi
