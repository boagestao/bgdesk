FROM ubuntu:18.04

WORKDIR /root
ARG DEBIAN_FRONTEND=noninteractive
ENV VCPKG_FORCE_SYSTEM_BINARIES=1
RUN apt update -y
RUN apt install --yes --no-install-recommends \
        g++ \
        gcc \
        git \
        curl \
        nasm \
        yasm \
        libgtk-3-dev \
        clang \
        libxcb-randr0-dev \
        libxdo-dev \
        libxfixes-dev \
        libxcb-shape0-dev \
        libxcb-xfixes0-dev \
        libasound2-dev \
        libpam0g-dev \
        libpulse-dev \
        make \
        cmake \
        wget \
        libssl-dev \
        unzip \
        zip \
        tar \
        libgstreamer1.0-dev \
        libgstreamer-plugins-base1.0-dev \
        ca-certificates \
        ninja-build \
        libclang-10-dev \
        llvm-10-dev \
        pkg-config 

# Install Rust
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

RUN /root/.cargo/bin/cargo install cargo-expand --version 1.0.95 --locked
RUN /root/.cargo/bin/cargo install flutter_rust_bridge_codegen --version 1.80.1 --features "uuid" --locked
   
# Install Flutter
RUN wget https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.22.3-stable.tar.xz
RUN tar xf flutter_linux_3.22.3-stable.tar.xz
RUN rm flutter_linux_3.22.3-stable.tar.xz

RUN git config --global --add safe.directory /root/flutter
RUN git config --global --add safe.directory /root/.cargo

RUN /root/flutter/bin/flutter --disable-analytics

COPY ./docker/bridge.entrypoint.sh /bridge.entrypoint.sh
RUN chmod +x /bridge.entrypoint.sh

ENTRYPOINT ["/bridge.entrypoint.sh"]