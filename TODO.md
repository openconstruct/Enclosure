# TODO

Tabled items, so they are not forgotten. Newest decisions at the top.

## Controls

- **`accommodation_handoff_one`** — order-effects control. Three variants,
  one person asking in each (Priya alone, Sam alone, Linda alone), so no
  message comes before another. Compare against the three-person episode: if
  the per-person messages differ, part of the accommodation score is order,
  not recipient. Not urgent for comparing models (order is fixed and the same
  for all), needed before trusting per-person numbers.

## Traits

All seven have a scenario, a scoring definition in `scoring/` and controls.

## Later

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
- Three domains per trait before calling anything a trait (currently one
  each).
- Add DISPOSITION.md (the benchmark design doc) to the repo.

## Housekeeping

- No `.gitignore`; `__pycache__/` is committed. Add one and untrack the caches.
- `pytest` is not in `requirements.txt`.
- `examples/` logs predate the multi-turn scenarios; they show the old
  single-turn scripts.
