Name:       bgdesk
Version:    1.4.8
Release:    0
Summary:    RPM package
License:    GPL-3.0
URL:        https://boagestao.com.br
Vendor:     bgdesk <contato@boagestao.com.br>
Requires:   gtk3 libxcb libXfixes alsa-lib libva pam gstreamer1-plugins-base
Recommends: libayatana-appindicator-gtk3 libxdo
Provides:   libdesktop_drop_plugin.so()(64bit), libdesktop_multi_window_plugin.so()(64bit), libfile_selector_linux_plugin.so()(64bit), libflutter_custom_cursor_plugin.so()(64bit), libflutter_linux_gtk.so()(64bit), libscreen_retriever_plugin.so()(64bit), libtray_manager_plugin.so()(64bit), liburl_launcher_linux_plugin.so()(64bit), libwindow_manager_plugin.so()(64bit), libwindow_size_plugin.so()(64bit), libtexture_rgba_renderer_plugin.so()(64bit)

# https://docs.fedoraproject.org/en-US/packaging-guidelines/Scriptlets/

%description
BGDesk remote desktop client software.

%prep
# we have no source, so nothing here

%build
# we have no source, so nothing here

# %global __python %{__python3}

%install

mkdir -p "%{buildroot}/usr/share/bgdesk" && cp -r ${HBB}/flutter/build/linux/x64/release/bundle/* -t "%{buildroot}/usr/share/bgdesk"
mkdir -p "%{buildroot}/usr/bin"
install -Dm 644 $HBB/res/bgdesk.service -t "%{buildroot}/usr/share/bgdesk/files"
install -Dm 644 $HBB/res/bgdesk.desktop -t "%{buildroot}/usr/share/bgdesk/files"
install -Dm 644 $HBB/res/bgdesk-link.desktop -t "%{buildroot}/usr/share/bgdesk/files"
install -Dm 644 $HBB/res/128x128@2x.png "%{buildroot}/usr/share/icons/hicolor/256x256/apps/bgdesk.png"
install -Dm 644 $HBB/res/scalable.svg "%{buildroot}/usr/share/icons/hicolor/scalable/apps/bgdesk.svg"

%files
/usr/share/bgdesk/*
/usr/share/bgdesk/files/bgdesk.service
/usr/share/icons/hicolor/256x256/apps/bgdesk.png
/usr/share/icons/hicolor/scalable/apps/bgdesk.svg
/usr/share/bgdesk/files/bgdesk.desktop
/usr/share/bgdesk/files/bgdesk-link.desktop

%changelog
# let's skip this for now

%pre
# can do something for centos7
case "$1" in
  1)
    # for install
  ;;
  2)
    # for upgrade
    systemctl stop bgdesk || true
  ;;
esac

%post
cp /usr/share/bgdesk/files/bgdesk.service /etc/systemd/system/bgdesk.service
cp /usr/share/bgdesk/files/bgdesk.desktop /usr/share/applications/
cp /usr/share/bgdesk/files/bgdesk-link.desktop /usr/share/applications/
ln -sf /usr/share/bgdesk/bgdesk /usr/bin/bgdesk
systemctl daemon-reload
systemctl enable bgdesk
systemctl start bgdesk
update-desktop-database

%preun
case "$1" in
  0)
    # for uninstall
    systemctl stop bgdesk || true
    systemctl disable bgdesk || true
    rm /etc/systemd/system/bgdesk.service || true
  ;;
  1)
    # for upgrade
  ;;
esac

%postun
case "$1" in
  0)
    # for uninstall
    rm /usr/bin/bgdesk || true
    rmdir /usr/lib/bgdesk || true
    rmdir /usr/local/bgdesk || true
    rmdir /usr/share/bgdesk || true
    rm /usr/share/applications/bgdesk.desktop || true
    rm /usr/share/applications/bgdesk-link.desktop || true
    update-desktop-database
  ;;
  1)
    # for upgrade
    rmdir /usr/lib/bgdesk || true
    rmdir /usr/local/bgdesk || true
  ;;
esac
