# Net Log 1.0.0

A browser-based logger for whoever is running net control on a ham radio net. It works on its own, with no radio
connected, and is also available as an add-on inside [RigPanel](https://github.com/GUAC88/RigPanel).

- **Check-ins:** type a callsign and press Enter. Each check-in is stamped in UTC, and the name, city and distance
  fill in from the FCC database (US calls, via callook.info). Duplicates are caught, and `/M` calls are flagged mobile.
- **Flags:** **Traffic**, **Short time**, **Mobile**, an **✓ acknowledged** tick and notes on every check-in.
- **Saved as you go:** every change is saved. If the browser closes mid-net, the open net comes back when you reopen it.
- **Export:** **PDF** or **Word (.docx)** with your letterhead, **CSV** for spreadsheets, **Copy summary** for posting,
  or **Print**.
- **Letterhead:** choose **Built-in** (your organization's name, tagline, contact line and accent colour, with an
  optional logo) or **My own image** (upload your existing letterhead artwork and it goes across the top).
- **Past nets:** reopen, re-export or delete earlier logs.

Runs on **Linux** and **Windows 10/11** with Python 3.8+ and nothing else to install.

![Net Log during a net: check-ins with names, flags and acknowledgements](https://raw.githubusercontent.com/GUAC88/RigPanel/main/docs/screenshots/netlog.png)

| | |
|---|---|
| ![Letterhead settings](https://raw.githubusercontent.com/GUAC88/RigPanel/main/docs/screenshots/netlog-letterhead.png) **Letterhead:** built-in, or upload your own | ![PDF export](https://raw.githubusercontent.com/GUAC88/RigPanel/main/docs/screenshots/netlog-pdf.png) **PDF export** (Word looks the same) |

*(Demo data: fictional N#CALL callsigns.)*

## Install
### Linux
```
tar xzf netlog-1.0.0.tar.gz
cd netlog
./install.sh
```
It asks for your callsign (the default net control) and grid square (for distances), then adds **Net Log** to your
app menu and starts it in the background at login. Open it at http://localhost:8074.

- Change settings: `./install.sh --reconfigure`
- Unattended: `./install.sh --yes --callsign N0CALL --grid EM26`
- Remove: `./uninstall.sh` (add `--purge` to also delete settings **and saved logs**)

### Windows
1. Unzip `netlog-1.0.0-windows.zip`.
2. Double-click **`windows\Install-NetLog.bat`**.

It installs Python with winget if needed and creates Start Menu and Desktop shortcuts. Remove it with **Start Menu → Net Log →
Uninstall Net Log**.

## Where things are kept
| | Linux | Windows |
|---|---|---|
| App | `~/.local/share/netlog/` | `%LOCALAPPDATA%\NetLog\` |
| Settings (`config.json`), letterhead | `~/.config/netlog/` | `%APPDATA%\NetLog\` |
| Net logs (one JSON file per net) | `~/.config/netlog/netlogs/` | `%APPDATA%\NetLog\netlogs\` |

`config.json` holds `callsign`, `grid` and `http_port` (default 8074). Net Log only listens on `localhost`.

## Using it with RigPanel
RigPanel's installer offers the same logger as an add-on, opened from a **📋 Net log** button. With a radio
connected, it fills in the frequency for you. The add-on keeps its logs in RigPanel's settings folder, and the
stand-alone app keeps its own.

## License
GPL-3.0, the same as RigPanel.
