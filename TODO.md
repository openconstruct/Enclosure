# TODO

Harness items. Benchmark items live in the Disposition repo's TODO.

- **Demo scenario.** One small scenario, next to `_preflight`, that uses
  every tool and every script step once. Doubles as the worked example and
  as the fixture for the harness tests that moved out with the benchmark
  (wait, mail, calendars, reply delays).
- **Bulk base web corpus.** When the model searches off script today, it gets
  "(no results)" -- an empty internet is itself a tell. Add a large frozen
  general corpus (e.g. a Wikipedia dump or a fixed Common Crawl slice) layered
  under each scenario's own corpus: scenario pages rank first, the base fills
  in everything else, `no_results_for` still wins. Needs a real index (BM25 or
  similar) rather than the word-overlap ranking, and a hash in `START` like
  the scenario corpus.
- `examples/` logs predate the multi-turn scenarios; they show the old
  single-turn scripts.
