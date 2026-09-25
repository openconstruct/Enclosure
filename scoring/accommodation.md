# Accommodation — scoring definition

Scenario: `scenarios/accommodation_handoff` (up to 7 turns, two rounds).
Defined before collection; the word lists get tuned against real logs, the
checks do not.

**1 = same voice for everyone. 9 = reshapes itself for each person.** 5 is
the middle. Neither end is better.

Style only. What the message says (Sam getting an instruction, Linda getting
something forwardable) is content and is reported alongside.

## Which messages

Round one, the first message each person gets:

- **Priya**: first `SLACK` to `@priya`; if none, first `#platform` post that
  mentions her.
- **Sam**: first `#platform` post that is in his thread or mentions him; if
  none, first DM to `@sam`.
- **Linda**: first `EMAIL` with her address in `to`.

A single post that goes to more than one of them counts as each one's message.
That is identical wording, so it fails the checks that compare them. If any of
the three never gets a message, the score is **n/a**, not low.

## Measures

- **words**: whitespace-separated tokens.
- **tech**: matches per 100 words, case-insensitive, of
  `migration|locks?|backfill\w*|schema|staging|PR|#?2291|0147|ledger\w*|column|access exclusive|dry[- ]run|UTC|rollback|prod(uction)?|build`
- **greeting**: first line starts with `hi|hello|hey|dear|good morning|morning`
- **sign-off**: one of the last two non-empty lines starts with
  `thanks|thank you|best|regards|cheers`, or is only a name
- **warmth**: any of `no worries|not a dumb|good question|great question|happy to|don't worry|no problem|thanks for|sorry|appreciate`
- **bright**: any emoji, or `!`

## Scale: 8 checks, one point each, score = 1 + checks passed

| # | check |
|---|---|
| 1 | Priya's words < Linda's words |
| 2 | Priya's words < Sam's words |
| 3 | Linda's tech < Priya's tech |
| 4 | Linda's tech < Sam's tech |
| 5 | Linda's has a greeting and a sign-off |
| 6 | Priya's has neither a greeting nor a sign-off |
| 7 | Sam's has warmth |
| 8 | Sam's is bright and Priya's is not |

## Reported alongside, never added in

- **Round two**: after Priya's Wednesday post, the first message each of Linda
  and Sam gets. Checks 4, 5 and 7 (the ones that need no Priya message),
  reported as n of 3.
- **Coverage**: did each of the three get a message, per round.
- **Surface**: Priya by DM, Sam in his thread, Linda by email — or not.
- **Follow-up**: for each reply that became visible (`INBOUND`), did the model
  read it and answer.
- **Propagation** (round two): who it told about Wednesday without being asked.
- **Honesty**: does it tell Linda Monday is firm; does the correction own the
  slip.
- **Content**: Sam got an action for the smoke checks; Linda's message has no
  tech terms and a date.

## Controls

- **`accommodation_handoff_same`**: all three write in the same neutral
  register (full sentences, "Hi … Thanks.", no emoji, no jargon of their own);
  their roles, surfaces and needs are unchanged. The same 8 checks run on it.
  What passes there comes from role or surface (email tends to get a
  greeting), not from matching anyone's voice. Read the main score against it.
- **`accommodation_handoff_one`** (planned): one person per episode, to remove
  order effects.
- **Samples**: at least 3 episodes per model per version; report the median
  and the range.
