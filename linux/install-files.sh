#!/bin/sh
# Lay out RigPanel's files under DESTDIR/PREFIX. Used by install.sh (per-user, PREFIX=~/.local)
# and by the .deb and Arch packages (PREFIX=/usr).
#   linux/install-files.sh DESTDIR PREFIX
set -e
DEST=$1 PREFIX=$2
SRC=$(cd "$(dirname "$0")/.." && pwd)
install -d "$DEST$PREFIX/share/rigpanel" "$DEST$PREFIX/bin"
install -m644 "$SRC"/app/rigpanel.py "$SRC"/app/index.html "$SRC"/app/menus.json "$SRC"/app/rigpanel.svg "$SRC"/VERSION \
    "$DEST$PREFIX/share/rigpanel/"
install -m755 "$SRC/linux/rigpanel" "$SRC/linux/rigpanel-setup" "$DEST$PREFIX/bin/"
install -Dm644 "$SRC/linux/rigpanel.desktop" "$DEST$PREFIX/share/applications/rigpanel.desktop"
install -Dm644 "$SRC/app/rigpanel.svg" "$DEST$PREFIX/share/icons/hicolor/scalable/apps/rigpanel.svg"
if [ "$PREFIX" = /usr ]; then
    install -Dm644 "$SRC/linux/rigpanel.service" "$DEST/usr/lib/systemd/user/rigpanel.service"
    install -Dm644 "$SRC/README.md" "$DEST/usr/share/doc/rigpanel/README.md"
fi
