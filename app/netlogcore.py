"""Net log: storage and web API, shared by RigPanel's Net log add-on and the standalone Net Log app.

Logs are JSON files in <config>/netlogs/. The letterhead, logo and banner live in the config folder and are
used by the PDF and Word exports (netexport.py)."""
import json
import os
import re
import urllib.parse

import netexport

NETLOG_ID = re.compile(r"^\d{8}-\d{6}$")


class Store:
    def __init__(self, config_dir):
        self.config_dir = config_dir
        self.dir = os.path.join(config_dir, "netlogs")

    def path(self, log_id):
        if not NETLOG_ID.match(str(log_id or "")):
            raise ValueError("bad net log id")
        return os.path.join(self.dir, log_id + ".json")

    def list(self):
        out = []
        try:
            names = sorted(os.listdir(self.dir), reverse=True)
        except OSError:
            return out
        for n in names:
            if n.endswith(".json") and NETLOG_ID.match(n[:-5]):
                try:
                    with open(os.path.join(self.dir, n)) as f:
                        d = json.load(f)
                    out.append({"id": n[:-5], "name": d.get("name", ""), "start": d.get("start"), "end": d.get("end"),
                                "count": len(d.get("entries") or [])})
                except (OSError, ValueError):
                    pass
        return out

    def load(self, log_id):
        with open(self.path(log_id)) as f:
            return json.load(f)

    def save(self, log):
        path = self.path(log.get("id"))
        os.makedirs(self.dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(log, f, indent=1)
        os.replace(tmp, path)   # never leave a half-written log

    def delete(self, log_id):
        os.remove(self.path(log_id))


def handle_get(h, path, config_dir, callsign):
    """Serve a net log GET request on handler `h` (needs _json, _file, send_error). True if it was ours."""
    store = Store(config_dir)
    route = path.split("?")[0]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    if route == "/api/netlogs":
        h._json(store.list())
    elif route == "/api/netlog":
        try:
            h._json(store.load(q.get("id", [""])[0]))
        except (OSError, ValueError):
            h._json({"error": "not found"}, 404)
    elif route == "/api/letterhead":
        h._json(netexport.load_letterhead(config_dir, callsign))
    elif route in ("/api/letterhead-logo", "/api/letterhead-banner"):
        img = netexport.read_image(config_dir, "logo" if route.endswith("logo") else "banner")
        h._file(img, "image/jpeg") if img else h.send_error(404)
    elif route == "/api/netlog-export":
        fmt = q.get("fmt", [""])[0]
        try:
            log = store.load(q.get("id", [""])[0])
        except (OSError, ValueError):
            h.send_error(404)
            return True
        lh = netexport.load_letterhead(config_dir, callsign)
        imgs = {"logo": netexport.read_image(config_dir, "logo"), "banner": netexport.read_image(config_dir, "banner")}
        if fmt == "pdf":
            h._file(netexport.build_pdf(log, lh, imgs), "application/pdf", netexport.filename(log, "pdf"))
        elif fmt == "docx":
            h._file(netexport.build_docx(log, lh, imgs),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", netexport.filename(log, "docx"))
        else:
            h.send_error(400)
    else:
        return False
    return True


def handle_raw_post(h, path, n, config_dir):
    """Image uploads (the page sends JPEG bytes, not JSON). True if it was ours."""
    kind = {"/api/letterhead-logo": "logo", "/api/letterhead-banner": "banner"}.get(path)
    if not kind:
        return False
    limit = netexport.IMAGE_MAX[kind]
    try:
        netexport.save_image(config_dir, kind, h.rfile.read(n) if 0 < n <= limit else None)
        h._json({"ok": True})
    except (OSError, ValueError) as e:
        h._json({"ok": False, "message": str(e)}, 400)
    return True


def handle_post(h, path, body, config_dir):
    """JSON POSTs. True if it was ours (the response has been sent)."""
    store = Store(config_dir)
    try:
        if path == "/api/netlog":
            store.save(body.get("log") or {})
        elif path == "/api/netlog/delete":
            store.delete(body.get("id"))
        elif path == "/api/letterhead":
            netexport.save_letterhead(config_dir, body)
        else:
            return False
    except (OSError, ValueError) as e:
        h._json({"ok": False, "message": str(e)}, 400)
        return True
    h._json({"ok": True})
    return True
