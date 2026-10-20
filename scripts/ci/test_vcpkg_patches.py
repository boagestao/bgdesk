"""The pinned mfx-dispatch patch must be usable without a patch download."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PORT = Path(__file__).resolve().parents[2] / 'res/vcpkg/mfx-dispatch'
PATCH = 'fix-missing-cstdint-import-d6241243f85a0d947bdfe813006686a930edef24.patch'
SHA512 = '5d2ffc4ec2ba0e5859d01d2e072f75436ebc3e62e0f6580b5bb8b9f82fe588e7558a46a1fdfa0297a782c0eeb8f50322258d0dd9e41d927cc9be496727b61e44'


class MfxPatchTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cmake'), 'CMake required to exercise the port')
    def test_port_uses_verified_local_patch_without_downloading_it(self):
        self.assertEqual(hashlib.sha512((PORT / PATCH).read_bytes()).hexdigest(), SHA512)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'offline-port.cmake'
            script.write_text('''
cmake_minimum_required(VERSION 3.14)
function(vcpkg_download_distfile)
    message(FATAL_ERROR "Unexpected separate patch download")
endfunction()
function(vcpkg_from_github)
    cmake_parse_arguments(P "" "OUT_SOURCE_PATH;REPO;REF;SHA512;HEAD_REF" "PATCHES" ${ARGN})
    foreach(patch IN LISTS P_PATCHES)
        if(NOT EXISTS "${PORT}/${patch}")
            message(FATAL_ERROR "Missing bundled patch: ${patch}")
        endif()
    endforeach()
    list(FIND P_PATCHES "${EXPECTED_PATCH}" found)
    if(found EQUAL -1)
        message(FATAL_ERROR "Pinned cstdint patch was not applied")
    endif()
    set(${P_OUT_SOURCE_PATH} "${CMAKE_CURRENT_BINARY_DIR}/source" PARENT_SCOPE)
endfunction()
foreach(helper IN ITEMS vcpkg_cmake_configure vcpkg_cmake_install vcpkg_copy_pdbs vcpkg_fixup_pkgconfig vcpkg_install_copyright)
    function(${helper})
    endfunction()
endforeach()
set(VCPKG_TARGET_IS_WINDOWS TRUE)
set(CURRENT_PACKAGES_DIR "${CMAKE_CURRENT_BINARY_DIR}/package")
set(VERSION 1.35.1)
include("${PORT}/portfile.cmake")
''')
            result = subprocess.run(['cmake', f'-DPORT={PORT.as_posix()}',
                                     f'-DEXPECTED_PATCH={PATCH}', '-P', str(script)],
                                    cwd=root, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
