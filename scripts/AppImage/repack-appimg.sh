ROOT="$( cd "$( dirname "$i" )" && pwd )"
PLATFORM="$(uname -p)"
cd $ROOT

FILENAME=$(basename $1)

# Backup the original file
if [ ! -f $FILENAME ]; then
    echo "File $FILENAME not found!"
    exit 1
fi
cp $FILENAME $FILENAME.bak

rm -rf squashfs-root

chmod +x $1
./$FILENAME --appimage-extract


cd squashfs-root

sed -i -e 's/\/rustdesk/\/bgdesk/g' AppRun.env

# Support repacking legacy RustDesk AppImages and current BGDesk AppImages.
[ -f rustdesk.desktop ] && mv rustdesk.desktop bgdesk.desktop
[ -f rustdesk.svg ] && mv rustdesk.svg bgdesk.svg
[ -d usr/share/rustdesk ] && mv usr/share/rustdesk usr/share/bgdesk
[ -f usr/share/bgdesk/rustdesk ] && mv usr/share/bgdesk/rustdesk usr/share/bgdesk/bgdesk
[ -f usr/share/bgdesk/files/systemd/rustdesk.service ] && \
  mv usr/share/bgdesk/files/systemd/rustdesk.service usr/share/bgdesk/files/systemd/bgdesk.service
[ -f usr/share/icons/hicolor/256x256/apps/rustdesk.png ] && \
  mv usr/share/icons/hicolor/256x256/apps/rustdesk.png usr/share/icons/hicolor/256x256/apps/bgdesk.png
[ -f usr/share/icons/hicolor/scalable/apps/rustdesk.svg ] && \
  mv usr/share/icons/hicolor/scalable/apps/rustdesk.svg usr/share/icons/hicolor/scalable/apps/bgdesk.svg

sed -i -e 's/rustdesk/bgdesk/g' bgdesk.desktop


echo $ROOT
cd $ROOT

./appimagetool-$PLATFORM.AppImage -v squashfs-root
