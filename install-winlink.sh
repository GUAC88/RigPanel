#!/usr/bin/env bash
# Winlink Express + VARA FM on Linux, under Wine. Optional part of the RigPanel installer (install.sh asks),
# and can also be run on its own.
#
# Both are Windows programs from winlink.org (VARA FM is by EA5HVK). They are free downloads, but the site
# only serves them to a web browser, so this script opens the download page, you download them, and it
# picks them up from your Downloads folder. They go into their own Wine prefix (~/.wine-vara) with menu
# entries, and the radio's Standard serial port becomes COM5 there for VARA's PTT.
#
# Usage: ./install-winlink.sh                  ask about each program that isn't installed yet
#        ./install-winlink.sh --winlink --vara install these without asking
#        add --yes to skip questions (programs not already downloaded are then skipped)
set -euo pipefail

PREFIX="$HOME/.wine-vara"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
WINLINK_URL="https://downloads.winlink.org/User%20Programs/"
VARA_URL="https://downloads.winlink.org/VARA%20Products/"
WANT_WL="" WANT_VARA="" YES=0 VARA_FILE="" WL_FILE="" FILE=""

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }
ask()  { # ask "Question" "default" -> REPLY
  local q="$1" def="${2:-}"
  if [ "$YES" = 1 ]; then REPLY="$def"; return; fi
  read -r -p "  $q [$def]: " REPLY || true; REPLY="${REPLY:-$def}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --winlink) WANT_WL=y; shift ;;
    --vara) WANT_VARA=y; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

export WINEPREFIX="$PREFIX" WINEDEBUG=-all
# no Wine menu entries or file associations (this script makes its own), no Mono/Gecko prompts
export WINEDLLOVERRIDES="winemenubuilder.exe=d;mscoree=;mshtml="

find_exe() { [ -d "$PREFIX/drive_c" ] && find "$PREFIX/drive_c" -maxdepth 3 -iname "$1" -print -quit 2>/dev/null || true; }
WL_EXE=$(find_exe 'RMS Express.exe')
VARA_EXE=$(find_exe 'VARAFM.exe')

bold "Winlink Express + VARA FM (Windows programs, run with Wine)"
if [ "$(uname -m)" != x86_64 ]; then
  warn "These are Windows programs for Intel/AMD PCs and won't run on this $(uname -m) computer."
  warn "On a Raspberry Pi, use Pat (https://getpat.io) with ardopc or a TNC instead."
  exit 0
fi
# naming one program on the command line means just that one
if [ -n "$WANT_WL$WANT_VARA" ]; then WANT_WL="${WANT_WL:-n}" WANT_VARA="${WANT_VARA:-n}"; fi
[ -n "$WL_EXE" ] && info "Winlink Express is already installed"
[ -n "$VARA_EXE" ] && info "VARA FM is already installed"
if [ -z "$WANT_WL" ] && [ -z "$WL_EXE" ]; then
  ask "Install Winlink Express (Winlink email client)? (y/n)" y; [[ "$REPLY" =~ ^[Yy] ]] && WANT_WL=y || WANT_WL=n
fi
if [ -z "$WANT_VARA" ] && [ -z "$VARA_EXE" ]; then
  ask "Install VARA FM (the sound modem Winlink uses on 2m/70cm)? (y/n)" y; [[ "$REPLY" =~ ^[Yy] ]] && WANT_VARA=y || WANT_VARA=n
fi
[ -n "$WL_EXE" ] && WANT_WL=n
[ -n "$VARA_EXE" ] && WANT_VARA=n

# --- Wine itself ---------------------------------------------------------------------------
if [ "$WANT_WL" = y ] || [ "$WANT_VARA" = y ]; then
  if ! command -v wine >/dev/null || ! command -v winetricks >/dev/null; then
    . /etc/os-release 2>/dev/null || true
    case " ${ID:-} ${ID_LIKE:-} " in
      *" arch "*) CMD="sudo pacman -S --needed wine winetricks" ;;
      *" debian "*|*" ubuntu "*) CMD="sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install -y wine wine32:i386 winetricks" ;;
      *) CMD="" ;;
    esac
    warn "Wine and winetricks are needed to run Windows programs."
    [ -n "$CMD" ] || die "Install wine and winetricks with your package manager, then run ./install-winlink.sh"
    ask "Install them now with: $CMD ? (y/n)" y
    [[ "$REPLY" =~ ^[Yy] ]] || die "Run later:  $CMD   then  ./install-winlink.sh"
    bash -c "$CMD" || die "Installing Wine failed (on Arch, the [multilib] repository must be enabled in /etc/pacman.conf)"
  fi
  info "$(wine --version)"
fi

# --- Downloads -------------------------------------------------------------------------
DL_DIR=$(xdg-user-dir DOWNLOAD 2>/dev/null || true)   # gives $HOME itself when no Downloads folder is configured
{ [ -d "$DL_DIR" ] && [ "$DL_DIR" != "$HOME" ]; } || DL_DIR="$HOME/Downloads"

newest() { # newest file in the Downloads folder matching any of the given patterns
  local p args=()
  for p in "$@"; do args+=(-o -iname "$p"); done
  find "$DL_DIR" -maxdepth 1 -type f \( "${args[@]:1}" \) -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-
}

get_download() { # get_download "Name" URL "what to click" pattern... -> FILE (empty = skipped)
  local name="$1" url="$2" hint="$3"; shift 3
  FILE=$(newest "$@")
  if [ -n "$FILE" ]; then info "Found $(basename "$FILE")"; return; fi
  if [ "$YES" = 1 ]; then warn "$name: not in $DL_DIR, skipped (download it from $url and run ./install-winlink.sh)"; return; fi
  echo "  $name: opening the download page. Download $hint into $DL_DIR."
  echo "    $url"
  xdg-open "$url" >/dev/null 2>&1 || true
  while :; do
    read -r -p "  Press Enter when the download has finished (or type s to skip $name): " REPLY || REPLY=s
    [[ "$REPLY" =~ ^[Ss] ]] && { warn "$name skipped"; FILE=""; return; }
    FILE=$(newest "$@")
    if [ -n "$FILE" ]; then info "Found $(basename "$FILE")"; return; fi
    warn "Not found in $DL_DIR yet (still downloading, or saved somewhere else?)"
  done
}

run_setup() { # run_setup "Name" FILE : unpack a .zip if needed and run the setup program in Wine
  local name="$1" file="$2" tmp exe
  tmp=$(mktemp -d)
  case "${file,,}" in
    *.zip) python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$file" "$tmp" \
             || die "Couldn't unpack $file (is the download complete?)"
           exe=$(find "$tmp" -iname '*.exe' \( -iname '*setup*' -o -iname '*install*' \) -print -quit)
           [ -n "$exe" ] || exe=$(find "$tmp" -iname '*.exe' -print -quit) ;;
    *) exe="$file" ;;
  esac
  [ -n "$exe" ] || die "No setup program found in $file"
  echo "  Starting the $name setup. Click through it (the default folder is fine), then come back here."
  (cd "$(dirname "$exe")" && wine "$exe" >/dev/null 2>&1) || true
  rm -rf "$tmp"
}

launcher() { # launcher file "comment" "exe dir" "exe name"
  cat > "$BIN_DIR/$1" <<EOF
#!/bin/sh
# $2
export WINEPREFIX="$PREFIX" WINEDEBUG=-all
cd "$3" && exec wine "$4" "\$@"
EOF
  chmod 755 "$BIN_DIR/$1"
}

menu_entry() { # menu_entry file "Name" "Comment" launcher icon categories
  cat > "$DESKTOP_DIR/$1.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$2
Comment=$3
Exec=$BIN_DIR/$4
Icon=$5
Terminal=false
Categories=$6
EOF
}

# --- Get the downloads first, so the long unattended part comes after the questions ---------
if [ "$WANT_VARA" = y ]; then
  echo; bold "VARA FM download"
  get_download "VARA FM" "$VARA_URL" 'the newest "VARA FM v... setup.zip" (not VARA HF)' 'VARA FM*.zip' 'VARA_FM*.zip' 'VARA FM*setup*.exe'
  VARA_FILE="$FILE"; [ -n "$FILE" ] || WANT_VARA=n
fi
if [ "$WANT_WL" = y ]; then
  echo; bold "Winlink Express download"
  get_download "Winlink Express" "$WINLINK_URL" 'the newest "Winlink_Express_install_....zip"' 'Winlink_Express_install*.zip' 'Winlink*Express*.zip'
  WL_FILE="$FILE"; [ -n "$FILE" ] || WANT_WL=n
fi

# --- Wine prefix and the Windows parts the programs need ------------------------------------
if [ "$WANT_WL" = y ] || [ "$WANT_VARA" = y ]; then
  echo
  if [ ! -f "$PREFIX/system.reg" ]; then
    echo "  Creating the Wine setup in $PREFIX ..."
    wineboot -i >/dev/null 2>&1 || die "wineboot failed"
    wineserver -w
  fi
  # keep Wine's own menu entries and file associations out of the desktop for good (winetricks resets
  # WINEDLLOVERRIDES, so the environment setting alone doesn't hold); our menu entries are made below
  wine reg add 'HKCU\Software\Wine\DllOverrides' /v winemenubuilder.exe /d '' /f >/dev/null 2>&1 || true
  VERBS=""
  [ "$WANT_VARA" = y ] && VERBS="vb6run pdh_nt4"
  [ "$WANT_WL" = y ] && VERBS="$VERBS dotnet48"
  TODO=""
  for v in $VERBS; do grep -qx "$v" "$PREFIX/winetricks.log" 2>/dev/null || TODO="$TODO $v"; done
  if [ -n "$TODO" ]; then
    echo "  Adding the Windows parts they need:$TODO"
    case "$TODO" in *dotnet48*) echo "  (.NET 4.8 for Winlink Express takes 10-20 minutes; windows may pop up and close)";; esac
    # shellcheck disable=SC2086
    winetricks -q $TODO >/dev/null 2>&1 || die "winetricks$TODO failed. Run it again: WINEPREFIX=$PREFIX winetricks$TODO"
    info "Installed:$TODO"
  fi
fi

mkdir -p "$BIN_DIR" "$DESKTOP_DIR"
if [ "$WANT_VARA" = y ]; then
  echo; bold "VARA FM"
  if [ -n "$VARA_FILE" ]; then
    run_setup "VARA FM" "$VARA_FILE"
    VARA_EXE=$(find_exe 'VARAFM.exe')
    if [ -n "$VARA_EXE" ]; then
      launcher vara-fm "Launch VARA FM in its Wine prefix" "$(dirname "$VARA_EXE")" VARAFM.exe
      menu_entry vara-fm "VARA FM" "VARA FM sound modem for Winlink (Wine)" vara-fm audio-card "Network;HamRadio;"
      info "VARA FM installed (menu: VARA FM)"
    else
      warn "VARA FM setup didn't finish (VARAFM.exe not found). Run ./install-winlink.sh --vara to try again."
    fi
  fi
fi
if [ "$WANT_WL" = y ]; then
  echo; bold "Winlink Express"
  if [ -n "$WL_FILE" ]; then
    run_setup "Winlink Express" "$WL_FILE"
    WL_EXE=$(find_exe 'RMS Express.exe')
    if [ -n "$WL_EXE" ]; then
      launcher winlink-express "Launch Winlink Express in the VARA Wine prefix (it starts VARA FM itself when needed)" \
        "$(dirname "$WL_EXE")" "RMS Express.exe"
      menu_entry winlink-express "Winlink Express" "Winlink email client (Wine)" winlink-express mail-send "Network;HamRadio;Email;"
      info "Winlink Express installed (menu: Winlink Express)"
    else
      warn "Winlink Express setup didn't finish. Run ./install-winlink.sh --winlink to try again."
    fi
  fi
fi
command -v update-desktop-database >/dev/null && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

# --- Radio ports for VARA's PTT ----------------------------------------------------------
# Yaesu radios with a CP210x bridge have two ports: if00 = Enhanced (CAT, used by RigPanel), if01 = Standard (PTT)
if [ -n "$VARA_EXE" ] && command -v wine >/dev/null; then
  STD=$(ls /dev/serial/by-id/ 2>/dev/null | grep -iE 'CP210.*if01' | head -1 || true)
  ENH=$(ls /dev/serial/by-id/ 2>/dev/null | grep -iE 'CP210.*if00' | head -1 || true)
  if [ -n "$STD" ]; then
    if ! grep -qF "\"COM5\"=\"/dev/serial/by-id/$STD\"" "$PREFIX/system.reg" 2>/dev/null; then
      [ -n "$ENH" ] && wine reg add 'HKLM\Software\Wine\Ports' /v COM4 /d "/dev/serial/by-id/$ENH" /f >/dev/null 2>&1 || true
      wine reg add 'HKLM\Software\Wine\Ports' /v COM5 /d "/dev/serial/by-id/$STD" /f >/dev/null 2>&1 || true
      # Wine reads the port list when it starts
      pgrep -f '[V]ARAFM.exe|[R]MS Express.exe' >/dev/null && warn "Close and reopen VARA FM / Winlink Express to see the new COM port" || true
    fi
    info "Radio's Standard port is COM5 in Wine (for VARA's PTT)"
    PTT_PORT=COM5
  else
    PTT_PORT="the radio's Standard port"
    warn "Radio not detected on USB. With the radio connected, run ./install-winlink.sh again to set up its COM port."
  fi
fi

echo
if [ -n "$VARA_EXE" ] || [ -n "$WL_EXE" ]; then
  bold "One-time setup inside the programs"
  [ -n "$VARA_EXE" ] && {
    echo "  VARA FM  Settings > SoundCard: input AND output = the radio's USB sound card (USB Audio CODEC / PCM2903B)."
    echo "           Settings > PTT: ${PTT_PORT:-COM5}, RTS. On the FT-991A set MENU 076 FM PKT PTT SELECT = RTS."
  }
  [ -n "$WL_EXE" ] && echo "  Winlink  Enter your callsign and Winlink password, then open a \"Vara FM Winlink\" session."
  echo "  In RigPanel, tap the Winlink (VARA FM) Quick Setup; the Station card checks VARA's audio for you."
fi
