# RigPanel 1.1.0

A browser control panel for the **Yaesu FT-991A**: one-tap Quick Setups (Winlink VARA FM, VarAC 2m/70cm, NOAA weather),
frequency/mode/power/squelch/tone controls, the radio's memory channels, all 153 MENU settings, a
callsign lookup card, and your callsign on the display.

Runs on **Linux (Arch, Debian, Ubuntu, Mint, Raspberry Pi OS)** and **Windows 10/11**.

## Install

### Linux
```
tar xzf rigpanel-1.1.0.tar.gz
cd rigpanel
./install.sh
```
The installer asks for your callsign (and fills in your grid square from the FCC database for US calls),
finds the radio's USB port, and adds **"<CALL> Rig Panel"** to your app menu. It installs for your user
only. The only time it uses `sudo` is to add you to the serial-port group (`uucp` on Arch, `dialout` on
Debian/Ubuntu) if you aren't already in it. Log out and back in afterwards.

- Change settings: `./install.sh --reconfigure`
- Unattended: `./install.sh --yes --callsign N0CALL --grid EM25fs --port /dev/ttyUSB0`
- Remove: `./uninstall.sh` (add `--purge` to also delete settings)

Needs: Python 3.8+ (preinstalled on most desktops). No other packages.

### Windows
1. Unzip `rigpanel-1.1.0-windows.zip`.
2. Double-click **`windows\Install-RigPanel.bat`**.

It installs Python with winget if needed, adds pyserial, asks for your callsign and COM port, and creates
Start Menu and Desktop shortcuts. If Windows shows no COM ports for the radio, install the
[Silicon Labs CP210x driver](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers).
The FT-991A shows up as two COM ports. The panel needs the **Enhanced** one.

Remove it with **Start Menu → RigPanel → Uninstall RigPanel**.

## Radio settings
- MENU **031 CAT RATE** must match the installer's baud rate (default 38400).
- Only one program can use the CAT port reliably at a time. If VARA FM also runs, set VARA's PTT to
  the radio's *Standard* COM port with RTS, not CAT.

## Sharing the radio with other programs (Hamlib)
RigPanel also runs a Hamlib `rigctld`-compatible server on `localhost:4532`. Point other programs
at it instead of the radio's COM port, and they control the radio *through* RigPanel, so nothing fights
over the CAT port:
- **VarAC**: Settings → Rig control → frequency control **Hamlib (rigctld)**, host `localhost`, port `4532`.
- **WSJT-X / fldigi / others**: rig **Hamlib NET rigctl**, address `localhost:4532`.

Supported: frequency, mode (USB/LSB/CW/FM/AM/RTTY/PKTUSB/PKTFM/C4FM...), PTT, RF power, S-meter, and
starting the antenna tuner. Change the port with `"hamlib_port"` in `config.json`, or set it to `0` to turn it off.

## How it's built
| Piece | What it does |
|---|---|
| `app/rigpanel.py` | A small Python web server (standard library only) on `localhost`. It talks to the radio with Yaesu CAT commands over the USB serial port: termios on Linux, pyserial on Windows. |
| `app/index.html` | The whole user interface. One page of HTML, CSS and JavaScript with no frameworks. It polls the server once a second. |
| `app/menus.json` | The FT-991A MENU table (001-153), built from Yaesu's CAT Operation Reference Manual, with known misprints corrected. |
| `install.sh` / `windows\*.ps1` | Per-user installers: copy files, write settings, create the menu entry and auto-start. |

Your settings live in `~/.config/rigpanel/` on Linux or `%APPDATA%\RigPanel\` on Windows:
- `config.json`: callsign, grid, port, baud, web port, Winlink frequency
- `profiles.json`: Quick Setup buttons, editable
- `presets.json`, `lookups.json`

The panel only listens on `localhost`, so other computers on your network can't control the radio.
Callsign lookups use [callook.info](https://callook.info) (FCC data, US calls only).

## License
Copyright (C) 2026 Cody KJ5JDO. RigPanel is free software under the
[GNU General Public License v3.0 or later](LICENSE). You can use, change and share it; if you share a
modified version, it must stay under the GPL too. It comes with no warranty. You are responsible for
what your station transmits.
