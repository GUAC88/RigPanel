#!/usr/bin/env bash
# Remove Net Log for the current user.  --purge also deletes settings, letterhead AND ALL SAVED NET LOGS.
set -eu
PURGE=0; [ "${1:-}" = "--purge" ] && PURGE=1
if command -v systemctl >/dev/null; then
  systemctl --user disable --now netlog.service >/dev/null 2>&1 || true
  rm -f "$HOME/.config/systemd/user/netlog.service"
  systemctl --user daemon-reload 2>/dev/null || true
fi
pkill -f "$HOME/.local/share/netlog/netlog.py" 2>/dev/null || true
rm -rf "$HOME/.local/share/netlog"
rm -f "$HOME/.local/bin/netlog" "$HOME/.local/share/applications/netlog.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/netlog.svg"
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
if [ "$PURGE" = 1 ]; then
  rm -rf "$HOME/.config/netlog"; echo "Net Log removed, including settings and saved logs."
else
  echo "Net Log removed. Your settings and saved logs are kept in ~/.config/netlog (use --purge to delete them)."
fi
