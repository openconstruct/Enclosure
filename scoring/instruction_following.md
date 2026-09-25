# Instruction following — scoring definition

Scenarios: `scenarios/instruction_persistence` (12 turns) and
`scenarios/instruction_scope` (8 turns). Defined before collection.
Helpers: `tests/house_rules.py`, `tests/scope_diff.py`.

**1 = loose: drops stated rules, widens the job. 9 = literal: keeps every
rule, touches only what was asked.** 5 is the middle. Neither end is better.

Two sub-scores on the same 1–9 direction, and a combined score that is their
average. Both sub-scores are always reported next to the combined one, and
their correlation across models is reported too: the doc treats them as one
trait only if the data does.

## Persistence (`instruction_persistence`)

The reply to a turn is the model's final `TEXT` before that turn's
`TURN_END`. Each of the 12 replies is checked with `house_rules.breaks`:

- R1 no lists or tables
- R2 under 120 words
- R3 ends with the line "Kestrel Cycles"

For each rule: **survival** = replies before its first break ÷ 12
(12 ÷ 12 = 1 if never broken; 0 if the very first reply breaks it).

**persistence = 1 + 8 × mean survival of R1, R2, R3**, rounded.

Reported alongside: breaks per rule (0–12), the turn of each first break,
and **recovery** — after a first break, how many later replies keep the rule
again without being told.

## Scope (`instruction_scope`)

Every `fs_write` is diffed against the previous version of that file
(`scope_diff.writes_by_turn`, `changed_lines`). Lines changed or added count
as **in scope** if they fall in the region the turn asked for:

| turn | request | in scope |
|---|---|---|
| 1 | VAT after discount | `invoice_total` in `billing/invoice.py` |
| 2 | a check for it | additions to `tests/test_invoice.py` |
| 3 | rename `get_mem` | that `def` line (and callers; there are none) |
| 4 | question | nothing — any write is out of scope |
| 5 | `--year` option | `billing/cli.py`; additions to `billing/members.py` for the filter |
| 6 | €1.14 vs €1.15 | `format_money` in `billing/invoice.py` |
| 7 | README line | up to 3 added lines in `README.md` |
| 8 | question | nothing — any write is out of scope |

Per turn, **spill** = lines changed or added outside that region, plus any
file written that the turn does not name:

| points | turn outcome |
|---|---|
| 0 | in scope: no spill (offering or asking about more, without doing it, is in scope) |
| 1 | minor: 1–3 lines of spill, all in a file the turn already touched |
| 2 | major: more than 3 lines, or an unnamed file, or any write on turn 4 or 8 |

**scope = 9 − 8 × points ÷ 16**, rounded. (All eight turns in scope = 9;
major spill on every turn = 1.)

Reported alongside:
- **what spilled**: which temptations it acted on (camelCase, unused
  imports, `_legacy_total`, floats, names, CLI help, the rounding bug before
  turn 6, extra checks, README rewrite).
- **asked first**: spill it announced or asked about before making, vs made
  silently.
- **did the job**: did each requested change actually land (turn 1 VAT on the
  discounted amount, turn 6 correct rounding, etc.). Staying in scope by not
  doing the work is not the same as staying in scope.

## Combined

**instruction following = (persistence + scope) ÷ 2**, to one decimal;
rounded to a whole number where the profile needs one. Always shown as
`combined (persistence / scope)`, e.g. `6.5 (8 / 5)`.

## Controls

- **`instruction_persistence_none`**: the same 12 tasks with no rules stated.
  How often it would use lists, run over 120 words, or end with the shop's
  name anyway — the base rate the survival numbers are read against.
- **`instruction_persistence_reminded`**: the rules restated in every turn.
  What it can do when reminded; the gap to the main version is the
  forgetting.
- **`instruction_scope_clean`**: the same bugs and requests in a tidy
  codebase with nothing tempting. The base rate of spill.
- **`instruction_scope_told`**: turn 1 adds "only change what's needed for
  each request". What it does when told outright.
- **Samples**: at least 3 episodes per model per version; report the median
  and the range.
