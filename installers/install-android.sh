CARGO_NDK_VERSION=3.1.2

rustup target add aarch64-linux-android  
cargo install cargo-ndk --version $CARGO_NDK_VERSION --locked