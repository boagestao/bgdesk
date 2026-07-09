#!/usr/bin/env bash
# Applies the Flutter 3.44-only source/pubspec changes on the fly.
#
# Windows arm64 needs Flutter >= 3.44 (the first stable release shipping an arm64 Dart SDK +
# engine), which renamed DialogTheme/TabBarTheme -> *Data and needs newer extended_text/
# google_fonts. macOS manual builds (./build.sh) use Flutter stable 3.44.6 and need the
# same renames. Every other platform is still on Flutter 3.24.5, where the old names/versions
# are required, so these changes are kept OUT of the committed sources and applied here instead.
#
# Used by the Windows arm64 build (flutter-build.yml), its dedicated bridge artifact (bridge.yml),
# and local macOS builds via ./build.sh so they share an identical source state.
#
# Remove this script (and commit the changes) once upstream bumps Flutter across the board.
#
# Run from the repository root. sed is used (not a git-apply patch) because the checked-out
# sources are CRLF on the windows-11-arm runner; the substitutions below are anchor-free and
# therefore CRLF-safe. Idempotent: safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# BSD sed (macOS) needs `sed -i ''`; GNU sed accepts `sed -i`.
if sed --version >/dev/null 2>&1; then
  sedi() { sed -i "$@"; }
else
  sedi() { sed -i '' "$@"; }
fi

# ThemeData API renames (Flutter 3.27+):
if ! grep -qF 'dialogTheme: DialogThemeData(' flutter/lib/common.dart; then
  sedi 's/dialogTheme: DialogTheme(/dialogTheme: DialogThemeData(/g' flutter/lib/common.dart
fi
if ! grep -qF 'tabBarTheme: const TabBarThemeData(' flutter/lib/common.dart; then
  sedi 's/tabBarTheme: const TabBarTheme(/tabBarTheme: const TabBarThemeData(/g' flutter/lib/common.dart
fi
if ! grep -qF 'backgroundColor: Colors.white,' flutter/lib/common.dart; then
  sedi '/static ThemeData lightTheme = ThemeData(/,/static ThemeData darkTheme = ThemeData(/s/dialogTheme: DialogThemeData(/dialogTheme: DialogThemeData(\
      backgroundColor: Colors.white,/' flutter/lib/common.dart
fi
if ! grep -qF 'backgroundColor: Color(0xFF18191E),' flutter/lib/common.dart; then
  sedi '/static ThemeData darkTheme = ThemeData(/,/scrollbarTheme: scrollbarThemeDark,/s/dialogTheme: DialogThemeData(/dialogTheme: DialogThemeData(\
      backgroundColor: Color(0xFF18191E),/' flutter/lib/common.dart
fi

# Dependency bumps required by the newer Dart/Flutter:
if ! grep -qF 'extended_text: 15.0.2' flutter/pubspec.yaml; then
  sedi 's/extended_text: 14.0.0/extended_text: 15.0.2/' flutter/pubspec.yaml
fi
if ! grep -qF 'google_fonts: ^8.1.0' flutter/pubspec.yaml; then
  sedi 's/google_fonts: \^6.2.1/google_fonts: ^8.1.0/' flutter/pubspec.yaml
fi

# Fail loudly if any expected string drifted, so we never silently build unpatched:
grep -qF 'dialogTheme: DialogThemeData(' flutter/lib/common.dart
grep -qF 'tabBarTheme: const TabBarThemeData(' flutter/lib/common.dart
grep -qF 'backgroundColor: Colors.white,' flutter/lib/common.dart
grep -qF 'backgroundColor: Color(0xFF18191E),' flutter/lib/common.dart
grep -qF 'extended_text: 15.0.2' flutter/pubspec.yaml
grep -qF 'google_fonts: ^8.1.0' flutter/pubspec.yaml

git --no-pager diff -- flutter/lib/common.dart flutter/pubspec.yaml || true
