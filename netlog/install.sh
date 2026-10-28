#!/usr/bin/env bash
# Net Log installer - a net control logger for ham radio nets (check-ins, FCC lookups, PDF/Word/CSV export).
# The same logger as RigPanel's Net log add-on, as its own app; it doesn't need a radio connected.
# Installs for the current user only; no root needed.
#
# Usage: ./install.sh                 interactive setup
#        ./install.sh --reconfigure   change your callsign, grid square or web port
#        ./install.sh --callsign N0CALL --grid EM26 --yes   unattended
set -euo pipefail

VERSION="1.2.0"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/app"; [ -d "$SRC" ] || SRC="$HERE/../app"   # package layout, or inside the RigPanel source tree
APP_DIR="$HOME/.local/share/netlog"
CFG_DIR="$HOME/.config/netlog"
CFG="$CFG_DIR/config.json"
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="$HOME/.config/systemd/user"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
FILES="netlog.py netlogcore.py netexport.py index-net.html netlog.svg"

CALL="" GRID="" HTTP_PORT="8075" YES=0 RECONF=0

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }
ask()  { # ask "Question" "default" -> REPLY
  local q="$1" def="${2:-}"
  if [ "$YES" = 1 ]; then REPLY="$def"; return; fi
  if [ -n "$def" ]; then read -r -p "  $q [$def]: " REPLY || true; REPLY="${REPLY:-$def}"
  else read -r -p "  $q: " REPLY || true; fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --callsign) CALL="${2^^}"; shift 2 ;;
    --grid) GRID="$2"; shift 2 ;;
    --http-port) HTTP_PORT="$2"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --reconfigure) RECONF=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

bold "Net Log $VERSION installer  -  net control logging for ham radio nets"
echo

# --- Requirements -------------------------------------------------------------
for f in $FILES; do [ -f "$SRC/$f" ] || die "Can't find $f in $SRC"; done
command -v python3 >/dev/null || die "python3 is required (Arch: sudo pacman -S python  |  Debian: sudo apt install python3)"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
  || die "Python 3.8 or newer is required (found $(python3 --version 2>&1))"
info "Python $(python3 -c 'import platform; print(platform.python_version())')"
HAVE_SYSTEMD=0
if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  HAVE_SYSTEMD=1
else
  warn "systemd user session not available - Net Log will start when you open it from the menu"
fi

# --- Setup questions ----------------------------------------------------------
if [ -f "$CFG" ] && [ "$RECONF" = 0 ] && [ -z "$CALL" ]; then
  info "Keeping existing settings in $CFG (use --reconfigure to change them)"
else
  echo; bold "Station setup"
  while :; do
    [ -n "$CALL" ] || { ask "Your callsign (the default net control)" ""; CALL="${REPLY^^}"; }
    if [[ "$CALL" =~ ^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z]$ ]]; then break; fi
    [ "$YES" = 1 ] && die "Invalid or missing --callsign"
    warn "\"$CALL\" doesn't look like a callsign, try again"; CALL=""
  done
  if [ -z "$GRID" ]; then
    GUESS=$(python3 - "$CALL" <<'PY' 2>/dev/null || true
import json, sys, urllib.request
try:
    r = urllib.request.urlopen(urllib.request.Request(
        f"https://callook.info/{sys.argv[1]}/json", headers={"User-Agent": "NetLog-installer"}), timeout=8)
    print(json.load(r).get("location", {}).get("gridsquare", ""))
except Exception:
    pass
PY
)
    [ -n "$GUESS" ] && info "Found $CALL in the FCC database (grid $GUESS)"
    ask "Grid square, used for check-in distances (blank = none)" "$GUESS"; GRID="$REPLY"
  fi
  [ -z "$GRID" ] || [[ "$GRID" =~ ^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$ ]] || die "Invalid grid square: $GRID"
  ask "Web port for Net Log" "$HTTP_PORT"; HTTP_PORT="$REPLY"
  [[ "$HTTP_PORT" =~ ^[0-9]{4,5}$ ]] || die "Invalid port: $HTTP_PORT"
  mkdir -p "$CFG_DIR"
  python3 - "$CFG" "$CALL" "$GRID" "$HTTP_PORT" <<'PY'
import json, sys
f, call, grid, port = sys.argv[1:]
json.dump({"callsign": call, "grid": grid, "http_port": int(port)}, open(f, "w"), indent=2)
PY
  info "Saved settings to $CFG"
fi
HTTP_PORT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("http_port", 8075))' "$CFG")

# --- Install files --------------------------------------------------------------
echo; bold "Installing"
mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
for f in $FILES; do install -m 644 "$SRC/$f" "$APP_DIR"/; done
chmod 755 "$APP_DIR/netlog.py"
install -m 644 "$SRC/netlog.svg" "$ICON_DIR/netlog.svg"
echo "$VERSION" > "$APP_DIR/VERSION"
info "App files -> $APP_DIR"

cat > "$BIN_DIR/netlog" <<EOF
#!/bin/sh
# Start Net Log if needed and open it in the browser
if command -v systemctl >/dev/null && systemctl --user cat netlog.service >/dev/null 2>&1; then
  systemctl --user start netlog.service
elif ! curl -s -o /dev/null http://localhost:$HTTP_PORT 2>/dev/null; then
  nohup python3 "$APP_DIR/netlog.py" >/dev/null 2>&1 &
fi
for i in \$(seq 1 20); do curl -s -o /dev/null http://localhost:$HTTP_PORT && break; sleep 0.25; done
exec xdg-open http://localhost:$HTTP_PORT
EOF
chmod 755 "$BIN_DIR/netlog"
info "Launcher -> $BIN_DIR/netlog"

cat > "$DESKTOP_DIR/netlog.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Net Log
Comment=Log check-ins for ham radio nets and export them with your letterhead
Exec=$BIN_DIR/netlog
Icon=netlog
Terminal=false
Categories=Network;HamRadio;
Keywords=net;ncs;net control;ares;checkin;log;ham;
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
info "Menu entry: \"Net Log\" (Ham Radio category)"

if [ "$HAVE_SYSTEMD" = 1 ]; then
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/netlog.service" <<EOF
[Unit]
Description=Net Log - ham radio net control logger (http://localhost:$HTTP_PORT)

[Service]
ExecStart=/usr/bin/env python3 %h/.local/share/netlog/netlog.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable netlog.service >/dev/null 2>&1
  systemctl --user restart netlog.service
  info "Background service enabled (starts at login)"
  for i in $(seq 1 20); do curl -s -o /dev/null "http://localhost:$HTTP_PORT" 2>/dev/null && break; sleep 0.25; done
  curl -s -o /dev/null "http://localhost:$HTTP_PORT" 2>/dev/null && info "Running on http://localhost:$HTTP_PORT" \
    || warn "Net Log didn't start; run  python3 $APP_DIR/netlog.py  to see why"
fi

echo
bold "Done!  Open \"Net Log\" from your app menu, or visit http://localhost:$HTTP_PORT"
echo "  Your logs are kept in $CFG_DIR/netlogs.   Change settings:  ./install.sh --reconfigure   Remove:  ./uninstall.sh"
