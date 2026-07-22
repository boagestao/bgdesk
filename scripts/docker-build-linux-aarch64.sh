#!/usr/bin/env bash
set -euo pipefail
set -o pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/build-out-dir.sh
source "$ROOT/scripts/build-out-dir.sh"
export BGDESK_BUILD_OUT_DIR="$(bgdesk_build_out_dir linux aarch64)"
bgdesk_prepare_build_out_dir "$BGDESK_BUILD_OUT_DIR"

IMAGE="bgdesk-build-aarch64"
DOCKERFILE="docker/build-linux-aarch64.dockerfile"
FORCE_REBUILD="${FORCE_REBUILD:-0}"
REBUILD_IMAGE="${REBUILD_IMAGE:-0}"
BUILD_BRIDGES="${BUILD_BRIDGES:-0}"
BGDESK_CLIENTE="${BGDESK_CLIENTE:-0}"

for arg in "$@"; do
  case "$arg" in
    --force|-f|force) FORCE_REBUILD=1 ;;
    --rebuild-image) REBUILD_IMAGE=1 ;;
    --build-bridges) BUILD_BRIDGES=1 ;;
    cliente|--cliente|--incoming-only) BGDESK_CLIENTE=1 ;;
  esac
done

if [[ "${REBUILD_IMAGE}" == "1" ]]; then
  echo "[docker-build-linux-aarch64] --rebuild-image: reconstruindo imagem ${IMAGE} (linux/arm64)..."
  docker build --platform linux/arm64 -t "${IMAGE}" -f "${DOCKERFILE}" .
elif docker image inspect "${IMAGE}" >/dev/null 2>&1; then
  echo "[docker-build-linux-aarch64] imagem ${IMAGE} já existe — pulando docker build (use --rebuild-image para forçar)"
else
  echo "[docker-build-linux-aarch64] imagem ${IMAGE} não encontrada — construindo (linux/arm64)..."
  docker build --platform linux/arm64 -t "${IMAGE}" -f "${DOCKERFILE}" .
fi

echo "[docker-build-linux-aarch64] running compile inside container (FORCE_REBUILD=${FORCE_REBUILD}, BUILD_BRIDGES=${BUILD_BRIDGES}, BGDESK_CLIENTE=${BGDESK_CLIENTE})..."
# target/ fica em volume Linux nativo: bind-mount do macOS quebra fingerprints do Cargo
# e força recompilação total a cada run. registry/git/pub também em volumes.
docker run --platform linux/arm64 --rm \
  -e FORCE_REBUILD="${FORCE_REBUILD}" \
  -e BUILD_BRIDGES="${BUILD_BRIDGES}" \
  -e BGDESK_CLIENTE="${BGDESK_CLIENTE}" \
  -e BGDESK_BUILD_OUT_DIR="${BGDESK_BUILD_OUT_DIR}" \
  -e CARGO_INCREMENTAL=1 \
  -v "${ROOT}:/root/bgdesk" \
  -v bgdesk-target-aarch64:/root/bgdesk/target \
  -v bgdesk-cargo-registry:/root/.cargo/registry \
  -v bgdesk-cargo-git:/root/.cargo/git \
  -v bgdesk-pub-cache:/root/.pub-cache \
  "${IMAGE}"

echo "[docker-build-linux-aarch64] collecting artifacts into ${BGDESK_BUILD_OUT_DIR}/..."
mkdir -p "$BGDESK_BUILD_OUT_DIR"
shopt -s nullglob
for f in bgdesk-*-aarch64.deb bgdesk-*-aarch64.rpm; do
  mv -f "$f" "$BGDESK_BUILD_OUT_DIR/"
done
for f in appimage/bgdesk-*.AppImage appimage/BGDesk-*.AppImage; do
  mv -f "$f" "$BGDESK_BUILD_OUT_DIR/"
done
rm -f appimage/*.zst appimage/debian-binary appimage/bgdesk.deb \
  appimage/control.tar.* appimage/data.tar.* ./*.zst 2>/dev/null || true
echo "[docker-build-linux-aarch64] done — artifacts:"
ls -lh "$BGDESK_BUILD_OUT_DIR"/*.deb "$BGDESK_BUILD_OUT_DIR"/*.rpm "$BGDESK_BUILD_OUT_DIR"/*.AppImage 2>/dev/null || true
