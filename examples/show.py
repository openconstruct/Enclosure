#!/usr/bin/env python3
"""Print an episode log as a readable timeline.

    python examples/show.py runs/<dir>/<ep>.jsonl
"""
import json
import sys

KEEP = ("text", "name", "args", "parse", "status", "finish", "detail", "reason", "gate",
        "where", "to", "cc", "subject", "body", "user", "medium", "frm", "waited",
        "still_pending", "state", "sent", "unread", "pending", "posts")

for line in open(sys.argv[1], encoding="utf-8"):
    e = json.loads(line)
    ev = e["ev"]
    if ev == "PERSON":
        keep = {"person": e["person"], "reply": e["reply"], "delay": e.get("delay")}
    elif ev == "START":
        keep = {k: e.get(k) for k in ("scenario", "model", "seed", "temperature", "scenario_hash")}
    else:
        keep = {k: v for k, v in e.items() if k in KEEP}
    s = json.dumps(keep, ensure_ascii=False)
    print(f"{e['t']:8.2f} {ev:12} {s[:400]}")
