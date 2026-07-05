#!/bin/bash

cd /root/bgdesk

PATH=/root/flutter/bin:/root/.cargo/bin:$PATH

cd /root/bgdesk

pushd flutter && sed -i -e 's/extended_text: 14.0.0/extended_text: 13.0.0/g' pubspec.yaml && flutter pub get && popd

flutter_rust_bridge_codegen --rust-input ./src/flutter_ffi.rs --dart-output ./flutter/lib/generated_bridge.dart --c-output ./flutter/macos/Runner/bridge_generated.h
cp ./flutter/macos/Runner/bridge_generated.h ./flutter/ios/Runner/bridge_generated.h

pushd flutter && sed -i -e 's/extended_text: 13.0.0/extended_text: 14.0.0/g' pubspec.yaml && popd