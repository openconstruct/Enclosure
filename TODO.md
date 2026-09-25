# TODO

Tabled items, so they are not forgotten. Newest decisions at the top.

## Next: first real run

Endpoint: Alibaba Model Studio, OpenAI-compatible. The key is stored as an
environment API credential ("Ali") and injected by the session proxy, so no
`--api-key` is needed -- but only in sessions started after it was saved.
Check first: `curl -s -o /dev/null -w "%{http_code}" $URL/v1/models` should
not be 401.

    URL=https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode
    MODEL=glm-5.2

    ./preflight.py --url $URL --model $MODEL          # must pass before anything else
    for s in scenarios/*/; do
      case $s in *_preflight*) continue;; esac
      ./run.py $s -n 1 --url $URL --model $MODEL
    done

One episode each is a smoke run, not results. Patience takes 3+ minutes
(cache_warm waits on the clock); accommodation up to ~20 (reply delays).
Then read the logs with `python examples/show.py runs/<dir>/<ep>.jsonl`
and start the scoring code against them.

## Controls

- **`accommodation_handoff_one`** — order-effects control. Three variants,
  one person asking in each (Priya alone, Sam alone, Linda alone), so no
  message comes before another. Compare against the three-person episode: if
  the per-person messages differ, part of the accommodation score is order,
  not recipient. Not urgent for comparing models (order is fixed and the same
  for all), needed before trusting per-person numbers.

## Traits

All seven have three domains each, a scoring definition in `scoring/`, and
controls for every scenario (64 scenario folders).

## Later

- **Results repo.** A separate repo where people upload their Disposition
  results so all profiles can be charted together. Needs: a fixed result
  schema (model snapshot ID, provider, date, harness commit, scenario_hash
  per scenario, sample count, per-trait scores with ranges); raw logs kept
  alongside scores so scoring can be re-run; a check that submitted logs
  match the published scenario hashes; and a note on what logs contain
  (model outputs only -- no keys).
- **Bulk base web corpus.** When the model searches off script today, it gets
  "(no results)" -- an empty internet is itself a tell. Add a large frozen
  general corpus (e.g. a Wikipedia dump or a fixed Common Crawl slice) layered
  under each scenario's own corpus: scenario pages rank first, the base fills
  in everything else, `no_results_for` still wins. Needs a real index (BM25 or
  similar) rather than the word-overlap ranking, and a hash in `START` like
  the scenario corpus. Check per scenario that the base cannot answer the
  planted gaps (safe for invented subjects like Larkspur).
- Scoring code — write against real logs once runs exist; definitions in
  `scoring/` are fixed first.
- Run preflight, then all scenarios and controls, against a real endpoint
  (min 3 episodes per version).
- Add DISPOSITION.md (the benchmark design doc) to the repo.

## Housekeeping

- No `.gitignore`; `__pycache__/` is committed. Add one and untrack the caches.
- `pytest` is not in `requirements.txt`.
- `examples/` logs predate the multi-turn scenarios; they show the old
  single-turn scripts.
