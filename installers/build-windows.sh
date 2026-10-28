#!/usr/bin/env bash
# Build the Windows installers into ../dist, each with its own embedded Python (no Python install needed):
#   RigPanel-X.Y.Z-Setup.exe  RigPanel-X.Y.Z.msi  NetLog-A.B.C-Setup.exe  NetLog-A.B.C.msi
# Runs on Linux. Needs: wine (runs Inno Setup's compiler) and msitools (wixl, for the .msi).
# Downloads (checksum-verified) are kept in installers/cache/.
set -euo pipefail
cd "$(dirname "$0")"
HERE=$PWD; ROOT=$(cd .. && pwd); CACHE=$HERE/cache; OUT=$ROOT/dist
RP=$(sed -n 's/^VERSION="\(.*\)"/\1/p' "$ROOT/install.sh")
NL=$(sed -n 's/^VERSION="\(.*\)"/\1/p' "$ROOT/netlog/install.sh")
PYV=3.14.8
PY_ZIP=python-$PYV-embed-amd64.zip;  PY_SHA=a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310
SER_WHL=pyserial-3.5-py2.py3-none-any.whl; SER_SHA=c4451db6ba391ca6ca299fb3ec7bae67a5c55dde170964c7a14ceefec02f2cf0
INNO=innosetup-6.7.3.exe; INNO_SHA=9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732
for t in wine wixl; do command -v $t >/dev/null || { echo "Missing $t (Arch: sudo pacman -S wine msitools)"; exit 1; }; done
mkdir -p "$CACHE" "$OUT"

fetch() {  # fetch FILE SHA256 URL
  [ -f "$CACHE/$1" ] || curl -sSL -o "$CACHE/$1" "$3"
  echo "$2  $CACHE/$1" | sha256sum -c --quiet || { echo "Checksum mismatch: $1"; rm -f "$CACHE/$1"; exit 1; }
}
fetch "$PY_ZIP" $PY_SHA "https://www.python.org/ftp/python/$PYV/$PY_ZIP"
fetch "$SER_WHL" $SER_SHA "https://files.pythonhosted.org/packages/07/bc/587a445451b253b285629263eb51c2d8e9bcea4fc97826266d186f96f558/pyserial-3.5-py2.py3-none-any.whl"
fetch "$INNO" $INNO_SHA "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/$INNO"
export WINEPREFIX=$CACHE/wineprefix WINEDEBUG=-all
export WINEDLLOVERRIDES="winemenubuilder.exe=d"   # never add Wine menu entries, file associations or Desktop shortcuts to this computer
ISCC="$WINEPREFIX/drive_c/InnoSetup6/ISCC.exe"
if [ ! -f "$ISCC" ]; then   # install Inno Setup once, silently, into this build's own Wine prefix
  wine "$CACHE/$INNO" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /NOICONS '/DIR=C:\InnoSetup6' >/dev/null 2>&1 || true
  [ -f "$ISCC" ] || { echo "Inno Setup didn't install under Wine"; exit 1; }
fi

STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
python3 - "$ROOT" "$STAGE" "$CACHE/$PY_ZIP" "$CACHE/$SER_WHL" <<'PY'
import os, shutil, sys, zipfile
root, stage, pyzip, whl = sys.argv[1:]
APPS = {
    "rigpanel": ["rigpanel.py", "radios.py", "index.html", "menus.json", "nwr.json", "rigpanel.svg", "rigpanel.ico",
                 "icsforms.py", "index-ics.html", "index-net.html", "netlogcore.py", "netexport.py", "launch.py", "stop.py"],
    "netlog": ["netlog.py", "netlogcore.py", "netexport.py", "index-net.html", "netlog.svg", "netlog.ico", "launch.py", "stop.py"],
}
for name, files in APPS.items():
    py = os.path.join(stage, name, "python")
    zipfile.ZipFile(pyzip).extractall(py)
    pth = [f for f in os.listdir(py) if f.endswith("._pth")][0]
    stdlib = [f for f in os.listdir(py) if f.startswith("python3") and f.endswith(".zip")][0]
    with open(os.path.join(py, pth), "w", newline="\r\n") as f:   # where the embedded Python looks for modules
        f.write(f"{stdlib}\n.\n..\\app\nLib\\site-packages\n")
    os.makedirs(os.path.join(py, "Lib", "site-packages"))
    if name == "rigpanel":   # pyserial: RigPanel's serial port access on Windows
        with zipfile.ZipFile(whl) as z:
            for m in z.namelist():
                if m.startswith("serial/"):
                    z.extract(m, os.path.join(py, "Lib", "site-packages"))
    app = os.path.join(stage, name, "app")
    os.makedirs(app)
    for f in files:
        shutil.copy2(os.path.join(root, "app", f), app)
print("staged", ", ".join(APPS))
PY

# --- .exe (Inno Setup, run under Wine) ------------------------------------------------------------
w() { winepath -w "$1" 2>/dev/null; }
for app in rigpanel:$RP netlog:$NL; do
  name=${app%%:*}; ver=${app##*:}
  wine "$ISCC" /Q "/O$(w "$OUT")" "/DAppVer=$ver" "/DStage=$(w "$STAGE/$name")" "/DRoot=$(w "$ROOT")" "$(w "$HERE/$name.iss")"
done

# --- .msi (wixl) -----------------------------------------------------------------------------------
python3 - "$STAGE" "$HERE" "$RP" "$NL" <<'PY'
import os, sys, uuid
stage, here, rp, nl = sys.argv[1:]
NS = uuid.UUID("5f0e0a4e-8b1c-4d3a-9b55-2f7c6a1d9e10")
ADDON = {"index-net.html", "netlogcore.py", "netexport.py"}
APPS = {
    "rigpanel": dict(ver=rp, title="RigPanel", dir="RigPanel", key="RigPanel", upgrade="8A1F5C2E-3B7D-4E61-9F2A-6C0D4B8E7A13",
                     ico="rigpanel.ico", arg="rigpanel", desc="Control your ham radio"),
    "netlog": dict(ver=nl, title="Net Log", dir="NetLog", key="NetLog", upgrade="2D6B9E47-0C3A-4F85-B1E2-7A9C5D3F8E64",
                   ico="netlog.ico", arg="netlog", desc="Log check-ins for ham radio nets"),
}
esc = lambda s: s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
for name, a in APPS.items():
    base = os.path.join(stage, name)
    ids, comps = {}, {"main": [], "addon": []}
    def tree(rel):
        out = []
        full = os.path.join(base, rel)
        for e in sorted(os.listdir(full)):
            r = os.path.join(rel, e) if rel else e
            if os.path.isdir(os.path.join(base, r)):
                did = "d" + uuid.uuid5(NS, name + "/" + r).hex[:16]
                out.append(f'<Directory Id="{did}" Name="{esc(e)}">' + "".join(tree(r)) + "</Directory>")
            else:
                cid = "c" + uuid.uuid5(NS, name + "/c/" + r).hex[:16]
                fid = "f" + uuid.uuid5(NS, name + "/f/" + r).hex[:16]
                ids[r.replace(os.sep, "/")] = fid
                guid = str(uuid.uuid5(NS, name + "/g/" + r)).upper()
                out.append(f'<Component Id="{cid}" Guid="{guid}"><File Id="{fid}" Name="{esc(e)}" Source="{esc(os.path.join(base, r))}" KeyPath="yes"/></Component>')
                (comps["addon"] if name == "rigpanel" and r.startswith("app") and e in ADDON else comps["main"]).append(cid)
        return out
    files = "".join(tree(""))
    pyw = ids["python/pythonw.exe"]
    target = f'"[INSTALLDIR]app\\launch.py" {a["arg"]}'
    def shortcut(sid, folder, args):
        return (f'<Component Id="sc{sid}" Guid="{str(uuid.uuid5(NS, name + "/sc/" + sid)).upper()}">'
                f'<Shortcut Id="s{sid}" Name="{esc(a["title"])}" Description="{esc(a["desc"])}" Directory="{folder}" '
                f'Target="[INSTALLDIR]python\\pythonw.exe" Arguments="{esc(args)}" WorkingDirectory="INSTALLDIR" Icon="AppIcon"/>'
                f'<RegistryValue Root="HKCU" Key="Software\\{a["key"]}\\Shortcuts" Name="{sid}" Type="integer" Value="1" KeyPath="yes"/>'
                f'</Component>')
    addon_feature = ("<Feature Id=\"NetLogAddon\" Title=\"Net log add-on\" Level=\"1\">" +
                     "".join(f'<ComponentRef Id="{c}"/>' for c in comps["addon"]) + "</Feature>") if comps["addon"] else ""
    wxs = f'''<?xml version="1.0" encoding="utf-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="{esc(a["title"])}" Language="1033" Version="{a["ver"]}" Manufacturer="KJ5JDO" UpgradeCode="{a["upgrade"]}">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perUser"
             Description="{esc(a["title"])} {a["ver"]}" Comments="https://github.com/GUAC88/RigPanel"/>
    <Media Id="1" Cabinet="app.cab" EmbedCab="yes"/>
    <Property Id="ALLUSERS" Value="2"/>
    <Property Id="MSIINSTALLPERUSER" Value="1"/>
    <Property Id="ARPPRODUCTICON" Value="AppIcon"/>
    <Property Id="ARPURLINFOABOUT" Value="https://github.com/GUAC88/RigPanel"/>
    <Icon Id="AppIcon" SourceFile="{esc(os.path.join(base, "app", a["ico"]))}"/>
    <Upgrade Id="{a["upgrade"]}">
      <UpgradeVersion Minimum="0.0.0" IncludeMinimum="yes" Maximum="{a["ver"]}" IncludeMaximum="no" Property="OLDERFOUND"/>
    </Upgrade>
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="LocalAppDataFolder">
        <Directory Id="LocalPrograms" Name="Programs">
          <Directory Id="INSTALLDIR" Name="{a["dir"]}">{files}</Directory>
        </Directory>
      </Directory>
      <Directory Id="ProgramMenuFolder">{shortcut("Menu", "ProgramMenuFolder", target)}</Directory>
      <Directory Id="DesktopFolder">{shortcut("Desktop", "DesktopFolder", target)}</Directory>
      <Directory Id="StartupFolder">{shortcut("Startup", "StartupFolder", target + " --no-browser")}</Directory>
    </Directory>
    <CustomAction Id="StopRunning" FileKey="{ids["python/python.exe"]}" ExeCommand='"[INSTALLDIR]app\\stop.py" {a["arg"]}' Execute="immediate" Return="ignore"/>
    <InstallExecuteSequence>
      <Custom Action="StopRunning" Before="InstallValidate">Installed</Custom>
      <RemoveExistingProducts After="InstallInitialize"/>
    </InstallExecuteSequence>
    <Feature Id="Main" Title="{esc(a["title"])}" Level="1" Absent="disallow">
      {"".join(f'<ComponentRef Id="{c}"/>' for c in comps["main"])}
      <ComponentRef Id="scMenu"/>
    </Feature>
    {addon_feature}
    <Feature Id="DesktopShortcut" Title="Desktop shortcut" Level="1"><ComponentRef Id="scDesktop"/></Feature>
    <Feature Id="StartAtLogin" Title="Start at login" Level="1000"><ComponentRef Id="scStartup"/></Feature>
  </Product>
</Wix>
'''
    with open(os.path.join(stage, name + ".wxs"), "w") as f:
        f.write(wxs)
print("wrote .wxs")
PY
wixl -a x64 -o "$OUT/RigPanel-$RP.msi" "$STAGE/rigpanel.wxs"
wixl -a x64 -o "$OUT/NetLog-$NL.msi" "$STAGE/netlog.wxs"
ls -l "$OUT"/*.exe "$OUT"/*.msi
