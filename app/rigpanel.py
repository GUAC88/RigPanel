#!/usr/bin/env python3
"""RigPanel: a simple browser control panel for the Yaesu FT-991A over CAT.

Serves http://localhost:<port> (default 8073). Talks to the radio's Enhanced (CAT) USB port.
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
import urllib.parse
import urllib.request
try:
    import termios  # Linux / macOS
except ImportError:  # Windows
    termios = None
try:
    import serial  # pyserial: required on Windows, optional elsewhere
    import serial.tools.list_ports
except ImportError:
    serial = None
import threading
import time
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    cfg["callsign"] = str(cfg["callsign"]).upper()
    if not cfg["serial_port"]:
        cfg["serial_port"] = detect_cat_port() or ("COM3" if os.name == "nt" else "/dev/ttyUSB0")
    return cfg


def detect_cat_port():
    """Find the FT-991A's Enhanced (CAT) port of its CP2105 USB bridge."""
    if os.name == "nt":
        if serial is None:
            return None
        for p in serial.tools.list_ports.comports():
            if "enhanced" in (p.description or "").lower() and "cp210" in (p.description or "").lower():
                return p.device
        return None
    byid = "/dev/serial/by-id"
    try:
        ports = sorted(p for p in os.listdir(byid) if "CP210" in p and "if00" in p)
    except OSError:
        ports = []
    return os.path.join(byid, ports[0]) if ports else None


CONFIG = load_config()
PORT_PATH = CONFIG["serial_port"]
BAUD = int(CONFIG["baud"]) if int(CONFIG["baud"]) in (4800, 9600, 19200, 38400) else 38400
LISTEN = ("127.0.0.1", int(CONFIG["http_port"]))
PRESETS_FILE = os.path.join(CONFIG_DIR, "presets.json")
PROFILES_FILE = os.path.join(CONFIG_DIR, "profiles.json")

MODES = {"1": "LSB", "2": "USB", "3": "CW", "4": "FM", "5": "AM",
         "8": "DATA-LSB", "A": "DATA-FM", "B": "FM-N", "C": "DATA-USB",
         "E": "C4FM"}
MODE_CODES = {v: k for k, v in MODES.items()}
CTCSS = [67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8,
         97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3, 131.8,
         136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3,
         173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5, 203.5,
         206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1]

DEFAULT_PRESETS = [
    {"name": "2m Calling", "freq": 146520000, "mode": "FM", "tone": None, "shift": "simplex"},
    {"name": "70cm Calling", "freq": 446000000, "mode": "FM", "tone": None, "shift": "simplex"},
]


# Radio settings editor. Each entry: key, group, label, kind, read cmd, value slice, write template, options/range.
# Only settings whose CAT meaning has been verified on this radio are listed.
SETTINGS = [
    # Receive
    {"key": "AG", "group": "Receive", "label": "Volume (AF gain)", "read": "AG0;", "val": (3, -1), "write": "AG0{:03d};", "range": [0, 255]},
    {"key": "SQ", "group": "Receive", "label": "Squelch (0 = open)", "read": "SQ0;", "val": (3, -1), "write": "SQ0{:03d};", "range": [0, 100]},
    {"key": "RG", "group": "Receive", "label": "RF gain", "read": "RG0;", "val": (3, -1), "write": "RG0{:03d};", "range": [0, 255]},
    {"key": "PA", "group": "Receive", "label": "Preamp", "read": "PA0;", "val": (3, -1), "write": "PA0{};", "options": {"0": "IPO (off)", "1": "AMP 1", "2": "AMP 2"}},
    {"key": "NB", "group": "Receive", "label": "Noise blanker", "read": "NB0;", "val": (3, -1), "write": "NB0{};", "options": {"0": "Off", "1": "On"}},
    # Transmit
    {"key": "PC", "group": "Transmit", "label": "Power (W)", "read": "PC;", "val": (2, -1), "write": "PC{:03d};", "range": [5, 100]},
    {"key": "MG", "group": "Transmit", "label": "Mic gain", "read": "MG;", "val": (2, -1), "write": "MG{:03d};", "range": [0, 100]},
]
for x in SETTINGS:
    x["group"] = "Front panel - " + x["group"]

# Full MENU table (001-153) from Yaesu's FT-991A CAT reference, misprints corrected
MENUS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "menus.json")))
for m in MENUS:
    entry = {"key": f"EX{m['num']:03d}", "group": f"Menu - {m['group']}",
             "label": f"{m['num']:03d} {m['name']}", "read": f"EX{m['num']:03d};", "val": (5, -1),
             "digits": m["digits"], "desc": m["desc"]}
    for k in ("options", "range", "warn", "readonly", "step"):
        if k in m:
            entry[k] = m[k]
    SETTINGS.append(entry)
SETTINGS_BY_KEY = {x["key"]: x for x in SETTINGS}


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
    {"name": "FM Repeater 443.85", "icon": "\U0001F4E1", "freq": 443850000, "mode": "FM",
     "tone": 88.5, "shift": "+", "squelch": 20, "power": 25},
    {"name": "NOAA Weather", "icon": "\u26C5", "freq": 162550000, "mode": "FM",
     "tone": None, "shift": "simplex", "squelch": 20, "power": 5},
]


class SerialPort:
    """Minimal non-blocking serial port: termios on Linux/macOS (no dependencies), pyserial on Windows."""

    def __init__(self, path, baud):
        self.path, self.baud = path, baud
        self.fd = None   # termios backend
        self.ser = None  # pyserial backend

    @property
    def is_open(self):
        return self.fd is not None or self.ser is not None

    def open(self):
        if termios is not None:
            fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            a = termios.tcgetattr(fd)
            a[0] = 0
            a[1] = 0
            a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            a[3] = 0
            a[4] = a[5] = getattr(termios, f"B{self.baud}")
            termios.tcsetattr(fd, termios.TCSANOW, a)
            self.fd = fd
        elif serial is not None:
            self.ser = serial.Serial(self.path, self.baud, timeout=0, write_timeout=1)
        else:
            raise OSError("pyserial is not installed (pip install pyserial)")

    def close(self):
        try:
            if self.fd is not None:
                os.close(self.fd)
            if self.ser is not None:
                self.ser.close()
        except OSError:
            pass
        self.fd = self.ser = None

    def flush_input(self):
        if self.fd is not None:
            termios.tcflush(self.fd, termios.TCIFLUSH)
        else:
            self.ser.reset_input_buffer()

    def write(self, data):
        if self.fd is not None:
            os.write(self.fd, data)
        else:
            self.ser.write(data)

    def read(self):
        """Return whatever bytes are waiting (possibly none) without blocking."""
        if self.fd is not None:
            try:
                return os.read(self.fd, 128)
            except BlockingIOError:
                return b""
        return self.ser.read(128)


PORT_ERRORS = (OSError,) + ((termios.error,) if termios is not None else ())


class Rig:
    def __init__(self, path):
        self.port = SerialPort(path, BAUD)
        self.lock = threading.Lock()

    def _close(self):
        self.port.close()

    def cmd(self, c, reply=True):
        """Send one CAT command; return the reply for queries."""
        with self.lock:
            for attempt in range(2):
                try:
                    if not self.port.is_open:
                        self.port.open()
                    self.port.flush_input()
                    self.port.write(c.encode())
                    if not reply:
                        time.sleep(0.05)
                        return ""
                    buf = b""
                    deadline = time.time() + 0.6
                    while time.time() < deadline:
                        buf += self.port.read()
                        if buf.endswith(b";"):
                            break
                        time.sleep(0.02)
                    r = buf.decode(errors="replace")
                    if r.startswith(c[:2]):
                        return r
                except PORT_ERRORS:
                    # Port vanished (radio power-cycled or USB replugged): reopen next try
                    self._close()
            return ""

    def status(self):
        s = {"ok": False}
        fa = self.cmd("FA;")
        if not fa:
            return s
        s["ok"] = True
        s["freq"] = int(fa[2:-1])
        md = self.cmd("MD0;")
        s["mode"] = MODES.get(md[3:4], md[3:4]) if md else "?"
        pc = self.cmd("PC;")
        s["power"] = int(pc[2:-1]) if pc else None
        ag = self.cmd("AG0;")
        s["volume"] = int(ag[3:-1]) if ag else None
        sq = self.cmd("SQ0;")
        s["squelch"] = int(sq[3:-1]) if sq else None
        sm = self.cmd("SM0;")
        s["smeter"] = int(sm[3:-1]) if sm else 0
        tx = self.cmd("TX;")
        s["tx"] = bool(tx) and tx[2:3] != "0"
        ct = self.cmd("CT0;")
        s["tone_mode"] = int(ct[3:4]) if ct else 0
        cn = self.cmd("CN00;")
        try:
            s["tone"] = CTCSS[int(cn[4:-1])]
        except (ValueError, IndexError):
            s["tone"] = None
        os_ = self.cmd("OS0;")
        s["shift"] = {"0": "simplex", "1": "+", "2": "-"}.get(os_[3:4], "?") if os_ else "?"
        return s

    def set_freq(self, hz):
        hz = int(hz)
        self.cmd(f"FA{hz:09d};", reply=False)

    def set_mode(self, mode):
        code = MODE_CODES.get(mode)
        if code:
            self.cmd(f"MD0{code};", reply=False)

    def set_power(self, w):
        w = max(5, min(100, int(w)))
        self.cmd(f"PC{w:03d};", reply=False)

    def set_squelch(self, v):
        v = max(0, min(100, int(v)))
        self.cmd(f"SQ0{v:03d};", reply=False)

    def set_tone(self, hz):
        if hz in (None, "", "off", 0):
            self.cmd("CT00;", reply=False)
            return
        hz = float(hz)
        idx = min(range(len(CTCSS)), key=lambda i: abs(CTCSS[i] - hz))
        self.cmd(f"CN00{idx:03d};", reply=False)
        self.cmd("CT02;", reply=False)  # encode only (repeater access)

    def set_shift(self, shift):
        code = {"simplex": "0", "+": "1", "-": "2"}.get(shift)
        if code:
            self.cmd(f"OS0{code};", reply=False)

    def memories(self):
        """Read every filled memory channel (1-117) from the radio."""
        mems = []
        for ch in range(1, 118):
            r = self.cmd(f"MT{ch:03d};")
            # MT ccc fffffffff +cccc R X M V T 00 S 0 TAG(12) ;
            if not r.startswith("MT") or len(r) < 41:
                continue
            freq = int(r[5:14])
            if freq == 0:
                continue
            mems.append({
                "ch": ch,
                "freq": freq,
                "mode": MODES.get(r[21:22], r[21:22]),
                "tone": r[23:24] != "0",
                "shift": {"0": "simplex", "1": "+", "2": "-"}.get(r[26:27], "?"),
                "name": r[28:40].strip(),
            })
        return mems

    def read_settings(self):
        out = []
        for d in SETTINGS:
            r = self.cmd(d["read"])
            a, b = d["val"]
            v = r[a:b] if r else None
            item = {k: d[k] for k in ("key", "group", "label") if k in d}
            item.update({k: d[k] for k in ("options", "range", "warn", "readonly", "step", "desc") if k in d})
            if v in (None, ""):
                item["value"] = None
            elif "range" in d:
                try:
                    item["value"] = int(v)
                except ValueError:
                    item["value"] = v
            else:
                item["value"] = v
            out.append(item)
        return out

    def write_setting(self, key, value):
        d = SETTINGS_BY_KEY[key]
        if d.get("readonly"):
            raise ValueError("read-only")
        if key.startswith("EX"):
            n = d["digits"]
            if "options" in d:
                if str(value) not in d["options"]:
                    raise ValueError("invalid option")
                p2 = str(value)
            elif "range" in d:
                lo, hi = d["range"]
                v = max(lo, min(hi, int(value)))
                if d.get("step"):
                    v = round(v / d["step"]) * d["step"]
                p2 = f"{v:0{n}d}"
            else:
                # signed/free-form values: must match the radio's exact digit count, e.g. "+05", "-120"
                p2 = str(value).strip()
                if not re.fullmatch(r"[+-]?\d+", p2) or len(p2) != n:
                    raise ValueError("bad format")
            self.cmd(f"{key}{p2};", reply=False)
            return
        if "range" in d:
            lo, hi = d["range"]
            value = max(lo, min(hi, int(value)))
        elif str(value) not in d["options"]:
            raise ValueError("invalid option")
        self.cmd(d["write"].format(value), reply=False)

    def set_volume(self, v):
        v = max(0, min(255, int(v)))
        self.cmd(f"AG0{v:03d};", reply=False)

    def recall(self, ch):
        self.cmd(f"MC{int(ch):03d};", reply=False)

    def apply_preset(self, p):
        self.set_mode(p["mode"])
        self.set_freq(p["freq"])
        self.set_shift(p.get("shift", "simplex"))
        self.set_tone(p.get("tone"))
        if p.get("squelch") is not None:
            self.set_squelch(p["squelch"])
        if p.get("power") is not None:
            self.set_power(p["power"])


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


def lookup_with_distance(call):
    res = dict(callook(call))
    if res.get("status") == "VALID" and res.get("lat") is not None:
        me = my_location()
        if me and res["call"] != MYCALL:
            res["miles"], res["bearing"] = distance_bearing(me, res)
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


rig = Rig(PORT_PATH)
_mem_cache = []
PAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


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

    def do_GET(self):
        if self.path == "/":
            PAGE = open(PAGE_PATH, "rb").read()
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
            if not _mem_cache or self.path.endswith("refresh=1"):
                _mem_cache = rig.memories()
            self._json(_mem_cache)
        elif self.path.startswith("/api/lookup?"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                self._json(lookup_with_distance(q.get("call", [""])[0]))
            except OSError:
                self._json({"status": "OFFLINE"})
        elif self.path == "/api/config":
            self._json({"callsign": MYCALL, "grid": CONFIG.get("grid", ""), "radio": "FT-991A"})
        elif self.path == "/api/lookups":
            self._json(load_lookups())
        elif self.path == "/api/settings":
            self._json(rig.read_settings())
        elif self.path == "/api/profiles":
            self._json(load_profiles())
        elif self.path == "/icon.svg":
            icon = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rigpanel.svg"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(icon)))
            self.end_headers()
            self.wfile.write(icon)
        else:
            self.send_error(404)

    def do_POST(self):
        # Only accept requests from this machine's own page
        origin = self.headers.get("Origin", "")
        if origin and origin not in (f"http://localhost:{LISTEN[1]}", f"http://127.0.0.1:{LISTEN[1]}"):
            self.send_error(403)
            return
        n = int(self.headers.get("Content-Length", 0) or 0)
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
        else:
            self.send_error(404)
            return
        self._json({"ok": True})


# --- Hamlib rigctld-compatible server ---------------------------------------------------
# Lets other programs (VarAC, WSJT-X, fldigi, ...) control the radio through RigPanel with
# Hamlib model 2 "NET rigctl", so only RigPanel ever opens the CAT port.
HAMLIB_MODES = {"1": "LSB", "2": "USB", "3": "CW", "4": "FM", "5": "AM", "6": "RTTY",
                "7": "CWR", "8": "PKTLSB", "9": "RTTYR", "A": "PKTFM", "B": "FMN",
                "C": "PKTUSB", "D": "AMN", "E": "C4FM"}
HAMLIB_CODES = {v: k for k, v in HAMLIB_MODES.items()}
PASSBAND = {"CW": 500, "CWR": 500, "RTTY": 500, "RTTYR": 500, "FM": 16000, "PKTFM": 16000,
            "C4FM": 16000, "FMN": 9000, "AM": 9000, "AMN": 6000}
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
    rig.set_shift("simplex")
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
        fa = rig.cmd("FA;")
        return (f"{int(fa[2:-1])}\n" if fa else RPRT_EIO), True
    if c == "F":
        rig.set_freq(round(float(args[0])))
        # The radio's auto repeater shift can kick in on a new frequency; data stays simplex
        md = rig.cmd("MD0;")
        if md[3:4] == "A":
            simplex_data()
        return RPRT_OK, True
    if c == "m":
        md = rig.cmd("MD0;")
        if not md:
            return RPRT_EIO, True
        mode = HAMLIB_MODES.get(md[3:4], "USB")
        return f"{mode}\n{PASSBAND.get(mode, 3000)}\n", True
    if c == "M":
        code = HAMLIB_CODES.get(args[0].upper()) if args else None
        if not code:
            return RPRT_EINVAL, True
        rig.cmd(f"MD0{code};", reply=False)
        if code == "A":
            simplex_data()
        return RPRT_OK, True
    if c == "t":
        tx = rig.cmd("TX;")
        return (f"{int(bool(tx) and tx[2:3] != '0')}\n" if tx else RPRT_EIO), True
    if c == "T":
        rig.cmd("TX1;" if args and args[0] != "0" else "TX0;", reply=False)
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
            pc = rig.cmd("PC;")
            return (f"{int(pc[2:-1]) / 100:.2f}\n" if pc else RPRT_EIO), True
        if name in ("STRENGTH", "RAWSTR"):
            sm = rig.cmd("SM0;")
            raw = int(sm[3:-1]) if sm else 0
            # FT-991A meter: 0-255, S9 near 130; STRENGTH is dB relative to S9
            return (f"{raw}\n" if name == "RAWSTR" else f"{round((raw - 130) * 0.45)}\n"), True
        return "0\n", True
    if c == "L":
        if len(args) == 2 and args[0].upper() == "RFPOWER":
            rig.set_power(float(args[1]) * 100)
        return RPRT_OK, True
    if c == "G":
        if args and args[0].upper() == "TUNE":
            rig.cmd("AC002;", reply=False)  # start the antenna tuner
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


if __name__ == "__main__":
    start_hamlib()
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
