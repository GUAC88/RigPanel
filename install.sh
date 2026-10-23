#!/usr/bin/env bash
# RigPanel installer - browser control panel for CAT-controlled ham radios (Yaesu, Icom, and more via Hamlib).
# Works on Arch/Manjaro/CachyOS and Debian/Ubuntu/Mint/Raspberry Pi OS.
# Installs for the current user only (no root needed except to join the serial-port group).
#
# Usage: ./install.sh                 interactive setup
#        ./install.sh --reconfigure   re-run the setup questions on an existing install
#        ./install.sh --callsign N0CALL --grid EM25fs --port /dev/ttyUSB0 --yes   unattended
set -euo pipefail

VERSION="1.3.0"
SRC="$(cd "$(dirname "$0")" && pwd)/app"
APP_DIR="$HOME/.local/share/rigpanel"
CFG_DIR="$HOME/.config/rigpanel"
CFG="$CFG_DIR/config.json"
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="$HOME/.config/systemd/user"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

CALL="" GRID="" PORT="" BAUD="38400" HTTP_PORT="8073" WL_FREQ="145.030" YES=0 RECONF=0

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
    --port) PORT="$2"; shift 2 ;;
    --baud) BAUD="$2"; shift 2 ;;
    --http-port) HTTP_PORT="$2"; shift 2 ;;
    --winlink-freq) WL_FREQ="$2"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --reconfigure) RECONF=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

bold "RigPanel $VERSION installer  -  ham radio control panel"
echo

# --- Requirements -------------------------------------------------------------
[ -d "$SRC" ] || die "Can't find the app/ folder next to install.sh"
command -v python3 >/dev/null || die "python3 is required (Arch: sudo pacman -S python  |  Debian: sudo apt install python3)"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
  || die "Python 3.8 or newer is required (found $(python3 --version 2>&1))"
info "Python $(python3 -c 'import platform; print(platform.python_version())')"

. /etc/os-release 2>/dev/null || true
case " ${ID:-} ${ID_LIKE:-} " in
  *" arch "*)   DISTRO=arch;   SERIAL_GROUP=uucp ;;
  *" debian "*|*" ubuntu "*) DISTRO=debian; SERIAL_GROUP=dialout ;;
  *) DISTRO=other; SERIAL_GROUP=$(stat -c %G /dev/ttyUSB0 2>/dev/null || echo dialout) ;;
esac
info "Detected ${PRETTY_NAME:-$DISTRO} (serial group: $SERIAL_GROUP)"

HAVE_SYSTEMD=0
if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  HAVE_SYSTEMD=1
else
  warn "systemd user session not available - RigPanel will start when you open it from the menu"
fi

# --- Setup questions ----------------------------------------------------------
if [ -f "$CFG" ] && [ "$RECONF" = 0 ] && [ -z "$CALL" ]; then
  info "Keeping existing settings in $CFG (use --reconfigure to change them)"
else
  echo; bold "Station setup"
  while :; do
    [ -n "$CALL" ] || { ask "Your callsign" ""; CALL="${REPLY^^}"; }
    if [[ "$CALL" =~ ^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z]$ ]]; then break; fi
    [ "$YES" = 1 ] && die "Invalid or missing --callsign"
    warn "\"$CALL\" doesn't look like a callsign, try again"; CALL=""
  done

  if [ -z "$GRID" ]; then
    # Offer the grid square from the FCC database for US calls
    GUESS=$(python3 - "$CALL" <<'PY' 2>/dev/null || true
import json, sys, urllib.request
try:
    r = urllib.request.urlopen(urllib.request.Request(
        f"https://callook.info/{sys.argv[1]}/json", headers={"User-Agent": "RigPanel-installer"}), timeout=8)
    print(json.load(r).get("location", {}).get("gridsquare", ""))
except Exception:
    pass
PY
)
    [ -n "$GUESS" ] && info "Found $CALL in the FCC database (grid $GUESS)"
    ask "Grid square (Maidenhead, e.g. EM25fs)" "$GUESS"; GRID="$REPLY"
  fi
  [ -z "$GRID" ] || [[ "$GRID" =~ ^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$ ]] || die "Invalid grid square: $GRID"

  if [ -z "$PORT" ]; then
    # Yaesu radios with a CP210x bridge show two ports (if00 = CAT); Icom radios name themselves
    mapfile -t PORTS < <(ls /dev/serial/by-id/ 2>/dev/null | grep -iE 'CP210.*if00|Icom|IC-[0-9]' | sed 's|^|/dev/serial/by-id/|' || true)
    if [ "${#PORTS[@]}" -gt 0 ]; then
      info "Found a radio's CAT port: ${PORTS[0]##*/}"
      ask "Radio CAT serial port (blank = find it automatically)" "${PORTS[0]}"
    else
      warn "No radio detected on USB. Plug it in and turn it on, or enter the port by hand."
      ask "Radio CAT serial port (leave blank to auto-detect at startup)" ""
    fi
    PORT="$REPLY"
  fi
  case "$PORT" in *Icom*|*IC-[0-9]*) [ "$BAUD" = 38400 ] && BAUD=115200 ;; esac
  ask "Radio CAT baud rate (Yaesu FT-991A: MENU 031, Icom: CI-V USB Baud Rate)" "$BAUD"; BAUD="$REPLY"
  [[ "$BAUD" =~ ^(4800|9600|19200|38400|57600|115200)$ ]] || die "Baud must be 4800, 9600, 19200, 38400, 57600 or 115200"
  ask "Your local Winlink VARA FM frequency in MHz" "$WL_FREQ"; WL_FREQ="$REPLY"
  WL_HZ=$(python3 -c "import sys; print(round(float(sys.argv[1]) * 1e6))" "$WL_FREQ") || die "Bad frequency: $WL_FREQ"
  ask "Web port for the panel" "$HTTP_PORT"; HTTP_PORT="$REPLY"
  [[ "$HTTP_PORT" =~ ^[0-9]{4,5}$ ]] || die "Invalid port: $HTTP_PORT"

  mkdir -p "$CFG_DIR"
  python3 - "$CFG" "$CALL" "$GRID" "$PORT" "$BAUD" "$HTTP_PORT" "$WL_HZ" <<'PY'
import json, sys
f, call, grid, port, baud, http_port, wl = sys.argv[1:]
json.dump({"callsign": call, "grid": grid, "serial_port": port, "baud": int(baud),
           "http_port": int(http_port), "winlink_freq": int(wl)}, open(f, "w"), indent=2)
PY
  info "Saved settings to $CFG"
fi
HTTP_PORT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("http_port", 8073))' "$CFG")

# --- Install files --------------------------------------------------------------
echo; bold "Installing"
mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
install -m 644 "$SRC"/index.html "$SRC"/menus.json "$SRC"/rigpanel.svg "$SRC"/radios.py "$APP_DIR"/
install -m 755 "$SRC"/rigpanel.py "$APP_DIR"/
install -m 644 "$SRC"/rigpanel.svg "$ICON_DIR"/rigpanel.svg
echo "$VERSION" > "$APP_DIR/VERSION"
info "App files -> $APP_DIR"

cat > "$BIN_DIR/rigpanel" <<EOF
#!/bin/sh
# Start RigPanel if needed and open it in the browser
if command -v systemctl >/dev/null && systemctl --user cat rigpanel.service >/dev/null 2>&1; then
  systemctl --user start rigpanel.service
elif ! curl -s -o /dev/null http://localhost:$HTTP_PORT 2>/dev/null; then
  nohup python3 "$APP_DIR/rigpanel.py" >/dev/null 2>&1 &
fi
for i in \$(seq 1 20); do curl -s -o /dev/null http://localhost:$HTTP_PORT && break; sleep 0.25; done
exec xdg-open http://localhost:$HTTP_PORT
EOF
chmod 755 "$BIN_DIR/rigpanel"
info "Launcher -> $BIN_DIR/rigpanel"

CALLNAME=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["callsign"])' "$CFG")
cat > "$DESKTOP_DIR/rigpanel.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$CALLNAME Rig Panel
Comment=Control your ham radio: frequencies, modes, presets, PC mic and more
Exec=$BIN_DIR/rigpanel
Icon=rigpanel
Terminal=false
Categories=Network;HamRadio;
Keywords=radio;yaesu;icom;ft991a;ic7300;hamlib;cat;winlink;
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
info "Menu entry: \"$CALLNAME Rig Panel\" (Ham Radio category)"

if [ "$HAVE_SYSTEMD" = 1 ]; then
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/rigpanel.service" <<EOF
[Unit]
Description=RigPanel radio control panel (http://localhost:$HTTP_PORT)

[Service]
ExecStart=/usr/bin/env python3 %h/.local/share/rigpanel/rigpanel.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable rigpanel.service >/dev/null 2>&1
  systemctl --user restart rigpanel.service
  info "Background service enabled (starts at login)"
fi

# --- Serial port permission -------------------------------------------------------
if ! id -nG "$USER" | tr ' ' '\n' | grep -qx "$SERIAL_GROUP"; then
  echo; warn "Your account isn't in the '$SERIAL_GROUP' group, which is needed to talk to the radio."
  ask "Add it now with sudo? (y/n)" "y"
  if [[ "$REPLY" =~ ^[Yy] ]]; then
    sudo usermod -aG "$SERIAL_GROUP" "$USER" && warn "Done - log out and back in for this to take effect."
  else
    warn "Run later:  sudo usermod -aG $SERIAL_GROUP $USER   (then log out and back in)"
  fi
fi

# --- Check ------------------------------------------------------------------------
echo
if [ "$HAVE_SYSTEMD" = 1 ]; then
  for i in $(seq 1 20); do curl -s -o /dev/null "http://localhost:$HTTP_PORT" 2>/dev/null && break; sleep 0.25; done
  if STATUS=$(curl -s --max-time 5 "http://localhost:$HTTP_PORT/api/status" 2>/dev/null) && [[ "$STATUS" == *'"ok": true'* ]]; then
    info "Connected to the radio"
  else
    warn "Panel is running but the radio isn't answering yet (check USB cable, power and baud rate $BAUD; or open Radio setup in the panel)"
  fi
fi
bold "Done!  Open \"$CALLNAME Rig Panel\" from your app menu, or visit http://localhost:$HTTP_PORT"
echo "  Change settings later:  ./install.sh --reconfigure      Remove:  ./uninstall.sh"
