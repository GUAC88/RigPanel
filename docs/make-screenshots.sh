#!/usr/bin/env bash
# Regenerate docs/screenshots/*.png from the demo server (made-up data: N0CALL, generic frequencies).
# Needs: google-chrome (or chromium), pdftoppm (poppler) for the PDF preview.
set -euo pipefail
cd "$(dirname "$0")"
PORT=8090
OUT="$PWD/screenshots"
CHROME=$(command -v google-chrome-stable || command -v google-chrome || command -v chromium || true)
[ -n "$CHROME" ] || { echo "Chrome or Chromium is needed"; exit 1; }
TMP=$(mktemp -d); trap 'kill $SRV 2>/dev/null; rm -rf "$TMP"' EXIT
python3 demo_server.py $PORT >/dev/null 2>&1 & SRV=$!
for i in $(seq 1 20); do curl -s -o /dev/null "http://localhost:$PORT/" && break; sleep 0.25; done

shot() {  # shot NAME WIDTH HEIGHT PATH
  rm -rf "$TMP/profile"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$TMP/profile" --window-size="$2,$3" \
    --virtual-time-budget=6000 --screenshot="$OUT/$1.png" "http://localhost:$PORT$4" >/dev/null 2>&1
  echo "  $1.png"
}
shot main-dark          1440 900 "/?accent=signal&mode=dark"
shot main-light         1440 900 "/?accent=ocean&mode=light"
shot background-grid    1440 900 "/?accent=signal&mode=dark&bg=grid&glass=55&strength=90"
shot background-waves   1440 900 "/?accent=violet&mode=dark&bg=waves&glass=55&strength=90"
shot background-picker  1440 900 "/?accent=signal&mode=dark&open=bg"
shot radio-setup        1440 900 "/?accent=signal&mode=dark&open=radio"
shot phone               390 844 "/?accent=signal&mode=dark"
shot netlog             1440 900 "/net?accent=signal&mode=dark"
shot netlog-letterhead  1440 900 "/net?accent=ocean&mode=light&open=lh"

# A page of the PDF export, made with the app's own exporter from the demo net
python3 - "$TMP/netlog.pdf" <<'PY'
import sys, os
sys.path.insert(0, "../app"); sys.path.insert(0, ".")
import datetime, netexport, demo_server
log = demo_server.demo_log()   # shown as a finished 47-minute net
start = datetime.datetime.fromisoformat(log["start"].replace("Z", "+00:00"))
log["end"] = (start + datetime.timedelta(minutes=47)).isoformat().replace("+00:00", "Z")
lh = dict(demo_server.LETTERHEAD)
open(sys.argv[1], "wb").write(netexport.build_pdf(log, lh, {"logo": open("demo-logo.jpg", "rb").read()}))
PY
pdftoppm -r 110 -png -f 1 -l 1 -singlefile "$TMP/netlog.pdf" "$OUT/netlog-pdf"
echo "  netlog-pdf.png"
