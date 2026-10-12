# RigPanel

A browser control panel for the **Yaesu FT-991A**: one-tap Quick Setups (Winlink VARA FM, NOAA weather),
frequency/mode/power/squelch/tone controls, the radio's memory channels, all 153 MENU settings, a
callsign lookup card, and your callsign on the display.

Runs on **Windows 10/11** and **Linux (Debian, Ubuntu, Mint, Raspberry Pi OS, Arch)**. Needs Python 3.8+.

## Download

Get the file for your system from the [latest release](https://github.com/GUAC88/RigPanel/releases/latest).

| System | File | Install |
|---|---|---|
| Windows 10/11 | `rigpanel-<version>-windows.zip` | Unzip, double-click `windows\Install-RigPanel.bat` |
| Debian, Ubuntu, Mint, Raspberry Pi OS | `rigpanel_<version>_all.deb` | `sudo apt install ./rigpanel_<version>_all.deb` |
| Arch, CachyOS, Manjaro | `rigpanel-<version>-1-any.pkg.tar.zst` | `sudo pacman -U rigpanel-<version>-1-any.pkg.tar.zst` |
| Any Linux, no root | `rigpanel-<version>.tar.gz` | `tar xzf rigpanel-<version>.tar.gz && cd rigpanel && ./install.sh` |

### Windows
The installer installs Python with winget if needed, adds pyserial, asks for your callsign and COM port, and
creates Start Menu and Desktop shortcuts. If Windows shows no COM ports for the radio, install the
[Silicon Labs CP210x driver](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers).
The FT-991A shows up as two COM ports. The panel needs the **Enhanced** one.
Remove it with **Start Menu → RigPanel → Uninstall RigPanel**.

### Linux packages (.deb / Arch)
After installing:
1. Join the serial-port group, then log out and back in:
   `sudo usermod -aG dialout $USER` on Debian/Ubuntu/Mint/Pi, `sudo usermod -aG uucp $USER` on Arch.
2. Open **Rig Panel** from your app menu, or run `rigpanel`. The first start asks for your callsign
   (and fills in your grid square from the FCC database for US calls).
3. Optional, start at login: `systemctl --user enable --now rigpanel`

Change settings with `rigpanel --setup`. Stop the panel with `rigpanel --stop`.

### Linux, per-user (tar.gz)
`./install.sh` asks for your callsign, finds the radio's USB port, and adds **"&lt;CALL&gt; Rig Panel"** to your app
menu. It installs into `~/.local` and only uses `sudo` to add you to the serial-port group.

- Change settings: `./install.sh --reconfigure`
- Unattended: `./install.sh --yes --callsign N0CALL --grid EM25fs --port /dev/ttyUSB0`
- Remove: `./uninstall.sh` (add `--purge` to also delete settings)

## Radio settings
- MENU **031 CAT RATE** must match the baud rate you chose (default 38400).
- Only one program can use the CAT port reliably at a time. If VARA FM also runs, set VARA's PTT to
  the radio's *Standard* port with RTS, not CAT.

## How it's built
| Piece | What it does |
|---|---|
| `app/rigpanel.py` | A small Python web server (standard library only) on `localhost`. It talks to the radio with Yaesu CAT commands over the USB serial port: termios on Linux, pyserial on Windows. |
| `app/index.html` | The whole user interface. One page of HTML, CSS and JavaScript with no frameworks. It polls the server once a second. |
| `app/menus.json` | The FT-991A MENU table (001-153), built from Yaesu's CAT Operation Reference Manual, with known misprints corrected. |
| `linux/` | The `rigpanel` launcher, `rigpanel-setup`, the app-menu entry and a systemd user service. |
| `install.sh`, `windows\*.ps1` | Per-user installers. |
| `packaging/` | `.deb` builder and Arch `PKGBUILD`. `./build-release.sh` builds every download into `dist/`. |

Your settings live in `~/.config/rigpanel/` on Linux or `%APPDATA%\RigPanel\` on Windows:
- `config.json`: callsign, grid, port, baud, web port, Winlink frequency
- `profiles.json`: Quick Setup buttons, editable
- `presets.json`, `lookups.json`

The panel only listens on `localhost`, so other computers on your network can't control the radio.
Callsign lookups use [callook.info](https://callook.info) (FCC data, US calls only).

## License
GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
