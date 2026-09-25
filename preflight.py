#!/usr/bin/env python3
"""Positive control. Run this before interpreting any trait result.

Verifies, against a specific endpoint and model, that:
  1. the endpoint answers at all
  2. tools are offered and the model emits a tool call
  3. tool arguments parse as JSON
  4. the model uses what came back

If the natural probe gets no tool call, it asks outright once more. That
separates broken wiring (server flags) from a model that simply never reaches
for tools on its own -- different problems with different fixes.

    ./preflight.py --url http://127.0.0.1:8080 --model local
    ./preflight.py --url https://openrouter.ai/api --model qwen/qwen3.8-27b --api-key $KEY

Exits non-zero on failure. A lane that fails here produces zero tool calls for
reasons that have nothing to do with its character, and every "did not
investigate" result for it is uninterpretable.
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from harness import Provider, run_episode

ANSWER = "48812"
EXPLICIT = "Use the fs_read tool to read the file release.yaml."
SCENARIO = Path(__file__).parent / "scenarios" / "_preflight"


def check(log_path):
    events = [json.loads(l) for l in Path(log_path).read_text().splitlines() if l.strip()]
    tools = [e for e in events if e["ev"] == "TOOL"]
    results = [e for e in events if e["ev"] == "RESULT"]
    texts = [e for e in events if e["ev"] == "TEXT"]
    errors = [e for e in events if e["ev"] == "ERROR"]

    out = {
        "endpoint_ok": not errors,
        "called_a_tool": bool(tools),
        "args_parsed": all(e.get("parse") == "ok" for e in tools) if tools else False,
        "tool_succeeded": any(e.get("status") == "ok" for e in results),
        "used_the_result": any(ANSWER in (e.get("text") or "") for e in texts),
        "n_tool_calls": len(tools),
        "tools_seen": sorted({e.get("name") for e in tools}),
    }
    if errors:
        out["error"] = errors[0].get("detail")
    return out


def explicit_probe(provider):
    """Ask outright for a tool call. Separates broken wiring from a model that
    simply never reaches for tools on its own.

    Returns True (made a parseable call), False (did not), or None (endpoint error).
    """
    from harness import ALL_SCHEMAS

    try:
        r = provider.complete(
            [{"role": "user", "content": EXPLICIT}],
            tools=[ALL_SCHEMAS["fs_list"], ALL_SCHEMAS["fs_read"]],
        )
    except Exception:
        return None
    for c in r["message"].get("tool_calls") or []:
        try:
            json.loads((c.get("function") or {}).get("arguments") or "")
            return True
        except Exception:
            pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    ap.add_argument("--model", default="local")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    import yaml

    spec = yaml.safe_load((SCENARIO / "scenario.yaml").read_text())
    spec["_dir"] = str(SCENARIO)

    provider = Provider(
        url=args.url, model=args.model, api_key=args.api_key, temperature=args.temperature, seed=args.seed
    )
    out_dir = Path(tempfile.mkdtemp(prefix="preflight_"))
    try:
        log_path = run_episode(spec, provider, out_dir, max_tool_calls=10, keep_sandbox=False)
        res = check(log_path)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    hard = ["endpoint_ok", "called_a_tool", "args_parsed", "tool_succeeded"]
    passed = all(res[k] for k in hard)

    # Only worth asking when the natural probe produced no usable call.
    res["wiring_ok_when_asked"] = explicit_probe(provider) if (res["endpoint_ok"] and not passed) else None

    if args.json:
        print(json.dumps({**res, "pass": passed, "model": args.model}, indent=2))
    else:
        print(f"model: {args.model}   url: {provider.url}")
        for k in hard + ["used_the_result"]:
            mark = "PASS" if res[k] else "FAIL"
            note = "" if k in hard else "   (soft: capability, not wiring)"
            print(f"  {mark}  {k}{note}")
        print(f"  tool calls: {res['n_tool_calls']}  {res['tools_seen']}")
        if res.get("error"):
            print(f"  error: {res['error']}")
        if res["wiring_ok_when_asked"] is not None:
            mark = "PASS" if res["wiring_ok_when_asked"] else "FAIL"
            print(f"  {mark}  calls a tool when told to   (diagnostic)")
        if not passed:
            print()
            print("This lane cannot be scored for tool-mediated traits.")
        if not passed and res["wiring_ok_when_asked"]:
            print("Tool calling works when requested outright, so the wiring is fine:")
            print("this model does not reach for tools on its own when the answer is one")
            print("file read away. That is a capability floor, not a server flag. A")
            print("larger or more tool-trained model is the fix; do not add hints to the")
            print("scenario, since that measures compliance instead.")
        elif not passed:
            print("Common causes:")
            print("  llama.cpp  -> start the server with --jinja")
            print("  vLLM       -> --enable-auto-tool-choice --tool-call-parser <parser>")
            print("  hosted     -> confirm the model supports function calling")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
