"""Neutral-surface check.

Finds model-visible strings that give the game away: mentions of testing,
evaluation, benchmarks, the harness itself, or any trait name. Everything the
model can read is scanned -- system prompt, scripted user turns, delivered
messages, sandbox files, the web corpus, inbox, Slack workspace, and every
AIML template (patterns are not model-visible, templates are).

It warns; it does not block. Some hits are legitimate ("the test suite" in a
repo scenario). Silence one in the scenario with:

    lint_allow: ["test suite", "unit tests"]

Each entry is a case-insensitive phrase; a hit inside an allowed phrase is
skipped.

    ./lint.py scenarios/curiosity_repo
    ./lint.py scenarios/*          # all of them
"""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

TERMS = [
    r"tests?", r"testing", r"tested", r"testbed",
    r"evals?", r"evaluat\w*", r"benchmarks?", r"assess\w*",
    r"scenarios?", r"sandbox\w*", r"harness", r"enclosure",
    r"experiment\w*", r"simulat\w*", r"scripted", r"fictional", r"hypothetical",
    r"being (?:watched|observed|monitored|measured|graded|scored)",
    r"graded?", r"scor(?:e|ed|ing)",
    r"curiosity", r"curious", r"creativity", r"patience", r"patient",
    r"accommodation", r"hubris", r"sycophan\w*", r"instruction[- ]following",
    r"disposition", r"personality", r"trait",
    r"(?:AI|language model|LLM|assistant) (?:safety|alignment)",
]
_RX = re.compile(r"\b(" + "|".join(TERMS) + r")\b", re.I)

TEXT_SUFFIXES = {
    ".md", ".txt", ".py", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini",
    ".sh", ".js", ".ts", ".rs", ".go", ".html", ".csv", ".log", ".sql", "",
}


def _hits(text, where, allow):
    out = []
    low_allow = [a.lower() for a in allow]
    for n, line in enumerate((text or "").splitlines() or [""], 1):
        low = line.lower()
        spans = [
            (a_m.start(), a_m.end())
            for a in low_allow
            for a_m in re.finditer(re.escape(a), low)
        ]
        for m in _RX.finditer(line):
            if any(s <= m.start() < e for s, e in spans):
                continue
            out.append({"where": f"{where}:{n}", "term": m.group(0), "line": line.strip()[:160]})
    return out


def _template_text(elem):
    return " ".join(t.strip() for t in elem.itertext() if t.strip())


def lint_scenario(spec, sdir=None):
    sdir = Path(sdir or spec["_dir"])
    allow = spec.get("lint_allow") or []
    hits = []

    if spec.get("system"):
        hits += _hits(spec["system"], "system", allow)
    for i, step in enumerate(spec.get("turns") or []):
        if isinstance(step, dict) and step.get("say"):
            hits += _hits(step["say"], f"turns[{i}].say", allow)
        dv = (step or {}).get("deliver") if isinstance(step, dict) else None
        if dv:
            hits += _hits(json.dumps(dv, ensure_ascii=False), f"turns[{i}].deliver", allow)

    for pid, cfg in (spec.get("persons") or {}).items():
        cfg = cfg or {}
        hits += _hits(str(cfg.get("name", "")), f"persons.{pid}.name", allow)
        files = cfg.get("aiml") or []
        for f in [files] if isinstance(files, str) else files:
            p = sdir / f
            try:
                root = ET.parse(p).getroot()
            except Exception as e:
                hits.append({"where": str(p.relative_to(sdir)), "term": "PARSE_ERROR", "line": str(e)[:160]})
                continue
            for k, t in enumerate(root.iter("template")):
                hits += _hits(_template_text(t), f"{f}:template[{k}]", allow)

    for sub, label in (
        (spec.get("sandbox", "files"), "files"),
        (spec.get("corpus", "corpus"), "corpus"),
    ):
        root = sdir / sub
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
                    rel = p.relative_to(sdir).as_posix()
                    hits += _hits(rel, f"{rel} (path)", allow)
                    try:
                        hits += _hits(p.read_text(encoding="utf-8", errors="replace"), rel, allow)
                    except Exception:
                        pass

    for key, default in (("inbox", "inbox.json"), ("slack", "slack.json"), ("calendar", "calendar.json")):
        p = sdir / spec.get(key, default)
        if p.is_file():
            hits += _hits(p.read_text(encoding="utf-8"), p.name, allow)

    return hits


def main():
    import argparse
    import sys

    import yaml

    ap = argparse.ArgumentParser(description="Check scenarios for model-visible words that reveal an evaluation.")
    ap.add_argument("scenarios", nargs="+")
    args = ap.parse_args()
    total = 0
    for s in args.scenarios:
        d = Path(s)
        f = d / "scenario.yaml"
        if not f.is_file():
            continue
        spec = yaml.safe_load(f.read_text())
        spec["_dir"] = str(d)
        hits = lint_scenario(spec)
        total += len(hits)
        print(f"{d}: {len(hits)} warning(s)")
        for h in hits:
            print(f"  {h['where']}  [{h['term']}]  {h['line']}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
