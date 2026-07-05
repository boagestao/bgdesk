#!/bin/bash

OS=$(uname -s)
ARCH=$(uname -m)

CURRENT_DIR=$(pwd)

MAC="Darwin"
WINDOWS="NT"
LINUX="Linux"

LLVM_VERSION="15.0.6"
FLUTTER_VERSION="3.24.5"
FLUTTER_RUST_BRIDGE_VERSION="1.80.1"
RUST_VERSION="1.75"
MAC_RUST_VERSION="1.81" 

USBMMIDD_URL=https://github.com/rustdesk-org/rdev/releases/download/usbmmidd_v2/usbmmidd_v2.zip

WINDOWS_LLVM_URL=https://github.com/llvm/llvm-project/releases/download/llvmorg-15.0.6/LLVM-15.0.6-win64.exe
WINDOWS_FLUTTER_PATH=$HOME/flutter
WINDOWS_LLVM_PATH=/c/LLVM


VCPKG_COMMIT_ID="6f29f12e82a8293156836ad81cc9bf5af41fe836"
WINDOWS_VCPKG_ROOT=$HOME/vcpkg

mkdir -p .temp

echo "Preparing the system to build..."
installWindows()
{   
   # rustup install $RUST_VERSION
   # rustup default $RUST_VERSION
     
   # curl -o .temp/flutter.zip https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_$FLUTTER_VERSION-stable.zip
   # rm -rf $HOME/flutter
   # unzip -q .temp/flutter.zip -d $HOME

   flutter doctor -v
   flutter precache --windows

   # # Patching the flutter

   curl -o windows-x64-release.zip https://github.com/rustdesk/engine/releases/download/main/windows-x64-release.zip
   unzip -q ./.temp/windows-x64-release.zip -d .temp/windows-x64-release

   cp -rf .temp/windows-x64-release/* $WINDOWS_FLUTTER_PATH/bin/cache/artifacts/engine/windows-x64-release
   

   cp .github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff $(dirname $(dirname $(which flutter)))
   cd $(dirname $(dirname $(which flutter)))
   [[ "3.24.5" == ${{FLUTTER_VERSION}} ]] && git apply flutter_3.24.4_dropdown_menu_enableFilter.diff


   # export VCPKG_ROOT=$WINDOWS_VCPKG_ROOT

   # $VCPKG_ROOT/vcpkg install --triplet x64-windows-static --x-install-root=$VCPKG_ROOT/installed


   # curl -o .temp/usbmmidd_v2.zip $USBMMIDD_URL

   # unzip -q ./.temp/usbmmidd_v2.zip -d .

}

installLinux()
{
    echo "Preparing the system to generate bridge on Linux"

    sudo apt-get install -y \
            clang \
            cmake \
            curl \
            gcc \
            git \
            g++ \
            libclang-10-dev \
            libgtk-3-dev \
            llvm-10-dev \
            nasm \
            ninja-build \
            pkg-config \
            wget
}

installMac()
{
    echo "Preparing the system to generate bridge on Mac"
}

clean()
{
   rm -rf .temp
}

if [[ $OS == *$WINDOWS* ]]; then
   installWindows
fi

if [[ $OS == *$MAC* ]]; then
   installMac
fi

if [[ $OS == *$LINUX* ]]; then
   installLinux
fi

clean