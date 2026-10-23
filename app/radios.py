"""Radio drivers for RigPanel.

Every driver offers the same small set of operations (frequency, mode, PTT, levels, tone, shift...) so
the panel and the Hamlib server don't need to know which radio is connected:

  Yaesu   native CAT for the FT-991A family (FT-991A, FT-991, FT-891, FT-710, FTDX10, FTDX101 ...)
  Icom    native CI-V (IC-7300, IC-705, IC-9700, IC-7610, IC-7100 ...)
  Hamlib  any other radio, through Hamlib's rigctld (must be installed separately)

Copyright (C) 2026 Cody KJ5JDO. GPL-3.0-or-later; see LICENSE.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
try:
    import termios  # Linux / macOS
except ImportError:  # Windows
    termios = None
try:
    import serial  # pyserial: required on Windows, optional elsewhere
    import serial.tools.list_ports
except ImportError:
    serial = None

HERE = os.path.dirname(os.path.abspath(__file__))

CTCSS = [67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8,
         97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3, 131.8,
         136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9, 171.3,
         173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5, 203.5,
         206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1]

HF = (30_000, 56_000_000)
HF6_2_70 = [(30_000, 56_000_000), (144_000_000, 148_000_000), (430_000_000, 450_000_000)]


# --- Serial port ---------------------------------------------------------------------------
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
            try:
                a = termios.tcgetattr(fd)
                a[0] = 0
                a[1] = 0
                a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
                a[3] = 0
                a[4] = a[5] = getattr(termios, f"B{self.baud}")
                termios.tcsetattr(fd, termios.TCSANOW, a)
            except (termios.error, AttributeError):
                os.close(fd)
                raise OSError(f"can't set up {self.path} at {self.baud} baud")
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
                return os.read(self.fd, 256)
            except BlockingIOError:
                return b""
        return self.ser.read(256)


PORT_ERRORS = (OSError,) + ((termios.error,) if termios is not None else ())
if serial is not None:
    PORT_ERRORS += (serial.SerialException,)


def list_ports():
    """Serial ports that could be a radio, most likely first: [{"path", "label"}]."""
    out = []
    if os.name == "nt":
        if serial is not None:
            for p in serial.tools.list_ports.comports():
                out.append({"path": p.device, "label": f"{p.device}  {p.description or ''}".strip()})
    else:
        byid = "/dev/serial/by-id"
        try:
            for name in sorted(os.listdir(byid)):
                out.append({"path": os.path.join(byid, name), "label": name.replace("usb-", "").replace("_", " ")})
        except OSError:
            pass
        seen = {os.path.realpath(p["path"]) for p in out}
        for name in sorted(os.listdir("/dev")):
            if re.fullmatch(r"tty(USB|ACM)\d+", name) and os.path.realpath("/dev/" + name) not in seen:
                out.append({"path": "/dev/" + name, "label": name})
    likely = lambda p: 0 if re.search(r"cp210|icom|ic-\d|yaesu|ft-?\d|enhanced", p["label"], re.I) else 1
    return sorted(out, key=likely)


def s_meter(db):
    """dB relative to S9 -> (bar 0-100, label like 'S7' or 'S9+20')."""
    if db is None:
        return 0, ""
    bar = max(0, min(100, (db + 54) / 114 * 100))
    label = f"S{max(0, min(9, round(9 + db / 6)))}" if db < 3 else f"S9+{round(db / 10) * 10}"
    return round(bar, 1), label


# Receive-only coverage beyond the transmit bands (manufacturers' specs), e.g. airband and NOAA weather radio
RECEIVE_EXTRA = {
    "FT-991A": [(118_000_000, 164_000_000), (420_000_000, 470_000_000)],
    "FT-991": [(118_000_000, 164_000_000), (420_000_000, 470_000_000)],
    "IC-7100": [(30_000, 199_999_999), (400_000_000, 470_000_000)],
    "IC-705": [(30_000, 199_999_999), (400_000_000, 470_000_000)],
    "IC-7000": [(30_000, 199_999_999), (400_000_000, 470_000_000)],
    "IC-9100": [(136_000_000, 174_000_000)],
}


# --- Driver interface ------------------------------------------------------------------------
class Radio:
    """Base class. Values: power in watts, volume and squelch 0-100 %, tone in Hz (None = off)."""
    family = "radio"
    maker = ""
    model = "Radio"
    buttons = ["USB", "LSB", "CW", "AM", "FM", "DATA-USB", "DATA-LSB", "DATA-FM"]
    power = (5, 100)
    ranges = [HF]
    features = set()       # memories menus tone shift squelch volume tuner mic_auto
    mic_hint = ""

    def caps(self):
        rx = list(self.ranges) + RECEIVE_EXTRA.get(self.model, [])
        return {"model": self.model, "maker": self.maker, "family": self.family, "modes": self.buttons, "power": list(self.power),
                "ranges": [list(r) for r in self.ranges], "rx_ranges": [list(r) for r in rx],
                "features": sorted(self.features), "mic_hint": self.mic_hint}

    def close(self):
        pass

    # Every driver implements these
    def get_freq(self): raise NotImplementedError
    def set_freq(self, hz): raise NotImplementedError
    def get_mode(self): raise NotImplementedError
    def set_mode(self, mode): raise NotImplementedError
    def get_ptt(self): raise NotImplementedError
    def set_ptt(self, on): raise NotImplementedError
    def status(self): raise NotImplementedError

    # Optional
    def set_power(self, watts): pass
    def set_volume(self, pct): pass
    def set_squelch(self, pct): pass
    def set_tone(self, hz): pass
    def set_shift(self, shift): pass
    def tune(self): pass
    def strength_db(self): return None
    def memories(self): return []
    def recall(self, ch): pass
    def read_settings(self): return []
    def write_setting(self, key, value): raise ValueError("no settings editor for this radio")
    def read_setting(self, key): return None
    def mic_usb_menus(self, mode):
        """Menus that switch the mic input to USB for this mode: [(key, value)], [] = nothing to switch,
        or None = the PC mic can't be used in this mode."""
        return []

    def apply_preset(self, p):
        self.set_mode(p["mode"])
        self.set_freq(p["freq"])
        if "shift" in self.features:
            self.set_shift(p.get("shift", "simplex"))
        if "tone" in self.features:
            self.set_tone(p.get("tone"))
        if p.get("squelch") is not None:
            self.set_squelch(p["squelch"])
        if p.get("power") is not None:
            self.set_power(p["power"])


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# --- Yaesu (FT-991A family, "new CAT") --------------------------------------------------------
YAESU_MODES = {"1": "LSB", "2": "USB", "3": "CW", "4": "FM", "5": "AM", "6": "RTTY", "7": "CW-R", "8": "DATA-LSB",
               "9": "RTTY-R", "A": "DATA-FM", "B": "FM-N", "C": "DATA-USB", "D": "AM-N"}
YAESU_HF_BUTTONS = ["USB", "LSB", "CW", "CW-R", "AM", "FM", "DATA-USB", "DATA-LSB", "RTTY"]
# ID; reply -> (model, extra mode codes, mode buttons, power range, frequency ranges, extra features)
YAESU_MODELS = {
    "0670": ("FT-991A", {"E": "C4FM"}, ["FM", "DATA-FM", "FM-N", "C4FM", "USB", "LSB", "DATA-USB", "AM", "CW"],
             (5, 100), HF6_2_70, {"memories", "menus", "mic_auto"}),
    "0570": ("FT-991", {"E": "C4FM"}, ["FM", "DATA-FM", "FM-N", "C4FM", "USB", "LSB", "DATA-USB", "AM", "CW"],
             (5, 100), HF6_2_70, {"memories"}),
    "0650": ("FT-891", {}, YAESU_HF_BUTTONS, (5, 100), [HF], set()),
    "0800": ("FT-710", {"E": "PSK", "F": "DATA-FM-N"}, YAESU_HF_BUTTONS, (5, 100), [HF], set()),
    "0761": ("FTDX10", {"E": "PSK", "F": "DATA-FM-N"}, YAESU_HF_BUTTONS, (5, 100), [(30_000, 74_800_000)], set()),
    "0681": ("FTDX101D", {"E": "PSK", "F": "DATA-FM-N"}, YAESU_HF_BUTTONS, (5, 100), [(30_000, 74_800_000)], set()),
    "0682": ("FTDX101MP", {"E": "PSK", "F": "DATA-FM-N"}, YAESU_HF_BUTTONS, (5, 200), [(30_000, 74_800_000)], set()),
    "0462": ("FT DX 3000", {}, YAESU_HF_BUTTONS, (5, 100), [HF], set()),
    "0583": ("FT DX 1200", {}, YAESU_HF_BUTTONS, (5, 100), [HF], set()),
    "0362": ("FT DX 5000", {}, YAESU_HF_BUTTONS, (5, 200), [HF], set()),
}

# FT-991A radio settings editor: front-panel items plus the full MENU table (001-153) from Yaesu's
# CAT reference, misprints corrected. Only settings whose CAT meaning has been verified are listed.
SETTINGS = [
    {"key": "AG", "group": "Receive", "label": "Volume (AF gain)", "read": "AG0;", "val": (3, -1), "write": "AG0{:03d};", "range": [0, 255]},
    {"key": "SQ", "group": "Receive", "label": "Squelch (0 = open)", "read": "SQ0;", "val": (3, -1), "write": "SQ0{:03d};", "range": [0, 100]},
    {"key": "RG", "group": "Receive", "label": "RF gain", "read": "RG0;", "val": (3, -1), "write": "RG0{:03d};", "range": [0, 255]},
    {"key": "PA", "group": "Receive", "label": "Preamp", "read": "PA0;", "val": (3, -1), "write": "PA0{};", "options": {"0": "IPO (off)", "1": "AMP 1", "2": "AMP 2"}},
    {"key": "NB", "group": "Receive", "label": "Noise blanker", "read": "NB0;", "val": (3, -1), "write": "NB0{};", "options": {"0": "Off", "1": "On"}},
    {"key": "PC", "group": "Transmit", "label": "Power (W)", "read": "PC;", "val": (2, -1), "write": "PC{:03d};", "range": [5, 100]},
    {"key": "MG", "group": "Transmit", "label": "Mic gain", "read": "MG;", "val": (2, -1), "write": "MG{:03d};", "range": [0, 100]},
]
for x in SETTINGS:
    x["group"] = "Front panel - " + x["group"]
for m in json.load(open(os.path.join(HERE, "menus.json"))):
    entry = {"key": f"EX{m['num']:03d}", "group": f"Menu - {m['group']}",
             "label": f"{m['num']:03d} {m['name']}", "read": f"EX{m['num']:03d};", "val": (5, -1),
             "digits": m["digits"], "desc": m["desc"]}
    for k in ("options", "range", "warn", "readonly", "step"):
        if k in m:
            entry[k] = m[k]
    SETTINGS.append(entry)
SETTINGS_BY_KEY = {x["key"]: x for x in SETTINGS}

# FT-991A: switch the mic input from the front MIC jack to the rear/USB input, per mode
FT991A_MIC_MENUS = {
    "FM": [("EX074", "1"), ("EX077", "1")], "FM-N": [("EX074", "1"), ("EX077", "1")],
    "USB": [("EX106", "1"), ("EX109", "1")], "LSB": [("EX106", "1"), ("EX109", "1")],
    "AM": [("EX045", "1"), ("EX048", "1")],
    "DATA-FM": [("EX077", "1")], "DATA-USB": [("EX070", "1"), ("EX072", "1")],
    "DATA-LSB": [("EX070", "1"), ("EX072", "1")],
}


class Yaesu(Radio):
    family = "yaesu"
    maker = "Yaesu"

    def __init__(self, path, baud, ident="0670"):
        self.port = SerialPort(path, baud)
        self.lock = threading.Lock()
        self.ident = ident
        model, extra, buttons, power, ranges, feats = YAESU_MODELS.get(
            ident, (f"Yaesu (ID {ident})", {}, YAESU_HF_BUTTONS, (5, 100), [HF], set()))
        self.model, self.buttons, self.power, self.ranges = model, buttons, power, ranges
        self.modes = dict(YAESU_MODES, **extra)
        self.codes = {v: k for k, v in self.modes.items()}
        self.features = {"tone", "shift", "squelch", "volume", "tuner"} | feats
        if "mic_auto" not in self.features:
            self.mic_hint = (f"On the {model}, set the radio's mod source for the mode you use (SSB / AM / FM / DATA) to "
                             "REAR or USB in its menu, or the PC mic won't be heard.")

    @classmethod
    def probe(cls, path, baud):
        """Return a driver if a Yaesu answers ID; on this port at this baud, else None."""
        d = cls(path, baud)
        try:
            r = d.cmd("ID;", tries=1)
        finally:
            d.close()
        m = re.fullmatch(r"ID(\d{4});", r)
        return cls(path, baud, m.group(1)) if m else None

    def close(self):
        self.port.close()

    def cmd(self, c, reply=True, tries=2):
        """Send one CAT command; return the reply for queries."""
        with self.lock:
            for attempt in range(tries):
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
                    self.port.close()
            return ""

    def get_freq(self):
        fa = self.cmd("FA;")
        return int(fa[2:-1]) if fa else None

    def set_freq(self, hz):
        self.cmd(f"FA{int(hz):09d};", reply=False)

    def get_mode(self):
        md = self.cmd("MD0;")
        return self.modes.get(md[3:4], md[3:4]) if md else None

    def set_mode(self, mode):
        code = self.codes.get(mode)
        if code:
            self.cmd(f"MD0{code};", reply=False)

    def get_ptt(self):
        tx = self.cmd("TX;")
        return (bool(tx) and tx[2:3] != "0") if tx else None

    def set_ptt(self, on):
        self.cmd("TX1;" if on else "TX0;", reply=False)

    def set_power(self, w):
        self.cmd(f"PC{clamp(int(w), *self.power):03d};", reply=False)

    def set_volume(self, pct):
        self.cmd(f"AG0{clamp(round(float(pct) * 2.55), 0, 255):03d};", reply=False)

    def set_squelch(self, pct):
        self.cmd(f"SQ0{clamp(int(pct), 0, 100):03d};", reply=False)

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

    def tune(self):
        self.cmd("AC002;", reply=False)  # start the antenna tuner

    def raw_smeter(self):
        sm = self.cmd("SM0;")
        return int(sm[3:-1]) if sm else None

    def strength_db(self, raw=None):
        raw = self.raw_smeter() if raw is None else raw
        if raw is None:
            return None
        # Meter 0-255: S9 near 130, S9+60 at 255
        return round((raw - 130) * (54 / 130 if raw < 130 else 60 / 125))

    def status(self):
        s = {"ok": False}
        f = self.get_freq()
        if f is None:
            return s
        s.update(ok=True, freq=f, mode=self.get_mode() or "?")
        pc = self.cmd("PC;")
        s["power"] = int(pc[2:-1]) if pc else None
        ag = self.cmd("AG0;")
        s["volume"] = round(int(ag[3:-1]) / 2.55) if ag else None
        sq = self.cmd("SQ0;")
        s["squelch"] = int(sq[3:-1]) if sq else None
        s["smeter"], s["s_label"] = s_meter(self.strength_db(self.raw_smeter() or 0))
        s["tx"] = bool(self.get_ptt())
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

    def memories(self):
        """Read every filled memory channel (1-117) from the radio (FT-991 / FT-991A format)."""
        if "memories" not in self.features:
            return []
        mems = []
        for ch in range(1, 118):
            r = self.cmd(f"MT{ch:03d};")
            # MT ccc fffffffff +cccc R X M V T 00 S 0 TAG(12) ;
            if not r.startswith("MT") or len(r) < 41:
                continue
            freq = int(r[5:14])
            if freq == 0:
                continue
            mems.append({"ch": ch, "freq": freq, "mode": self.modes.get(r[21:22], r[21:22]),
                         "tone": r[23:24] != "0", "shift": {"0": "simplex", "1": "+", "2": "-"}.get(r[26:27], "?"),
                         "name": r[28:40].strip()})
        return mems

    def recall(self, ch):
        if "memories" in self.features:
            self.cmd(f"MC{int(ch):03d};", reply=False)

    def read_settings(self):
        if "menus" not in self.features:
            return []
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

    def read_setting(self, key):
        d = SETTINGS_BY_KEY[key]
        r = self.cmd(d["read"])
        a, b = d["val"]
        return r[a:b] if r else None

    def write_setting(self, key, value):
        if "menus" not in self.features:
            raise ValueError("no settings editor for this radio")
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
                v = clamp(int(value), lo, hi)
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
            value = clamp(int(value), lo, hi)
        elif str(value) not in d["options"]:
            raise ValueError("invalid option")
        self.cmd(d["write"].format(value), reply=False)

    def mic_usb_menus(self, mode):
        if "mic_auto" not in self.features:
            return [] if mode not in ("CW", "CW-R", "C4FM") else None
        return FT991A_MIC_MENUS.get(mode)


# --- Icom CI-V -------------------------------------------------------------------------------
ICOM_MODELS = {   # default CI-V address -> (model, max watts, frequency ranges, mode buttons)
    0x94: ("IC-7300", 100, [(30_000, 74_800_000)], None),
    0xA4: ("IC-705", 10, HF6_2_70, ["FM", "DATA-FM", "USB", "LSB", "DATA-USB", "AM", "CW", "DV"]),
    0xA2: ("IC-9700", 100, [(144_000_000, 148_000_000), (430_000_000, 450_000_000), (1_240_000_000, 1_300_000_000)],
           ["FM", "DATA-FM", "USB", "LSB", "DATA-USB", "CW", "DV"]),
    0x98: ("IC-7610", 100, [(30_000, 60_000_000)], None),
    0x88: ("IC-7100", 100, HF6_2_70, ["FM", "DATA-FM", "USB", "LSB", "DATA-USB", "AM", "CW", "DV"]),
    0x80: ("IC-7410", 100, [(30_000, 60_000_000)], None),
    0x7C: ("IC-9100", 100, HF6_2_70 + [(1_240_000_000, 1_300_000_000)], ["FM", "DATA-FM", "USB", "LSB", "DATA-USB", "AM", "CW", "DV"]),
    0x8E: ("IC-7851", 200, [(30_000, 60_000_000)], None),
    0x76: ("IC-7200", 100, [(30_000, 60_000_000)], None),
    0x70: ("IC-7000", 100, HF6_2_70, ["FM", "USB", "LSB", "AM", "CW"]),
    0xAC: ("IC-905", 10, [(144_000_000, 148_000_000), (430_000_000, 450_000_000), (1_240_000_000, 1_300_000_000)],
           ["FM", "DATA-FM", "USB", "LSB", "DATA-USB", "CW", "DV"]),
}
ICOM_MODES = {0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY", 0x05: "FM", 0x06: "WFM",
              0x07: "CW-R", 0x08: "RTTY-R", 0x17: "DV"}
ICOM_CODES = {v: k for k, v in ICOM_MODES.items()}
CTRL = 0xE0   # RigPanel's own CI-V address (the usual "controller" address)


def to_bcd(n, nbytes):
    """Little-endian packed BCD (frequency format)."""
    digits = f"{int(n):0{nbytes * 2}d}"[-nbytes * 2:]
    return bytes(int(digits[i:i + 2], 16) for i in range(len(digits) - 2, -1, -2))


def from_bcd(b):
    return int("".join(f"{x:02X}" for x in reversed(b)))


def bcd_level(v):
    """0-255 level -> 2-byte big-endian BCD, e.g. 128 -> 01 28."""
    s = f"{int(v):04d}"
    return bytes([int(s[:2], 16), int(s[2:], 16)])


def level_val(b):
    return int(f"{b[0]:02X}{b[1]:02X}")


class Icom(Radio):
    family = "icom"
    maker = "Icom"
    buttons = ["USB", "LSB", "CW", "CW-R", "AM", "FM", "DATA-USB", "DATA-LSB", "RTTY"]

    def __init__(self, path, baud, addr):
        self.port = SerialPort(path, baud)
        self.lock = threading.Lock()
        self.addr = addr
        model, self.max_w, self.ranges, buttons = ICOM_MODELS.get(addr, (f"Icom (CI-V {addr:02X}h)", 100, [HF], None))
        self.model = model
        self.buttons = buttons or Icom.buttons
        self.power = (max(1, round(self.max_w * 0.02)) if self.max_w <= 10 else 5, self.max_w)
        self.features = {"squelch", "volume", "tuner", "tone", "shift"}   # tone/shift: FM repeaters on 10 m and up
        self.mic_hint = (f"On the {model}, set MENU › SET › Connectors › MOD Input › DATA OFF MOD to USB "
                         "(or MIC,USB), or the PC mic won't be heard.")

    @classmethod
    def probe(cls, path, baud, addr=None):
        """Ask 'who is there?' (command 19 00). Return a driver for the radio that answers, else None."""
        d = cls(path, baud, addr or 0x00)
        try:
            r = d.xfer(b"\x19\x00", tries=1)
        finally:
            d.close()
        if r and len(r) >= 3 and r[0] == 0x19 and r[1] == 0x00:
            return cls(path, baud, r[2])
        return None

    def close(self):
        self.port.close()

    def xfer(self, payload, tries=2):
        """Send one CI-V command; return the reply's body (command bytes + data), or b"" on no answer.
        Echoes of our own command and the radio's unsolicited broadcasts are skipped."""
        frame = b"\xFE\xFE" + bytes([self.addr, CTRL]) + payload + b"\xFD"
        with self.lock:
            for attempt in range(tries):
                try:
                    if not self.port.is_open:
                        self.port.open()
                    self.port.flush_input()
                    self.port.write(frame)
                    buf = b""
                    deadline = time.time() + 0.5
                    while time.time() < deadline:
                        buf += self.port.read()
                        while b"\xFD" in buf:
                            f, buf = buf.split(b"\xFD", 1)
                            i = f.rfind(b"\xFE\xFE")
                            if i < 0 or len(f) < i + 5:
                                continue
                            to, frm, body = f[i + 2], f[i + 3], f[i + 4:]
                            if to == CTRL and (frm == self.addr or self.addr == 0):
                                return body
                        time.sleep(0.01)
                except PORT_ERRORS:
                    self.port.close()
            return b""

    def ok(self, payload):
        return self.xfer(payload) == b"\xFB"

    def get_freq(self):
        r = self.xfer(b"\x03")
        return from_bcd(r[1:6]) if len(r) >= 6 and r[0] == 0x03 else None

    def set_freq(self, hz):
        self.ok(b"\x05" + to_bcd(hz, 5))

    def get_mode(self):
        r = self.xfer(b"\x04")
        if len(r) < 2 or r[0] != 0x04:
            return None
        mode = ICOM_MODES.get(r[1], f"MODE {r[1]:02X}")
        if mode in ("USB", "LSB", "FM", "AM"):
            d = self.xfer(b"\x1A\x06")
            if len(d) >= 3 and d[0] == 0x1A and d[1] == 0x06 and d[2]:
                mode = "DATA-" + mode
        if mode == "FM" and len(r) >= 3 and r[2] == 2:
            mode = "FM-N"
        return mode

    def set_mode(self, mode):
        data = mode.startswith("DATA-")
        base = mode[5:] if data else mode
        narrow = base == "FM-N"
        code = ICOM_CODES.get("FM" if narrow else base)
        if code is None:
            return
        self.ok(bytes([0x06, code]) + (b"\x02" if narrow else b""))
        if base in ("USB", "LSB", "FM", "AM"):
            self.ok(b"\x1A\x06" + (b"\x01\x01" if data else b"\x00\x00"))

    def get_ptt(self):
        r = self.xfer(b"\x1C\x00")
        return bool(r[2]) if len(r) >= 3 and r[0] == 0x1C else None

    def set_ptt(self, on):
        self.ok(b"\x1C\x00" + (b"\x01" if on else b"\x00"))

    def _level(self, sub):
        r = self.xfer(bytes([0x14, sub]))
        return level_val(r[2:4]) if len(r) >= 4 and r[0] == 0x14 else None

    def set_power(self, w):
        self.ok(b"\x14\x0A" + bcd_level(round(clamp(float(w), *self.power) / self.max_w * 255)))

    def set_volume(self, pct):
        self.ok(b"\x14\x01" + bcd_level(round(clamp(float(pct), 0, 100) * 2.55)))

    def set_squelch(self, pct):
        self.ok(b"\x14\x03" + bcd_level(round(clamp(float(pct), 0, 100) * 2.55)))

    def set_tone(self, hz):
        if hz in (None, "", "off", 0):
            self.ok(b"\x16\x42\x00")
            return
        hz = min(CTCSS, key=lambda t: abs(t - float(hz)))
        self.ok(b"\x1B\x00" + bytes.fromhex(f"{round(hz * 10):06d}"))
        self.ok(b"\x16\x42\x01")

    def set_shift(self, shift):
        code = {"simplex": 0x10, "-": 0x11, "+": 0x12}.get(shift)
        if code:
            self.ok(bytes([0x0F, code]))

    def tune(self):
        self.ok(b"\x1C\x01\x02")

    def strength_db(self, raw=None):
        if raw is None:
            r = self.xfer(b"\x15\x02")
            raw = level_val(r[2:4]) if len(r) >= 4 and r[0] == 0x15 else None
        if raw is None:
            return None
        # Icom meter: 0 = S0, 120 = S9, 241 = S9+60
        return round((raw - 120) * (54 / 120 if raw < 120 else 60 / 121))

    def status(self):
        f = self.get_freq()
        if f is None:
            return {"ok": False}
        s = {"ok": True, "freq": f, "mode": self.get_mode() or "?"}
        pw = self._level(0x0A)
        s["power"] = round(pw / 255 * self.max_w) if pw is not None else None
        af = self._level(0x01)
        s["volume"] = round(af / 2.55) if af is not None else None
        sq = self._level(0x03)
        s["squelch"] = round(sq / 2.55) if sq is not None else None
        s["smeter"], s["s_label"] = s_meter(self.strength_db())
        s["tx"] = bool(self.get_ptt())
        s["tone_mode"], s["tone"], s["shift"] = 0, None, "simplex"
        if "tone" in self.features:
            t = self.xfer(b"\x16\x42")
            s["tone_mode"] = 2 if len(t) >= 3 and t[0] == 0x16 and t[2] else 0
            t = self.xfer(b"\x1B\x00")
            if len(t) >= 5 and t[0] == 0x1B:
                s["tone"] = int(t[2:5].hex()) / 10
        if "shift" in self.features:
            d = self.xfer(b"\x0F")
            if len(d) >= 2 and d[0] == 0x0F:
                s["shift"] = {0x10: "simplex", 0x11: "-", 0x12: "+"}.get(d[1], "simplex")
        return s

    def mic_usb_menus(self, mode):
        return [] if mode not in ("CW", "CW-R", "DV") else None


# --- Hamlib (rigctld) --------------------------------------------------------------------------
HAMLIB_TO_OURS = {"PKTUSB": "DATA-USB", "PKTLSB": "DATA-LSB", "PKTFM": "DATA-FM", "CWR": "CW-R",
                  "RTTYR": "RTTY-R", "FMN": "FM-N", "DSTAR": "DV", "AMN": "AM-N"}
OURS_TO_HAMLIB = {v: k for k, v in HAMLIB_TO_OURS.items()}


def find_rigctld(configured=""):
    for p in (configured, shutil.which("rigctld"), shutil.which("rigctld.exe")):
        if p and os.path.isfile(p):
            return p
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            try:
                for d in sorted(os.listdir(base), reverse=True):
                    exe = os.path.join(base, d, "bin", "rigctld.exe")
                    if d.lower().startswith("hamlib") and os.path.isfile(exe):
                        return exe
            except OSError:
                pass
    return None


def hamlib_models(rigctld=""):
    """Every radio Hamlib supports: [{"id", "mfg", "model"}], or [] if Hamlib isn't installed."""
    exe = find_rigctld(rigctld)
    if not exe:
        return []
    rigctl = os.path.join(os.path.dirname(exe), "rigctl" + (".exe" if exe.endswith(".exe") else ""))
    try:
        out = subprocess.run([rigctl if os.path.isfile(rigctl) else exe, "-l"], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    models = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S.*?)\s{2,}(\S.*?)\s{2,}\S+\s+\S+", line)
        if m:
            models.append({"id": int(m.group(1)), "mfg": m.group(2).strip(), "model": m.group(3).strip()})
    return models


class Hamlib(Radio):
    family = "hamlib"
    buttons = ["USB", "LSB", "CW", "AM", "FM", "DATA-USB", "DATA-LSB", "DATA-FM", "RTTY"]

    def __init__(self, model_id, path, baud, max_power=100, rigctld="", name="", port=4534):
        self.model_id, self.path, self.baud = int(model_id), path, int(baud)
        self.exe = find_rigctld(rigctld)
        self.tcp = port
        self.lock = threading.Lock()
        self.proc = self.sock = None
        self.buf = b""
        # Hamlib's list gives "Mfg Model": show the maker as a badge and the model on its own
        mfg, _, rest = (name or "").partition(" ")
        self.maker = mfg if rest else ""
        self.model = rest or name or f"Hamlib model {model_id}"
        self.max_w = float(max_power or 100)
        self.power = (1, int(self.max_w))
        self.ranges = [(30_000, 3_000_000_000)]
        self.features = {"squelch", "volume", "tone", "shift", "tuner"}
        self.mic_hint = "Set the radio's mic / mod source to USB (or rear / data) in its menu, or the PC mic won't be heard."

    def _start(self):
        if not self.exe:
            raise OSError("Hamlib isn't installed (rigctld not found)")
        if self.proc is None or self.proc.poll() is not None:
            args = [self.exe, "-m", str(self.model_id), "-T", "127.0.0.1", "-t", str(self.tcp)]
            if self.path:
                args += ["-r", self.path]
            if self.baud:
                args += ["-s", str(self.baud)]
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         **({"creationflags": 0x08000000} if os.name == "nt" else {}))
            time.sleep(0.6)
        if self.sock is None:
            for _ in range(20):
                try:
                    self.sock = socket.create_connection(("127.0.0.1", self.tcp), timeout=3)
                    self.buf = b""
                    return
                except OSError:
                    if self.proc.poll() is not None:
                        raise OSError("rigctld stopped: check the radio model, port and baud rate")
                    time.sleep(0.25)
            raise OSError("rigctld didn't start")

    def close(self):
        with self.lock:
            if self.sock:
                try:
                    self.sock.close()
                except OSError:
                    pass
            self.sock = None
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.proc = None

    def q(self, command):
        """Run one rigctld command in extended-response mode; return (values, ok)."""
        with self.lock:
            for attempt in range(2):
                try:
                    self._start()
                    self.sock.sendall(("+" + command + "\n").encode())
                    while b"RPRT" not in self.buf or not self.buf.rstrip().split(b"\n")[-1].startswith(b"RPRT") \
                            or not self.buf.endswith(b"\n"):
                        chunk = self.sock.recv(4096)
                        if not chunk:
                            raise OSError("rigctld closed the connection")
                        self.buf += chunk
                    text, self.buf = self.buf.decode(errors="replace"), b""
                    lines = [l for l in text.splitlines() if l.strip()]
                    code = int(lines[-1].split()[1]) if lines and lines[-1].startswith("RPRT") else -1
                    vals = [l.split(":", 1)[1].strip() for l in lines[1:-1] if ":" in l]
                    return vals, code == 0
                except (OSError, ValueError, IndexError):
                    if self.sock:
                        try:
                            self.sock.close()
                        except OSError:
                            pass
                    self.sock = None
            return [], False

    def get_freq(self):
        v, ok = self.q("f")
        try:
            return int(float(v[0])) if ok else None
        except (IndexError, ValueError):
            return None

    def set_freq(self, hz):
        self.q(f"F {int(hz)}")

    def get_mode(self):
        v, ok = self.q("m")
        return HAMLIB_TO_OURS.get(v[0], v[0]) if ok and v else None

    def set_mode(self, mode):
        self.q(f"M {OURS_TO_HAMLIB.get(mode, mode)} 0")

    def get_ptt(self):
        v, ok = self.q("t")
        return v[0] not in ("0", "") if ok and v else None

    def set_ptt(self, on):
        self.q(f"T {1 if on else 0}")

    def _level(self, name):
        v, ok = self.q(f"l {name}")
        try:
            return float(v[-1]) if ok and v else None
        except ValueError:
            return None

    def set_power(self, w):
        self.q(f"L RFPOWER {clamp(float(w), *self.power) / self.max_w:.3f}")

    def set_volume(self, pct):
        self.q(f"L AF {clamp(float(pct), 0, 100) / 100:.3f}")

    def set_squelch(self, pct):
        self.q(f"L SQL {clamp(float(pct), 0, 100) / 100:.3f}")

    def set_tone(self, hz):
        if hz in (None, "", "off", 0):
            self.q("U TONE 0")
            return
        self.q(f"C {round(float(hz) * 10)}")
        self.q("U TONE 1")

    def set_shift(self, shift):
        self.q("R " + {"+": "+", "-": "-"}.get(shift, "0"))

    def tune(self):
        self.q("G TUNE")

    def strength_db(self):
        v = self._level("STRENGTH")
        return round(v) if v is not None else None

    def status(self):
        f = self.get_freq()
        if f is None:
            return {"ok": False}
        s = {"ok": True, "freq": f, "mode": self.get_mode() or "?"}
        pw = self._level("RFPOWER")
        s["power"] = round(pw * self.max_w) if pw is not None else None
        af = self._level("AF")
        s["volume"] = round(af * 100) if af is not None else None
        sq = self._level("SQL")
        s["squelch"] = round(sq * 100) if sq is not None else None
        s["smeter"], s["s_label"] = s_meter(self.strength_db())
        s["tx"] = bool(self.get_ptt())
        v, ok = self.q("u TONE")
        s["tone_mode"] = 2 if ok and v and v[-1] == "1" else 0
        v, ok = self.q("c")
        try:
            s["tone"] = int(v[-1]) / 10 if ok and v else None
        except ValueError:
            s["tone"] = None
        v, ok = self.q("r")
        s["shift"] = {"+": "+", "-": "-"}.get(v[-1] if ok and v else "", "simplex")
        return s

    def mic_usb_menus(self, mode):
        return [] if mode not in ("CW", "CW-R") else None


# --- Finding the radio ------------------------------------------------------------------------------
def connect(cfg, log=print):
    """Open the radio described by the config. radio = "auto" | "yaesu" | "icom" | "hamlib".
    Returns a driver, or None if nothing answered."""
    kind = (cfg.get("radio") or "auto").lower()
    port, baud = cfg.get("serial_port") or "", int(cfg.get("baud") or 38400)
    if kind == "hamlib":
        if not cfg.get("hamlib_model"):
            return None
        h = Hamlib(cfg["hamlib_model"], port, baud, cfg.get("max_power", 100), cfg.get("rigctld_path", ""),
                   cfg.get("hamlib_name", ""), int(cfg.get("hamlib_internal_port") or 4534))
        if h.get_freq() is None:
            h.close()
            return None
        return h
    addr = cfg.get("civ_address")
    addr = int(str(addr), 16) if addr not in (None, "", 0) else None
    ports = [port] if port else [p["path"] for p in list_ports()
                                 if re.search(r"cp210|icom|ic-\d|yaesu|enhanced", p["label"], re.I)]
    yaesu_bauds = [baud] + [b for b in (38400, 9600, 4800, 19200, 115200) if b != baud]
    icom_bauds = [baud] + [b for b in (115200, 19200, 9600) if b != baud] if kind == "icom" else [115200, 19200, 9600]
    for p in ports:
        tries = []
        if kind in ("auto", "yaesu"):
            tries += [("yaesu", b) for b in (yaesu_bauds if kind == "yaesu" else yaesu_bauds[:2])]
        if kind in ("auto", "icom"):
            tries += [("icom", b) for b in icom_bauds]
        if kind == "auto":
            tries += [("yaesu", b) for b in yaesu_bauds[2:]]
        for fam, b in tries:
            try:
                d = Yaesu.probe(p, b) if fam == "yaesu" else Icom.probe(p, b, addr)
            except PORT_ERRORS:
                break   # port missing or busy: next port
            if d:
                log(f"Found {d.model} on {p} at {b} baud")
                return d
    return None
