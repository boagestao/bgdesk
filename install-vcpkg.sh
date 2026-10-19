cd "$(dirname "$0")"

clean_args=()
if [[ "${VCPKG_CLEAN_AFTER_BUILD:-0}" == 1 ]]; then
  clean_args+=(--clean-after-build)
fi

if ! $VCPKG_ROOT/vcpkg \
  install \
  --triplet $VCPKG_TRIPLET \
  --x-install-root="$VCPKG_ROOT/installed" "${clean_args[@]}"; then
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
