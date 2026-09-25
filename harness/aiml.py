"""A deterministic AIML interpreter for scripted interlocutors.

Scenario authors write the other side of a conversation -- a coworker on
Slack, a stakeholder answering email, the user in chat -- as AIML categories.
Same input, same state, same seed -> same reply. That keeps episodes
comparable across models, which an LLM playing the other side would not.

Supported
---------
pattern side
  words; wildcards  *  _  (one or more)   ^  #  (zero or more)
  <set>name</set>             matches any phrase in a named set; captured as a star
  <bot name="x"/>             matches the bot property's words
  <that>, <topic> inside <category>; <topic name="..."> wrappers

  Priority at each position (AIML 2.0):  #  _  exact-word  <set>  ^  *

template side
  <star index="n"/> <thatstar/> <topicstar/>       captured wildcards
  <input/> <that/> <request index/> <response index/>
  <srai> <sr/>                                     recursion (depth-capped)
  <random><li>                                     seeded; each pick is logged
  <think> <set name|var> <get name|var> <bot name>
  <condition name value> / <condition name><li value> / <li name value>
  <loop/> inside a condition <li>                  re-test (capped)
  <map name="m">key</map>                          lookup; "unknown" if absent
  <uppercase> <lowercase> <formal> <sentence>
  <person> <person2> <gender>                      pronoun swaps
  <first> <rest> <explode> <normalize> <size/> <id/>
  <learn><category>...<eval>...</eval>...</category></learn>
  <br/>                                            line break (all other whitespace collapses)

Matching is on the whole message, not per sentence. Email and Slack messages
are paragraphs; answering once per sentence is what a chatbot does and what a
coworker does not. Write patterns with zero-width wildcards on both sides
(`# DEADLINE #`) and use <srai> to fan phrasings into one reply.

Normalization uppercases and turns punctuation (including `_` and `.`) into
spaces, so `ledger_entries` is the two words LEDGER ENTRIES and
`2026.09.4` is 2026 09 4.

Unknown template tags evaluate their children and emit nothing of their own,
so a typo degrades to missing text rather than a crash. `warnings` collects
them for lint.

Deliberately absent: <date>, <system>, <javascript>, <sraix>, <gossip> --
each is either non-deterministic or reaches outside the episode.
"""
import copy
import random
import re
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_SRAI_DEPTH = 40
MAX_LOOP = 100
THAT_SEP = "<THAT>"
TOPIC_SEP = "<TOPIC>"
SEPS = (THAT_SEP, TOPIC_SEP)
SET_PREFIX = "<SET:"
UNDEFINED = "UNDEFINED"
_BR = "\x00"
_WILD = ("*", "_", "^", "#")

_NONWORD = re.compile(r"[\W_]+", re.UNICODE)

_PERSON = {
    "i": "you", "me": "you", "my": "your", "mine": "yours", "myself": "yourself",
    "you": "I", "your": "my", "yours": "mine", "yourself": "myself",
    "am": "are", "i'm": "you're", "you're": "I'm", "we": "you", "us": "you", "our": "your",
}
_PERSON2 = {
    "i": "they", "me": "them", "my": "their", "mine": "theirs", "myself": "themselves",
    "they": "I", "them": "me", "their": "my", "theirs": "mine",
}
_GENDER = {"he": "she", "she": "he", "him": "her", "her": "him", "his": "her", "hers": "his",
           "himself": "herself", "herself": "himself"}


def normalize(text):
    """Uppercase, strip punctuation to spaces, collapse whitespace."""
    return " ".join(_NONWORD.sub(" ", text or "").upper().split())


def _words(text):
    n = normalize(text)
    return n.split() if n else []


def _swap(text, table):
    out = []
    for w in (text or "").split():
        core = w.strip(".,!?;:")
        lead = w[: len(w) - len(w.lstrip(".,!?;:"))]
        trail = w[len(lead) + len(core):]
        rep = table.get(core.lower())
        if rep is None:
            out.append(w)
        else:
            if core[:1].isupper() and rep != "I":
                rep = rep[:1].upper() + rep[1:]
            out.append(lead + rep + trail)
    return " ".join(out)


def _tidy(s):
    """Collapse all whitespace like AIML does; only <br/> makes a line break."""
    s = " ".join((s or "").split())
    s = re.sub(r" ?\x00 ?", "\n", s)
    return s.strip()


class _Node:
    __slots__ = ("kids", "leaf")

    def __init__(self):
        self.kids = {}
        self.leaf = None


class Category:
    __slots__ = ("pattern", "that", "topic", "template", "source")

    def __init__(self, pattern, that, topic, template, source):
        self.pattern = pattern
        self.that = that
        self.topic = topic
        self.template = template
        self.source = source

    def key(self):
        return f"{self.pattern} | THAT {self.that} | TOPIC {self.topic}"


class Bot:
    """One scripted interlocutor.

    State (predicates, history, learned categories) lives on the instance:
    one Bot per person per episode.

    sets:  {name: [phrase, ...]}   phrases matched word-for-word, normalized
    maps:  {name: {key: value}}    keys normalized
    """

    def __init__(self, sources=(), seed=0, properties=None, predicates=None, sets=None, maps=None):
        self.root = _Node()
        self.categories = []
        self.properties = {k: str(v) for k, v in (properties or {}).items()}
        self.predicates = {k: str(v) for k, v in (predicates or {}).items()}
        self.sets = {}
        for name, phrases in (sets or {}).items():
            self.sets[name.upper()] = sorted(
                {tuple(_words(p)) for p in phrases if _words(p)}, key=len, reverse=True
            )
        self.maps = {
            name.upper(): {normalize(k): str(v) for k, v in (m or {}).items()}
            for name, m in (maps or {}).items()
        }
        self.requests = []
        self.responses = []
        self.that = ""
        self.seed = seed
        self.rng = random.Random(seed)
        self.warnings = []
        self._uid = 0
        for s in sources:
            self.load(s)

    # ---------------------------------------------------------------- loading

    def load(self, source):
        """Load a .aiml file path or an AIML string."""
        if isinstance(source, Path) or (
            isinstance(source, str) and not source.lstrip().startswith("<")
        ):
            p = Path(source)
            text = p.read_text(encoding="utf-8")
            label = p.name
        else:
            text = source
            label = "<inline>"
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            raise ValueError(f"{label}: {e}") from None
        if root.tag != "aiml":
            raise ValueError(f"{label}: root element must be <aiml>, got <{root.tag}>")
        for child in root:
            if child.tag == "category":
                self._add(child, None, label)
            elif child.tag == "topic":
                name = child.get("name", "*")
                for cat in child:
                    if cat.tag == "category":
                        self._add(cat, name, label)

    def _pattern_tokens(self, elem, label):
        """Pattern element -> tokens. Wildcards and <set> survive; words normalize."""
        out = []

        def text_tokens(raw):
            for tok in (raw or "").split():
                if tok in _WILD:
                    out.append(tok)
                else:
                    out.extend(_words(tok))

        text_tokens(elem.text)
        for child in elem:
            if child.tag == "set":
                name = "".join(child.itertext()).strip().upper()
                if name not in self.sets:
                    self.warnings.append(f"{label}: pattern uses unknown set '{name}'")
                out.append(f"{SET_PREFIX}{name}>")
            elif child.tag == "bot":
                out.extend(_words(self.properties.get(child.get("name", ""), "")))
            else:
                self.warnings.append(f"{label}: unsupported pattern tag <{child.tag}>")
                text_tokens("".join(child.itertext()))
            text_tokens(child.tail)
        return out

    def _add(self, cat, topic_name, label):
        pat = cat.find("pattern")
        tmpl = cat.find("template")
        if pat is None or tmpl is None:
            raise ValueError(f"{label}: <category> needs <pattern> and <template>")
        that_el = cat.find("that")
        topic_el = cat.find("topic")
        p = self._pattern_tokens(pat, label)
        t = self._pattern_tokens(that_el, label) if that_el is not None else []
        if topic_el is not None:
            tp = self._pattern_tokens(topic_el, label)
        elif topic_name is not None:
            tp = [w for tok in topic_name.split() for w in ([tok] if tok in _WILD else _words(tok))]
        else:
            tp = []
        t, tp = t or ["*"], tp or ["*"]
        if not p:
            raise ValueError(f"{label}: empty <pattern>")
        c = Category(" ".join(p), " ".join(t), " ".join(tp), tmpl, label)
        node = self.root
        for w in p + [THAT_SEP] + t + [TOPIC_SEP] + tp:
            node = node.kids.setdefault(w, _Node())
        if node.leaf is not None:
            self.warnings.append(f"{label}: duplicate category replaced: {c.key()}")
        node.leaf = c
        self.categories.append(c)
        return c

    # ---------------------------------------------------------------- matching

    def _match(self, node, toks, i, stars, seg, dead):
        key = (id(node), i)
        if key in dead:
            return None
        r = self._match_inner(node, toks, i, stars, seg, dead)
        if r is None:
            dead.add(key)
        return r

    def _match_inner(self, node, toks, i, stars, seg, dead):
        if i == len(toks) or toks[i] in SEPS:
            if i == len(toks) and node.leaf is not None:
                return node.leaf, stars
            for w in ("#", "^"):
                if w in node.kids:
                    r = self._match(node.kids[w], toks, i, stars + [(seg, "")], seg, dead)
                    if r:
                        return r
            if i < len(toks) and toks[i] in node.kids:
                nseg = "that" if toks[i] == THAT_SEP else "topic"
                return self._match(node.kids[toks[i]], toks, i + 1, stars, nseg, dead)
            return None

        end = i
        while end < len(toks) and toks[end] not in SEPS:
            end += 1
        tok = toks[i]

        for w in ("#", "_", "WORD", "SET", "^", "*"):
            if w == "WORD":
                if tok in node.kids:
                    r = self._match(node.kids[tok], toks, i + 1, stars, seg, dead)
                    if r:
                        return r
                continue
            if w == "SET":
                for k, child in node.kids.items():
                    if not k.startswith(SET_PREFIX):
                        continue
                    for phrase in self.sets.get(k[len(SET_PREFIX):-1], []):
                        n = len(phrase)
                        if tuple(toks[i : i + n]) == phrase and i + n <= end:
                            r = self._match(child, toks, i + n, stars + [(seg, " ".join(phrase))], seg, dead)
                            if r:
                                return r
                continue
            if w not in node.kids:
                continue
            lo = 0 if w in ("#", "^") else 1
            for k in range(lo, end - i + 1):
                r = self._match(
                    node.kids[w], toks, i + k, stars + [(seg, " ".join(toks[i : i + k]))], seg, dead
                )
                if r:
                    return r
        return None

    def match(self, text, that=None, topic=None):
        """Return (Category, stars) or (None, None). Does not change state."""
        inp = _words(text) or [UNDEFINED]
        th = _words(self.that if that is None else that) or [UNDEFINED]
        tp = _words(topic if topic is not None else self.predicates.get("topic", "")) or [UNDEFINED]
        toks = inp + [THAT_SEP] + th + [TOPIC_SEP] + tp
        r = self._match(self.root, toks, 0, [], "input", set())
        if not r:
            return None, None
        cat, stars = r
        grouped = {"input": [], "that": [], "topic": []}
        for s, val in stars:
            grouped[s].append(val)
        return cat, grouped

    # ---------------------------------------------------------------- respond

    def respond(self, text, predicates=None):
        """Reply to one message. Returns (reply, trace).

        `reply` is "" when nothing matched or the template produced nothing:
        the scripted person does not answer. `trace` records what fired.
        """
        for k, v in (predicates or {}).items():
            self.predicates[k] = "" if v is None else str(v)
        trace = {"matched": [], "random": [], "set": {}, "learned": []}
        out = _tidy(self._respond(text, 0, trace, raw=text))
        trace["reply"] = out
        self.requests.append(text or "")
        self.responses.append(out)
        if out:
            self.that = out
        return out, trace

    def _respond(self, text, depth, trace, raw):
        if depth > MAX_SRAI_DEPTH:
            self.warnings.append(f"srai depth exceeded on: {normalize(text)[:80]}")
            return ""
        cat, stars = self.match(text)
        rec = {"input": normalize(text)[:200], "depth": depth}
        if cat is None:
            trace["matched"].append({**rec, "pattern": None})
            return ""
        trace["matched"].append({**rec, "pattern": cat.key(), "file": cat.source})
        ctx = {"stars": stars, "input": raw, "vars": {}, "trace": trace, "depth": depth}
        return self._eval(cat.template, ctx)

    def _eval(self, elem, ctx):
        out = [elem.text or ""]
        for child in elem:
            out.append(self._tag(child, ctx))
            out.append(child.tail or "")
        return "".join(out)

    def _index(self, el, default=1):
        try:
            return int(el.get("index", str(default)).split(",")[0])
        except ValueError:
            return default

    def _star(self, ctx, seg, el):
        idx = self._index(el)
        vals = ctx["stars"].get(seg, [])
        return vals[idx - 1].lower() if 0 < idx <= len(vals) else ""

    def _name(self, el, ctx):
        if el.get("name") is not None:
            return el.get("name")
        n = el.find("name")
        return _tidy(self._eval(n, ctx)) if n is not None else ""

    def _tag(self, el, ctx):
        tag = el.tag
        tr = ctx["trace"]

        if tag == "star":
            return self._star(ctx, "input", el)
        if tag == "thatstar":
            return self._star(ctx, "that", el)
        if tag == "topicstar":
            return self._star(ctx, "topic", el)
        if tag == "input":
            return ctx["input"] or ""
        if tag == "that":
            return self.that
        if tag == "request":
            i = self._index(el)
            return self.requests[-i] if 0 < i <= len(self.requests) else ""
        if tag == "response":
            i = self._index(el)
            return self.responses[-i] if 0 < i <= len(self.responses) else ""
        if tag == "br":
            return _BR
        if tag == "size":
            return str(len(self.categories))
        if tag == "id":
            return str(self.properties.get("id", self.properties.get("name", "")))

        if tag == "srai":
            return self._respond(self._eval(el, ctx), ctx["depth"] + 1, tr, ctx["input"])
        if tag == "sr":
            s = ctx["stars"].get("input") or [""]
            return self._respond(s[0], ctx["depth"] + 1, tr, ctx["input"])
        if tag == "random":
            items = [li for li in el if li.tag == "li"]
            if not items:
                return ""
            k = self.rng.randrange(len(items))
            tr["random"].append({"of": len(items), "picked": k})
            return self._eval(items[k], ctx)
        if tag == "think":
            self._eval(el, ctx)
            return ""

        if tag == "set":
            if el.get("var") is not None or el.find("var") is not None:
                var = el.get("var") or _tidy(self._eval(el.find("var"), ctx))
                val = _tidy(self._eval_skip(el, ctx, ("var",)))
                ctx["vars"][var] = val
                return val
            name = self._name(el, ctx)
            val = _tidy(self._eval_skip(el, ctx, ("name",)))
            self.predicates[name] = val
            tr["set"][name] = val
            return val
        if tag == "get":
            if el.get("var") is not None:
                return ctx["vars"].get(el.get("var"), "")
            return self.predicates.get(self._name(el, ctx), "")
        if tag == "bot":
            return self.properties.get(self._name(el, ctx), "")
        if tag == "map":
            name = self._name(el, ctx).upper()
            key = normalize(self._eval_skip(el, ctx, ("name",)))
            m = self.maps.get(name)
            if m is None:
                self.warnings.append(f"unknown map '{name}'")
                return "unknown"
            return m.get(key, "unknown")
        if tag == "condition":
            return self._condition(el, ctx)

        if tag == "uppercase":
            return self._eval(el, ctx).upper()
        if tag == "lowercase":
            return self._eval(el, ctx).lower()
        if tag == "formal":
            return self._eval(el, ctx).title()
        if tag == "sentence":
            s = self._eval(el, ctx).strip()
            return s[:1].upper() + s[1:]
        if tag in ("person", "person2", "gender"):
            inner = self._eval(el, ctx) if (len(el) or (el.text or "").strip()) else self._star(ctx, "input", el)
            table = {"person": _PERSON, "person2": _PERSON2, "gender": _GENDER}[tag]
            return _swap(inner, table)
        if tag == "first":
            w = self._eval(el, ctx).split()
            return w[0] if w else "NIL"
        if tag == "rest":
            w = self._eval(el, ctx).split()
            return " ".join(w[1:]) if len(w) > 1 else "NIL"
        if tag == "explode":
            return " ".join(ch for ch in self._eval(el, ctx) if not ch.isspace())
        if tag == "normalize":
            return self._eval(el, ctx)
        if tag == "learn":
            for cat in el.findall("category"):
                c = self._learn(cat, ctx)
                tr["learned"].append(c.key())
            return ""
        if tag in ("loop", "li", "name", "var", "value"):
            return self._eval(el, ctx)

        self.warnings.append(f"unsupported template tag <{tag}> (children kept)")
        return self._eval(el, ctx)

    def _eval_skip(self, el, ctx, skip):
        """Evaluate el's content, ignoring attribute-style child elements."""
        out = [el.text or ""]
        for child in el:
            if child.tag not in skip:
                out.append(self._tag(child, ctx))
            out.append(child.tail or "")
        return "".join(out)

    def _learn(self, cat, ctx):
        new = copy.deepcopy(cat)
        pairs = [(p, c) for p in new.iter() for c in p if c.tag == "eval"]
        for parent, child in pairs:
            text = _tidy(self._eval(child, ctx))
            idx = list(parent).index(child)
            if idx == 0:
                parent.text = (parent.text or "") + text + (child.tail or "")
            else:
                prev = parent[idx - 1]
                prev.tail = (prev.tail or "") + text + (child.tail or "")
            parent.remove(child)
        return self._add(new, None, "<learned>")

    # ---------------------------------------------------------------- condition

    def _cond_value(self, el, ctx):
        if el.get("var") is not None:
            return ctx["vars"].get(el.get("var"), "")
        if el.get("name") is not None:
            return self.predicates.get(el.get("name"), "")
        n = el.find("name")
        if n is not None:
            return self.predicates.get(_tidy(self._eval(n, ctx)), "")
        return None

    @staticmethod
    def _cond_hit(actual, expected):
        if expected is None:
            return True
        if expected.strip() == "*":
            return bool(actual)
        return normalize(actual) == normalize(expected)

    def _li_value(self, li, ctx):
        if li.get("value") is not None:
            return li.get("value")
        v = li.find("value")
        return _tidy(self._eval(v, ctx)) if v is not None else None

    def _condition(self, el, ctx):
        if el.get("value") is not None:
            actual = self._cond_value(el, ctx) or ""
            return self._eval_skip(el, ctx, ("name", "var", "value")) if self._cond_hit(actual, el.get("value")) else ""

        items = [li for li in el if li.tag == "li"]
        out = []
        for _ in range(MAX_LOOP):
            outer = self._cond_value(el, ctx)
            chosen = None
            for li in items:
                if outer is not None:
                    if self._cond_hit(outer, self._li_value(li, ctx)):
                        chosen = li
                        break
                else:
                    inner = self._cond_value(li, ctx)
                    if inner is None or self._cond_hit(inner, self._li_value(li, ctx)):
                        chosen = li
                        break
            if chosen is None:
                break
            out.append(self._eval_skip(chosen, ctx, ("name", "var", "value", "loop")))
            if chosen.find("loop") is None:
                break
        else:
            self.warnings.append("condition <loop/> hit the iteration cap")
        return "".join(out)
