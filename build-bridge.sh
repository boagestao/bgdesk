#!/bin/bash

OS=$(uname -s)
ARCH=$(uname -m)

echo "Building bridge for $OS $ARCH"
echo "OS: $OS"
echo "ARCH: $ARCH"

MAC="Darwin"
WINDOWS="NT"
LINUX="Linux"

rm -rf build
mkdir -p build

buildWindows()
{
    # On windows, is better to generate the bridge using a docker image    
    docker build -t bgdesk-bridge -f docker/bridge.dockerfile .
    docker run -it -v $(pwd -W):/root/bgdesk bgdesk-bridge
}

buildLinux()
{
    # On windows, is better to generate the bridge using a docker image    
    docker build -t bgdesk-bridge -f docker/bridge.dockerfile .
    docker run -it -v $(pwd):/root/bgdesk bgdesk-bridge
}

buildMac()
{
    cargo install cargo-expand --version 1.0.95 --locked
    cargo install flutter_rust_bridge_codegen --version 1.80.1 --features "uuid" --locked
    pushd flutter && sed -i -e 's/extended_text: 14.0.0/extended_text: 13.0.0/g' pubspec.yaml && flutter pub get && popd
    ~/.cargo/bin/flutter_rust_bridge_codegen --llvm-path="/c/LLVM" --rust-input ./src/flutter_ffi.rs --dart-output ./flutter/lib/generated_bridge.dart --c-output ./flutter/macos/Runner/bridge_generated.h
    cp ./flutter/macos/Runner/bridge_generated.h ./flutter/ios/Runner/bridge_generated.h
    
    # Case of mac-os it must change all classes to "final class"
}

if [[ $OS == *$WINDOWS* ]]; then
   buildWindows
fi

if [[ $OS == *$MAC* ]]; then
   buildMac
fi

if [[ $OS == *$LINUX* ]]; then
   buildLinux
fi

