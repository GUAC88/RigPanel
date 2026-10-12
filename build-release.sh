#!/bin/bash
# Build every download into dist/: Windows zip, Linux tar.gz, Debian .deb, Arch package.
set -e
cd "$(dirname "$0")"
V=$(cat VERSION)
rm -rf dist; mkdir dist
COMMON=(app README.md LICENSE VERSION)
# Windows: unzip, double-click windows\Install-RigPanel.bat
W=$(mktemp -d); mkdir "$W/rigpanel"; cp -r "${COMMON[@]}" windows "$W/rigpanel/"
(cd "$W" && python3 -m zipfile -c "$OLDPWD/dist/rigpanel-$V-windows.zip" rigpanel); rm -rf "$W"
# Linux, any distro: tar xzf, ./install.sh
tar --transform "s|^|rigpanel/|" --owner=0 --group=0 -czf "dist/rigpanel-$V.tar.gz" "${COMMON[@]}" linux install.sh uninstall.sh
# Debian / Ubuntu / Mint / Raspberry Pi OS
packaging/debian/build-deb.sh >/dev/null
# Arch: build from a local copy of the tag archive
A=$(mktemp -d); cp packaging/arch/PKGBUILD packaging/arch/rigpanel.install "$A/"
git archive --prefix="RigPanel-$V/" -o "$A/rigpanel-$V.tar.gz" HEAD 2>/dev/null ||
    tar --transform "s|^|RigPanel-$V/|" -czf "$A/rigpanel-$V.tar.gz" --exclude=dist --exclude=.git .
(cd "$A" && PKGDEST="$OLDPWD/dist" makepkg -f --nodeps >/dev/null 2>&1) || { echo "makepkg failed (run it in $A to see why)"; exit 1; }
rm -rf "$A"
(cd dist && sha256sum * > SHA256SUMS)
ls -l dist
