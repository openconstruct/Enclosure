"""Scripted people.

A person is someone the model can email, message on Slack, or who speaks as
the user in chat. Each is driven by an AIML bot, so the same message in the
same state always gets the same reply. An LLM on the other side would make
every episode a two-model interaction, and the measurement would be of the pair.

Scenario config:

    aiml_seed: 0                      # fixed per scenario, logged
    aiml_sets: {teams: [platform, data platform]}     # or a path to a file, one phrase per line
    aiml_maps: {owners: {platform: Priya}}            # or a path to a JSON object
    reply_delay: {median: 30, max: 600}               # seconds; or a number; 0 = instant
    persons:
      priya:
        name: Priya Raman             # display name
        email: priya@corp.example     # optional
        slack: priya                  # optional handle (no @)
        aiml: people/priya.aiml       # one file or a list, relative to scenario dir
        properties: {role: staff engineer}   # <bot name="role"/>
        predicates: {mood: busy}      # initial <get name="mood"/>
        channels: mentions            # mentions | all  -- when to answer in channels
        reply_delay: 5                # overrides the scenario default for this person

Predicates the harness sets before every reply, usable in <condition>:

    medium    email | slack | chat
    subject   email subject                (email)
    role      to | cc                      (email)
    channel   channel name or "dm"         (slack)
    thread    yes | no                     (slack)
    mentioned yes | no                     (slack)

Reply delay: each email or Slack reply lands after a seeded random delay,
lognormal around `median`, capped at `max`. With the default (30s median,
600s cap) most replies arrive inside a minute or two and a few take several
minutes. Same seed, same sequence of delays, so timing is as reproducible as
content. Replies are invisible until due; the model has to come back for them.
Chat replies (`say_aiml`) are immediate -- the user is right there.

An empty reply means the person does not answer. That is the normal way to
script silence: write no catch-all category, or one that returns nothing.
"""
import email.utils
import json
import math
import random
import re
import time
import zlib
from pathlib import Path

from .aiml import Bot


DEFAULT_DELAY = {"median": 30, "max": 600}


def _delay_cfg(v):
    if v is None:
        return dict(DEFAULT_DELAY)
    if isinstance(v, (int, float)):
        return {"fixed": float(v)}
    return {"median": float(v.get("median", 30)), "max": float(v.get("max", 600)), "min": float(v.get("min", 0))}


def _load_sets(spec, sdir):
    out = {}
    for name, v in (spec or {}).items():
        if isinstance(v, str):
            v = [ln.strip() for ln in (Path(sdir) / v).read_text(encoding="utf-8").splitlines() if ln.strip()]
        out[name] = list(v)
    return out


def _load_maps(spec, sdir):
    out = {}
    for name, v in (spec or {}).items():
        if isinstance(v, str):
            v = json.loads((Path(sdir) / v).read_text(encoding="utf-8"))
        out[name] = dict(v)
    return out


class Person:
    def __init__(self, pid, cfg, scenario_dir, seed, sets=None, maps=None, delay=None):
        self.id = pid
        self.name = cfg.get("name") or pid
        self.email = (cfg.get("email") or "").strip().lower() or None
        self.slack = (cfg.get("slack") or "").strip().lstrip("@").lower() or None
        self.channels = cfg.get("channels", "mentions")
        files = cfg.get("aiml") or []
        if isinstance(files, str):
            files = [files]
        self.aiml_files = [Path(scenario_dir) / f for f in files]
        props = {"name": self.name, **(cfg.get("properties") or {})}
        # per-person seed: stable across episodes and models, different per person
        pseed = zlib.crc32(f"{int(seed)}:{pid}".encode())
        self.bot = Bot(
            self.aiml_files,
            seed=pseed,
            properties=props,
            predicates=cfg.get("predicates"),
            sets=sets,
            maps=maps,
        )
        self.delay = _delay_cfg(cfg["reply_delay"]) if "reply_delay" in cfg else (delay or dict(DEFAULT_DELAY))
        self._delay_rng = random.Random(zlib.crc32(f"{int(seed)}:{pid}:delay".encode()))

    def next_delay(self):
        """Seconds until this person's next reply lands. Deterministic per seed."""
        d = self.delay
        if "fixed" in d:
            return max(0.0, d["fixed"])
        x = d["median"] * math.exp(self._delay_rng.gauss(0.0, 1.0))
        return round(min(d["max"], max(d.get("min", 0.0), x)), 3)

    @property
    def first(self):
        return self.name.split()[0].lower()

    def address(self):
        return email.utils.formataddr((self.name, self.email)) if self.email else self.name


class Cast:
    """Everyone in the scenario, plus the logic for who answers what."""

    def __init__(self, spec, scenario_dir, log=None, fast=False, t0=None):
        self.seed = int(spec.get("aiml_seed", 0) or 0)
        self.log = log
        self.fast = fast
        self.t0 = time.perf_counter() if t0 is None else t0
        sets = _load_sets(spec.get("aiml_sets"), scenario_dir)
        maps = _load_maps(spec.get("aiml_maps"), scenario_dir)
        delay = _delay_cfg(spec.get("reply_delay"))
        self.people = {
            pid: Person(pid, cfg or {}, scenario_dir, self.seed, sets=sets, maps=maps, delay=delay)
            for pid, cfg in (spec.get("persons") or {}).items()
        }

    def now(self):
        """Seconds since episode start -- the same clock as the event log."""
        return time.perf_counter() - self.t0

    def __bool__(self):
        return bool(self.people)

    def get(self, pid):
        if pid not in self.people:
            raise ValueError(f"no person '{pid}' in scenario")
        return self.people[pid]

    def by_email(self, addr):
        a = (addr or "").strip().lower()
        for p in self.people.values():
            if p.email and p.email == a:
                return p
        return None

    def by_slack(self, handle):
        h = (handle or "").strip().lstrip("@").lower()
        for p in self.people.values():
            if p.slack and p.slack == h:
                return p
        return None

    def mentioned_in(self, text):
        """People @-mentioned in a Slack message, by handle or first name."""
        found = []
        for tok in re.findall(r"<?@([\w.\-]+)>?", text or ""):
            t = tok.lower().rstrip(".")
            for p in self.people.values():
                if p not in found and (t == p.slack or t == p.first):
                    found.append(p)
        return found

    def reply(self, person, text, medium, **predicates):
        """Run one person's bot on one message. Logs PERSON.

        Returns (reply, due) where due is the episode time the reply becomes
        visible. reply is '' when the person says nothing.
        """
        reply, trace = person.bot.respond(text, {"medium": medium, **predicates})
        delay = 0.0
        if reply and medium != "chat":
            # draw only for real replies, so silence does not shift later delays
            delay = person.next_delay()
            if self.fast:
                delay = 0.0
        due = round(self.now() + delay, 3)
        if self.log is not None:
            self.log.write(
                "PERSON",
                person=person.id,
                medium=medium,
                context={k: v for k, v in predicates.items() if v is not None},
                matched=trace["matched"],
                random=trace["random"],
                set=trace["set"],
                reply=reply,
                delay=delay,
                due=due,
            )
        return reply, due

    def state(self):
        return {pid: {"predicates": dict(p.bot.predicates), "that": p.bot.that} for pid, p in self.people.items()}

    def warnings(self):
        return {pid: list(p.bot.warnings) for pid, p in self.people.items() if p.bot.warnings}


def parse_addresses(value):
    """'a@x, B <b@y>' or ['a@x', ...] -> ['a@x', 'b@y'] (lowercased)."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    return [a.strip().lower() for _, a in email.utils.getaddresses([str(value)]) if a.strip()]
