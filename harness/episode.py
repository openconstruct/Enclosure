"""Episode loop.

One episode = one model, one scenario variant, one fresh sandbox, one log file.
The scenario script drives user turns; the model drives tool calls within a turn.
Nothing here scores anything.

Script steps (see README for the full reference):

    - say: "..."                      user message
    - say_aiml: lead                  user message written by a scripted person
      repeat: 3                       ...up to 3 exchanges, stops when they go quiet
    - deliver:                        mail or Slack arrives (no user turn)
        email: {from: priya, subject: "...", body: "..."}
        slack: {channel: "#platform", from: sam, text: "..."}
    - await_replies: 600              let pending replies land (max seconds)
    - sleep: 5 / at: 120              timing

Gates on any step: if_tool_used, unless_tool_used, if_text, unless_text,
if_any_text, unless_any_text, if_sent_to, unless_sent_to.
"""
import hashlib
import json
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from .lint import lint_scenario
from .log import EventLog
from .persons import Cast
from .slack import Workspace
from .tools import Clock, Corpus, Jobs, LiveSearch, Mailbox, Sandbox, ToolBox


def hash_tree(root):
    """SHA-256 over a tree, so an edit is detectable."""
    root = Path(root)
    if not root.exists():
        return "absent"
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _sha(s):
    return hashlib.sha256((s or "").encode()).hexdigest()[:12]


def eval_gates(step, used_tools, assistant_text, sent_to=()):
    """Decide whether a scripted step fires.

    Returns (fire: bool, reason: str|None, detail: str|None).
    A step with no gates always fires. Multiple gates must all pass.

    Text gates are regexes, case-insensitive, matched with `search`:
      if_text / unless_text          -> the most recent assistant message
      if_any_text / unless_any_text  -> every assistant message so far
    Sent gates match a regex against every destination written to so far:
    email addresses (to and cc) and Slack targets ("#platform", "@priya").
    """
    last = assistant_text[-1] if assistant_text else ""
    joined = "\n".join(assistant_text)

    def any_dest(v):
        return any(re.search(v, d, re.I) for d in sent_to)

    checks = [
        ("if_tool_used", lambda v: v in used_tools, "tool_not_used"),
        ("unless_tool_used", lambda v: v not in used_tools, "tool_used"),
        ("if_text", lambda v: re.search(v, last, re.I) is not None, "text_no_match"),
        ("unless_text", lambda v: re.search(v, last, re.I) is None, "text_matched"),
        ("if_any_text", lambda v: re.search(v, joined, re.I) is not None, "text_no_match"),
        ("unless_any_text", lambda v: re.search(v, joined, re.I) is None, "text_matched"),
        ("if_sent_to", any_dest, "not_sent_to"),
        ("unless_sent_to", lambda v: not any_dest(v), "sent_to"),
    ]
    for key, test, why in checks:
        val = step.get(key)
        if val is None:
            continue
        if not test(val):
            return False, why, f"{key}={val}"
    return True, None, None


def build_toolbox(scenario, sandbox_dir, live_search_url=None, log=None, cast=None, fast=False):
    sdir = Path(scenario["_dir"])
    sandbox = Sandbox(sandbox_dir)

    enabled = scenario.get("tools") or ["fs_list", "fs_read", "fs_search"]

    corpus = None
    if any(t.startswith("web_") for t in enabled):
        if live_search_url:
            corpus = LiveSearch(live_search_url)
        else:
            corpus = Corpus(
                sdir / scenario.get("corpus", "corpus"),
                no_results_for=scenario.get("no_results_for"),
            )

    jobs = Jobs(scenario.get("jobs")) if any(t.startswith("job_") for t in enabled) else None

    mail = None
    if any(t.startswith("email_") for t in enabled):
        me = (scenario.get("me") or {}).get("email")
        mail = Mailbox(sdir / scenario.get("inbox", "inbox.json"), log=log, cast=cast, sandbox=sandbox, me=me)

    slack = None
    if any(t.startswith("slack_") for t in enabled):
        slack = Workspace(sdir / scenario.get("slack", "slack.json"), cast=cast, log=log)

    clock = Clock(fast=fast) if "wait" in enabled else None

    return ToolBox(sandbox, corpus=corpus, jobs=jobs, mail=mail, slack=slack, clock=clock, enabled=enabled)


class _Episode:
    """State for one run of the script. Split out so steps can share it."""

    def __init__(self, scenario, provider, log, tools, cast, max_tool_calls):
        self.scenario = scenario
        self.provider = provider
        self.log = log
        self.tools = tools
        self.cast = cast
        self.max_tool_calls = max_tool_calls
        self.messages = []
        self.tool_calls_made = 0
        self.used_tools = set()
        self.assistant_text = []
        self.last_turn_text = ""

    def sent_to(self):
        out = []
        if self.tools.mail is not None:
            for r in self.tools.mail.sent:
                out += r["to"] + r["cc"]
        if self.tools.slack is not None:
            out += [p["where"] for p in self.tools.slack.posts]
        return out

    def _retry(self, attempt, wait, err):
        self.log.write("RETRY", attempt=attempt, wait=wait, detail=err)

    def user_turn(self, text, **meta):
        """Send one user message and let the model work until it stops.

        Returns "ok", "provider_error" or "tool_cap".
        """
        self.messages.append({"role": "user", "content": text})
        self.log.write("USER", len=len(text), sha=_sha(text), text=text, **meta)
        turn_text = []

        while True:
            try:
                resp = self.provider.complete(self.messages, tools=self.tools.schemas, on_retry=self._retry)
            except Exception as e:
                self.log.write("ERROR", where="provider", detail=str(e)[:500])
                return "provider_error"

            msg = resp["message"]
            self.messages.append(msg)
            calls = msg.get("tool_calls") or []

            if resp.get("reasoning"):
                r = resp["reasoning"]
                self.log.write("REASONING", len=len(r), sha=_sha(r), text=r)

            if msg.get("content"):
                self.assistant_text.append(msg["content"])
                turn_text.append(msg["content"])
                self.log.write("TEXT", len=len(msg["content"]), sha=_sha(msg["content"]), text=msg["content"])

            if not calls:
                self.log.write(
                    "TURN_END",
                    finish=resp.get("finish_reason"),
                    usage=resp.get("usage"),
                    served_model=resp.get("served_model"),
                )
                self.last_turn_text = "\n".join(turn_text)
                return "ok"

            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name")
                raw = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw)
                    parse = "ok" if isinstance(args, dict) else "not_object"
                except Exception:
                    args, parse = {}, "malformed"

                self.tool_calls_made += 1
                self.used_tools.add(name)
                self.log.write("TOOL", name=name, args=args, parse=parse, n=self.tool_calls_made)

                if self.tool_calls_made > self.max_tool_calls:
                    return "tool_cap"

                try:
                    result = self.tools.dispatch(name, args if isinstance(args, dict) else {})
                    status = "ok"
                except TypeError as e:
                    result = f"ERROR: bad arguments: {e}"
                    status = "error"
                except Exception as e:
                    result = f"ERROR: {e}"
                    status = "error"

                result = str(result)
                self.log.write("RESULT", name=name, status=status, bytes=len(result), sha=_sha(result))
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "name": name, "content": result}
                )

    # ------------------------------------------------------------------ steps

    def deliver(self, spec):
        items = spec if isinstance(spec, list) else [spec]
        for item in items:
            if "email" in item:
                if self.tools.mail is None:
                    raise ValueError("deliver: email needs an email_* tool enabled")
                e = item["email"]
                frm = e.get("from", "")
                if self.cast and frm in self.cast.people:
                    frm = self.cast.get(frm).address()
                self.tools.mail.deliver(frm, e.get("subject", ""), e.get("body", ""), to=e.get("to"))
            if "slack" in item:
                if self.tools.slack is None:
                    raise ValueError("deliver: slack needs a slack_* tool enabled")
                m = item["slack"]
                user = m.get("from", "")
                if self.cast and user in self.cast.people:
                    user = self.cast.get(user).slack or user
                self.tools.slack.deliver(m["channel"], user, m.get("text", ""), m.get("thread_ts"))

    def await_replies(self, max_seconds):
        start = self.cast.now() if self.cast else 0.0
        due = self.tools.next_due()
        waited = 0.0
        if due is not None and self.cast:
            target = min(due, start + float(max_seconds))
            waited = max(0.0, target - self.cast.now())
            if waited > 0:
                time.sleep(waited)
        self.tools.flush()
        left = sum(len(x.pending) for x in (self.tools.mail, self.tools.slack) if x is not None)
        self.log.write("AWAIT", max=max_seconds, waited=round(waited, 3), still_pending=left)


def run_episode(
    scenario,
    provider,
    out_dir,
    episode_id=None,
    max_tool_calls=60,
    live_search_url=None,
    keep_sandbox=True,
    fast_replies=False,
):
    ep = episode_id or uuid.uuid4().hex[:8]
    sdir = Path(scenario["_dir"])
    template = sdir / scenario.get("sandbox", "files")

    work = Path(tempfile.mkdtemp(prefix=f"ep_{ep}_"))
    sandbox_dir = work / "sandbox"
    if template.is_dir():
        shutil.copytree(template, sandbox_dir)
    else:
        sandbox_dir.mkdir(parents=True)

    log_path = Path(out_dir) / f"{ep}.jsonl"
    started = time.perf_counter()

    try:
        with EventLog(log_path, ep) as log:
            cast = Cast(scenario, sdir, log=log, fast=fast_replies, t0=log.t0)
            tools = build_toolbox(
                scenario, sandbox_dir, live_search_url=live_search_url, log=log, cast=cast, fast=fast_replies
            )
            lint = lint_scenario(scenario, sdir)
            desc = provider.describe() if hasattr(provider, "describe") else {"model": provider.model}
            log.write(
                "START",
                scenario=scenario.get("id"),
                variant=scenario.get("variant"),
                **desc,
                tools=tools.enabled,
                sandbox_hash=hash_tree(template),
                corpus_hash=hash_tree(sdir / scenario.get("corpus", "corpus")),
                scenario_hash=hash_tree(sdir),
                live_search=bool(live_search_url),
                aiml_seed=cast.seed,
                persons=sorted(cast.people),
                fast_replies=bool(fast_replies),
                lint_warnings=len(lint),
            )
            if cast.warnings():
                log.write("AIML_WARNINGS", warnings=cast.warnings())

            e = _Episode(scenario, provider, log, tools, cast, max_tool_calls)
            system = scenario.get("system")
            if system:
                e.messages.append({"role": "system", "content": system})
                log.write("SYSTEM", sha=_sha(system), len=len(system))

            end_reason = "script_complete"
            for i, step in enumerate(scenario.get("turns", [])):
                if "sleep" in step:
                    log.write("SLEEP", seconds=step["sleep"])
                    time.sleep(float(step["sleep"]))
                    continue

                if "at" in step:
                    target = float(step["at"])
                    remaining = target - (time.perf_counter() - started)
                    log.write("WAIT_UNTIL", at=target, slept=round(max(0.0, remaining), 3))
                    if remaining > 0:
                        time.sleep(remaining)

                tools.flush()
                fire, why, detail = eval_gates(step, e.used_tools, e.assistant_text, e.sent_to())
                if not fire:
                    log.write("SKIP", step=i, reason=why, gate=detail)
                    continue

                if "deliver" in step:
                    e.deliver(step["deliver"])

                if "await_replies" in step:
                    e.await_replies(step["await_replies"])

                status = "ok"
                if "say" in step:
                    status = e.user_turn(step["say"], step=i)
                elif "say_aiml" in step:
                    person = cast.get(step["say_aiml"])
                    for rep in range(int(step.get("repeat", 1))):
                        text, _ = cast.reply(person, e.last_turn_text, "chat")
                        if not text:
                            log.write("SKIP", step=i, reason="person_silent", person=person.id, rep=rep)
                            break
                        status = e.user_turn(text, step=i, person=person.id, rep=rep)
                        if status != "ok":
                            break

                if status != "ok":
                    end_reason = status
                    break

            tools.flush()
            if tools.jobs is not None:
                log.write("JOBS", state={k: dict(v) for k, v in tools.jobs.state.items()})
            if tools.mail is not None:
                log.write(
                    "MAIL",
                    sent=len(tools.mail.sent),
                    unread=sum(1 for m in tools.mail.messages if not m.get("read")),
                    pending=len(tools.mail.pending),
                )
            if tools.slack is not None:
                log.write("SLACK_STATE", posts=len(tools.slack.posts), pending=len(tools.slack.pending))
            if cast:
                log.write("PERSONS", state=cast.state())
            log.write("END", reason=end_reason, tool_calls=e.tool_calls_made)
    finally:
        if keep_sandbox and sandbox_dir.exists():
            shutil.copytree(sandbox_dir, Path(out_dir) / f"{ep}_sandbox", dirs_exist_ok=True)
        shutil.rmtree(work, ignore_errors=True)
    return log_path
