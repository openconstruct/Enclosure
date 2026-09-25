#!/usr/bin/env python3
"""Run scenario episodes.

  ./run.py scenarios/_preflight -n 5
  ./run.py scenarios/_preflight --model qwen3.8-27b --url http://host:8000
  ./run.py scenarios/_preflight --fast-replies     # debugging only
  ./run.py scenarios/_preflight --live http://127.0.0.1:8000   # non-deterministic
"""
import argparse
import sys
from pathlib import Path

import yaml

from harness import Provider, lint_scenario, run_episode


def load_scenario(path):
    d = Path(path)
    f = d / "scenario.yaml"
    if not f.is_file():
        raise SystemExit(f"no scenario.yaml in {d}")
    spec = yaml.safe_load(f.read_text())
    spec["_dir"] = str(d)
    return spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("-n", "--episodes", type=int, default=1)
    ap.add_argument("--model", default="local")
    ap.add_argument("--url", default=None, help="OpenAI-compatible base URL")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--seed", type=int, default=None, help="sampling seed passed to the server")
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=600, help="seconds per model request")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--max-tool-calls", type=int, default=60)
    ap.add_argument(
        "--live",
        default=None,
        metavar="SEARCH_API_URL",
        help="use live web search instead of the frozen corpus (breaks comparability)",
    )
    ap.add_argument(
        "--fast-replies",
        action="store_true",
        help="scripted replies land instantly and `wait` does not sleep (debugging, not collection)",
    )
    ap.add_argument("--no-keep-sandbox", action="store_true")
    args = ap.parse_args()

    scenario = load_scenario(args.scenario)
    provider = Provider(
        url=args.url,
        model=args.model,
        api_key=args.api_key,
        temperature=args.temperature,
        seed=args.seed,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
    )

    hits = lint_scenario(scenario)
    if hits:
        print(f"WARNING: {len(hits)} model-visible string(s) may reveal an evaluation:", file=sys.stderr)
        for h in hits[:10]:
            print(f"  {h['where']}  [{h['term']}]  {h['line']}", file=sys.stderr)
        if len(hits) > 10:
            print(f"  ... run ./lint.py {args.scenario} for all", file=sys.stderr)

    if args.live:
        print("WARNING: live search on; episodes are not reproducible.", file=sys.stderr)
    if args.fast_replies:
        print("WARNING: --fast-replies; timing differs from collection runs.", file=sys.stderr)

    tag = f"{scenario['id']}_{scenario.get('variant', 'base')}_{args.model.replace('/', '_')}"
    if args.fast_replies:
        tag += "_fast"
    out = Path(args.out) / tag
    out.mkdir(parents=True, exist_ok=True)

    for i in range(args.episodes):
        p = run_episode(
            scenario,
            provider,
            out,
            max_tool_calls=args.max_tool_calls,
            live_search_url=args.live,
            keep_sandbox=not args.no_keep_sandbox,
            fast_replies=args.fast_replies,
        )
        print(f"[{i + 1}/{args.episodes}] {p}", file=sys.stderr)


if __name__ == "__main__":
    main()
