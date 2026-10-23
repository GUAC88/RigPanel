#!/usr/bin/env python3
"""Refresh app/nwr.json from NOAA's NOAA Weather Radio County Coverage Listing (public domain, US government data).

Source: https://www.weather.gov/source/nwr/JS/CCL.js, the data behind https://www.weather.gov/nwr/county_coverage
Writes  {"source", "updated", "tx": {callsign: [site, location, state, freq MHz, lat, lon, watts, status]},
         "counties": {SAME code: [callsigns serving that county]}}
Usage: tools/update-nwr.py [path/to/CCL.js]   (downloads it when no file is given)"""
import datetime
import json
import os
import re
import sys
import urllib.request

URL = "https://www.weather.gov/source/nwr/JS/CCL.js"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "nwr.json")

if len(sys.argv) > 1:
    text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
else:
    req = urllib.request.Request(URL, headers={"User-Agent": "RigPanel nwr updater"})
    text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")

rows = {}
for name, idx, val in re.findall(r'^(\w+)\[(\d+)\]\s*=\s*"(.*)";\s*$', text, re.M):
    rows.setdefault(int(idx), {})[name] = val.strip()

tx, counties = {}, {}
for r in rows.values():
    call, same = r.get("CALLSIGN", ""), r.get("SAME", "")
    try:
        freq, lat, lon = float(r["FREQ"]), float(r["LAT"]), float(r["LON"])
    except (KeyError, ValueError):
        continue
    if not call or not re.fullmatch(r"\d{6}", same) or not 162.39 < freq < 162.56:
        continue
    try:
        pwr = int(float(r.get("PWR") or 0))
    except ValueError:
        pwr = 0
    tx[call] = [r.get("SITENAME", ""), r.get("SITELOC", ""), r.get("SITESTATE", ""), round(freq, 3),
                round(lat, 4), round(lon, 4), pwr, r.get("STATUS", "")]
    counties.setdefault(same, [])
    if call not in counties[same]:
        counties[same].append(call)

if len(tx) < 500:
    sys.exit(f"Only {len(tx)} transmitters found; NOAA's file format may have changed. Not writing {OUT}.")
data = {"source": "NOAA Weather Radio County Coverage Listing, " + URL,
        "updated": datetime.date.today().isoformat(), "tx": tx, "counties": counties}
with open(OUT, "w") as f:
    json.dump(data, f, separators=(",", ":"))
print(f"{len(tx)} transmitters, {len(counties)} counties -> {os.path.normpath(OUT)} ({os.path.getsize(OUT) // 1024} KB)")
