#!/bin/bash
# Remove a per-user RigPanel install. Settings in ~/.config/rigpanel are kept unless you pass --purge.
PREFIX="$HOME/.local"
systemctl --user disable --now rigpanel.service 2>/dev/null
rm -f "$HOME/.config/systemd/user/rigpanel.service"
systemctl --user daemon-reload 2>/dev/null
pkill -f "python3 $PREFIX/share/rigpanel/rigpanel.py"
rm -rf "$PREFIX/share/rigpanel"
rm -f "$PREFIX/bin/rigpanel" "$PREFIX/bin/rigpanel-setup" "$PREFIX/share/applications/rigpanel.desktop" \
      "$PREFIX/share/icons/hicolor/scalable/apps/rigpanel.svg"
update-desktop-database "$PREFIX/share/applications" 2>/dev/null
if [ "$1" = --purge ]; then rm -rf "$HOME/.config/rigpanel"; echo "  Settings deleted."; fi
echo "  RigPanel removed."
