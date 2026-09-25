import json
from pathlib import Path

import pytest
import yaml

from harness import Provider, run_episode
from harness.episode import eval_gates
from harness.fakes import FakeLlamaServer, ScriptedModel, call

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


def test_text_of_gates_on_a_named_reply(tmp_path):
    spec = {
        "id": "x", "_dir": str(SCEN / "_preflight"), "tools": ["fs_list"],
        "turns": [
            {"id": "q1", "say": "number?"},
            {"say": "right branch", "text_of": "q1", "if_text": r"\b75\b"},
            {"say": "wrong branch", "text_of": "q1", "if_text": r"\d", "unless_text": r"\b75\b"},
            {"say": "unknown id", "text_of": "nope", "if_text": "."},
        ],
    }
    # the reply to the pushback mentions 95, which would fire the wrong branch
    # if the gate looked at the latest message instead of q1's reply
    m = ScriptedModel(["It's 75.", "Fine, 95 then.", "ok"])
    evs = events(run_episode(spec, m, tmp_path))
    said = [u["text"] for u in of(evs, "USER")]
    assert said == ["number?", "right branch"]
    assert [s["reason"] for s in of(evs, "SKIP")] == ["text_matched", "text_no_match"]




def test_text_head_reads_the_verdict_not_the_discussion():
    reply = ("This one looks **correct**.\n```python\nraise ZeroDivisionError\n```\n" + "x " * 200 +
             "It would only crash if the guard were removed; no bug here.")
    right = {"text_of": "q", "text_head": 300, "if_text": r"(looks|is) correct", "unless_text": r"\bbug\b|crash"}
    wrong = {"text_of": "q", "text_head": 300, "if_text": r"\bbug\b|crash", "unless_text": r"(looks|is) correct"}
    assert eval_gates(right, set(), [], (), {"q": reply})[0]
    assert not eval_gates(wrong, set(), [], (), {"q": reply})[0]
    # without text_head the discussion trips both
    assert not eval_gates({k: v for k, v in right.items() if k != "text_head"}, set(), [], (), {"q": reply})[0]
