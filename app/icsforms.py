"""ICS forms: fill in, save and print the standard ICS forms (201 through 309).

Forms are JSON files in <config>/icsforms/. Each form type is described once in SPECS: the web page builds its
editor from it and build_pdf() draws the printed form (boxes numbered like the FEMA/NIMS form) from it, so the
two always match. Self-contained (standard library only), so it works with or without the Net log add-on."""
import datetime
import io
import json
import os
import re
import urllib.parse

FORM_ID = re.compile(r"^\d{8}-\d{6}(-\d{1,3})?$")

# Layout blocks, top to bottom:
#   ("row",   [(label, key, width fraction, kind), ...])   one line of boxes
#   ("area",  label, key, height in points)                 a box for longer text
#   ("table", label, key, [(heading, key, width fraction, kind), ...], min rows, fill the page with blank rows, options)
#             options: {"rows": [...] the rows a new form starts with, "import": "presets" | "netlog"}
# Kinds: text | date | time | datetime | check (a tick box) | choice:A|B|C (pick one)
# A spec's "defaults" fill new forms: $call = your callsign, $today, $time, $now. Every form also starts with
# prep_name = $call and op_date_from = $today when it has those boxes.
YESNO = "choice:Yes|No"


def T(label, key, w, kind="text"):
    return (label, key, w, kind)


def op_period(n, widths=(.13, .13, .1, .1)):
    """The operational period boxes (numbered n on the form)."""
    return [T(f"{n}. Op. Period: Date From", "op_date_from", widths[0], "date"), T("Date To", "op_date_to", widths[1], "date"),
            T("Time From", "op_time_from", widths[2], "time"), T("Time To", "op_time_to", widths[3], "time")]


def head(n=2):
    """Box 1 (incident name) and the operational period, the first row of most forms."""
    return ("row", [T("1. Incident Name", "incident", .48)] + op_period(n, (.16, .12, .12, .12)))


def prepared(n, sig=True):
    return ("row", [T(f"{n}. Prepared by: Name", "prep_name", .3), T("Position/Title", "prep_pos", .25)] +
            ([T("Signature", "prep_sig", .2)] if sig else []) + [T("Date/Time", "prep_dt", .25 if sig else .45, "datetime")])


def roles(*names):
    return [{"position": n} for n in names]


POSITION_NAME = [T("Position", "position", .45), T("Name", "name", .55)]

SPECS = {
    "201": {"title": "INCIDENT BRIEFING (ICS 201)", "short": "ICS-201 Incident Briefing", "landscape": False,
            "defaults": {"initiated": "$now"}, "layout": [
        ("row", [T("1. Incident Name", "incident", .5), T("2. Incident Number", "number", .2), T("3. Date/Time Initiated", "initiated", .3, "datetime")]),
        ("area", "4. Map/Sketch (describe the area of operations, the incident site and threatened areas, or attach a map)", "map", 130),
        ("area", "5. Situation Summary and Health and Safety Briefing (for briefings or transfer of command)", "situation", 170),
        prepared(6),
        ("area", "7. Current and Planned Objectives", "objectives", 100),
        ("table", "8. Current and Planned Actions, Strategies, and Tactics", "actions", [T("Time", "time", .14, "time"), T("Actions", "action", .86)], 6, False),
        ("table", "9. Current Organization", "org", POSITION_NAME, 0, False, {"rows": roles(
            "Incident Commander(s)", "Liaison Officer", "Safety Officer", "Public Information Officer", "Planning Section Chief",
            "Operations Section Chief", "Finance/Administration Section Chief", "Logistics Section Chief")}),
        ("table", "10. Resource Summary", "resources", [
            T("Resource", "resource", .2), T("Resource Identifier", "ident", .17), T("Date/Time Ordered", "ordered", .15, "datetime"),
            T("ETA", "eta", .1), T("Arrived", "arrived", .08, YESNO), T("Notes (location/assignment/status)", "notes", .3)], 8, True),
    ]},
    "202": {"title": "INCIDENT OBJECTIVES (ICS 202)", "short": "ICS-202 Incident Objectives", "landscape": False, "layout": [
        head(),
        ("area", "3. Objective(s)", "objectives", 190),
        ("area", "4. Operational Period Command Emphasis", "emphasis", 110),
        ("area", "General Situational Awareness", "awareness", 90),
        ("row", [T("5. Site Safety Plan Required?", "ssp_req", .3, YESNO), T("Approved Site Safety Plan(s) Located at", "ssp_loc", .7)]),
        ("row", [T("6. Incident Action Plan includes (ICS 203, 204, 205, 205A, 206, 207, 208, map/chart, weather, other)", "iap", 1)]),
        ("row", [T("7. Prepared by: Name", "prep_name", .35), T("Position/Title", "prep_pos", .35), T("Signature", "prep_sig", .3)]),
        ("row", [T("8. Approved by Incident Commander: Name", "ic_name", .4), T("Signature", "ic_sig", .3), T("Date/Time", "ic_dt", .3, "datetime")]),
    ]},
    "203": {"title": "ORGANIZATION ASSIGNMENT LIST (ICS 203)", "short": "ICS-203 Organization List", "landscape": False, "layout": [
        head(),
        ("table", "3. Incident Commander(s) and Command Staff", "command", POSITION_NAME, 0, False, {"rows": roles(
            "IC/UCs", "Deputy", "Safety Officer", "Public Information Officer", "Liaison Officer")}),
        ("table", "4. Agency/Organization Representatives", "agencies", [T("Agency/Organization", "agency", .45), T("Name", "name", .55)], 3, False),
        ("table", "5. Planning Section", "planning", POSITION_NAME, 0, False, {"rows": roles(
            "Chief", "Deputy", "Resources Unit", "Situation Unit", "Documentation Unit", "Demobilization Unit", "Technical Specialists")}),
        ("table", "6. Logistics Section", "logistics", POSITION_NAME, 0, False, {"rows": roles(
            "Chief", "Deputy", "Support Branch Director", "Supply Unit", "Facilities Unit", "Ground Support Unit",
            "Service Branch Director", "Communications Unit", "Medical Unit", "Food Unit")}),
        ("table", "7. Operations Section", "operations", POSITION_NAME, 0, False, {"rows": roles(
            "Chief", "Deputy", "Staging Area", "Branch Director", "Division/Group", "Air Operations Branch Director")}),
        ("table", "8. Finance/Administration Section", "finance", POSITION_NAME, 0, False, {"rows": roles(
            "Chief", "Deputy", "Time Unit", "Procurement Unit", "Comp/Claims Unit", "Cost Unit")}),
        prepared(9),
    ]},
    "204": {"title": "ASSIGNMENT LIST (ICS 204)", "short": "ICS-204 Assignment List", "landscape": False, "layout": [
        head(),
        ("row", [T("3. Branch", "branch", .25), T("Division", "division", .25), T("Group", "group", .25), T("Staging Area", "staging", .25)]),
        ("table", "4. Operations Personnel", "personnel", [T("Position", "position", .35), T("Name", "name", .35), T("Contact Number(s)", "contact", .3)],
         0, False, {"rows": roles("Operations Section Chief", "Branch Director", "Division/Group Supervisor")}),
        ("table", "5. Resources Assigned", "resources", [
            T("Resource Identifier", "ident", .14), T("Leader", "leader", .14), T("# of Persons", "persons", .07),
            T("Contact (phone, radio frequency, etc.)", "contact", .17),
            T("Reporting Location, Special Equipment and Supplies, Remarks, Notes, Information", "notes", .48)], 6, False),
        ("area", "6. Work Assignments", "work", 80),
        ("area", "7. Special Instructions", "instructions", 60),
        ("table", "8. Communications (radio and/or phone contact numbers needed for this assignment)", "comms", [
            T("Name/Function", "name", .4), T("Primary Contact: cell, pager, or radio (frequency/system/channel)", "contact", .6)], 4, False),
        ("row", [T("9. Prepared by: Name", "prep_name", .25), T("Position/Title", "prep_pos", .2), T("Signature", "prep_sig", .15),
                 T("10. Approved by: Name", "appr_name", .2), T("Signature", "appr_sig", .1), T("Date/Time", "appr_dt", .1, "datetime")]),
    ]},
    "205": {"title": "INCIDENT RADIO COMMUNICATIONS PLAN (ICS 205)", "short": "ICS-205 Radio Plan", "landscape": True,
            "defaults": {"prepared": "$now"}, "layout": [
        ("row", [T("1. Incident Name", "incident", .34), T("2. Date/Time Prepared", "prepared", .2, "datetime")] +
                op_period(3, (.14, .12, .1, .1))),
        ("table", "4. Basic Radio Channel Use", "channels", [
            T("Zone Grp.", "zone", .05), T("Ch #", "ch", .04), T("Function", "function", .09),
            T("Channel Name / Talkgroup", "name", .13), T("Assignment", "assignment", .12),
            T("RX Freq N or W", "rx", .09), T("RX Tone/NAC", "rx_tone", .07), T("TX Freq N or W", "tx", .09), T("TX Tone/NAC", "tx_tone", .07),
            T("Mode (A, D or M)", "mode", .06), T("Remarks", "remarks", .19)], 10, True, {"import": "presets"}),
        ("area", "5. Special Instructions", "instructions", 54),
        ("row", [T("6. Prepared by (Communications Unit Leader): Name", "prep_name", .5), T("Signature", "prep_sig", .5)]),
    ]},
    "205A": {"title": "COMMUNICATIONS LIST (ICS 205A)", "short": "ICS-205A Communications List", "landscape": False, "layout": [
        head(),
        ("table", "3. Basic Local Communications Information", "contacts", [
            T("Incident Assigned Position", "position", .3), T("Name (Alphabetized)", "name", .3),
            T("Method(s) of Contact (phone, pager, cell, radio, etc.)", "contact", .4)], 15, True),
        prepared(4),
    ]},
    "206": {"title": "MEDICAL PLAN (ICS 206)", "short": "ICS-206 Medical Plan", "landscape": False, "layout": [
        head(),
        ("table", "3. Medical Aid Stations", "stations", [
            T("Name", "name", .25), T("Location", "location", .3), T("Contact Number(s)/Frequency", "contact", .3),
            T("Paramedics on Site?", "paramedics", .15, YESNO)], 4, False),
        ("table", "4. Transportation (indicate air or ground)", "transport", [
            T("Ambulance Service", "service", .25), T("Location", "location", .3), T("Contact Number(s)/Frequency", "contact", .3),
            T("Level of Service", "level", .15, "choice:ALS|BLS")], 4, False),
        ("table", "5. Hospitals", "hospitals", [
            T("Hospital Name", "name", .2), T("Address, Latitude & Longitude if Helipad", "address", .25),
            T("Contact Number(s)/Frequency", "contact", .17), T("Travel Time: Air", "air", .08), T("Ground", "ground", .08),
            T("Trauma Center", "trauma", .08, YESNO), T("Burn Center", "burn", .07, YESNO), T("Helipad", "helipad", .07, YESNO)], 4, False),
        ("area", "6. Special Medical Emergency Procedures", "procedures", 110),
        ("row", [T("Aviation assets are used for rescue (coordinate with Air Operations)", "aviation", 1, "check")]),
        ("row", [T("7. Prepared by (Medical Unit Leader): Name", "prep_name", .5), T("Signature", "prep_sig", .5)]),
        ("row", [T("8. Approved by (Safety Officer): Name", "appr_name", .4), T("Signature", "appr_sig", .3), T("Date/Time", "appr_dt", .3, "datetime")]),
    ]},
    "208": {"title": "SAFETY MESSAGE/PLAN (ICS 208)", "short": "ICS-208 Safety Message", "landscape": False, "layout": [
        head(),
        ("area", "3. Safety Message/Expanded Safety Message, Safety Plan, Site Safety Plan", "message", 400),
        ("row", [T("4. Site Safety Plan Required?", "ssp_req", .3, YESNO), T("Approved Site Safety Plan(s) Located At", "ssp_loc", .7)]),
        prepared(5),
    ]},
    "210": {"title": "RESOURCE STATUS CHANGE (ICS 210)", "short": "ICS-210 Resource Status Change", "landscape": False,
            "defaults": {"effective": "$now"}, "layout": [
        ("row", [T("1. Incident Name", "incident", .45), T("2. Incident Number", "number", .25), T("3. Change Effective: Date/Time", "effective", .3, "datetime")]),
        ("table", "Status changes", "changes", [
            T("4. Resource Number", "resource", .2), T("5. New Status (Available, Assigned, O/S)", "status", .2, "choice:Available|Assigned|O/S"),
            T("6. From (Assignment and Status)", "from", .3), T("7. To (Assignment and Status)", "to", .3)], 12, False),
        ("area", "8. Comments", "comments", 120),
        prepared(9),
    ]},
    "211": {"title": "INCIDENT CHECK-IN LIST (ICS 211)", "short": "ICS-211 Check-In List", "landscape": True,
            "defaults": {"start": "$now"}, "layout": [
        ("row", [T("1. Incident Name", "incident", .35), T("2. Incident Number", "number", .15),
                 T("3. Check-In Location (Base, Staging Area, ICP, Helibase, Other)", "location", .3), T("4. Start Date/Time", "start", .2, "datetime")]),
        ("table", "Check-In Information", "checkins", [
            T("5. Resource (State, Agency, Category, Kind, Type), Name or Identifier", "resource", .16), T("6. Order Request #", "order", .06),
            T("7. Date/Time Check-In", "checkin", .09, "datetime"), T("8. Leader's Name", "leader", .09), T("9. Total # of Personnel", "persons", .05),
            T("10. Incident Contact Information", "contact", .1), T("11. Home Unit or Agency", "home", .09),
            T("12. Departure Point, Date and Time", "departure", .08), T("13. Method of Travel", "travel", .06),
            T("14. Incident Assignment", "assignment", .09), T("15. Other Qualifications", "quals", .07),
            T("16. Sent to RESTAT: Time/Initials", "restat", .06)], 12, True, {"import": "netlog"}),
        prepared(17),
    ]},
    "213": {"title": "GENERAL MESSAGE (ICS 213)", "short": "ICS-213 General Message", "landscape": False,
            "defaults": {"from": "$call", "date": "$today", "time": "$time"}, "layout": [
        ("row", [T("1. Incident Name (Optional)", "incident", 1)]),
        ("row", [T("2. To (Name and Position)", "to", 1)]),
        ("row", [T("3. From (Name and Position)", "from", 1)]),
        ("row", [T("4. Subject", "subject", .6), T("5. Date", "date", .2, "date"), T("6. Time", "time", .2, "time")]),
        ("area", "7. Message", "message", 270),
        ("row", [T("8. Approved by: Name", "appr_name", .4), T("Signature", "appr_sig", .25), T("Position/Title", "appr_pos", .35)]),
        ("area", "9. Reply", "reply", 150),
        ("row", [T("10. Replied by: Name", "rep_name", .3), T("Position/Title", "rep_pos", .25),
                 T("Signature", "rep_sig", .2), T("Date/Time", "rep_dt", .25, "datetime")]),
    ]},
    "213RR": {"title": "RESOURCE REQUEST MESSAGE (ICS 213 RR)", "short": "ICS-213RR Resource Request", "landscape": False,
              "defaults": {"dt": "$now", "requested_by": "$call"}, "layout": [
        ("row", [T("1. Incident Name", "incident", .45), T("2. Date/Time", "dt", .3, "datetime"), T("3. Resource Request Number", "rr_number", .25)]),
        ("table", "4. Order (use additional forms when requesting different resource sources of supply)", "items", [
            T("Qty.", "qty", .06), T("Kind", "kind", .1), T("Type", "type", .08),
            T("Detailed Item Description (vital characteristics, brand, specs, experience, size, etc.)", "desc", .4),
            T("Arrival: Requested", "req_arrival", .12, "datetime"), T("Estimated", "est_arrival", .12, "datetime"), T("Cost", "cost", .12)], 6, False),
        ("row", [T("5. Requested Delivery/Reporting Location", "delivery", .5), T("6. Suitable Substitutes and/or Suggested Sources", "substitutes", .5)]),
        ("row", [T("7. Requested by Name/Position", "requested_by", .4), T("8. Priority", "priority", .2, "choice:Urgent|Routine|Low"),
                 T("9. Section Chief Approval", "chief_approval", .4)]),
        ("row", [T("10. Logistics Order Number", "log_order", .3), T("11. Supplier Phone/Fax/Email", "supplier_contact", .35),
                 T("12. Name of Supplier/POC", "supplier", .35)]),
        ("area", "13. Notes", "notes", 50),
        ("row", [T("14. Approval Signature of Auth Logistics Rep", "log_sig", .4), T("15. Date/Time", "log_dt", .25, "datetime"),
                 T("16. Order placed by", "placed_by", .35, "choice:SPUL|PROC|Other")]),
        ("area", "17. Reply/Comments from Finance", "finance_reply", 50),
        ("row", [T("18. Finance Section Signature", "fin_sig", .6), T("19. Date/Time", "fin_dt", .4, "datetime")]),
    ]},
    "214": {"title": "ACTIVITY LOG (ICS 214)", "short": "ICS-214 Activity Log", "landscape": False, "defaults": {"name": "$call"}, "layout": [
        head(),
        ("row", [T("3. Name", "name", .34), T("4. ICS Position", "position", .33), T("5. Home Agency (and Unit)", "agency", .33)]),
        ("table", "6. Resources Assigned", "resources", [T("Name", "name", .34), T("ICS Position", "position", .33),
                                                         T("Home Agency (and Unit)", "agency", .33)], 5, False),
        ("table", "7. Activity Log", "activity", [T("Date/Time", "dt", .2, "datetime"), T("Notable Activities", "text", .8)], 12, True),
        prepared(8),
    ]},
    "217A": {"title": "COMMUNICATIONS RESOURCE AVAILABILITY WORKSHEET (ICS 217A)", "short": "ICS-217A Comms Resources", "landscape": True,
             "defaults": {"prepared": "$now"}, "layout": [
        ("row", [T("1. Band", "band", .3), T("Incident Name (Optional)", "incident", .4), T("Date/Time Prepared", "prepared", .3, "datetime")]),
        ("table", "2. Channels", "channels", [
            T("Channel Configuration", "config", .1), T("Channel Name / Talkgroup", "name", .15), T("Eligible Users", "users", .13),
            T("RX Freq N or W", "rx", .1), T("RX Tone/NAC", "rx_tone", .08), T("TX Freq N or W", "tx", .1), T("TX Tone/NAC", "tx_tone", .08),
            T("Mode (A, D or M)", "mode", .07), T("Remarks", "remarks", .19)], 12, True, {"import": "presets"}),
    ]},
    "221": {"title": "DEMOBILIZATION CHECK-OUT (ICS 221)", "short": "ICS-221 Demob Check-Out", "landscape": False, "layout": [
        ("row", [T("1. Incident Name", "incident", .45), T("2. Incident Number", "number", .25), T("3. Planned Release Date/Time", "release", .3, "datetime")]),
        ("row", [T("4. Resource or Personnel Released", "released", .6), T("5. Order Request Number", "order", .4)]),
        ("table", "6. Resource or Personnel: released only when the units below have signed off", "signoff", [
            T("Unit/Manager", "unit", .35), T("Remarks", "remarks", .3), T("Name", "name", .2), T("Signature", "sig", .15)], 0, False,
         {"rows": [{"unit": u} for u in ("Logistics: Supply Unit", "Logistics: Communications Unit", "Logistics: Facilities Unit",
                                           "Logistics: Ground Support Unit", "Planning: Documentation Unit", "Finance/Admin: Time Unit",
                                           "Other Section/Staff")]}),
        ("area", "7. Remarks", "remarks", 70),
        ("row", [T("8. Travel: Room Overnight?", "overnight", .2, YESNO), T("Estimated Time of Departure", "etd", .2, "datetime"),
                 T("Actual Release Date/Time", "actual", .2, "datetime"), T("Destination", "destination", .2),
                 T("Estimated Time of Arrival", "eta", .2, "datetime")]),
        ("row", [T("Travel Method", "travel", .25), T("Contact Information While Traveling", "travel_contact", .35),
                 T("Manifest? / Number", "manifest", .15), T("Reassignment Information", "reassign", .25)]),
        prepared(9),
    ]},
    "309": {"title": "COMMUNICATIONS LOG (ICS 309)", "short": "ICS-309 Comms Log", "landscape": False, "defaults": {"operator": "$call"}, "layout": [
        head(),
        ("row", [T("3. Radio Operator (Name, Call Sign)", "operator", 1)]),
        ("table", "4. Communications Log", "log", [
            T("Time", "time", .09, "time"), T("From: Call Sign/ID", "from", .15), T("Msg #", "from_msg", .07),
            T("To: Call Sign/ID", "to", .15), T("Msg #", "to_msg", .07), T("Message", "message", .47)], 20, True, {"import": "netlog"}),
        ("row", [T("5. Prepared by: Name", "prep_name", .5), T("Date & Time Prepared", "prep_dt", .5, "datetime")]),
    ]},
}
MOST_USED = ["213", "214", "205", "309"]


def title_of(form):
    """The name shown in the saved-forms list."""
    f = form.get("fields") or {}
    spec = SPECS.get(form.get("type"), {})
    main = f.get("subject") if form.get("type") == "213" else f.get("incident") or f.get("band")
    return (main or "").strip() or spec.get("short", "ICS form")


class Store:
    def __init__(self, config_dir):
        self.dir = os.path.join(config_dir, "icsforms")

    def path(self, form_id):
        if not FORM_ID.match(str(form_id or "")):
            raise ValueError("bad form id")
        return os.path.join(self.dir, form_id + ".json")

    def list(self):
        out = []
        try:
            names = os.listdir(self.dir)
        except OSError:
            return out
        for n in names:
            if n.endswith(".json") and FORM_ID.match(n[:-5]):
                try:
                    with open(os.path.join(self.dir, n)) as f:
                        d = json.load(f)
                    out.append({"id": n[:-5], "type": d.get("type"), "title": title_of(d), "updated": d.get("updated")})
                except (OSError, ValueError):
                    pass
        return sorted(out, key=lambda d: d.get("updated") or "", reverse=True)

    def load(self, form_id):
        with open(self.path(form_id)) as f:
            return json.load(f)

    def new_id(self):
        base = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        fid, n = base, 1
        while os.path.exists(os.path.join(self.dir, fid + ".json")):
            n += 1
            fid = f"{base}-{n}"
        return fid

    def save(self, form):
        if form.get("type") not in SPECS:
            raise ValueError("unknown form type")
        os.makedirs(self.dir, exist_ok=True)
        if not form.get("id"):
            form["id"] = self.new_id()
        clean = {"id": form["id"], "type": form["type"],
                 "fields": {str(k): str(v) for k, v in (form.get("fields") or {}).items() if v is not None},
                 "tables": {str(k): [{str(c): str(v) for c, v in r.items() if v is not None} for r in rows if isinstance(r, dict)]
                            for k, rows in (form.get("tables") or {}).items() if isinstance(rows, list)},
                 "created": form.get("created") or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                 "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
        path = self.path(clean["id"])
        with open(path + ".tmp", "w") as f:
            json.dump(clean, f, indent=1)
        os.replace(path + ".tmp", path)   # never leave a half-written form
        return clean

    def delete(self, form_id):
        os.remove(self.path(form_id))


# --- PDF ---------------------------------------------------------------------------------------------
# Standard Helvetica metrics (1/1000 em), characters 32..126
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
        [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556,
         278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334,
         260, 334, 584]
_HELVB = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
         [333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
          667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556,
          333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389,
          280, 389, 584]
FONTS = {"R": ("Helvetica", _HELV), "B": ("Helvetica-Bold", _HELVB)}
BLACK, GREY, SHADE = (0, 0, 0), (90, 90, 90), (225, 225, 225)


def _w(text, font, size):
    widths = FONTS[font][1]
    return sum(widths[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in text) * size / 1000


def _wrap(text, font, size, width):
    lines = []
    for para in str(text or "").split("\n"):
        line = ""
        for word in para.split(" "):
            cand = (line + " " + word) if line else word
            if _w(cand, font, size) <= width:
                line = cand
                continue
            if line:
                lines.append(line)
            while _w(word, font, size) > width:   # a single word wider than the box
                n = len(word)
                while n > 1 and _w(word[:n], font, size) > width:
                    n -= 1
                lines.append(word[:n])
                word = word[n:]
            line = word
        lines.append(line)
    return lines or [""]


def _pdfstr(text):
    b = str(text).encode("cp1252", "replace")
    return b"(" + b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


class _Page:
    def __init__(self):
        self.ops = []

    def text(self, x, y, s, font="R", size=10, rgb=BLACK):
        self.ops.append(b"BT /F%s %.2f Tf %.3f %.3f %.3f rg %.2f %.2f Td %s Tj ET" % (
            font.encode(), size, *(c / 255 for c in rgb), x, y, _pdfstr(s)))

    def fill(self, x, y, w, h, rgb):
        self.ops.append(b"%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f" % (*(c / 255 for c in rgb), x, y, w, h))

    def box(self, x, y, w, h, width=0.7):
        self.ops.append(b"0 0 0 RG %.2f w %.2f %.2f %.2f %.2f re S" % (width, x, y, w, h))


def _show(value, kind):
    """Dates from the page's date pickers (YYYY-MM-DD) printed as MM/DD/YYYY, like the paper forms."""
    v = str(value or "")
    if kind == "check":
        return ""   # drawn as a tick box
    if kind == "date" and re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        return f"{v[5:7]}/{v[8:10]}/{v[:4]}"
    if kind == "datetime" and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", v):
        return f"{v[5:7]}/{v[8:10]}/{v[:4]} {v[11:16]}"
    return v


def build_pdf(form):
    spec = SPECS[form["type"]]
    W, H = (792, 612) if spec["landscape"] else (612, 792)
    M = 30
    fields, tables = form.get("fields") or {}, form.get("tables") or {}
    pages = []
    LBL, VAL, LEAD = 6.8, 9.5, 11.5
    bottom = M + 22

    def new_page(cont=False):
        pg = _Page()
        pages.append(pg)
        t = spec["title"] + (" (continued)" if cont else "")
        pg.box(M, H - M - 22, W - 2 * M, 22, 1.2)
        pg.text((W - _w(t, "B", 12)) / 2, H - M - 15.5, t, "B", 12)
        return pg, H - M - 22

    def cells_height(cells, total):
        h = 0
        for label, key, frac, kind in cells:
            lines = _wrap(_show(fields.get(key), kind), "R", VAL, frac * total - 6)
            h = max(h, 13 + LEAD * len(lines) + 4)
        return max(h, 28)

    def area_height(key, min_h, total):
        return max(min_h, 14 + LEAD * len(_wrap(fields.get(key), "R", VAL, total - 8)) + 6)

    def block_height(b, total):
        if b[0] == "row":
            return cells_height(b[1], total)
        if b[0] == "area":
            return area_height(b[2], b[3], total)
        return 40   # a table needs at least its title, headings and a row

    def table_head(pg, y, label, cols, total):
        pg.fill(M, y - 14, total, 14, SHADE)
        pg.box(M, y - 14, total, 14)
        pg.text(M + 3, y - 10, label, "B", 8)
        y -= 14
        heads = [_wrap(h, "B", LBL, frac * total - 4) for h, _, frac, _ in cols]
        hh = max(len(h) for h in heads) * 8 + 6
        x = M
        for (h, _, frac, _), lines in zip(cols, heads):
            pg.box(x, y - hh, frac * total, hh)
            for i, ln in enumerate(lines):
                pg.text(x + 2, y - 9 - i * 8, ln, "B", LBL)
            x += frac * total
        return y - hh

    total = W - 2 * M
    pg, y = new_page()
    layout = spec["layout"]
    for bi, b in enumerate(layout):
        rest = sum(block_height(x, total) for x in layout[bi + 1:])   # what still has to fit below
        if b[0] in ("row", "area"):
            h = block_height(b, total)
            if y - h < bottom:
                pg, y = new_page(True)
            if b[0] == "row":
                x = M
                for label, key, frac, kind in b[1]:
                    w = frac * total
                    pg.box(x, y - h, w, h)
                    if kind == "check":   # a tick box in front of the label
                        pg.box(x + 4, y - 15, 9, 9)
                        if fields.get(key):
                            pg.text(x + 5.6, y - 13.4, "X", "B", 8.5)
                        pg.text(x + 18, y - 13, label, "B", 8)
                        x += w
                        continue
                    pg.text(x + 3, y - 8.5, label, "B", LBL)
                    for i, ln in enumerate(_wrap(_show(fields.get(key), kind), "R", VAL, w - 6)):
                        pg.text(x + 3, y - 20 - i * LEAD, ln, "R", VAL)
                    x += w
            else:
                pg.box(M, y - h, total, h)
                pg.text(M + 3, y - 8.5, b[1], "B", LBL)
                for i, ln in enumerate(_wrap(fields.get(b[2]), "R", VAL, total - 8)):
                    pg.text(M + 4, y - 22 - i * LEAD, ln, "R", VAL)
            y -= h
            continue

        _, label, key, cols, min_rows, fill = b[:6]
        rows = [r for r in tables.get(key) or [] if any(str(v).strip() for v in r.values())]
        if y - 60 < bottom:
            pg, y = new_page(True)
        y = table_head(pg, y, label, cols, total)
        n = 0
        while True:
            r = rows[n] if n < len(rows) else None
            if r is None and n >= min_rows and not fill:
                break
            cells = [_wrap(_show(r.get(k), kind), "R", 8.5, frac * total - 4) if r else [""] for _, k, frac, kind in cols]
            rh = max(16, max(len(c) for c in cells) * 10 + 6)
            if r is None and y - rh - rest < bottom:
                break   # blank rows only fill the space left above the boxes that follow
            if y - rh < bottom:
                pg, y = new_page(True)
                y = table_head(pg, y, label + " (continued)", cols, total)
            x = M
            for (_, k, frac, kind), lines in zip(cols, cells):
                pg.box(x, y - rh, frac * total, rh)
                for i, ln in enumerate(lines):
                    pg.text(x + 2, y - 11 - i * 10, ln, "R", 8.5)
                x += frac * total
            y -= rh
            n += 1

    made = "Prepared with RigPanel · " + datetime.datetime.now().strftime("%m/%d/%Y %H:%M")
    for i, p in enumerate(pages, 1):
        p.text(M, M + 6, f"ICS {form['type']}", "B", 9)
        p.text(M + 50, M + 6, made, "R", 7, GREY)
        t = f"Page {i} of {len(pages)}"
        p.text(W - M - _w(t, "R", 8), M + 6, t, "R", 8)

    objs = []

    def add(b):
        objs.append(b)
        return len(objs)

    fonts = {k: add(b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % v[0].encode())
             for k, v in FONTS.items()}
    res = b"<< /Font << " + b" ".join(b"/F%s %d 0 R" % (k.encode(), n) for k, n in fonts.items()) + b" >> >>"
    pages_id = len(objs) + 1 + 2 * len(pages)
    kids = []
    for p in pages:
        stream = b"\n".join(p.ops)
        c = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources %s /Contents %d 0 R >>"
                        % (pages_id, W, H, res, c)))
    assert add(b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)) == pages_id
    title = (spec["short"] + " - " + title_of(form)).encode("latin-1", "replace").translate(None, b"\\()")
    info = add(b"<< /Title (" + title + b") /Producer (RigPanel) >>")
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, b in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % n + b + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for o in offsets:
        out.write(b"%010d 00000 n \n" % o)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, info, xref))
    return out.getvalue()


def filename(form):
    base = "".join(c if c.isalnum() or c in "-_" else "_" for c in title_of(form)).strip("_")[:40] or "form"
    return f"ICS-{form['type']}-{base}-{form.get('id', '')}.pdf"


# --- Web API ---------------------------------------------------------------------------------------------
def handle_get(h, path, config_dir):
    """Serve an ICS forms GET request on handler `h` (needs _json, _file, send_error). True if it was ours."""
    store = Store(config_dir)
    route = path.split("?")[0]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    if route == "/api/icsforms":
        h._json(store.list())
    elif route == "/api/icsform-specs":
        h._json({"most_used": MOST_USED, "forms": {k: {"title": v["title"], "short": v["short"], "layout": v["layout"],
                                                         "defaults": v.get("defaults", {})} for k, v in SPECS.items()}})
    elif route in ("/api/icsform", "/api/icsform-pdf"):
        try:
            form = store.load(q.get("id", [""])[0])
        except (OSError, ValueError):
            h._json({"error": "not found"}, 404)
            return True
        if route == "/api/icsform":
            h._json(form)
        else:
            h._file(build_pdf(form), "application/pdf", filename(form) if q.get("download") else None)
    else:
        return False
    return True


def handle_post(h, path, body, config_dir):
    store = Store(config_dir)
    try:
        if path == "/api/icsform":
            form = store.save(body)
            h._json({"ok": True, "id": form["id"], "updated": form["updated"], "title": title_of(form)})
        elif path == "/api/icsform/delete":
            store.delete(body.get("id"))
            h._json({"ok": True})
        else:
            return False
    except (OSError, ValueError) as e:
        h._json({"ok": False, "message": str(e)}, 400)
    return True
