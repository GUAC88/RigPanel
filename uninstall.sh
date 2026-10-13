#!/usr/bin/env bash
# Remove RigPanel for the current user.  --purge also deletes settings, presets and lookup history.
set -eu
PURGE=0; [ "${1:-}" = "--purge" ] && PURGE=1
if command -v systemctl >/dev/null; then
  systemctl --user disable --now rigpanel.service >/dev/null 2>&1 || true
  rm -f "$HOME/.config/systemd/user/rigpanel.service"
  systemctl --user daemon-reload 2>/dev/null || true
fi
pkill -f "$HOME/.local/share/rigpanel/rigpanel.py" 2>/dev/null || true
rm -rf "$HOME/.local/share/rigpanel"
rm -f "$HOME/.local/bin/rigpanel" "$HOME/.local/share/applications/rigpanel.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/rigpanel.svg"
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
if [ "$PURGE" = 1 ]; then
  rm -rf "$HOME/.config/rigpanel"; echo "RigPanel removed, including settings."
else
  echo "RigPanel removed. Settings kept in ~/.config/rigpanel (use --purge to delete them)."
fi
