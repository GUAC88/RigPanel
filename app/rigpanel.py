#!/usr/bin/env python3
"""RigPanel: a simple browser control panel for the Yaesu FT-991A over CAT.

Serves http://localhost:<port> (default 8073). Talks to the radio's Enhanced (CAT) USB port.
Per-station settings live in ~/.config/rigpanel/config.json (written by the installer).
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


if __name__ == "__main__":
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
