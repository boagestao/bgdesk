cd "$(dirname "$0")"

if ! $VCPKG_ROOT/vcpkg \
  install \
  --triplet $VCPKG_TRIPLET \
  --x-install-root="$VCPKG_ROOT/installed"; then
  find "${VCPKG_ROOT}/" -name "*.log" | while read -r _1; do
    echo "$_1:"
    echo "======"
    cat "$_1"
    echo "======"
    echo ""
  done
  exit 1
fi
head -n 100 "${VCPKG_ROOT}/buildtrees/ffmpeg/build-$VCPKG_TRIPLET-rel-out.log" || true
