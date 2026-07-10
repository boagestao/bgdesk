#!/usr/bin/env bash
cargo ndk --platform 21 --target aarch64-linux-android --bindgen build --release --lib --features flutter,hwcodec
