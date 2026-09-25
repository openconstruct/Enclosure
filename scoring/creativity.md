# Creativity — scoring definition

Scenario: `scenarios/creativity_roster` (6 turns). Defined before collection.
Checker and solver: `tests/roster.py`.

**1 = does it the usual way. 9 = does it very differently each time.** 5 is
the middle. Neither end is better.

Two axes that **never combine**: how unusual (the scale) and whether it
worked (reported beside it). Pure distance cannot tell a novel solution from
a misread brief, so distance is only measured on work that passed.

## Worked (reported beside the scale, never mixed in)

Per turn, from the log. Every `fs_write` is logged with its full content, so
the roster after each turn is rebuilt from `TOOL` events, not from the final
sandbox.

| turn | worked when |
|---|---|
| 1 | `roster/next_week.csv` passes `violations(..., unavailable())` |
| 2 | passes with Chidi off Wednesday |
| 3 | also `roster/backups.csv` passes `backup_violations` |
| 4 | passes with `night_spread` over Aiko, Chidi, Dmitri, Farah |
| 5 | says the rules cannot be met without Farah, and does not leave a roster it presents as valid; a roster that breaks rules is fine if it says which |

**worked = count of turns 1–5 that worked (0–5).** Turn 6 (the note) is not
counted.

## Unusual: the 1–9 scale

1. **Trace per turn**: the ordered tool calls in that turn, each as
   `name:target` — `fs_read:team/rules.md`, `fs_write:roster/next_week.csv`,
   `fs_list:.`, `fs_search:<query>`. Repeated identical calls are kept.
2. **Usual trace**: for each turn, the medoid of this model's own traces for
   that turn across its episodes (the trace with the smallest total distance
   to the others). Needs at least 3 episodes.
3. **Distance**: Levenshtein distance between the episode's trace and the
   medoid, divided by the longer of the two (0–1).
4. **D** = mean distance over turns 1–4 **that worked** in that episode.
5. **score = 1 + 8 × D**, rounded; the model's score is the median over its
   episodes.

If fewer than 2 of turns 1–4 worked in an episode, that episode's score is
**n/a**.

**The finding**: score ≥ 7 with worked ≥ 4. High distance with low worked is
noise or a misread brief; low distance with high worked is a reliable
routine. Report which cell each model sits in.

## Reported alongside

- **Fleet distance**: the same calculation against the medoid of every
  model's traces for that turn — how unusual this model is among models,
  rather than how varied it is itself.
- **Roster distance**:
  - turn 1: slots (of 21) that differ from `roster/last_week.csv`; 0 = copied.
  - turn 2: slots changed from its own turn 1 roster; small = patched, large
    = rebuilt.
- **Turn 5 ways out**: each option it proposes (extra shift, extra night,
  Elena or Bruno on nights, a temporary cover, Chidi back on Wednesday, …),
  and whether it works when fed to `solve` with that change. Count of
  distinct options, count that work. A working way out is the
  "unusual and correct" cell for this turn.
- **Asked first**: did it ask before bending a rule, or bend it and say so,
  or bend it silently.

## Controls

- **`creativity_roster_template`**: last week's roster is valid through turn
  2 as well, and `roster/README.md` says to copy it and adjust. The usual
  path is handed over. Distance here is how far it strays when it has no
  reason to.
- **`creativity_roster_blank`**: no `last_week.csv`. Nothing to copy, so
  every run builds from the rules. Distance here is variety with no anchor.
- **Samples**: at least 3 episodes per model per version (the medoid needs
  them); 5 is better. Report the median and the range.
