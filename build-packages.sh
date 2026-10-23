#!/usr/bin/env bash
# Build the release downloads into ./dist:
#   rigpanel-X.Y.Z.tar.gz, rigpanel-X.Y.Z-windows.zip   RigPanel (the Net log add-on is offered by its installers)
#   netlog-A.B.C.tar.gz,   netlog-A.B.C-windows.zip     the stand-alone Net Log app
# Versions come from install.sh and netlog/install.sh. The Windows Setup.exe/.msi come from installers/build-windows.sh.
set -euo pipefail
cd "$(dirname "$0")"
RP=$(sed -n 's/^VERSION="\(.*\)"/\1/p' install.sh)
NL=$(sed -n 's/^VERSION="\(.*\)"/\1/p' netlog/install.sh)
OUT="$PWD/dist"; mkdir -p "$OUT"; rm -f "$OUT"/rigpanel-*.tar.gz "$OUT"/rigpanel-*-windows.zip "$OUT"/netlog-*.tar.gz "$OUT"/netlog-*-windows.zip
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT

python3 - "$PWD" "$STAGE" "$OUT" "$RP" "$NL" <<'PY'
import os, shutil, sys, tarfile, zipfile
src, stage, out, rp, nl = sys.argv[1:]
ADDON = ["index-net.html", "netlogcore.py", "netexport.py"]
CORE = ["rigpanel.py", "radios.py", "index.html", "menus.json", "nwr.json", "rigpanel.svg", "rigpanel.ico"]
NETLOG_APP = ["netlog.py", "netlogcore.py", "netexport.py", "index-net.html", "netlog.svg", "netlog.ico"]

def copy(rel, dest_root, dest_rel=None):
    d = os.path.join(dest_root, dest_rel or rel)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copy2(os.path.join(src, rel), d)

def tar(folder, name):
    def clean(t):
        t.uid = t.gid = 0; t.uname = t.gname = ""
        return t
    with tarfile.open(os.path.join(out, name), "w:gz") as tf:
        tf.add(os.path.join(stage, folder), arcname=folder, filter=clean)

def zipup(folder, name, files):
    with zipfile.ZipFile(os.path.join(out, name), "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(os.path.join(stage, folder, f), f"{folder}/{f}")

# RigPanel: the whole project except trial pages and build leftovers
rp_dir = os.path.join(stage, "rigpanel")
skip_dirs = {".git", "__pycache__", "dist", "cache"}   # cache = installer downloads and Wine prefix
for root, dirs, files in os.walk(src):
    dirs[:] = [d for d in dirs if d not in skip_dirs]
    for f in files:
        rel = os.path.relpath(os.path.join(root, f), src)
        if f in ("index-new.html",) or f.endswith((".pyc", ".tar.gz", ".zip")):
            continue
        copy(rel, rp_dir)
tar("rigpanel", f"rigpanel-{rp}.tar.gz")
zipup("rigpanel", f"rigpanel-{rp}-windows.zip",
      ["README.md", "LICENSE"] + [f"app/{f}" for f in CORE + ADDON] +
      [f"windows/{f}" for f in ("Install-RigPanel.bat", "Install-RigPanel.ps1", "Uninstall-RigPanel.ps1")])

# Net Log: its own folder with an app/ next to the installers
nl_dir = os.path.join(stage, "netlog")
for f in ("README.md", "install.sh", "uninstall.sh", "windows/Install-NetLog.bat", "windows/Install-NetLog.ps1", "windows/Uninstall-NetLog.ps1"):
    copy(f"netlog/{f}", nl_dir, f)
copy("LICENSE", nl_dir)
for f in NETLOG_APP:
    copy(f"app/{f}", nl_dir, f"app/{f}")
os.remove(os.path.join(nl_dir, "app", "netlog.ico"))   # Windows only
tar("netlog", f"netlog-{nl}.tar.gz")
copy("app/netlog.ico", nl_dir, "app/netlog.ico")
zipup("netlog", f"netlog-{nl}-windows.zip",
      ["README.md", "LICENSE"] + [f"app/{f}" for f in NETLOG_APP] +
      [f"windows/{f}" for f in ("Install-NetLog.bat", "Install-NetLog.ps1", "Uninstall-NetLog.ps1")])
PY
ls -l "$OUT"
