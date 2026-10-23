#!/usr/bin/env python3
"""Demo server for README screenshots: the real RigPanel page with made-up data (N0CALL, generic frequencies).
No radio needed and nothing is saved.  Usage: demo_server.py [port]   (default 8090)

Page options (query string): accent=signal|ocean|aurora|violet  mode=dark|light  bg=glow|plain|grid|waves|waterfall|topo|stars
                             glass=0-100 (see-through panels)  strength=0-100 (background pattern)
                             open=bg|radio|lh   (opens that dialog after loading; lh = the net log's Letterhead)
The net log page is at /net, with a sample net in progress (fictional N#CALL callsigns, which aren't valid US calls)."""
import datetime
import json
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
VERSION = re.search(r'^VERSION = "([^"]+)"', open(os.path.join(APP, "rigpanel.py")).read(), re.M).group(1)
BG = {"style": "glow", "strength": 60, "animate": False, "dim": 50, "blur": 0, "fit": "cover", "glass": 0, "v": 1, "photo": False}
CAPS = {"model": "FT-991A", "maker": "Yaesu", "family": "yaesu",
        "modes": ["FM", "DATA-FM", "FM-N", "C4FM", "USB", "LSB", "DATA-USB", "AM", "CW"], "power": [5, 100],
        "ranges": [[30000, 56000000], [144000000, 148000000], [430000000, 450000000]],
        "features": ["memories", "menus", "mic_auto", "shift", "squelch", "tone", "tuner", "volume"], "mic_hint": ""}
STATUS = {"ok": True, "freq": 146520000, "mode": "FM", "power": 25, "volume": 45, "squelch": 12, "smeter": 48.0,
          "s_label": "S7", "tx": False, "tone_mode": 0, "tone": None, "shift": "simplex", "pc_tx": False}
PRESETS = [{"name": "2m Calling", "freq": 146520000, "mode": "FM", "tone": None, "shift": "simplex"},
           {"name": "70cm Calling", "freq": 446000000, "mode": "FM", "tone": None, "shift": "simplex"},
           {"name": "6m Calling", "freq": 52525000, "mode": "FM", "tone": None, "shift": "simplex"}]
PROFILES = [{"name": "Winlink (VARA FM)", "icon": "✉", "freq": 145030000, "mode": "DATA-FM", "tone": None, "shift": "simplex", "squelch": 0, "power": 25},
            {"name": "VarAC 2m", "icon": "\U0001F4AC", "freq": 144950000, "mode": "DATA-FM", "tone": None, "shift": "simplex", "squelch": 0, "power": 25},
            {"name": "VarAC 70cm", "icon": "\U0001F4AC", "freq": 439600000, "mode": "DATA-FM", "tone": None, "shift": "simplex", "squelch": 0, "power": 25}]
MEMORIES = [{"ch": i + 1, "freq": f, "mode": m, "tone": t, "shift": sh, "name": n} for i, (f, m, t, sh, n) in enumerate([
    (146520000, "FM", False, "simplex", "2M CALL"), (144390000, "FM", False, "simplex", "APRS"),
    (146550000, "FM", False, "simplex", "SIMPLEX 1"), (146580000, "FM", False, "simplex", "SIMPLEX 2"),
    (147555000, "FM", False, "simplex", "SIMPLEX 3"), (146940000, "FM", True, "-", "LOCAL RPT"),
    (147180000, "FM", True, "+", "RPT 2"), (145800000, "FM", False, "simplex", "ISS VOICE"),
    (144200000, "USB", False, "simplex", "2M SSB"), (145030000, "DATA-FM", False, "simplex", "WINLINK"),
    (446000000, "FM", False, "simplex", "70CM CALL"), (446500000, "FM", False, "simplex", "70CM SPLX"),
    (444000000, "FM", True, "+", "UHF RPT"), (52525000, "FM", False, "simplex", "6M CALL"),
    (50125000, "USB", False, "simplex", "6M SSB"), (162400000, "FM", False, "simplex", "NOAA WX1"),
    (162550000, "FM", False, "simplex", "NOAA WX2"), (28400000, "USB", False, "simplex", "10M CALL")])]
STATION = {"checks": [{"id": "radio", "label": "Radio control", "state": "ok", "detail": "FT-991A"},
                      {"id": "card", "label": "Radio sound card", "state": "ok", "detail": "in and out"},
                      {"id": "vara", "label": "VARA", "state": "ok", "detail": "running"},
                      {"id": "vara-out", "label": "VARA → radio", "state": "ok", "detail": "radio sound card"},
                      {"id": "vara-in", "label": "VARA ← radio", "state": "ok", "detail": "radio sound card"}], "fixable": False}
PORTS = [{"path": "/dev/ttyUSB0", "label": "Silicon Labs CP2105 Dual USB to UART Bridge (Enhanced)"},
         {"path": "/dev/ttyUSB1", "label": "Silicon Labs CP2105 Dual USB to UART Bridge (Standard)"}]
RADIO = {"config": {"radio": "auto", "serial_port": "", "baud": 38400, "civ_address": "", "hamlib_model": 0, "hamlib_name": "",
                    "max_power": 100}, "ports": PORTS, "hamlib": True, "connected": "FT-991A", "message": ""}


LETTERHEAD = {"org": "Anytown Amateur Radio Club", "tagline": "ARES Net Control · Anytown County",
              "contact": "N0CALL · net@example.org", "accent": "#1d3f73", "style": "built", "has_logo": True, "has_banner": False}
CHECKINS = [("N1CALL", "Sample Operator", "Anytown, US", 3, "traffic"), ("N2CALL", "Alex Example", "Riverside, US", 12, ""),
            ("N3CALL", "Jordan Placeholder", "Lakeview, US", 8, "short"), ("N4CALL/M", "Casey Demo", "Mobile", None, "mobile"),
            ("N5CALL", "Pat Sample", "Hillcrest, US", 21, ""), ("N6CALL", "Riley Test", "Anytown, US", 2, "traffic"),
            ("N7CALL", "Morgan Fictional", "Fairview, US", 15, ""), ("N8CALL", "Taylor Mock", "Oakdale, US", 27, "")]


def demo_log():
    """A net that started 23 minutes ago, so the page shows it on the air."""
    start = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0) - datetime.timedelta(minutes=23)
    ents = []
    for i, (call, name, loc, mi, flag) in enumerate(CHECKINS):
        ents.append({"t": (start + datetime.timedelta(minutes=1 + i * 2)).isoformat().replace("+00:00", "Z"),
                     "call": call, "name": name, "loc": loc, "grid": "", "miles": mi,
                     "traffic": flag == "traffic", "short": flag == "short", "mobile": flag == "mobile", "ack": i < 5,
                     "notes": {0: "Weather report for the county", 2: "Leaving at 0130Z", 5: "Message for net manager"}.get(i, "")})
    return {"id": start.strftime("%Y%m%d-%H%M%S"), "name": "Anytown ARES Weekly Net", "ncs": "N0CALL",
            "freq": "146.520 MHz FM", "mode": "", "start": start.isoformat().replace("+00:00", "Z"), "end": None, "entries": ents}


PAST = [{"id": "20261015-010000", "name": "Anytown ARES Weekly Net", "start": "2026-10-15T01:00:00Z", "end": "2026-10-15T01:42:00Z", "count": 11},
        {"id": "20261008-010000", "name": "Anytown ARES Weekly Net", "start": "2026-10-08T01:00:00Z", "end": "2026-10-08T01:38:00Z", "count": 9},
        {"id": "20261004-150000", "name": "Simulated Emergency Test", "start": "2026-10-04T15:00:00Z", "end": "2026-10-04T18:05:00Z", "count": 23}]


def page(name, q):
    html = open(os.path.join(APP, name), encoding="utf-8").read()
    ls = "".join(f'localStorage.setItem("rp-{k}", {json.dumps(q[k])});' for k in ("accent", "mode") if q.get(k))
    html = html.replace("<head>", "<head>\n<script>try { localStorage.clear(); " + ls + " } catch {}</script>", 1)
    if q.get("open") in ("bg", "radio", "lh"):
        html = html.replace("</body>", f'<script>setTimeout(() => document.getElementById("open-{q["open"]}").click(), 900);</script>\n</body>', 1)
    return html.encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        p = u.path
        if p == "/":
            return self._send(page("index.html", q), "text/html; charset=utf-8")
        if p == "/net":
            return self._send(page("index-net.html", q), "text/html; charset=utf-8")
        if p == "/api/letterhead-logo":
            return self._send(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo-logo.jpg"), "rb").read(), "image/jpeg")
        if p == "/api/netlogs":
            log = demo_log()
            return self._send([{"id": log["id"], "name": log["name"], "start": log["start"], "end": None, "count": len(log["entries"])}] + PAST)
        if p == "/api/netlog":
            return self._send(demo_log())
        if p == "/icon.svg":
            return self._send(open(os.path.join(APP, "rigpanel.svg"), "rb").read(), "image/svg+xml")
        bg = dict(BG, style=self.headers.get("X-Bg") or BG["style"])
        ref = urllib.parse.parse_qs(urllib.parse.urlparse(self.headers.get("Referer", "")).query)
        if ref.get("bg"):
            bg["style"] = ref["bg"][0]
        for k in ("glass", "strength"):   # see-through panels / pattern strength, for the background screenshots
            if ref.get(k):
                bg[k] = int(ref[k][0])
        data = {"/api/status": STATUS, "/api/presets": PRESETS, "/api/profiles": PROFILES, "/api/memories": MEMORIES,
                "/api/lookups": [], "/api/station": STATION, "/api/letterhead": LETTERHEAD, "/api/radio": RADIO, "/api/hamlib-models": [],
                "/api/config": {"callsign": "N0CALL", "grid": "EM15", "version": VERSION, "background": bg,
                                "radio": "FT-991A", "caps": CAPS, "trials": ["net"]},
                "/api/lookup": {"call": q.get("call", "N0CALL"), "status": "VALID", "name": "Sample Operator", "type": "PERSON",
                                "cityState": "ANYTOWN, US", "grid": "EM15"}}.get(p)
        if data is None:
            self.send_error(404)
        else:
            self._send(data)

    def do_POST(self):   # accept and ignore: nothing is changed in the demo
        self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        self._send({"ok": True})


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f"RigPanel demo on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
