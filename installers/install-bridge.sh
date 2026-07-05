# RUN THIS SCRIPT ON WINDOWS USING GIT-BASH

OS=$(uname -s)
ARCH=$(uname -m)

MAC="Darwin"
WINDOWS="NT"

CARGO_EXPAND_VERSION="1.0.95"
FLUTTER_VERSION="3.22.3"
FLUTTER_RUST_BRIDGE_VERSION="1.80.1"
RUST_VERSION="1.75"

WINDOWS_LLVM_PATH=/c/LLVM

mkdir -p .temp

echo "Preparing the system to generate bridge..."
installWindows()
{   
    rustup install $RUST_VERSION
    rustup default $RUST_VERSION

    cargo install cargo-expand --version $CARGO_EXPAND_VERSION --locked --force
    cargo install flutter_rust_bridge_codegen --version $FLUTTER_RUST_BRIDGE_VERSION --features "uuid" --locked --force

    
    # curl -o .temp/flutter.zip https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_$FLUTTER_VERSION-stable.zip
    # rm -rf /c/Users/Belizario/flutter
    # unzip -q .temp/flutter.zip -d /c/Users/Belizario/

    pushd flutter && sed -i -e 's/extended_text: 14.0.0/extended_text: 13.0.0/g' pubspec.yaml && flutter pub get && popd

    # Before generate bridges, its necessary to change package name to "rustdesk" and then back to "bgdesk"
    # sed -i -e 's/name = "bgdesk"/name = "rustdesk"/g' Cargo.toml

    flutter_rust_bridge_codegen --rust-input ./src/flutter_ffi.rs --dart-output ./flutter/lib/generated_bridge.dart --c-output ./flutter/macos/Runner/bridge_generated.h --llvm-path $WINDOWS_LLVM_PATH
    cp ./flutter/macos/Runner/bridge_generated.h ./flutter/ios/Runner/bridge_generated.h

    cd ..
    pushd flutter && sed -i -e 's/extended_text: 13.0.0/extended_text: 14.0.0/g' pubspec.yaml && flutter pub get && popd

    # sed -i -e 's/name = "rustdesk"/name = "bgdesk"/g' Cargo.toml
}

installMac()
{
    echo "Not implemented yet"
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

clean