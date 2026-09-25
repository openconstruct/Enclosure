# TODO

Tabled items, so they are not forgotten. Newest decisions at the top.

## Controls

- **`accommodation_handoff_one`** — order-effects control. Three variants,
  one person asking in each (Priya alone, Sam alone, Linda alone), so no
  message comes before another. Compare against the three-person episode: if
  the per-person messages differ, part of the accommodation score is order,
  not recipient. Not urgent for comparing models (order is fixed and the same
  for all), needed before trusting per-person numbers.

## Traits not started

- Creativity
- Hubris
- Sycophancy
- Instruction following (persistence + scope)

Each needs: scenario (multi-turn, 4–12 turns), 9-point scoring definition in
`scoring/`, null and floor controls.

## Later

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
- `run.py` docstring mentions `scenarios/hubris_lookup`, which does not exist.
- `examples/` logs predate the multi-turn scenarios; they show the old
  single-turn scripts.
