"""Start RigPanel or Net Log in the background if it isn't running, then open it in the browser.

Used by the Windows .exe/.msi shortcuts (run with pythonw.exe, so no console window appears):
    pythonw.exe launch.py rigpanel        or        pythonw.exe launch.py netlog
Add --no-browser to only start the server (the "start at login" entry does that)."""
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = {"rigpanel": ("rigpanel.py", "RigPanel", "rigpanel", 8073), "netlog": ("netlog.py", "NetLog", "netlog", 8075)}


def config_port(win_dir, nix_dir, default):
    base = os.path.join(os.environ.get("APPDATA") or "", win_dir) if os.name == "nt" else os.path.expanduser("~/.config/" + nix_dir)
    try:
        with open(os.path.join(base, "config.json")) as f:
            return int(json.load(f).get("http_port") or default)
    except (OSError, ValueError, TypeError):
        return default


def up(url):
    try:
        urllib.request.urlopen(url + "/api/config", timeout=1).read()
        return True
    except OSError:
        return False


def main():
    name = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in APPS else "rigpanel"
    script, win_dir, nix_dir, default = APPS[name]
    url = f"http://localhost:{config_port(win_dir, nix_dir, default)}"
    if not up(url):
        py = sys.executable
        if os.name == "nt" and os.path.basename(py).lower() == "python.exe" and os.path.exists(py[:-10] + "pythonw.exe"):
            py = py[:-10] + "pythonw.exe"   # no console window for the server
        flags = 0x00000008 | 0x00000200 | 0x08000000 if os.name == "nt" else 0   # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
        subprocess.Popen([py, os.path.join(HERE, script)], cwd=HERE, close_fds=True, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            time.sleep(0.25)
            if up(url):
                break
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)


if __name__ == "__main__":
    main()
