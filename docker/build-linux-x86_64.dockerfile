FROM ubuntu:22.04

WORKDIR /root
ARG DEBIAN_FRONTEND=noninteractive
ENV VCPKG_FORCE_SYSTEM_BINARIES=1
ENV VCPKG_ROOT=/vcpkg
ENV VCPKG_TRIPLET=x64-linux
ENV DEB_ARCH=amd64
ENV CARGO_INCREMENTAL=0
ENV PUB_CACHE=/root/.pub-cache
ENV PATH="/opt/flutter/bin:/root/.cargo/bin:${PATH}"

ARG RUST_VERSION=1.75.0
ARG FLUTTER_VERSION=3.29.3
ARG VCPKG_COMMIT_ID=120deac3062162151622ca4860575a33844ba10b
ARG FLUTTER_RUST_BRIDGE_VERSION=1.80.1
ARG CARGO_EXPAND_VERSION=1.0.95

# --- system packages ---
RUN apt-get update -y && apt-get install -y --no-install-recommends \
        autoconf \
        automake \
        autotools-dev \
        build-essential \
        ca-certificates \
        clang \
        cmake \
        curl \
        dpkg-dev \
        fakeroot \
        gcc \
        git \
        g++ \
        libarchive-tools \
        libtool \
        libasound2-dev \
        libayatana-appindicator3-dev \
        libclang-dev \
        libfuse2 \
        libgstreamer1.0-dev \
        libgstreamer-plugins-base1.0-dev \
        libgtk-3-dev \
        libpam0g-dev \
        libpulse-dev \
        libssl-dev \
        libva-dev \
        libxcb-randr0-dev \
        libxcb-shape0-dev \
        libxcb-xfixes0-dev \
        libxdo-dev \
        libxfixes-dev \
        llvm-dev \
        nasm \
        ninja-build \
        pkg-config \
        python3 \
        python3-pip \
        python3-venv \
        rpm \
        squashfs-tools \
        unzip \
        wget \
        zip \
        zstd \
        zsync \
        xz-utils \
    # Project builds opus via vcpkg; system libopus-dev conflicts.
    && apt-get remove -y libopus-dev || true \
    && rm -rf /var/lib/apt/lists/* \
    && git config --global --add safe.directory /opt/flutter \
    && git config --global --add safe.directory /root/bgdesk \
    && mkdir -p /root/rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

# vcpkg-tool-meson requires ninja >= 1.12.1; Ubuntu 22.04 ships 1.10.1 via ninja-build.
RUN wget -qO /tmp/ninja-linux.zip \
        "https://github.com/ninja-build/ninja/releases/download/v1.12.1/ninja-linux.zip" \
    && unzip -q /tmp/ninja-linux.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/ninja \
    && rm /tmp/ninja-linux.zip \
    && ninja --version

# --- Rust toolchain + codegen tools ---
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain "${RUST_VERSION}" \
    && rustup target add x86_64-unknown-linux-gnu \
    && rustup component add rustfmt \
    && cargo install cargo-expand --version "${CARGO_EXPAND_VERSION}" --locked \
    && cargo install flutter_rust_bridge_codegen --version "${FLUTTER_RUST_BRIDGE_VERSION}" --features "uuid" --locked

# --- vcpkg bootstrap ---
RUN git clone https://github.com/microsoft/vcpkg.git "${VCPKG_ROOT}" \
    && git -C "${VCPKG_ROOT}" checkout "${VCPKG_COMMIT_ID}" --force \
    && "${VCPKG_ROOT}/bootstrap-vcpkg.sh" -disableMetrics

# --- Flutter (x86_64) ---
RUN wget -q "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" \
    && tar xf "flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" -C /opt \
    && rm "flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" \
    && /opt/flutter/bin/flutter config --no-analytics \
    && /opt/flutter/bin/flutter precache --linux \
    && /opt/flutter/bin/flutter doctor -v || true

# --- appimage-builder ---
RUN pip3 install --no-cache-dir "setuptools_scm<10" \
    && pip3 install --no-cache-dir git+https://github.com/rustdesk-org/appimage-builder.git

# --- project vcpkg deps (baked into the image; only invalidated when manifests change) ---
COPY vcpkg.json /tmp/bgdesk-vcpkg/vcpkg.json
COPY res/vcpkg /tmp/bgdesk-vcpkg/res/vcpkg
RUN cd /tmp/bgdesk-vcpkg \
    && "${VCPKG_ROOT}/vcpkg" install \
        --triplet "${VCPKG_TRIPLET}" \
        --x-install-root="${VCPKG_ROOT}/installed" \
    && rm -rf /tmp/bgdesk-vcpkg \
        "${VCPKG_ROOT}/buildtrees" \
        "${VCPKG_ROOT}/downloads" \
        "${VCPKG_ROOT}/packages"

# Compile script lives in the bind-mounted sources so entrypoint changes do not
# require --rebuild-image. Only toolchain/prep layers are baked here.
RUN printf '%s\n' \
      '#!/bin/bash' \
      'set -euo pipefail' \
      'exec /root/bgdesk/docker/build-linux-x86_64.entrypoint.sh "$@"' \
      > /entrypoint.sh \
    && chmod +x /entrypoint.sh

WORKDIR /root/bgdesk
ENTRYPOINT ["/entrypoint.sh"]
