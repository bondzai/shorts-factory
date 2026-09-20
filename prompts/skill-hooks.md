# Skill: hooks that make a viewer pick a side

Think like the channel's marketer, not its engineer. A viewer gives the first
frame one second. In that second the hook has exactly one job: **make them
pick a marble.** A viewer who has picked a side has a stake — their marble
might lose — and a viewer with a stake stays to the finish. Nothing else the
title or caption could say does as much as getting the pick.

Everything below follows from that.

## The two rules the server enforces

**Never name the winner.** Not in the title, the caption, the pinned comment
or the first sentence of the description; not for the final and not for the
heat. A named winner is a paid-out bet.

**Never tell the result in any form.** No "decided", "won", "took", "beats",
"upset", "photo finish", and no margin — "by 0.7s" is the ending with the
name filed off. The margin lives in `facts`; it may appear in the description
after its first sentence, where only someone who already watched will read it.

Metadata that breaks either rule is refused with the reason; write it again.

## The caption (`hook_text`) — the render chooses one, you rarely override it

- **Two or three words, second person, a verb.** `PICK ONE`. `CALL IT NOW`.
  `BET ON ONE`. `DON'T BLINK`. Readable in half a second on a phone.
- **No arithmetic.** `PICK ONE · 4 SPINNERS` asks the viewer to read a spec
  sheet in the second they gave us. How many spinners there are is something
  they *see*; the caption's job is to make them care which marble gets past
  them.
- **No slogans about the ending.** `INSANE FINISH` is a claim about the result,
  and a lie one time in three.
- The render rotates its captions by seed (Settings → Factory → opening
  captions). Override only when the operator's Directions ask for a wording,
  and keep it inside these rules.

## The title — the same hook, written for the feed

A title is read before the first frame on the feed, so it is the hook's second
chance. Marketing rules for it:

1. **Lead with the pick.** A verb or "you" in the first three words:
   `Pick your marble: red, blue or green`, `Call it before the spinners do`,
   `Three go in. Which one is yours?`
2. **Name the lineup, never the winner.** The colours are the menu the viewer
   picks from; naming all of them gives nothing away. Naming one is a spoiler.
3. **Present tense, second person.** "You" and "which" are invitations; "won"
   and "decided" are reports.
4. **Numbers only when they are the drama.** "75 pegs" can be a scale claim;
   "3 spinners, 24 bumpers" is inventory. Default to none.
5. **Truthful or nothing.** Every colour, count and round you mention is in
   `facts`. A promise the clip does not keep costs more than a dull title —
   it teaches the audience not to trust the next one.
6. **Shape.** Sentence case, under 60 characters, American spelling on the US
   channel, no emoji, no ALL CAPS.

   - ✗ `Amber by 0.04s in the final, blue took the heat`
   - ✗ `Decided by 0.7s in the heat, then a final on 8 ramps`
   - ✗ `Blue, violet, green: 3 spinners, 24 bumpers` — a parts list
   - ✓ `Pick your marble: blue, violet or green`
   - ✓ `Call it now — only one gets out`
   - ✓ `Two rounds, same three marbles. Which one is yours?`

## The pinned comment — the pick, again, after the fact

`Blue, violet or green — which did you back?` It names the whole lineup, asks
the one question the viewer can answer, and stays true after the result, so
it never needs editing. Every clip gets one.

## The description

First sentence: the pick, in plain words (it is checked like a title). After
that, the facts are welcome — the course, the number of rounds, and yes, the
margin — for the viewer who has already watched and wants to know how close
it was.

## Self-check before `submit_metadata`

Read only your title. Do you know who won, how close it was, or even that it
was close? Rewrite. Does it ask the reader to pick a marble? If not, it is not
doing the job.
