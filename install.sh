#!/bin/bash
# RigPanel installer for Linux (Arch, Debian, Ubuntu, Mint, Raspberry Pi OS). Installs for the current user only.
#   ./install.sh                 install, asking for callsign / port / etc.
#   ./install.sh --reconfigure   re-run the setup questions
#   ./install.sh --yes --callsign N0CALL [--grid EM25fs] [--port /dev/ttyUSB0] [--autostart]
set -e
cd "$(dirname "$0")"
VERSION=$(cat VERSION)
PREFIX="$HOME/.local"
CFG="$HOME/.config/rigpanel/config.json"
RECONF=0 YES=0 AUTO="" SETUP_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --reconfigure) RECONF=1 ;;
        --autostart) AUTO=y ;;
        --no-autostart) AUTO=n ;;
        --yes|-y) YES=1; SETUP_ARGS+=("$1") ;;
        --callsign|--grid|--port|--baud|--winlink|--http-port) SETUP_ARGS+=("$1" "$2"); shift ;;
        -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done
ok() { echo "  [OK] $*"; }
warn() { echo "  [!]  $*"; }

echo
echo "RigPanel $VERSION installer - Yaesu FT-991A control panel"
command -v python3 >/dev/null || { warn "Python 3 is needed: sudo apt install python3  /  sudo pacman -S python"; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' || { warn "Python 3.8 or newer is needed"; exit 1; }
if command -v dpkg >/dev/null && dpkg -s rigpanel >/dev/null 2>&1 || command -v pacman >/dev/null && pacman -Q rigpanel >/dev/null 2>&1; then
    warn "The rigpanel system package is already installed; this per-user copy will take priority in your menu."
fi

# Stop a running copy so the new files are picked up
pkill -f "python3 $PREFIX/share/rigpanel/rigpanel.py" 2>/dev/null || true
linux/install-files.sh "" "$PREFIX"
ok "App files -> $PREFIX/share/rigpanel"

if [ -f "$CFG" ] && [ $RECONF = 0 ] && [ ${#SETUP_ARGS[@]} = 0 ]; then
    ok "Keeping existing settings in $CFG (./install.sh --reconfigure to change them)"
else
    "$PREFIX/bin/rigpanel-setup" "${SETUP_ARGS[@]}"
fi
CALL=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['callsign'])" "$CFG")
sed -i "s|^Name=.*|Name=$CALL Rig Panel|; s|^Exec=.*|Exec=$PREFIX/bin/rigpanel|" "$PREFIX/share/applications/rigpanel.desktop"
update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true
ok "App menu entry: \"$CALL Rig Panel\""

# Serial port group (the only step that uses sudo)
GRP=$([ -e /etc/arch-release ] && echo uucp || echo dialout)
for d in /dev/ttyUSB0 /dev/ttyUSB1; do [ -e "$d" ] && GRP=$(stat -c %G "$d") && break; done
if ! id -nG | tr ' ' '\n' | grep -qx "$GRP"; then
    echo "  Adding you to the '$GRP' group so the panel can use the radio's USB port (needs sudo)."
    if sudo usermod -aG "$GRP" "$USER"; then ok "Added to $GRP. Log out and back in before using the panel."
    else warn "Couldn't add you to $GRP. Run: sudo usermod -aG $GRP $USER"; fi
fi

if [ -z "$AUTO" ]; then
    if [ $YES = 1 ]; then AUTO=n; else read -rp "  Start the panel automatically when you log in? (y/n) [y]: " AUTO; AUTO=${AUTO:-y}; fi
fi
UNIT="$HOME/.config/systemd/user/rigpanel.service"
if [[ $AUTO =~ ^[Yy] ]]; then
    install -Dm644 linux/rigpanel.service "$UNIT"
    sed -i "s|^ExecStart=.*|ExecStart=$PREFIX/bin/rigpanel --server|" "$UNIT"
    systemctl --user daemon-reload && systemctl --user enable --now rigpanel.service && ok "Will start at login"
else
    "$PREFIX/bin/rigpanel" >/dev/null 2>&1 &
fi

PORT=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('http_port',8073))" "$CFG")
sleep 2
if python3 -c "import json,urllib.request,sys;sys.exit(0 if json.load(urllib.request.urlopen('http://localhost:$PORT/api/status',timeout=5)).get('ok') else 3)" 2>/dev/null; then
    ok "Connected to the radio"
elif [ $? = 3 ]; then
    warn "Panel is running but the radio isn't answering (check USB cable, power, port, MENU 031 baud rate)"
fi
case ":$PATH:" in *":$PREFIX/bin:"*) ;; *) warn "$PREFIX/bin isn't on your PATH; use the app menu entry or $PREFIX/bin/rigpanel" ;; esac
echo
echo "Done! Open \"$CALL Rig Panel\" from your app menu, run 'rigpanel', or visit http://localhost:$PORT"
