#!/usr/bin/env bash
# Verifica se não há vazamento de "RustDesk" onde deveria ser "BGDesk".
# Ver AUALIZACAO.md — Fase 10.2

set -euo pipefail

ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

ERRORS=0

while IFS= read -r line; do
  file="${line%%:*}"
  [[ "$file" == *"docs/"* ]] && continue
  [[ "$file" == *"LICENCE"* ]] && continue
  [[ "$file" == *"CONTRIBUTING"* ]] && continue
  [[ "$file" == *"Cargo.toml" ]] && continue
  [[ "$file" == *"AppInfo.xcconfig" ]] && continue
  echo "⚠️  $line"
  ERRORS=$((ERRORS + 1))
done < <(grep -rn 'RustDesk' \
  --include='*.dart' --include='*.xml' --include='*.plist' \
  --include='*.gradle' --include='*.wxl' --include='*.nsi' \
  --include='*.desktop' --include='*.service' --include='*.html' \
  --include='*.tis' --include='*.css' \
  src/ flutter/ res/ flatpak/ appimage/ 2>/dev/null || true)

if [ "$ERRORS" -eq 0 ]; then
  echo "✅ Nenhum vazamento de branding detectado"
else
  echo "❌ $ERRORS ocorrências de 'RustDesk' encontradas — revisar acima"
  exit 1
fi
