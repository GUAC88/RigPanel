#!/usr/bin/env python3
"""Net Log: a stand-alone net control logger (the same log page as RigPanel's Net log add-on, without a radio).

Serves http://localhost:8075 (change "http_port" in config.json). Python standard library only.
Settings and logs: ~/.config/netlog/ on Linux, %APPDATA%\\NetLog\\ on Windows."""
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # netlogcore / netexport sit next to this file
sys.dont_write_bytecode = True   # no __pycache__ folders in the install folder
import netlogcore  # noqa: E402

VERSION = "1.2.0"
HERE = os.path.dirname(os.path.abspath(__file__))
if os.name == "nt":
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "NetLog")
else:
    CONFIG_DIR = os.path.expanduser("~/.config/netlog")
CONFIG = {"callsign": "N0CALL", "grid": "", "http_port": 8075}
try:
    with open(os.path.join(CONFIG_DIR, "config.json")) as f:
        CONFIG.update(json.load(f))
except (OSError, ValueError):
    pass
CALL = str(CONFIG["callsign"]).upper()
PORT = int(CONFIG["http_port"])
CALLSIGN_RE = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z]$")


def station_setup(body):
    """Save the callsign and grid square from the first-run screen (the .msi installer asks no questions)."""
    global CALL
    call = str(body.get("callsign") or "").strip().upper()
    grid = str(body.get("grid") or "").strip()
    if not CALLSIGN_RE.match(call):
        raise ValueError(f"{call or 'That'} doesn't look like a callsign")
    if grid and not re.fullmatch(r"[A-Ra-r]{2}\d{2}([A-Xa-x]{2})?", grid):
        raise ValueError(f"{grid} isn't a grid square (e.g. EM26 or EM26av)")
    CONFIG.update(callsign=call, grid=grid)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(os.path.join(CONFIG_DIR, "config.json"), "w") as f:
        json.dump(CONFIG, f, indent=2)
    CALL = call


# --- callsign lookups (callook.info, FCC data, US calls) with distance from your grid square ---------------
def grid_center(grid):
    g = str(grid or "").strip()
    if len(g) < 4 or not g[:2].isalpha() or not g[2:4].isdigit():
        return None
    lon = (ord(g[0].upper()) - 65) * 20 - 180 + int(g[2]) * 2 + 1
    lat = (ord(g[1].upper()) - 65) * 10 - 90 + int(g[3]) + 0.5
    if len(g) >= 6 and g[4:6].isalpha():
        lon += (ord(g[4].lower()) - 97) * (2 / 24) + 1 / 24 - 1
        lat += (ord(g[5].lower()) - 97) * (1 / 24) + 1 / 48 - 0.5
    return lat, lon


def miles_between(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


_cache = {}


def lookup(call):
    call = "".join(c for c in str(call).upper() if c.isalnum())[:10]
    if not call:
        return {"status": "INVALID"}
    hit = _cache.get(call)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    req = urllib.request.Request(f"https://callook.info/{call}/json", headers={"User-Agent": f"NetLog/{VERSION} ({CALL})"})
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.load(r)
    if d.get("status") != "VALID":
        res = {"call": call, "status": d.get("status", "NOT FOUND")}
        _cache[call] = (time.time(), res)
        return res
    loc = d.get("location") or {}
    res = {"call": call, "status": "VALID", "name": (d.get("name") or "").strip(), "type": d.get("type", ""),
           # city/state only - the street address is deliberately left out
           "cityState": re.sub(r"\s+\d{5}(-\d{4})?$", "", (d.get("address") or {}).get("line2") or ""),
           "grid": loc.get("gridsquare") or ""}
    try:
        lat, lon = float(loc.get("latitude")), float(loc.get("longitude"))
        home = grid_center(CONFIG.get("grid"))
        if home and call != CALL:
            res["miles"] = round(miles_between(home, (lat, lon)), 1)
    except (TypeError, ValueError):
        pass
    _cache[call] = (time.time(), res)
    return res


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
        path = self.path
        if path in ("/", "/net"):
            with open(os.path.join(HERE, "index-net.html"), "rb") as f:
                self._file(f.read(), "text/html; charset=utf-8")
        elif path == "/icon.svg":
            with open(os.path.join(HERE, "netlog.svg"), "rb") as f:
                self._file(f.read(), "image/svg+xml")
        elif path == "/api/config":
            self._json({"callsign": CALL, "grid": CONFIG.get("grid", ""), "version": VERSION, "standalone": True,
                        "needs_setup": CALL == "N0CALL" or not CALLSIGN_RE.match(CALL)})
        elif path == "/api/status":
            self._json({"ok": False, "standalone": True})
        elif path.startswith("/api/lookup?"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
            try:
                self._json(lookup(q.get("call", [""])[0]))
            except (OSError, ValueError):
                self._json({"status": "OFFLINE"})
        elif not netlogcore.handle_get(self, path, CONFIG_DIR, CALL):
            self.send_error(404)

    def do_POST(self):
        # Only accept requests from this machine's own page
        origin = self.headers.get("Origin", "")
        if origin and origin not in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"):
            self.send_error(403)
            return
        n = int(self.headers.get("Content-Length", 0) or 0)
        if netlogcore.handle_raw_post(self, self.path, n, CONFIG_DIR):
            return
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self.send_error(400)
            return
        if self.path == "/api/station-setup":
            try:
                station_setup(body)
                self._json({"ok": True})
            except (OSError, ValueError) as e:
                self._json({"ok": False, "message": str(e)}, 400)
        elif not netlogcore.handle_post(self, self.path, body, CONFIG_DIR):
            self.send_error(404)


if __name__ == "__main__":
    print(f"Net Log {VERSION} for {CALL} on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
