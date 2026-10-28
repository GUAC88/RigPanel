#!/usr/bin/env python3
"""RigPanel: a simple browser control panel for CAT-controlled ham radios.

Native drivers for the Yaesu FT-991A family and Icom CI-V radios; any other radio through Hamlib.

Serves http://localhost:<port> (default 8073). Talks to the radio's CAT / CI-V USB port.
Per-station settings live in ~/.config/rigpanel/config.json (written by the installer).

Copyright (C) 2026 Cody KJ5JDO
This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
LICENSE file or <https://www.gnu.org/licenses/>.
"""
import json
import math
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import threading
import time
import socketserver
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # radios / netlogcore sit next to this file (also under an embedded Python)
sys.dont_write_bytecode = True   # no __pycache__ folders in the install folder (uninstallers leave nothing behind)
import radios  # noqa: E402

VERSION = "1.6.0"

if os.name == "nt":
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "RigPanel")
else:
    CONFIG_DIR = os.path.expanduser("~/.config/rigpanel")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_CONFIG = {
    "callsign": "N0CALL",
    "grid": "",
    "serial_port": "",
    "baud": 38400,
    "http_port": 8073,
    "winlink_freq": 145030000,
    "hamlib_port": 4532,  # rigctld-compatible TCP port for VarAC, WSJT-X, etc. 0 = off
    "ptt_timeout": 180,   # PC mic: longest single transmission in seconds before RigPanel unkeys
    "radio": "auto",      # auto | yaesu | icom | hamlib
    "civ_address": "",    # Icom: CI-V address in hex, blank = ask the radio
    "hamlib_model": 0,    # Hamlib: rig model number (rigctl -l)
    "hamlib_name": "",
    "max_power": 100,     # Hamlib: the radio's full power in watts
    "rigctld_path": "",
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    cfg["callsign"] = str(cfg["callsign"]).upper()
    return cfg


def save_config(changes):
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    cfg.update(changes)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    CONFIG.update(changes)


CONFIG = load_config()
LISTEN = ("127.0.0.1", int(CONFIG["http_port"]))
PRESETS_FILE = os.path.join(CONFIG_DIR, "presets.json")
PROFILES_FILE = os.path.join(CONFIG_DIR, "profiles.json")
PTT_RESTORE_FILE = os.path.join(CONFIG_DIR, "ptt-restore.json")
BACKGROUND_FILE = os.path.join(CONFIG_DIR, "background")   # the page's background photo, if any
BACKGROUND_MAX = 15 * 1024 * 1024
DEFAULT_BACKGROUND = {"style": "glow", "strength": 50, "animate": True, "dim": 55, "blur": 4, "fit": "cover", "glass": 15, "v": 0}
BACKGROUND_STYLES = ("glow", "plain", "grid", "waves", "waterfall", "topo", "stars", "photo")

DEFAULT_PRESETS = [
    {"name": "2m Calling", "freq": 146520000, "mode": "FM", "tone": None, "shift": "simplex"},
    {"name": "70cm Calling", "freq": 446000000, "mode": "FM", "tone": None, "shift": "simplex"},
]


# Quick Setup profiles: configure the whole radio for one job in one tap
DEFAULT_PROFILES = [
    {"name": "Winlink (VARA FM)", "icon": "\u2709", "freq": int(CONFIG["winlink_freq"]), "mode": "DATA-FM",
     "tone": None, "shift": "simplex", "squelch": 0, "power": 25},
    {"name": "VarAC 2m", "icon": "\U0001F4AC", "freq": 144950000, "mode": "DATA-FM",
     "tone": None, "shift": "simplex", "squelch": 0, "power": 25},
    {"name": "VarAC 70cm", "icon": "\U0001F4AC", "freq": 439600000, "mode": "DATA-FM",
     "tone": None, "shift": "simplex", "squelch": 0, "power": 25},
    {"name": "FM Voice", "icon": "\U0001F399", "freq": 146520000, "mode": "FM",
     "tone": None, "shift": "simplex", "squelch": 20, "power": 25},
    {"name": "NOAA Weather", "icon": "\u26C5", "freq": 162550000, "mode": "FM",
     "tone": None, "shift": "simplex", "squelch": 20, "power": 5},
]


def load_presets():
    try:
        with open(PRESETS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        os.makedirs(os.path.dirname(PRESETS_FILE), exist_ok=True)
        with open(PRESETS_FILE, "w") as f:
            json.dump(DEFAULT_PRESETS, f, indent=2)
        return DEFAULT_PRESETS


def load_profiles():
    try:
        with open(PROFILES_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
        with open(PROFILES_FILE, "w") as f:
            json.dump(DEFAULT_PROFILES, f, indent=2)
        return DEFAULT_PROFILES


def save_presets(presets):
    with open(PRESETS_FILE, "w") as f:
        json.dump(presets, f, indent=2)


MYCALL = CONFIG["callsign"]
CALLSIGN_RE = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z]$")


def needs_setup():
    """First run (e.g. after the .msi installer, which asks no questions): no real callsign yet."""
    return MYCALL == "N0CALL" or not CALLSIGN_RE.match(MYCALL)


def station_setup(body):
    """Save the callsign and grid square from the panel's first-run screen."""
    global MYCALL
    call = str(body.get("callsign") or "").strip().upper()
    grid = str(body.get("grid") or "").strip()
    if not CALLSIGN_RE.match(call):
        raise ValueError(f"{call or 'That'} doesn't look like a callsign")
    if grid and not re.fullmatch(r"[A-Ra-r]{2}\d{2}([A-Xa-x]{2})?", grid):
        raise ValueError(f"{grid} isn't a grid square (e.g. EM26 or EM26av)")
    save_config({"callsign": call, "grid": grid})
    MYCALL = call
    _noaa.update(t=0, pick=None)   # new location: pick the NOAA transmitter again
LOOKUPS_FILE = os.path.join(CONFIG_DIR, "lookups.json")
_lookup_cache = {}


def callook(call):
    """Look up a US amateur callsign via callook.info (FCC ULS data)."""
    call = call.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,7}", call):
        return {"call": call, "status": "INVALID"}
    if call in _lookup_cache:
        return _lookup_cache[call]
    req = urllib.request.Request(f"https://callook.info/{urllib.parse.quote(call)}/json",
                                 headers={"User-Agent": f"RigPanel/1.0 ({MYCALL})"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.load(r)
    if d.get("status") != "VALID":
        res = {"call": call, "status": d.get("status", "NOT FOUND")}
    else:
        loc = d.get("location") or {}
        res = {
            "call": call, "status": "VALID",
            "name": (d.get("name") or "").title(),
            "type": d.get("type"),
            "class": ((d.get("current") or {}).get("operClass") or "").title(),
            "trustee": (d.get("trustee") or {}).get("callsign") or "",
            # city/state only - street address is deliberately not shown
            "cityState": re.sub(r"\s+\d{5}(-\d{4})?$", "", (d.get("address") or {}).get("line2") or ""),
            "grid": loc.get("gridsquare") or "",
            "lat": float(loc["latitude"]) if loc.get("latitude") else None,
            "lon": float(loc["longitude"]) if loc.get("longitude") else None,
            "expires": (d.get("otherInfo") or {}).get("expiryDate") or "",
            "uls": (d.get("otherInfo") or {}).get("ulsUrl") or "",
        }
    _lookup_cache[call] = res
    return res


def distance_bearing(a, b):
    """Great-circle distance (miles) and bearing (degrees) from a to b."""
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    miles = 3958.8 * 2 * math.asin(math.sqrt(h))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return round(miles, 1), round((math.degrees(math.atan2(y, x)) + 360) % 360)


def lookup_with_distance(call, remember=True):
    res = dict(callook(call))
    if res.get("status") == "VALID" and res.get("lat") is not None:
        me = my_location()
        if me and res["call"] != MYCALL:
            res["miles"], res["bearing"] = distance_bearing(me, res)
    if remember and res.get("status") == "VALID" and res.get("lat") is not None:
        hist = load_lookups()
        hist = [h for h in hist if h["call"] != res["call"]]
        hist.insert(0, {"call": res["call"], "name": res["name"], "cityState": res["cityState"],
                        "when": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())})
        save_lookups(hist[:25])
    return res


def grid_to_latlon(grid):
    """Centre of a 4- or 6-character Maidenhead locator."""
    g = grid.strip()
    if not re.fullmatch(r"[A-Ra-r]{2}\d{2}([A-Xa-x]{2})?", g):
        return None
    g = g[:2].upper() + g[2:4] + g[4:].lower()
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) == 6:
        lon += (ord(g[4]) - 97) * (2 / 24) + 1 / 24
        lat += (ord(g[5]) - 97) * (1 / 24) + 1 / 48
    else:
        lon += 1
        lat += 0.5
    return {"lat": lat, "lon": lon}


def my_location():
    """Own station position: FCC license location if available, else grid centre."""
    try:
        me = callook(MYCALL)
        if me.get("lat") is not None:
            return me
    except OSError:
        pass
    return grid_to_latlon(CONFIG.get("grid", ""))


# --- NOAA Weather Radio: the transmitter that serves your county -------------------------------------
# nwr.json is built from NOAA's County Coverage Listing (tools/update-nwr.py). Your county comes from your
# FCC license location (or grid square) through the FCC's census area lookup, cached in the config folder.
NWR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nwr.json")
NWR_CACHE = os.path.join(CONFIG_DIR, "nwr-location.json")
WX_BAND = (162_390_000, 162_560_000)
_noaa = {"t": 0, "pick": None}
_noaa_lock = threading.Lock()


def county_fips(lat, lon):
    key = f"{lat:.3f},{lon:.3f}"
    try:
        with open(NWR_CACHE) as f:
            c = json.load(f)
        if c.get("key") == key and c.get("fips"):
            return c["fips"], c.get("county", "")
    except (OSError, ValueError):
        pass
    url = f"https://geo.fcc.gov/api/census/area?lat={lat:.6f}&lon={lon:.6f}&censusYear=2020&format=json"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": f"RigPanel/{VERSION}"}), timeout=10) as r:
        res = (json.load(r).get("results") or [{}])[0]
    fips, county = res.get("county_fips", ""), f"{res.get('county_name', '')}, {res.get('state_code', '')}".strip(", ")
    if fips:
        with open(NWR_CACHE, "w") as f:
            json.dump({"key": key, "fips": fips, "county": county}, f)
    return fips, county


def noaa_pick():
    """The NOAA Weather Radio transmitter to listen to: the nearest in-service one NOAA lists for your county,
    else the nearest in-service one within 100 miles. Recomputed every 12 hours."""
    with _noaa_lock:
        if _noaa["pick"] is not None and time.time() - _noaa["t"] < 12 * 3600:
            return _noaa["pick"] or None
        pick = {}
        try:
            with open(NWR_FILE) as f:
                nwr = json.load(f)
            me = my_location()
            if me and me.get("lat") is not None:
                county, cands = "", []
                try:
                    fips, county = county_fips(me["lat"], me["lon"])
                    cands = nwr["counties"].get("0" + fips, [])
                except (OSError, ValueError):
                    pass
                def miles(call):
                    t = nwr["tx"][call]
                    return distance_bearing(me, {"lat": t[4], "lon": t[5]})[0]
                ok = [c for c in cands if c in nwr["tx"] and nwr["tx"][c][7] != "OUT OF SERVICE"]
                if not ok:   # county unknown (offline) or nothing listed: nearest working transmitter
                    near = sorted((miles(c), c) for c, t in nwr["tx"].items() if t[7] == "NORMAL")
                    ok, county = [c for m, c in near[:3] if m <= 100], ""
                ok.sort(key=lambda c: (nwr["tx"][c][7] != "NORMAL", miles(c)))
                if ok:
                    t = nwr["tx"][ok[0]]
                    pick = {"call": ok[0], "site": t[0], "state": t[2], "freq": int(round(t[3] * 1e6)), "miles": round(miles(ok[0])),
                            "county": county, "status": t[7],
                            "others": [{"call": c, "site": nwr["tx"][c][0], "freq": int(round(nwr["tx"][c][3] * 1e6))} for c in ok[1:]]}
        except (OSError, ValueError, KeyError):
            pass
        _noaa.update(t=time.time(), pick=pick)
        return pick or None


def profiles_for_here():
    """Quick Setups as shown: any NOAA Weather one is tuned to your local transmitter."""
    out = []
    for p in load_profiles():
        if WX_BAND[0] <= int(p.get("freq") or 0) <= WX_BAND[1]:
            w = noaa_pick()
            if w:
                p = dict(p, freq=w["freq"], name=f"NOAA Weather · {w['site']}",
                         noaa=f"{w['call']} {w['site']}, {w['state']} · {w['miles']} mi" + (f" · serves {w['county']}" if w["county"] else ""))
        out.append(p)
    return out


def load_lookups():
    try:
        with open(LOOKUPS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_lookups(h):
    os.makedirs(os.path.dirname(LOOKUPS_FILE), exist_ok=True)
    with open(LOOKUPS_FILE, "w") as f:
        json.dump(h, f, indent=2)


class RadioManager:
    """Holds the connected radio's driver. Finds the radio in the background, reconnects after it's
    switched off and on, and can be pointed at a different radio from the page."""

    def __init__(self):
        self.drv = None
        self.lock = threading.Lock()
        self.searching = False
        self.last_try = 0.0
        self.fails = 0
        self.message = "Looking for the radio…"

    def _search(self):
        try:
            drv = radios.connect(CONFIG, log=lambda m: print(m, flush=True))
        except Exception as e:   # never let a probe kill the panel
            drv = None
            print(f"Radio search failed: {e}", flush=True)
        with self.lock:
            if self.drv:
                self.drv.close()
            self.drv, self.searching, self.fails = drv, False, 0
            kind = (CONFIG.get("radio") or "auto").lower()
            if drv:
                self.message = ""
                threading.Thread(target=recover_ptt, daemon=True).start()
            elif kind == "hamlib" and not radios.find_rigctld(CONFIG.get("rigctld_path", "")):
                self.message = "Hamlib isn't installed: rigctld wasn't found."
            elif kind == "hamlib" and not CONFIG.get("hamlib_model"):
                self.message = "Pick your radio's Hamlib model in Radio setup."
            else:
                self.message = "Radio not responding: is it on and plugged in? Check the port and baud rate in Radio setup."

    def search(self, wait=False):
        with self.lock:
            if self.searching:
                return
            self.searching, self.last_try = True, time.time()
            self.message = "Looking for the radio…"
        t = threading.Thread(target=self._search, daemon=True)
        t.start()
        if wait:
            t.join()

    def status(self):
        drv = self.drv
        if drv is None:
            if not self.searching and time.time() - self.last_try > 8:
                self.search()
            return {"ok": False, "message": self.message, "searching": self.searching}
        s = drv.status()
        if s.get("ok"):
            self.fails = 0
        else:
            self.fails += 1
            s["message"] = "Radio not responding: is it on and plugged in?"
            # Lost for a while: look again (the radio may be on another port or baud after a restart)
            if self.fails >= 10 and (CONFIG.get("radio") or "auto") != "hamlib" and not CONFIG.get("serial_port"):
                with self.lock:
                    self.drv = None
                drv.close()
                self.last_try = 0
        s["pc_tx"] = pc_ptt.keyed
        return s

    def __getattr__(self, name):
        drv = self.__dict__.get("drv")
        if drv is None:
            raise RadioMissing()
        return getattr(drv, name)


class RadioMissing(Exception):
    pass


rig = RadioManager()


# --- PC microphone transmit -------------------------------------------------------------
# --- PC microphone transmit -------------------------------------------------------------
# The page sends the computer's mic to the radio's USB sound card. While the TX button is held, the
# current mode's mic input is switched from the front MIC jack to the rear/USB input (on radios where
# RigPanel knows how), then put back.
class PcPtt:
    """Keys the radio for the page's TX button. The page repeats its 'on' request every half second;
    if those stop (page closed, browser crashed, network gone) or a transmission runs past the time-out,
    the radio is unkeyed."""
    HEARTBEAT = 2.5

    def __init__(self):
        self.lock = threading.Lock()
        self.keyed = False
        self.since = self.last = 0.0
        self.restore = []
        self.stopped = ""
        self.limit = int(CONFIG.get("ptt_timeout") or 180)

    def hold(self):
        """Heartbeat from the page while the button is held. Never keys the radio by itself."""
        with self.lock:
            if not self.keyed:
                return {"ok": False, "tx": False, "error": f"Transmit stopped: {self.stopped or 'radio unkeyed'}."}
            self.last = time.time()
            return {"ok": True, "tx": True, "left": round(self.limit - (time.time() - self.since))}

    def key(self):
        with self.lock:
            if self.keyed:
                self.last = time.time()
                return {"ok": True, "tx": True, "left": round(self.limit - (time.time() - self.since))}
            try:
                mode = rig.get_mode()
            except RadioMissing:
                mode = None
            if mode is None:
                return {"ok": False, "error": "Radio not responding"}
            menus = rig.mic_usb_menus(mode)
            if menus is None:
                return {"ok": False, "error": f"The PC mic can't transmit in {mode}. Use FM, SSB, AM or a DATA mode."}
            restore = []
            for key, usb in menus:
                old = rig.read_setting(key) or ""
                if old and old != usb:
                    restore.append((key, old))
                    rig.write_setting(key, usb)
            self.restore = restore
            save_ptt_restore(restore)
            fix_audio_routes()
            rig.set_ptt(True)
            self.keyed, self.since, self.last, self.stopped = True, time.time(), time.time(), ""
            return {"ok": True, "tx": True, "left": self.limit}

    def unkey(self, why=""):
        with self.lock:
            if not self.keyed:
                return {"ok": True, "tx": False}
            try:
                rig.set_ptt(False)
                time.sleep(0.1)
                for key, old in self.restore:
                    rig.write_setting(key, old)
            except RadioMissing:
                pass
            self.keyed, self.restore, self.stopped = False, [], why
            save_ptt_restore([])
            if why:
                print(f"PC mic transmit stopped: {why}", flush=True)
            return {"ok": True, "tx": False, "stopped": why}

    def watchdog(self):
        while True:
            time.sleep(0.5)
            if self.keyed and time.time() - self.last > self.HEARTBEAT:
                self.unkey("the page stopped responding")
            elif self.keyed and time.time() - self.since > self.limit:
                self.unkey(f"{self.limit} second time-out")


def fix_audio_routes():
    """Linux/PipeWire: when the radio is switched off and on (or its USB cable re-plugged), its sound card
    goes away and the browser's sound is moved to the computer's speakers. It stays there after the radio
    comes back, even though the browser still asks for the radio. Put such streams back where they asked to go."""
    if os.name == "nt" or not (shutil.which("pactl") and shutil.which("pw-metadata")):
        return
    try:
        r = subprocess.run(["pactl", "-f", "json", "list", "sinks"], capture_output=True, text=True, timeout=3)
        sinks = {x["name"]: x["index"] for x in json.loads(r.stdout or "[]")}
        r = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True, timeout=3)
        for x in json.loads(r.stdout or "[]"):
            props = x.get("properties", {})
            want, node = props.get("target.object"), props.get("object.id")
            if want in sinks and x.get("sink") != sinks[want] and node:
                subprocess.run(["pw-metadata", str(node), "target.object", want], capture_output=True, timeout=3)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


# --- Station status (Linux/PipeWire): is the radio's sound card there, and is VARA's audio going to it? ------
RADIO_CARD = re.compile(r"audio codec|pcm29\d\d|burr-brown|ft-991", re.I)


def _pw_graph():
    """Nodes, ports and links from pw-dump, or None if PipeWire isn't available."""
    if os.name == "nt" or not shutil.which("pw-dump"):
        return None
    try:
        objs = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    g = {"nodes": {}, "ports": {}, "links": {}}
    for o in objs:
        info = o.get("info") or {}
        props = info.get("props") or {}
        if o.get("type") == "PipeWire:Interface:Node":
            g["nodes"][o["id"]] = props
        elif o.get("type") == "PipeWire:Interface:Port":
            g["ports"][o["id"]] = {"node": props.get("node.id"), "dir": info.get("direction"), "ch": props.get("audio.channel")}
        elif o.get("type") == "PipeWire:Interface:Link":
            g["links"][o["id"]] = (info.get("output-node-id"), info.get("output-port-id"), info.get("input-node-id"), info.get("input-port-id"))
    return g


def _radio_devices(g):
    sink = src = None
    for nid, p in g["nodes"].items():
        if RADIO_CARD.search(p.get("node.description", "") + " " + p.get("node.name", "")):
            if p.get("media.class") == "Audio/Sink" and sink is None:
                sink = nid
            elif p.get("media.class") == "Audio/Source" and src is None:
                src = nid
    return sink, src


def _vara_streams(g):
    return [(nid, p) for nid, p in g["nodes"].items()
            if "vara" in (p.get("application.name", "") + p.get("node.name", "")).lower()
            and p.get("media.class") in ("Stream/Output/Audio", "Stream/Input/Audio")]


def _vara_routes(g, sink, src):
    """[(stream node, playing?, [connected device nodes], ok?)] for each VARA stream."""
    out = []
    for nid, p in _vara_streams(g):
        play = p.get("media.class") == "Stream/Output/Audio"
        peers = sorted({(l[2] if play else l[0]) for l in g["links"].values() if (l[0] if play else l[2]) == nid})
        want = sink if play else src
        out.append((nid, play, peers, bool(peers) and want is not None and all(x == want for x in peers)))
    return out


# Windows: no sound-server routing to inspect, so check the sound card exists and read VARA's own settings
VARA_INIS = [os.path.join(d, "VARA FM", "VARAFM.ini") for d in
             ("C:\\", os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")) if d]
_win_cache = {}


def _win_run(args, ttl):
    """Run a console command without flashing a window; cache the output for `ttl` seconds."""
    hit = _win_cache.get(tuple(args))
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    _win_cache[tuple(args)] = (time.time(), out)
    return out


def _win_sound_devices():
    return _win_run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_SoundDevice | ForEach-Object Name"], 60).splitlines()


def _win_vara_running():
    return any(re.match(r'"vara[^"]*\.exe"', line, re.I) for line in _win_run(["tasklist", "/FO", "CSV", "/NH"], 4).splitlines())


def _read_ini(path):
    sec, out = "", {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    sec = line[1:-1].lower()
                elif "=" in line:
                    k, v = line.split("=", 1)
                    out.setdefault(f"{sec}.{k.strip().lower()}", v.strip())
    except OSError:
        pass
    return out


def _win_station(st):
    card = any(RADIO_CARD.search(n) for n in _win_sound_devices())
    st["checks"].append({"id": "card", "label": "Radio sound card", "state": "ok" if card else "bad",
                         "detail": "found" if card else "not found"})
    running = _win_vara_running()
    st["checks"].append({"id": "vara", "label": "VARA", "state": "ok" if running else "off",
                         "detail": "running" if running else "not running"})
    ini = next((p for p in VARA_INIS if os.path.exists(p)), None)
    if not ini:
        return st
    v = _read_ini(ini)
    i, o = v.get("soundcard.input device name", ""), v.get("soundcard.output device name", "")
    good = bool(RADIO_CARD.search(i)) and bool(RADIO_CARD.search(o))
    st["checks"].append({"id": "vara-snd", "label": "VARA sound card", "state": "ok" if good else "bad",
                         "detail": "radio's USB Audio CODEC" if good else
                                   ("input: " + (i or "not set")) if not RADIO_CARD.search(i) else ("output: " + (o or "not set"))})
    mine = str(getattr(getattr(rig.drv, "port", None), "path", "") or CONFIG.get("serial_port") or "").upper()
    cat = v.get("ptt.catport", "").upper()
    clash = bool(mine) and cat == mine
    st["checks"].append({"id": "vara-ptt", "label": "VARA PTT port", "state": "warn" if clash else "ok",
                         "detail": f"{cat} is RigPanel's port: use RTS on the Standard port" if clash
                                   else (v.get("ptt.pttport") or "VOX")})
    return st


def station_status():
    st = {"checks": [], "fixable": False}
    st["checks"].append({"id": "radio", "label": "Radio control", "state": "ok" if rig.drv else "bad",
                         "detail": rig.drv.model if rig.drv else (rig.message or "not connected")})
    if os.name == "nt":
        return _win_station(st)
    g = _pw_graph()
    if g is None:
        return st
    sink, src = _radio_devices(g)
    card = sink is not None and src is not None
    st["checks"].append({"id": "card", "label": "Radio sound card", "state": "ok" if card else "bad",
                         "detail": "in and out" if card else "output only" if sink else "input only" if src else "not found"})
    routes = _vara_routes(g, sink, src)
    if not routes:
        st["checks"].append({"id": "vara", "label": "VARA", "state": "off", "detail": "not running"})
        return st
    st["checks"].append({"id": "vara", "label": "VARA", "state": "ok", "detail": "running"})
    name = lambda n: (g["nodes"].get(n, {}).get("node.description") or "?").replace(" Analog Stereo", "").replace(" Mono", "")
    for play in (True, False):
        mine = [r for r in routes if r[1] == play]
        if not mine:
            continue
        ok = all(r[3] for r in mine)
        peers = sorted({x for r in mine for x in r[2]})
        st["checks"].append({"id": "vara-out" if play else "vara-in", "label": "VARA " + ("→ radio" if play else "← radio"),
                             "state": "ok" if ok else "bad",
                             "detail": "radio sound card" if ok else ("going to " if play else "listening to ") +
                                       (", ".join(name(x) for x in peers) or "nothing")})
        st["fixable"] = st["fixable"] or (not ok and card)
    return st


def fix_vara_audio():
    """Put VARA's streams back on the radio's sound card. Wine marks them don't-reconnect, so after the radio's
    USB drops out they stay on the fallback device: try the polite move first, then relink the ports directly."""
    for attempt in range(3):
        g = _pw_graph()
        if g is None:
            return {"ok": False, "message": "Needs PipeWire (Linux)."}
        sink, src = _radio_devices(g)
        if sink is None or src is None:
            return {"ok": False, "message": "The radio's sound card isn't there. Is the radio on and plugged in?"}
        bad = [r for r in _vara_routes(g, sink, src) if not r[3]]
        if not bad:
            break
        for nid, play, peers, _ in bad:
            if attempt == 0:   # the normal way: ask the sound server to move the stream
                dev = g["nodes"][sink if play else src].get("node.name")
                subprocess.run(["pw-metadata", str(nid), "target.object", dev], capture_output=True, timeout=3)
                continue
            dev = sink if play else src
            for lid, (on, op, inn, ip) in g["links"].items():   # drop links to the wrong device
                if (play and on == nid and inn != dev) or (not play and inn == nid and on != dev):
                    subprocess.run(["pw-link", "-d", str(lid)], capture_output=True, timeout=3)
            mine = {p["ch"]: pid for pid, p in g["ports"].items() if p["node"] == nid and p["dir"] == ("output" if play else "input")}
            theirs = {p["ch"]: pid for pid, p in g["ports"].items() if p["node"] == dev and p["dir"] == ("input" if play else "output")}
            for ch, pid in mine.items():
                other = theirs.get(ch) or theirs.get("FL" if ch in ("MONO", None) else ch)
                if other:
                    a, b = (pid, other) if play else (other, pid)
                    subprocess.run(["pw-link", str(a), str(b)], capture_output=True, timeout=3)
        time.sleep(1.5)   # let the session manager settle before checking again
    st = station_status()
    return {"ok": not st["fixable"] and all(c["state"] != "bad" for c in st["checks"] if c["id"].startswith("vara")),
            "status": st}


def save_ptt_restore(items):
    """Remember menus to put back, in case RigPanel is stopped mid-transmission."""
    try:
        if items:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(PTT_RESTORE_FILE, "w") as f:
                json.dump(items, f)
        elif os.path.exists(PTT_RESTORE_FILE):
            os.remove(PTT_RESTORE_FILE)
    except OSError:
        pass


def recover_ptt():
    """RigPanel stopped while the PC mic was keyed: unkey and put the mic menus back."""
    try:
        with open(PTT_RESTORE_FILE) as f:
            items = json.load(f)
    except (OSError, ValueError):
        return
    try:
        rig.set_ptt(False)
        for key, old in items:
            try:
                rig.write_setting(key, old)
            except (KeyError, ValueError):
                pass
    except RadioMissing:
        return   # try again once the radio is found
    save_ptt_restore([])


pc_ptt = PcPtt()
_mem_cache = {}
def image_type(b):
    """Content type of a JPEG / PNG / WebP / GIF image, or None for anything else."""
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def background_settings():
    bg = dict(DEFAULT_BACKGROUND)
    bg.update(CONFIG.get("background") or {})
    bg["photo"] = os.path.exists(BACKGROUND_FILE)
    return bg


def save_background_settings(body):
    style = str(body.get("style", "glow"))
    if style not in BACKGROUND_STYLES:
        raise ValueError("unknown background style")
    fit = str(body.get("fit", "cover"))
    if fit not in ("cover", "contain", "tile"):
        raise ValueError("unknown fit")
    bg = background_settings()
    bg.update(style=style, fit=fit, dim=max(0, min(90, int(body.get("dim", 55)))),
              strength=max(5, min(100, int(body.get("strength", 50)))), animate=bool(body.get("animate", True)),
              blur=max(0, min(30, int(body.get("blur", 4)))), glass=max(0, min(60, int(body.get("glass", 15)))))
    bg.pop("photo", None)
    save_config({"background": bg})
    return background_settings()


def save_background_photo(data, n):
    """Store an uploaded background photo (empty upload = remove it). Returns (reply, status)."""
    if n == 0:
        try:
            os.remove(BACKGROUND_FILE)
        except OSError:
            pass
        bg = background_settings()
        if bg["style"] == "photo":
            bg["style"] = "glow"
        bg.pop("photo", None)
        save_config({"background": bg})
        return {"ok": True, "background": background_settings()}, 200
    if data is None:
        return {"ok": False, "message": "That picture is too big (15 MB at most)."}, 413
    if not image_type(data):
        return {"ok": False, "message": "That isn't a JPEG, PNG, WebP or GIF picture."}, 415
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(BACKGROUND_FILE + ".tmp", "wb") as f:
        f.write(data)
    os.replace(BACKGROUND_FILE + ".tmp", BACKGROUND_FILE)
    bg = background_settings()
    bg.update(style="photo", v=int(time.time()))
    bg.pop("photo", None)
    save_config({"background": bg})
    return {"ok": True, "background": background_settings()}, 200


_hamlib_models = []
RADIO_KEYS = ("radio", "serial_port", "baud", "civ_address", "hamlib_model", "hamlib_name", "max_power")


def radio_settings(body):
    """Check the Radio setup form from the page; return the config changes."""
    kind = str(body.get("radio", "auto")).lower()
    if kind not in ("auto", "yaesu", "icom", "hamlib"):
        raise ValueError("unknown radio type")
    port = str(body.get("serial_port") or "").strip()
    if port and not re.fullmatch(r"(/dev/[\w./:+-]+|COM\d{1,3}|[\w.-]+:\d{1,5})", port):
        raise ValueError("that doesn't look like a serial port")
    baud = int(body.get("baud") or 38400)
    if baud not in (1200, 4800, 9600, 19200, 38400, 57600, 115200):
        raise ValueError("unsupported baud rate")
    civ = str(body.get("civ_address") or "").strip().upper().removesuffix("H")
    if civ and not re.fullmatch(r"[0-9A-F]{2}", civ):
        raise ValueError("CI-V address must be two hex digits, like 94")
    model = int(body.get("hamlib_model") or 0)
    if kind == "hamlib" and model <= 0:
        raise ValueError("pick a Hamlib radio model")
    power = int(body.get("max_power") or 100)
    if not 1 <= power <= 2000:
        raise ValueError("full power must be 1-2000 W")
    return {"radio": kind, "serial_port": port, "baud": baud, "civ_address": civ, "hamlib_model": model,
            "hamlib_name": str(body.get("hamlib_name") or "")[:80], "max_power": power}


PAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
# Optional pages, served only when their files are installed next to index.html. The Net log add-on also needs
# netlogcore.py + netexport.py (the installer copies all three when you choose the add-on).
try:
    import netlogcore
except ImportError:
    netlogcore = None
try:
    import icsforms   # ICS-213/214/205/309 forms (index-ics.html)
except ImportError:
    icsforms = None
TRIAL_PAGES = {"/new": "index-new.html", "/net": "index-net.html", "/ics": "index-ics.html"}


def trial_page(path):
    if (path == "/net" and not netlogcore) or (path == "/ics" and not icsforms):
        return None
    f = TRIAL_PAGES.get(path)
    f = f and os.path.join(os.path.dirname(PAGE_PATH), f)
    return f if f and os.path.exists(f) else None




class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _file(self, data, ctype, name=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if name:
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            self._get()
        except RadioMissing:
            self._json({"ok": False, "message": rig.message}, 503)

    def do_POST(self):
        try:
            self._post()
        except RadioMissing:
            self._json({"ok": False, "message": rig.message}, 503)

    def _get(self):
        if self.path == "/" or trial_page(self.path):
            PAGE = open(PAGE_PATH if self.path == "/" else trial_page(self.path), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)
        elif self.path == "/api/status":
            self._json(rig.status())
        elif self.path == "/api/presets":
            self._json(load_presets())
        elif self.path in ("/api/memories", "/api/memories?refresh=1"):
            global _mem_cache
            if _mem_cache.get("model") != rig.model or self.path.endswith("refresh=1"):
                _mem_cache = {"model": rig.model, "list": rig.memories()}
            self._json(_mem_cache["list"])
        elif self.path.startswith("/api/lookup?"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                self._json(lookup_with_distance(q.get("call", [""])[0], remember=q.get("quiet", ["0"])[0] != "1"))
            except OSError:
                self._json({"status": "OFFLINE"})
        elif self.path == "/api/config":
            drv = rig.drv
            self._json({"callsign": MYCALL, "grid": CONFIG.get("grid", ""), "version": VERSION,
                        "background": background_settings(),
                        "radio": drv.model if drv else "", "caps": drv.caps() if drv else None,
                        "trials": [k[1:] for k in TRIAL_PAGES if trial_page(k)], "needs_setup": needs_setup()})
        elif netlogcore and netlogcore.handle_get(self, self.path, CONFIG_DIR, MYCALL):
            pass
        elif icsforms and icsforms.handle_get(self, self.path, CONFIG_DIR):
            pass
        elif self.path == "/api/station":
            self._json(station_status())
        elif self.path == "/api/radio":
            self._json({"config": {k: CONFIG.get(k) for k in RADIO_KEYS},
                        "ports": radios.list_ports(),
                        "hamlib": bool(radios.find_rigctld(CONFIG.get("rigctld_path", ""))),
                        "connected": rig.drv.model if rig.drv else "", "message": rig.message})
        elif self.path == "/api/hamlib-models":
            global _hamlib_models
            if not _hamlib_models:
                _hamlib_models = radios.hamlib_models(CONFIG.get("rigctld_path", ""))
            self._json(_hamlib_models)
        elif self.path == "/api/lookups":
            self._json(load_lookups())
        elif self.path == "/api/settings":
            self._json(rig.read_settings())
        elif self.path == "/api/profiles":
            self._json(profiles_for_here())
        elif self.path.split("?")[0] == "/background":
            try:
                with open(BACKGROUND_FILE, "rb") as f:
                    img = f.read()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", image_type(img) or "application/octet-stream")
            self.send_header("Content-Length", str(len(img)))
            self.send_header("Cache-Control", "max-age=31536000")   # the page adds ?v=<version> when it changes
            self.end_headers()
            self.wfile.write(img)
        elif self.path == "/icon.svg":
            icon = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rigpanel.svg"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(icon)))
            self.end_headers()
            self.wfile.write(icon)
        else:
            self.send_error(404)

    def _post(self):
        # Only accept requests from this machine's own page
        origin = self.headers.get("Origin", "")
        if origin and origin not in (f"http://localhost:{LISTEN[1]}", f"http://127.0.0.1:{LISTEN[1]}"):
            self.send_error(403)
            return
        n = int(self.headers.get("Content-Length", 0) or 0)
        if self.path == "/api/background-photo":
            self._json(*save_background_photo(self.rfile.read(n) if 0 < n <= BACKGROUND_MAX else None, n))
            return
        if netlogcore and netlogcore.handle_raw_post(self, self.path, n, CONFIG_DIR):
            return
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self.send_error(400)
            return
        p = self.path
        if p == "/api/freq":
            rig.set_freq(body["hz"])
        elif p == "/api/mode":
            rig.set_mode(body["mode"])
        elif p == "/api/power":
            rig.set_power(body["watts"])
        elif p == "/api/squelch":
            rig.set_squelch(body["level"])
        elif p == "/api/tone":
            rig.set_tone(body.get("hz"))
        elif p == "/api/shift":
            rig.set_shift(body["shift"])
        elif p == "/api/volume":
            rig.set_volume(body["level"])
        elif p == "/api/setting":
            try:
                rig.write_setting(body["key"], body["value"])
            except (KeyError, ValueError):
                self.send_error(400)
                return
        elif p == "/api/recall":
            rig.recall(body["ch"])
        elif p == "/api/preset":
            rig.apply_preset(body)
        elif p == "/api/presets":
            save_presets(body)
        elif p == "/api/radio":
            try:
                changes = radio_settings(body)
            except (KeyError, ValueError, TypeError) as e:
                self._json({"ok": False, "message": str(e)}, 400)
                return
            if pc_ptt.keyed:
                pc_ptt.unkey("radio setup changed")
            save_config(changes)
            rig.search(wait=True)
            self._json({"ok": bool(rig.drv), "connected": rig.drv.model if rig.drv else "", "message": rig.message})
            return
        elif p == "/api/background":
            try:
                self._json({"ok": True, "background": save_background_settings(body)})
            except (ValueError, TypeError) as e:
                self._json({"ok": False, "message": str(e)}, 400)
            return
        elif netlogcore and netlogcore.handle_post(self, p, body, CONFIG_DIR):
            return
        elif icsforms and icsforms.handle_post(self, p, body, CONFIG_DIR):
            return
        elif p == "/api/station-setup":
            try:
                station_setup(body)
            except (OSError, ValueError) as e:
                self._json({"ok": False, "message": str(e)}, 400)
                return
        elif p == "/api/station/fix-audio":
            self._json(fix_vara_audio())
            return
        elif p == "/api/ptt":
            self._json(pc_ptt.unkey() if not body.get("on") else pc_ptt.hold() if body.get("hold") else pc_ptt.key())
            return
        else:
            self.send_error(404)
            return
        self._json({"ok": True})


# --- Hamlib rigctld-compatible server ---------------------------------------------------
# Lets other programs (VarAC, WSJT-X, fldigi, ...) control the radio through RigPanel with
# Hamlib model 2 "NET rigctl", so only RigPanel ever opens the CAT port.
# Our mode names <-> Hamlib's
HAMLIB_NAMES = {"CW-R": "CWR", "RTTY-R": "RTTYR", "DATA-LSB": "PKTLSB", "DATA-FM": "PKTFM", "DATA-USB": "PKTUSB",
                "FM-N": "FMN", "AM-N": "AMN", "DV": "DSTAR", "DATA-FM-N": "PKTFMN"}
OUR_NAMES = {v: k for k, v in HAMLIB_NAMES.items()}
PASSBAND = {"CW": 500, "CWR": 500, "RTTY": 500, "RTTYR": 500, "FM": 16000, "PKTFM": 16000,
            "C4FM": 16000, "DSTAR": 16000, "FMN": 9000, "AM": 9000, "AMN": 6000}
LONG_NAMES = {"get_freq": "f", "set_freq": "F", "get_mode": "m", "set_mode": "M",
              "get_ptt": "t", "set_ptt": "T", "get_vfo": "v", "set_vfo": "V",
              "get_split_vfo": "s", "set_split_vfo": "S", "get_level": "l", "set_level": "L",
              "vfo_op": "G", "get_powerstat": "get_powerstat", "chk_vfo": "chk_vfo",
              "dump_state": "dump_state", "quit": "q"}
DUMP_STATE = """1
1
0
30000.000000 470000000.000000 0x1ff -1 -1 0x3 0x3
0 0 0 0 0 0 0
1800000.000000 470000000.000000 0x1ff 5000 100000 0x3 0x3
0 0 0 0 0 0 0
0x1ff 1
0 0
0x1ff 3000
0x82 500
0x821 16000
0 0
9999
9999
0
0
10 20
0
0x40000020
0x40000020
0x0
0x0
0x0
0x0
done
"""
RPRT_OK, RPRT_EINVAL, RPRT_ENIMPL, RPRT_EIO = "RPRT 0\n", "RPRT -1\n", "RPRT -11\n", "RPRT -6\n"


def simplex_data():
    """VARA FM / packet (PKTFM) is always simplex with no tone: clear any repeater setup."""
    if "shift" in rig.features:
        rig.set_shift("simplex")
    if "tone" in rig.features:
        rig.set_tone(None)


def hamlib_command(line):
    """Run one rigctld command line; return (reply text, keep connection open)."""
    parts = line.split()
    if not parts:
        return "", True
    c, args = parts[0], parts[1:]
    if c.startswith("\\"):
        c = LONG_NAMES.get(c[1:], c)
    if c in ("q", "Q"):
        return "", False
    if c == "f":
        f = rig.get_freq()
        return (f"{f}\n" if f is not None else RPRT_EIO), True
    if c == "F":
        rig.set_freq(round(float(args[0])))
        # The radio's auto repeater shift can kick in on a new frequency; data stays simplex
        if rig.get_mode() == "DATA-FM":
            simplex_data()
        return RPRT_OK, True
    if c == "m":
        mode = rig.get_mode()
        if mode is None:
            return RPRT_EIO, True
        mode = HAMLIB_NAMES.get(mode, mode)
        return f"{mode}\n{PASSBAND.get(mode, 3000)}\n", True
    if c == "M":
        mode = OUR_NAMES.get(args[0].upper(), args[0].upper()) if args else ""
        if mode not in rig.caps()["modes"] and mode not in ("RTTY", "CW-R", "DATA-LSB", "FM-N", "AM-N", "RTTY-R"):
            return RPRT_EINVAL, True
        rig.set_mode(mode)
        if mode == "DATA-FM":
            simplex_data()
        return RPRT_OK, True
    if c == "t":
        tx = rig.get_ptt()
        return (f"{int(tx)}\n" if tx is not None else RPRT_EIO), True
    if c == "T":
        rig.set_ptt(bool(args) and args[0] != "0")
        return RPRT_OK, True
    if c == "v":
        return "VFOA\n", True
    if c in ("V", "S"):
        return RPRT_OK, True
    if c == "s":
        return "0\nVFOA\n", True
    if c == "l":
        name = args[0].upper() if args else ""
        if name == "RFPOWER":
            st = rig.status()
            return (f"{st['power'] / rig.power[1]:.2f}\n" if st.get("power") is not None else RPRT_EIO), True
        if name in ("STRENGTH", "RAWSTR"):
            db = rig.strength_db()
            if db is None:
                return RPRT_EIO, True
            return (f"{db}\n" if name == "STRENGTH" else f"{round(max(0, db + 54) / 114 * 255)}\n"), True
        return "0\n", True
    if c == "L":
        if len(args) == 2 and args[0].upper() == "RFPOWER":
            rig.set_power(float(args[1]) * rig.power[1])
        return RPRT_OK, True
    if c == "G":
        if args and args[0].upper() == "TUNE":
            rig.tune()
        return RPRT_OK, True
    if c == "get_powerstat":
        return "1\n", True
    if c == "chk_vfo":
        return "0\n", True
    if c == "dump_state":
        return DUMP_STATE, True
    return RPRT_ENIMPL, True


class HamlibHandler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            try:
                reply, keep = hamlib_command(raw.decode(errors="replace").strip())
            except (ValueError, IndexError):
                reply, keep = RPRT_EINVAL, True
            except RadioMissing:
                reply, keep = RPRT_EIO, True
            if reply:
                self.wfile.write(reply.encode())
            if not keep:
                break


class HamlibServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_hamlib():
    port = int(CONFIG.get("hamlib_port") or 0)
    if not port:
        return
    try:
        srv = HamlibServer(("127.0.0.1", port), HamlibHandler)
    except OSError as e:
        print(f"Hamlib server not started on port {port}: {e}", flush=True)
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def shutdown(*_):
    """Unkey and close the radio (and any rigctld RigPanel started) when RigPanel is stopped."""
    try:
        if pc_ptt.keyed:
            pc_ptt.unkey("RigPanel stopped")
        if rig.drv:
            rig.drv.close()
    finally:
        os._exit(0)


if __name__ == "__main__":
    import signal
    for sig in ("SIGTERM", "SIGINT", "SIGBREAK"):
        if hasattr(signal, sig):
            signal.signal(getattr(signal, sig), shutdown)
    rig.search()   # recover_ptt() runs once the radio is found
    threading.Thread(target=pc_ptt.watchdog, daemon=True).start()
    start_hamlib()
    threading.Thread(target=noaa_pick, daemon=True).start()   # look up the local NOAA transmitter in the background
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
