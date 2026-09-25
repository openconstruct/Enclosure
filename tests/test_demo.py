"""The demo scenario: every tool once, every script step once."""
import json
from pathlib import Path

import yaml

import harness.episode
from harness import ALL_SCHEMAS, run_episode
from harness.fakes import ScriptedModel, call
from harness.slack import _TS0

DEMO = Path(__file__).resolve().parent.parent / "scenarios" / "demo"
SAM_FLOUR = f"{_TS0 + 1}.000001"    # first #kitchen message; its reply is 2
SAM_STARTER = f"{_TS0 + 3}.000003"


def load():
    spec = yaml.safe_load((DEMO / "scenario.yaml").read_text())
    spec["_dir"] = str(DEMO)
    return spec


def events(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def of(evs, kind):
    return [e for e in evs if e["ev"] == kind]


SCRIPT = [
    # files
    [call("fs_list", path="."), call("fs_read", path="checklist.md")], "Here's the checklist.",
    [call("fs_search", query="service")], "equipment/oven.md: Tuesday 29 September, 08:00.",
    [call("fs_rename", path="notes/todo.txt", new_path="notes/todo-old.txt"),
     call("fs_rename_many", path="receipts", pattern="^rcpt-", replacement="receipt-")], "Renamed.",
    [call("fs_write", path="notes/today.md", content="Read the checklist.\nTidied notes and receipts.\n")], "Written.",
    # web
    [call("web_search", query="sourdough proofing temperature")],
    [call("web_fetch", url="https://www.breadcraft.example/guides/proofing-sourdough")],
    "Proof at 24 to 26°C.",
    # jobs and time
    [call("job_status", name="mixer_clean")], [call("wait", seconds=10)],
    [call("job_status", name="mixer_clean")], [call("job_status", name="mixer_clean")], "The mixer is done.",
    [call("job_status", name="label_print")], [call("job_force", name="label_print")], "Forced it through.",
    # mail
    [call("email_inbox")], [call("email_read", id="1")],
    [call("email_reply", id="1", body="Tuesday at 7 is perfect, thanks."),
     call("email_send", to="priya.nair@gmail.com", subject="Your cake",
          body="Your chocolate cake is ready to collect on Wednesday at 4.")],
    "Replied to Mo and emailed Priya.",
    # Slack
    [call("slack_channels"), call("slack_users")], [call("slack_read", channel="#kitchen")],
    [call("slack_thread", channel="#kitchen", ts=SAM_FLOUR)], [call("slack_search", query="delivery")],
    [call("slack_post", channel="#kitchen", text="@sam flour arrives Tuesday at 7.")],
    [call("slack_react", channel="#kitchen", ts=SAM_STARTER, emoji="thumbsup")], "Posted and reacted.",
    # calendars
    [call("cal_calendars")], [call("cal_events", calendar="shared", start="2026-09-28", end="2026-10-04")],
    [call("cal_event", calendar="shared", id="o1")],
    [call("cal_attachment", calendar="shared", id="o1", name="service-sheet.txt")],
    [call("cal_search", query="tasting")],
    [call("cal_add", calendar="shared", title="Staff tasting", start="2026-10-01 15:00", end="2026-10-01 15:30",
          location="Shop")],
    [call("cal_update", calendar="shared", id="o1", start="2026-09-29 10:00", end="2026-09-29 12:00")],
    "Booked the tasting and moved the oven service to 10:00.",
    # the two say_aiml exchanges with Ines
    "Mo confirmed Tuesday at 7.", "Nothing else today.",
]


def test_demo_uses_every_tool_once(tmp_path, monkeypatch):
    monkeypatch.setattr(harness.episode.time, "sleep", lambda s: None)  # `sleep` and `at` steps
    spec = load()
    assert sorted(spec["tools"]) == sorted(ALL_SCHEMAS), "the demo must offer every tool"

    evs = events(run_episode(spec, ScriptedModel(list(SCRIPT)), tmp_path, fast_replies=True))
    tools = of(evs, "TOOL")
    results = of(evs, "RESULT")
    assert sorted({t["name"] for t in tools}) == sorted(ALL_SCHEMAS)
    assert all(r["status"] == "ok" for r in results), [r for r in results if r["status"] != "ok"]
    assert of(evs, "END")[0]["reason"] == "script_complete"

    # every step type ran
    for kind in ["AWAIT", "SLEEP", "WAIT_UNTIL", "EMAIL", "SLACK", "SLACK_REACT", "CAL_ADD", "CAL_UPDATE",
                 "PERSON", "INBOUND", "JOBS"]:
        assert of(evs, kind), kind
    said = [u["text"] for u in of(evs, "USER")]
    assert "Great, 24 to 26 matches what I had." in said           # text_of + if_text fired
    assert not any("double-check" in s for s in said)               # its opposite did not
    gates = {s["gate"].split("=")[0] for s in of(evs, "SKIP")}
    assert gates == {"unless_tool_used", "unless_sent_to", "unless_text", "unless_any_text"}, gates
    assert [u for u in of(evs, "USER") if u.get("person") == "ines"], "say_aiml wrote the user's side"
    assert {p["person"] for p in of(evs, "PERSON")} >= {"mo", "sam", "ines"}

    sandbox = tmp_path / f"{evs[0]['ep']}_sandbox"
    assert (sandbox / "notes" / "todo-old.txt").is_file() and (sandbox / "receipts" / "receipt-0902.txt").is_file()
    assert of(evs, "JOBS")[0]["state"]["label_print"]["forced"] is True


def test_demo_no_results_query_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(harness.episode.time, "sleep", lambda s: None)
    spec = load()
    spec["turns"] = [{"say": "look it up"}]
    m = ScriptedModel([[call("web_search", query="croissant lamination")], "Nothing found."])
    run_episode(spec, m, tmp_path, fast_replies=True)
    tool_msg = [x for x in m.requests[-1]["messages"] if x["role"] == "tool"][-1]
    assert "no results" in tool_msg["content"].lower()
