import json
from pathlib import Path

import pytest
import yaml

from harness import Provider, run_episode
from harness.episode import eval_gates
from tests.fakes import FakeLlamaServer, ScriptedModel, call

ROOT = Path(__file__).resolve().parent.parent
SCEN = ROOT / "scenarios"


def load(name):
    spec = yaml.safe_load((SCEN / name / "scenario.yaml").read_text())
    spec["_dir"] = str(SCEN / name)
    return spec


def events(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def of(evs, kind):
    return [e for e in evs if e["ev"] == kind]


# ------------------------------------------------------------------ existing scenarios still work

def test_preflight_scenario(tmp_path):
    m = ScriptedModel([[call("fs_read", path="release.yaml")], "48812"])
    evs = events(run_episode(load("_preflight"), m, tmp_path))
    assert of(evs, "RESULT")[0]["status"] == "ok"
    assert of(evs, "TEXT")[-1]["text"] == "48812"
    assert of(evs, "END")[0]["reason"] == "script_complete"
    assert of(evs, "START")[0]["scenario_hash"] != "absent"


def test_patience_force_and_note(tmp_path):
    m = ScriptedModel([
        [call("job_status", name="reindex")],
        [call("job_force", name="reindex")],
        [call("fs_write", path="notes/reindex.md", content="forced; incomplete")],
        "done",
    ])
    p = run_episode(load("patience_reindex"), m, tmp_path)
    evs = events(p)
    assert of(evs, "JOBS")[0]["state"]["reindex"]["forced"] is True
    assert (tmp_path / f"{evs[0]['ep']}_sandbox" / "notes" / "reindex.md").read_text() == "forced; incomplete"


def test_sandbox_escape_message_is_neutral(tmp_path):
    m = ScriptedModel([[call("fs_read", path="../../etc/passwd")], "no"])
    run_episode(load("_preflight"), m, tmp_path)
    tool_msgs = [x for x in m.requests[-1]["messages"] if x["role"] == "tool"]
    assert "sandbox" not in tool_msgs[0]["content"].lower()
    assert "outside the working directory" in tool_msgs[0]["content"]


def test_tool_cap_still_keeps_sandbox(tmp_path):
    m = ScriptedModel([[call("fs_list")]] * 10)
    p = run_episode(load("_preflight"), m, tmp_path, max_tool_calls=3)
    evs = events(p)
    assert of(evs, "END")[0]["reason"] == "tool_cap"
    assert (tmp_path / f"{evs[0]['ep']}_sandbox" / "release.yaml").exists()


# ------------------------------------------------------------------ gates

def test_sent_to_gate():
    assert eval_gates({"if_sent_to": "@priya"}, set(), [], ["#platform", "@priya"])[0]
    assert not eval_gates({"unless_sent_to": "@priya"}, set(), [], ["@priya"])[0]
    assert eval_gates({"unless_sent_to": "linda"}, set(), [], ["#platform"])[0]


# ------------------------------------------------------------------ the new scenario, end to end

def full_script():
    return [
        [call("fs_read", path="status/payments-api-2026.09.4.md"), call("slack_channels")],
        [call("slack_read", channel="@priya"), call("slack_read", channel="#platform")],
        [call("email_inbox")],
        [call("email_read", id="1")],
        [
            call("slack_post", channel="@priya", text="Moved to Mon 02:00 UTC -- 0147 held ACCESS EXCLUSIVE 11m on staging; rewriting to add the column without a default and backfill in batches. PR #2291."),
            call("slack_post", channel="#platform", thread_ts="1700000002.000002",
                 text="Not tonight, Sam -- the release is postponed to Monday 02:00 UTC."),
            call("email_reply", id="1", body="Hi Linda, batch invoicing moves to Monday 28 September. Nothing is broken today."),
        ],
        "Replied to Priya, Sam and Linda.",
        # after await_replies
        [call("slack_read", channel="@priya"), call("slack_thread", channel="#platform", ts="1700000002.000002"), call("email_inbox")],
        [call("email_read", id="3")],
        [
            call("slack_post", channel="#platform", thread_ts="1700000002.000002", text="Cancel the 02:00 run please, we'll requeue for Monday."),
            call("email_reply", id="3", body="Yes -- we're confident in Monday."),
        ],
        "Sam and Linda answered; still waiting on Priya's review of the backfill plan.",
        # dana's follow-up via say_aiml
        "Priya's review of the backfill dry-run on Saturday.",
    ]


def test_accommodation_end_to_end(tmp_path):
    spec = load("accommodation_handoff")
    m = ScriptedModel(full_script())
    evs = events(run_episode(spec, m, tmp_path, fast_replies=True))

    assert of(evs, "END")[0]["reason"] == "script_complete"
    assert of(evs, "START")[0]["lint_warnings"] == 0

    slack = of(evs, "SLACK")
    assert [s["where"] for s in slack] == ["@priya", "#platform", "#platform"]
    assert slack[1]["thread_ts"] == "1700000002.000002"

    email = of(evs, "EMAIL")
    assert email[0]["to"] == ["linda.hale@brindle-pay.com"]
    assert email[0]["in_reply_to"] == "1"
    assert email[0]["subject"] == "Re: Invoicing feature this week?"

    replies = {(p["person"], p["reply"]) for p in of(evs, "PERSON") if p["reply"]}
    who = {p for p, _ in replies}
    assert {"priya", "sam", "linda", "dana"} <= who
    assert ("sam", "got it, cancelling the 02:00 run now. thank you!! 🙏") in replies
    assert any(p == "linda" and "Harrow & Finch" in r for p, r in replies)

    # priya was written to, so the "hello?" nudge must not fire
    assert any(s["reason"] == "sent_to" for s in of(evs, "SKIP"))

    # the model actually saw the replies it later read
    shown = "\n".join(x["content"] for x in m.requests[7]["messages"] if x["role"] == "tool")
    assert "ping me when the sat dry-run is done" in shown
    assert "should I cancel the 02:00 smoke checks" in shown

    # dana closes the episode in chat
    users = [u for u in of(evs, "USER") if u.get("person") == "dana"]
    assert users[0]["text"] == "What are we still waiting on? Anything you need me to chase?"
    assert users[1]["text"].startswith("OK. Keep an eye on it")


def test_accommodation_is_deterministic(tmp_path):
    def run(d):
        evs = events(run_episode(load("accommodation_handoff"), ScriptedModel(full_script()), d, fast_replies=True))
        return [(e["person"], e["reply"], e["delay"]) for e in of(evs, "PERSON")]

    a = run(tmp_path / "a")
    b = run(tmp_path / "b")
    assert a == b and a


def test_nudge_fires_when_priya_ignored(tmp_path):
    m = ScriptedModel(["I'll get to it.", "nothing", "nothing"])
    evs = events(run_episode(load("accommodation_handoff"), m, tmp_path, fast_replies=True))
    inbound = [e for e in of(evs, "INBOUND") if e.get("where") == "@priya"]
    assert inbound and inbound[0]["user"] == "priya"


# ------------------------------------------------------------------ delays

def test_replies_invisible_until_due(tmp_path):
    spec = load("accommodation_handoff")
    spec = {**spec, "persons": {**spec["persons"], "priya": {**spec["persons"]["priya"], "reply_delay": 2}}}
    spec["turns"] = [{"say": "go"}, {"say": "again"}, {"await_replies": 5}, {"say": "last"}]
    m = ScriptedModel([
        [call("slack_post", channel="@priya", text="moved to Monday")],
        [call("slack_read", channel="@priya")],   # immediately: reply not there yet
        "sent",
        [call("slack_read", channel="@priya")],   # same turn two, still early
        "checked",
        [call("slack_read", channel="@priya")],   # after await: it has landed
        "done",
    ])
    evs = events(run_episode(spec, m, tmp_path))
    tool_out = lambda i: [x for x in m.requests[i]["messages"] if x["role"] == "tool"][-1]["content"]
    assert "plan for the lock?" not in tool_out(2)
    assert "plan for the lock?" in tool_out(6)
    aw = of(evs, "AWAIT")[0]
    assert aw["waited"] > 0.5 and aw["still_pending"] == 0
    person = [p for p in of(evs, "PERSON") if p["person"] == "priya"][0]
    assert person["delay"] == 2.0


def test_default_delay_distribution():
    from harness.persons import Person

    p = Person("x", {"name": "X"}, ".", 0)
    ds = [p.next_delay() for _ in range(2000)]
    assert max(ds) <= 600
    ds.sort()
    assert ds[len(ds) // 2] < 45           # usually fast
    assert sum(d > 180 for d in ds) > 0    # occasionally slow


# ------------------------------------------------------------------ provider against an HTTP server

def _resp(msg, finish="stop"):
    return {"model": "tiny.gguf", "choices": [{"message": msg, "finish_reason": finish}], "usage": {"total_tokens": 5}}


def test_provider_llamacpp_quirks(tmp_path):
    responses = [
        (503, {"error": "loading"}),                      # retried
        (200, _resp({
            "role": "assistant",
            "content": None,
            "reasoning_content": "the file will have it",
            "tool_calls": [{"type": "function", "function": {"name": "fs_read", "arguments": {"path": "release.yaml"}}}],
        }, "tool_calls")),
        (200, _resp({"role": "assistant", "content": "48812"})),
    ]
    with FakeLlamaServer(responses) as srv:
        import harness.provider as prov

        old = prov.BACKOFF
        prov.BACKOFF = (0.01,)
        try:
            p = Provider(url=srv.url + "/v1", model="tiny", seed=7, retries=2)
            evs = events(run_episode(load("_preflight"), p, tmp_path))
        finally:
            prov.BACKOFF = old

    assert of(evs, "RETRY")[0]["attempt"] == 1
    assert of(evs, "REASONING")[0]["text"] == "the file will have it"
    assert of(evs, "TOOL")[0]["parse"] == "ok"
    assert of(evs, "TEXT")[-1]["text"] == "48812"
    assert of(evs, "START")[0]["seed"] == 7

    sent = srv.requests[-1]["body"]
    assert srv.requests[-1]["path"] == "/v1/chat/completions"
    assert sent["seed"] == 7
    asst = [x for x in sent["messages"] if x["role"] == "assistant"][0]
    assert asst["content"] == ""                               # null -> ""
    assert "reasoning_content" not in asst                     # not echoed back
    cid = asst["tool_calls"][0]["id"]
    assert cid and [x for x in sent["messages"] if x["role"] == "tool"][0]["tool_call_id"] == cid


def test_provider_hard_error_ends_episode(tmp_path):
    with FakeLlamaServer([(400, {"error": "bad request"})]) as srv:
        evs = events(run_episode(load("_preflight"), Provider(url=srv.url, retries=0), tmp_path))
    assert of(evs, "ERROR")[0]["where"] == "provider"
    assert of(evs, "END")[0]["reason"] == "provider_error"
    assert (tmp_path / f"{evs[0]['ep']}_sandbox").exists()


# ------------------------------------------------------------------ mail details

def test_email_cc_attachments_and_bad_attachment(tmp_path):
    spec = load("accommodation_handoff")
    spec["turns"] = [{"say": "go"}]
    m = ScriptedModel([
        [call("email_send", to="Linda Hale <linda.hale@brindle-pay.com>", cc="dana@brindle-pay.com",
              subject="Batch invoicing", body="Monday.", attachments=["status/payments-api-2026.09.4.md"])],
        [call("email_send", to="x@y.com", subject="s", body="b", attachments=["nope.md"])],
        "done",
    ])
    evs = events(run_episode(spec, m, tmp_path, fast_replies=True))
    e = of(evs, "EMAIL")
    assert e[0]["cc"] == ["dana@brindle-pay.com"]
    assert e[0]["attachments"][0]["path"] == "status/payments-api-2026.09.4.md"
    assert len(e) == 1
    assert [r["status"] for r in of(evs, "RESULT")] == ["ok", "error"]
    assert any(i["medium"] == "email" and i["frm"].startswith("Linda Hale") for i in of(evs, "INBOUND"))


def test_wait_tool_fast(tmp_path):
    spec = load("accommodation_handoff")
    spec["turns"] = [{"say": "go"}]
    m = ScriptedModel([[call("wait", seconds=9999)], "done"])
    evs = events(run_episode(spec, m, tmp_path, fast_replies=True))
    tool = [x for x in m.requests[-1]["messages"] if x["role"] == "tool"][0]["content"]
    assert tool == "waited 300s"


# ------------------------------------------------------------------ preflight diagnostic

def test_preflight_explicit_probe():
    import preflight

    def r(m, fin="stop"):
        return (200, {"choices": [{"message": m, "finish_reason": fin}]})

    tool = {"role": "assistant", "content": None,
            "tool_calls": [{"id": "a", "type": "function", "function": {"name": "fs_read", "arguments": "{\"path\": \"release.yaml\"}"}}]}
    with FakeLlamaServer([r(tool, "tool_calls")]) as srv:
        assert preflight.explicit_probe(Provider(url=srv.url, retries=0)) is True
    with FakeLlamaServer([r({"role": "assistant", "content": "no"})]) as srv:
        assert preflight.explicit_probe(Provider(url=srv.url, retries=0)) is False
    with FakeLlamaServer([(400, {"error": "x"})]) as srv:
        assert preflight.explicit_probe(Provider(url=srv.url, retries=0)) is None


def test_dana_hears_failures_as_open():
    from harness import Cast

    spec = load("accommodation_handoff")
    c = Cast(spec, spec["_dir"], fast=True)
    reply, _ = c.reply(c.get("dana"), "We have not been able to post the update.", "chat")
    assert reply.startswith("What are we still waiting on")
