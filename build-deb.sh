#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

rm -rf bgdesk.deb
rm -rf tmpdebe

bash ./scripts/rename-linux-artifacts.sh

mkdir -p tmpdeb/usr/bin/
mkdir -p tmpdeb/usr/share/bgdesk
mkdir -p tmpdeb/usr/share/bgdesk/files/systemd/
mkdir -p tmpdeb/usr/share/icons/hicolor/256x256/apps/
mkdir -p tmpdeb/usr/share/icons/hicolor/scalable/apps/
mkdir -p tmpdeb/usr/share/applications/
mkdir -p tmpdeb/usr/share/polkit-1/actions
rm -rf tmpdeb/usr/bin/bgdesk 
cp -rf target/release/bgdesk tmpdeb/usr/bin/bgdesk
cp -rf res/bgdesk.service tmpdeb/usr/share/bgdesk/files/systemd/
cp -rf res/128x128@2x.png tmpdeb/usr/share/icons/hicolor/256x256/apps/bgdesk.png
cp -rf res/scalable.svg tmpdeb/usr/share/icons/hicolor/scalable/apps/bgdesk.svg
cp -rf res/bgdesk.desktop tmpdeb/usr/share/applications/bgdesk.desktop
cp -rf res/bgdesk-link.desktop tmpdeb/usr/share/applications/bgdesk-link.desktop
echo \"#!/bin/sh\" >> tmpdeb/usr/share/bgdesk/files/polkit && chmod a+x tmpdeb/usr/share/bgdesk/files/polkit


mkdir -p tmpdeb/DEBIAN
mkdir -p tmpdeb/etc/bgdesk/

cp -a res/startwm.sh tmpdeb/etc/bgdesk/
mkdir -p tmpdeb/etc/X11/bgdesk/
cp res/xorg.conf tmpdeb/etc/X11/bgdesk/
cp -a res/DEBIAN/* tmpdeb/DEBIAN/
mkdir -p tmpdeb/etc/pam.d/
cp res/pam.d/bgdesk.debian tmpdeb/etc/pam.d/bgdesk

strip tmpdeb/usr/bin/bgdesk

mkdir -p tmpdeb/usr/share/bgdesk
mv tmpdeb/usr/bin/bgdesk tmpdeb/usr/share/bgdesk/
cp target/release/libsciter-gtk.so tmpdeb/usr/share/bgdesk/


cat > tmpdeb/DEBIAN/control <<EOL
Package: bgdesk
Section: net
Priority: optional
Version: 1.0.0
Architecture: amd64
Maintainer: bgdesk <contato@boagestao.com.br>
Homepage: https://boagestao.com.br
Depends: libgtk-3-0, libxcb-randr0, libxdo3, libxfixes3, libxcb-shape0, libxcb-xfixes0, libasound2, libsystemd0, curl, libva2, libva-drm2, libva-x11-2, libgstreamer-plugins-base1.0-0, libpam0g, gstreamer1.0-pipewire
Recommends: libayatana-appindicator3-1
Description: A remote control software.
EOL

./md5.py


dpkg-deb -b tmpdeb bgdesk.deb


# rm -rf tmpdeb