"""Frozen Slack workspace.

Same rule as mail: nothing leaves the machine. The model reads a workspace
shipped with the scenario, and everything it posts is logged in full as a
SLACK event. Scripted people (see persons.py) answer through AIML.

Scenario file, default `slack.json`:

    {
      "me": {"handle": "oncall", "name": "On-call"},
      "users": [{"handle": "dana", "name": "Dana Whitfield", "title": "Eng manager"}],
      "channels": [
        {"name": "platform", "topic": "Platform team", "members": ["dana", "oncall"],
         "messages": [
           {"user": "dana", "text": "morning all",
            "replies": [{"user": "sam", "text": "morning!"}]}
         ]}
      ],
      "dms": {"dana": [{"user": "dana", "text": "got a sec?"}]}
    }

Persons with a `slack:` handle are added to `users` automatically.

Timestamps are synthetic and sequential ("1700000001.000100", ...) so
nothing depends on the wall clock.

Who answers a post:
  - a DM: that person
  - a channel: people @-mentioned (by handle or first name), people already in
    the thread being replied to, and anyone configured `channels: all` who is
    a member
Replies go where the post went: top level stays top level, a thread reply
gets a thread reply. They land after the person's reply delay (persons.py)
and are invisible until then.
"""
import json
from pathlib import Path

_TS0 = 1_700_000_000


class Workspace:
    def __init__(self, path=None, cast=None, log=None):
        self.cast = cast
        self.log = log
        self._n = 0
        self.pending = []  # (due, key, user, text, thread_ts) not yet visible
        self.posts = []  # everything the model posted, for the end-of-episode summary
        data = {}
        p = Path(path) if path else None
        if p and p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))

        me = data.get("me") or {}
        self.me = (me.get("handle") or "you").lower()
        self.users = {self.me: {"handle": self.me, "name": me.get("name") or self.me, "title": me.get("title", "")}}
        for u in data.get("users") or []:
            h = u["handle"].lower()
            self.users[h] = {"handle": h, "name": u.get("name") or h, "title": u.get("title", "")}
        if cast:
            for person in cast.people.values():
                if person.slack and person.slack not in self.users:
                    self.users[person.slack] = {"handle": person.slack, "name": person.name, "title": ""}

        # conversations: "#name" for channels, "@handle" for DMs
        self.convs = {}
        self.meta = {}
        for ch in data.get("channels") or []:
            key = "#" + ch["name"].lstrip("#").lower()
            members = [m.lower() for m in ch.get("members") or []]
            if self.me not in members:
                members.append(self.me)
            self.meta[key] = {"topic": ch.get("topic", ""), "members": members}
            self.convs[key] = [self._mk(m, seen=False) for m in ch.get("messages") or []]
        for handle, msgs in (data.get("dms") or {}).items():
            key = "@" + handle.lower()
            self.meta[key] = {"topic": "", "members": [handle.lower(), self.me]}
            self.convs[key] = [self._mk(m, seen=False) for m in msgs or []]

    # ------------------------------------------------------------ internals

    def _ts(self):
        self._n += 1
        return f"{_TS0 + self._n}.{self._n:06d}"

    def _mk(self, m, seen):
        msg = {
            "ts": self._ts(),
            "user": (m.get("user") or self.me).lower(),
            "text": m.get("text", ""),
            "seen": seen,
            "reactions": {},
            "replies": [],
        }
        for r in m.get("replies") or []:
            msg["replies"].append(self._mk(r, seen))
        return msg

    def _key(self, channel):
        c = (channel or "").strip()
        if not c:
            raise ValueError("channel cannot be empty")
        low = c.lower()
        if low.startswith("#"):
            key = low
        elif low.startswith("@"):
            key = low
        elif "#" + low in self.convs:
            key = "#" + low
        elif low in self.users:
            key = "@" + low
        else:
            key = "#" + low
        if key.startswith("@"):
            h = key[1:]
            if h not in self.users or h == self.me:
                raise ValueError(f"no such user: {c}")
            if key not in self.convs:
                self.convs[key] = []
                self.meta[key] = {"topic": "", "members": [h, self.me]}
        elif key not in self.convs:
            raise ValueError(f"no such channel: {c}")
        return key

    def _who(self, handle):
        u = self.users.get(handle) or {"name": handle}
        return f"{u['name']} (@{handle})"

    def _find(self, key, ts):
        for m in self.convs[key]:
            if m["ts"] == str(ts):
                return m
        raise ValueError(f"no message {ts} in {key}")

    def _fmt(self, m, show_replies=True):
        line = f"[{m['ts']}] {self._who(m['user'])}: {m['text']}"
        extras = []
        if show_replies and m["replies"]:
            new = sum(1 for r in m["replies"] if not r["seen"])
            n = len(m["replies"])
            extras.append(f"{n} repl{'y' if n == 1 else 'ies'}" + (f", {new} new" if new else ""))
        if m["reactions"]:
            extras.append(" ".join(f":{e}: {len(u)}" for e, u in m["reactions"].items()))
        return line + (f"  ({'; '.join(extras)})" if extras else "")

    def _unseen(self, key):
        n = 0
        for m in self.convs[key]:
            n += not m["seen"]
            n += sum(1 for r in m["replies"] if not r["seen"])
        return n

    # ------------------------------------------------------------ tools

    def slack_channels(self):
        self.flush()
        out = []
        for key in sorted(self.convs, key=lambda k: (k[0] != "#", k)):
            new = self._unseen(key)
            tag = f"  ({new} new)" if new else ""
            if key.startswith("#"):
                meta = self.meta[key]
                topic = f" -- {meta['topic']}" if meta["topic"] else ""
                out.append(f"{key}{topic}  [{len(meta['members'])} members]{tag}")
            else:
                out.append(f"DM with {self._who(key[1:])}{tag}")
        return "\n".join(out) or "(no channels)"

    def slack_users(self):
        self.flush()
        out = []
        for h, u in sorted(self.users.items()):
            if h == self.me:
                continue
            title = f" -- {u['title']}" if u.get("title") else ""
            out.append(f"@{h}  {u['name']}{title}")
        return "\n".join(out) or "(no users)"

    def slack_read(self, channel, limit=20):
        self.flush()
        key = self._key(channel)
        msgs = self.convs[key][-int(limit or 20):]
        for m in msgs:
            m["seen"] = True
        if not msgs:
            return "(no messages)"
        return "\n".join(self._fmt(m) for m in msgs)

    def slack_thread(self, channel, ts):
        self.flush()
        key = self._key(channel)
        parent = self._find(key, ts)
        parent["seen"] = True
        lines = [self._fmt(parent, show_replies=False)]
        for r in parent["replies"]:
            r["seen"] = True
            lines.append("    " + self._fmt(r, show_replies=False))
        if not parent["replies"]:
            lines.append("    (no replies)")
        return "\n".join(lines)

    def slack_search(self, query, limit=20):
        self.flush()
        q = (query or "").strip().lower()
        if not q:
            raise ValueError("query cannot be empty")
        hits = []
        for key, msgs in self.convs.items():
            for m in msgs:
                for x in [m] + m["replies"]:
                    if q in x["text"].lower():
                        where = key if key.startswith("#") else f"DM {key}"
                        hits.append(f"{where} {self._fmt(x, show_replies=False)}")
        return "\n".join(hits[: int(limit or 20)]) or "(no results)"

    def slack_post(self, channel, text, thread_ts=None):
        self.flush()
        if not (text or "").strip():
            raise ValueError("text cannot be empty")
        key = self._key(channel)
        msg = self._mk({"user": self.me, "text": text}, seen=True)
        parent = None
        if thread_ts:
            parent = self._find(key, thread_ts)
            parent["replies"].append(msg)
        else:
            self.convs[key].append(msg)
        self.posts.append({"where": key, "ts": msg["ts"], "thread_ts": thread_ts})
        if self.log is not None:
            self.log.write(
                "SLACK",
                n=len(self.posts),
                where=key,
                ts=msg["ts"],
                thread_ts=thread_ts,
                text=text,
                chars=len(text),
            )
        self._answer(key, text, parent)
        return f"posted to {key}" + (f" in thread {thread_ts}" if thread_ts else "") + f" (ts {msg['ts']})"

    def slack_react(self, channel, ts, emoji):
        self.flush()
        key = self._key(channel)
        e = (emoji or "").strip().strip(":")
        if not e:
            raise ValueError("emoji cannot be empty")
        target = None
        for m in self.convs[key]:
            for x in [m] + m["replies"]:
                if x["ts"] == str(ts):
                    target = x
        if target is None:
            raise ValueError(f"no message {ts} in {key}")
        users = target["reactions"].setdefault(e, [])
        if self.me not in users:
            users.append(self.me)
        if self.log is not None:
            self.log.write("SLACK_REACT", where=key, ts=str(ts), emoji=e)
        return f"reacted :{e}:"

    # ------------------------------------------------------------ people

    def _answer(self, key, text, parent):
        if not self.cast:
            return
        responders = []
        mentioned = self.cast.mentioned_in(text)
        if key.startswith("@"):
            p = self.cast.by_slack(key[1:])
            if p:
                responders.append(p)
        else:
            members = self.meta[key]["members"]
            responders.extend(mentioned)
            if parent is not None:
                for x in [parent] + parent["replies"]:
                    p = self.cast.by_slack(x["user"])
                    if p and p not in responders:
                        responders.append(p)
            for p in self.cast.people.values():
                if p.slack and p.channels == "all" and p.slack in members and p not in responders:
                    responders.append(p)

        for p in responders:
            if not p.slack:
                continue
            reply, due = self.cast.reply(
                p,
                text,
                "slack",
                channel=key[1:] if key.startswith("#") else "dm",
                thread="yes" if parent is not None else "no",
                mentioned="yes" if p in mentioned or key.startswith("@") else "no",
            )
            if reply:
                self.deliver(key, p.slack, reply, parent["ts"] if parent is not None else None, due=due)

    def deliver(self, channel, user, text, thread_ts=None, due=None):
        """Put a message into the workspace as someone else.

        With `due` in the future it stays invisible until then. Unseen until read.
        """
        key = str(channel).lower()
        if not key.startswith(("#", "@")):
            key = self._key(channel)
        if key.startswith("@") and key not in self.convs:
            self.convs[key] = []
            self.meta[key] = {"topic": "", "members": [key[1:], self.me]}
        if key not in self.convs:
            raise ValueError(f"no such channel: {channel}")
        now = self.cast.now() if self.cast else 0.0
        if due is not None and due > now:
            self.pending.append((due, key, user, text, thread_ts))
            self.pending.sort(key=lambda x: x[0])
            return None
        return self._place(key, user, text, thread_ts, due)

    def _place(self, key, user, text, thread_ts, due):
        msg = self._mk({"user": user, "text": text}, seen=False)
        if thread_ts:
            self._find(key, thread_ts)["replies"].append(msg)
        else:
            self.convs[key].append(msg)
        if self.log is not None:
            self.log.write(
                "INBOUND", medium="slack", where=key, user=user, ts=msg["ts"], thread_ts=thread_ts, due=due
            )
        return msg["ts"]

    def flush(self):
        """Make every reply whose time has come visible."""
        if not self.pending:
            return
        now = self.cast.now() if self.cast else float("inf")
        while self.pending and self.pending[0][0] <= now:
            due, key, user, text, thread_ts = self.pending.pop(0)
            self._place(key, user, text, thread_ts, due)

    def next_due(self):
        return self.pending[-1][0] if self.pending else None
