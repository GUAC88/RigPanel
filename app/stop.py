"""Stop a running RigPanel or Net Log (Windows), before an upgrade or uninstall.

    python.exe stop.py rigpanel        or        python.exe stop.py netlog

Finds Python processes whose command line runs ...rigpanel.py / ...netlog.py. That covers this install and
older zip/PowerShell installs."""
import subprocess
import sys

SCRIPTS = {"rigpanel": "rigpanel.py", "netlog": "netlog.py"}


def main():
    script = SCRIPTS.get(sys.argv[1] if len(sys.argv) > 1 else "", "")
    if not script or not sys.platform.startswith("win"):
        return
    ps = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
          f"Where-Object {{ $_.CommandLine -like '*{script}*' -and $_.CommandLine -notlike '*stop.py*' }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                   creationflags=0x08000000, timeout=30)   # CREATE_NO_WINDOW


if __name__ == "__main__":
    main()
