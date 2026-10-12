#!/bin/sh
# Build dist/rigpanel_<version>_all.deb without needing dpkg-deb (works on Arch too).
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
V=$(cat "$ROOT/VERSION")
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
"$ROOT/linux/install-files.sh" "$W/data" /usr
SIZE=$(du -sk "$W/data" | cut -f1)
mkdir "$W/control"
sed "s/@VERSION@/$V/; s/@SIZE@/$SIZE/" "$ROOT/packaging/debian/control" > "$W/control/control"
install -m755 "$ROOT/packaging/debian/postinst" "$ROOT/packaging/debian/postrm" "$W/control/"
(cd "$W/data" && find . -type f ! -path ./DEBIAN -printf '%P\n' | sort | xargs md5sum) > "$W/control/md5sums"
TAROPTS="--owner=0 --group=0 --numeric-owner --sort=name --mtime=@${SOURCE_DATE_EPOCH:-$(date +%s)}"
(cd "$W/control" && tar $TAROPTS -cJf "$W/control.tar.xz" ./)
(cd "$W/data" && tar $TAROPTS -cJf "$W/data.tar.xz" ./)
echo 2.0 > "$W/debian-binary"
mkdir -p "$ROOT/dist"; OUT="$ROOT/dist/rigpanel_${V}_all.deb"; rm -f "$OUT"
(cd "$W" && ar rcD "$OUT" debian-binary control.tar.xz data.tar.xz)
echo "$OUT"
