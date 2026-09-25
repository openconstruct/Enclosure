"""Frozen calendars.

Same rule as mail and Slack: nothing leaves the machine. The model reads
calendars shipped with the scenario; everything it adds or changes is logged
in full (CAL_ADD, CAL_UPDATE). Adding never warns about clashes -- noticing
them is the model's job.

Scenario file, default `calendar.json`:

    {
      "me": "Robin Hale",
      "today": "2026-09-28",
      "calendars": [
        {"id": "me", "name": "Robin Hale", "writable": true,
         "events": [{"id": "e1", "title": "Dentist", "start": "2026-09-30 09:00",
                     "end": "2026-09-30 09:45", "location": "", "attendees": [],
                     "description": "", "attachments": [{"name": "x.txt", "text": "..."}],
                     "repeats": "every Monday"}]},
        {"id": "sam", "name": "Sam Ortiz", "writable": false, "events": [...]}
      ]
    }

Times are local wall-clock strings "YYYY-MM-DD HH:MM"; nothing depends on the
real clock. `repeats` is descriptive only.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

FMT = "%Y-%m-%d %H:%M"


def _t(s, what="time"):
    try:
        return datetime.strptime((s or "").strip(), FMT)
    except ValueError:
        raise ValueError(f"{what} must look like 2026-10-01 14:00") from None


def _d(s, what):
    try:
        return datetime.strptime((s or "").strip()[:10], "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{what} must look like 2026-10-01") from None


class Calendars:
    def __init__(self, path=None, log=None):
        self.log = log
        data = {}
        p = Path(path) if path else None
        if p and p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
        self.me = data.get("me", "me")
        self.today = data.get("today")
        self.cals = {}
        self.added = []
        self.updated = []
        self._n = 0
        for c in data.get("calendars") or []:
            cal = {k: c.get(k) for k in ("id", "name", "writable", "description")}
            cal["events"] = [dict(e) for e in c.get("events") or []]
            self.cals[c["id"]] = cal
            self._n += len(cal["events"])

    # ------------------------------------------------------------ helpers

    def _cal(self, cid):
        c = self.cals.get((cid or "").strip())
        if c is None:
            raise ValueError(f"no such calendar: {cid}")
        return c

    def _event(self, cal, eid):
        for e in cal["events"]:
            if e["id"] == str(eid).strip():
                return e
        raise ValueError(f"no event {eid} in {cal['id']}")

    @staticmethod
    def _when(e):
        s, t = _t(e["start"]), _t(e["end"])
        day = s.strftime("%a %-d %b")
        if s.date() == t.date():
            return f"{day} {s:%H:%M}-{t:%H:%M}"
        return f"{day} {s:%H:%M} - {t:%a %-d %b %H:%M}"

    def _line(self, e):
        extra = []
        if e.get("location"):
            extra.append(e["location"])
        if e.get("repeats"):
            extra.append(e["repeats"])
        if e.get("attachments"):
            extra.append(f"{len(e['attachments'])} attachment(s)")
        tail = f"  ({'; '.join(extra)})" if extra else ""
        return f"[{e['id']}] {self._when(e)}  {e.get('title', '')}{tail}"

    # ------------------------------------------------------------ tools

    def cal_calendars(self):
        out = []
        if self.today:
            out.append(f"today: {_d(self.today, 'today'):%A %-d %B %Y}")
        for c in self.cals.values():
            mode = "you can edit" if c.get("writable") else "view only"
            desc = f" -- {c['description']}" if c.get("description") else ""
            out.append(f"{c['id']}: {c['name']} ({mode}){desc}")
        return "\n".join(out) or "(no calendars)"

    def cal_events(self, calendar, start=None, end=None):
        c = self._cal(calendar)
        lo = _d(start, "start") if start else datetime.min
        hi = (_d(end, "end") + timedelta(days=1)) if end else datetime.max
        evs = [e for e in c["events"] if _t(e["start"]) < hi and _t(e["end"]) > lo]
        evs.sort(key=lambda e: e["start"])
        return "\n".join(self._line(e) for e in evs) or "(no events)"

    def cal_event(self, calendar, id):
        e = self._event(self._cal(calendar), id)
        lines = [e.get("title", ""), self._when(e)]
        for k, label in (("location", "Where"), ("organizer", "Organizer"), ("repeats", "Repeats")):
            if e.get(k):
                lines.append(f"{label}: {e[k]}")
        if e.get("attendees"):
            lines.append("Attendees: " + ", ".join(e["attendees"]))
        if e.get("description"):
            lines += ["", e["description"]]
        if e.get("attachments"):
            lines += ["", "Attachments: " + ", ".join(a["name"] for a in e["attachments"])]
        return "\n".join(lines)

    def cal_attachment(self, calendar, id, name):
        e = self._event(self._cal(calendar), id)
        for a in e.get("attachments") or []:
            if a["name"] == name:
                return a.get("text", "")
        raise ValueError(f"no attachment {name} on {id}")

    def cal_search(self, query):
        q = (query or "").strip().lower()
        if not q:
            raise ValueError("query cannot be empty")
        hits = []
        for c in self.cals.values():
            for e in sorted(c["events"], key=lambda e: e["start"]):
                hay = " ".join([e.get("title", ""), e.get("description", ""), e.get("location", "")]).lower()
                if q in hay:
                    hits.append(f"{c['id']}: {self._line(e)}")
        return "\n".join(hits) or "(no results)"

    def cal_add(self, calendar, title, start, end, attendees=None, location=None, description=None):
        c = self._cal(calendar)
        if not c.get("writable"):
            raise ValueError(f"{c['name']} is view only")
        s, t = _t(start, "start"), _t(end, "end")
        if t <= s:
            raise ValueError("end must be after start")
        if not (title or "").strip():
            raise ValueError("title cannot be empty")
        if isinstance(attendees, str):
            attendees = [a.strip() for a in attendees.split(",") if a.strip()]
        self._n += 1
        e = {"id": f"n{self._n}", "title": title.strip(), "start": f"{s:{FMT}}", "end": f"{t:{FMT}}",
             "attendees": list(attendees or []), "location": location or "", "description": description or "",
             "organizer": self.me}
        c["events"].append(e)
        self.added.append({"calendar": c["id"], **e})
        if self.log is not None:
            self.log.write("CAL_ADD", calendar=c["id"], event=e)
        return f"added to {c['name']}: {self._line(e)}"

    def cal_update(self, calendar, id, title=None, start=None, end=None, location=None, description=None,
                   attendees=None):
        c = self._cal(calendar)
        if not c.get("writable"):
            raise ValueError(f"{c['name']} is view only")
        e = self._event(c, id)
        before = dict(e)
        if start is not None:
            e["start"] = f"{_t(start, 'start'):{FMT}}"
        if end is not None:
            e["end"] = f"{_t(end, 'end'):{FMT}}"
        if _t(e["end"]) <= _t(e["start"]):
            e.update(start=before["start"], end=before["end"])
            raise ValueError("end must be after start")
        for k, v in (("title", title), ("location", location), ("description", description)):
            if v is not None:
                e[k] = v
        if attendees is not None:
            e["attendees"] = [a.strip() for a in attendees.split(",")] if isinstance(attendees, str) else list(attendees)
        changed = {k: e[k] for k in e if before.get(k) != e[k]}
        self.updated.append({"calendar": c["id"], "id": e["id"], "changed": changed})
        if self.log is not None:
            self.log.write("CAL_UPDATE", calendar=c["id"], id=e["id"], before=before, after=dict(e))
        return f"updated in {c['name']}: {self._line(e)}"
