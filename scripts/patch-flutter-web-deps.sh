#!/usr/bin/env bash
# qr_code_scanner 1.0.1 still uses dart:ui's removed platformViewRegistry.
# Run after flutter pub get when building/testing with modern Flutter.
set -euo pipefail

QR_WEB="${PUB_CACHE:-$HOME/.pub-cache}/hosted/pub.dev/qr_code_scanner-1.0.1/lib/src/web/flutter_qr_web.dart"
python3 - "$QR_WEB" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()
if "import 'dart:ui_web' as ui_web;" not in source:
    anchor = "import 'dart:ui' as ui;"
    if anchor not in source:
        raise SystemExit(f"Unexpected qr_code_scanner web implementation: {path}")
    source = source.replace(anchor, anchor + " import 'dart:ui_web' as ui_web;")
source = source.replace('ui.platformViewRegistry', 'ui_web.platformViewRegistry')
if 'ui_web.platformViewRegistry' not in source:
    raise SystemExit(f"Missing platformViewRegistry in {path}")
path.write_text(source)
PY
