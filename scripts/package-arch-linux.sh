#!/usr/bin/env bash
# Reuse the Linux x64 Flutter bundle; makepkg only assembles the Arch package.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
edition="${1:-}"
case "$edition" in cliente|suporte) ;; *) echo 'Usage: package-arch-linux.sh cliente|suporte [--bundle DIR] [--output DIR]' >&2; exit 2 ;; esac
shift
bundle="$root/flutter/build/linux/x64/release/bundle"
output="$root/build/linux-x86_64-$edition"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle) bundle="$2"; shift 2 ;;
    --output) output="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -x "$bundle/bgdesk" && -d "$bundle/lib" && -d "$bundle/data" ]] || {
  echo "Missing compiled Linux x64 Flutter bundle: $bundle" >&2; exit 1;
}
version="$(python3 -c 'import sys,tomllib; print(tomllib.load(open(sys.argv[1],"rb"))["package"]["version"])' "$root/Cargo.toml")"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Invalid stable version' >&2; exit 1; }
work="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/bgdesk-arch.XXXXXX")"
trap 'rm -rf "$work"' EXIT
# Mount only public packaging inputs and the compiled payload, never .env/config.
cp -a "$bundle" "$work/bundle"
cp "$root/res/arch/PKGBUILD" "$root/res/arch/bgdesk.install" "$root/res/arch/bgdesk.pam" "$work/"
for asset in bgdesk.service bgdesk.desktop bgdesk-link.desktop 128x128@2x.png scalable.svg startwm.sh; do
  cp "$root/res/$asset" "$work/"
done
image='archlinux:base-devel@sha256:0ccc8b2e55c0c26a6e501e892cc6b1cdea7cfdf77e432941320148b4dabd2bff'
docker run --rm --platform linux/amd64 --network none \
  -e "BGDESK_EDITION=$edition" -e "BGDESK_VERSION=$version" \
  -e "BGDESK_OWNER=$(id -u):$(id -g)" \
  -v "$work:/package" "$image" bash -euc '
    trap '\''chown -R "$BGDESK_OWNER" /package'\'' EXIT
    useradd --create-home builder
    chown -R builder:builder /package
    cd /package
    runuser -u builder -- env BGDESK_EDITION="$BGDESK_EDITION" BGDESK_VERSION="$BGDESK_VERSION" \
      makepkg --nodeps --nocheck --noconfirm
    package="bgdesk-$BGDESK_EDITION-$BGDESK_VERSION-1-x86_64.pkg.tar.zst"
    pacman -Qip "$package"
    bsdtar -tf "$package" | grep -qx usr/lib/systemd/system/bgdesk.service
    bsdtar -tf "$package" | grep -qx .INSTALL
  '
mkdir -p "$output"
cp "$work/bgdesk-$edition-$version-1-x86_64.pkg.tar.zst" "$output/bgdesk-$edition-x86_64.pkg.tar.zst"
echo "Arch package: $output/bgdesk-$edition-x86_64.pkg.tar.zst"
