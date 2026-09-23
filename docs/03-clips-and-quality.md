# Clips and quality

## The hard gates

Before any opinion, four measurements. A clip that fails any of them is
rejected in code and never reaches a reviewer.

- **Length** inside the window (Settings → Factory settings).
- **Loudness** normalised to the target, within tolerance.
- **Similarity** — a perceptual hash of four frames, compared against every
  clip on this channel that could still be on YouTube. Above the ceiling is a
  reject. Rejected and binned clips do not count; published ones always do,
  even from the bin, because YouTube has them whether this page shows them
  or not.
- **A finished race**: a stage that stalls, or finishes under the shortest
  allowed length, is retried on a derived seed before it costs anything.

## Why similarity is the one that bites

A variant has a capacity: the number of clips it can make before new ones
start looking like old ones to the hash. Measured over 25 seeds, a zigzag race
alone accepts about 15; with the three stages mixed, 18. That is why there
are several stages and several variants, and why a fixed seed makes one clip
and not three.

## Captions and titles

A viewer gives the first frame one second, and the hook has one job in it:
**make them pick a marble.** A viewer who has picked a side has a stake, and a
viewer with a stake stays to the finish. That single idea sets every rule
here; the full brief agents get is `prompts/skill-hooks.md`.

**The opening caption** is two or three words in the second person — `PICK
ONE`, `CALL IT NOW`, `BET ON ONE`. The render picks one per seed from the bank
under Settings → Factory → opening captions (separated by `|`), so consecutive
clips do not open on the same words. It is never the result and never the
stage's numbers: `DECIDED BY 0.4s` pays the bet out before it is placed, and
`PICK ONE · 4 SPINNERS` asks for arithmetic in the second we have. The second
round of a two-round clip opens on `FINAL · RUN IT BACK`.

**The caption is drawn large** — 11.5% of the frame's width, set under
Settings → Factory → caption size. Studio's number for this channel is that
most viewers who start a clip watch most of it and few get past the opening,
so the one thing on screen in that second is sized to be read at arm's
length rather than to be tasteful.

**The clip asks for a comment once the result is in.** `COMMENT YOUR PICK`
is drawn from the moment the winner crosses until the clip ends, about a
second later (Settings → Factory → closing ask; empty turns it off). It
cannot appear earlier, because an ask on screen would tell the viewer the
race is about to end. The pinned comment should say the same thing in the
same words, with the colours named.

**A race cannot loop seamlessly**, and nothing in the wording should imply
it does: it starts with marbles at the top and ends with them at the bottom.
What earns the replay is an ending worth seeing that comes round quickly,
which is why the clip cuts about a second after the winner crosses.

**The title** is the same hook written for the feed: lead with the pick, name
the lineup, present tense — `Pick your marble: red, blue or green`. Naming
every colour gives nothing away; naming one is a spoiler. Numbers only when
they are the drama ("75 pegs" as scale), never as inventory.

**The pinned comment** asks the pick again after the fact — `Red, blue or
green — which did you back?` — and stays true whatever happened.

**The server enforces the two hard rules** on `submit_metadata` and
`retitle`: no winner's name (heat or final) and no result language
("decided", "won", "took", "by 0.7s", "photo finish", "upset") in the title,
caption, pinned comment or first sentence of the description. Refused
metadata comes back with the reason, and the agent writes it again. **Re-render caption** on Today burns a
different caption into the same race (same seed, only the pixels change).

A title can change at any time, including after publishing. **Retitle** keeps
the old title and the metrics at that moment, so the next numbers can be read
as before/after rather than one blurred figure. On a manual channel the new
title also has to be typed into Studio; the page says when.

**Suggest titles**, on any clip, asks the Metadata brain for five ways in —
one per angle — and shows only the ones the server let through:

| angle | what it does to the thumb | e.g. |
|---|---|---|
| pick | the ritual: choose a marble, whole lineup named | `Pick your marble: red, blue or green` |
| curiosity | there is an outcome; it is not said | `Only one gets out. Red, blue or green?` |
| stakes | a number that describes the scene, never the ending | `Fifty-four marbles, one throat` |
| challenge | call it before the mechanism does | `Call it before the wheel does` |
| series | one of a run, a reason to come back | `Run it back: same three, the drums` |

Nothing the model says is trusted. Each idea goes through the same spoiler
gate as an agent's title, the feed's 60-character line, the channel's emoji
setting (`[titles] emoji`, off — the rules say none, and no number yet says
otherwise), English only, and a repetition check: an idea that opens on the
same three words as any of the last twenty titles is dropped, which is the
"not the same title in different colours" the button exists for. What was
dropped is listed with its reason, so two ideas instead of five says why.

Choosing one is a retitle, so the old title and its numbers are kept — and
the angle is kept with them (`angle: curiosity` in the history). When metrics
arrive, that is how the channel learns which angle earns, instead of arguing
about it. On an unpublished clip each idea can also carry a caption; choosing
that re-renders the same race with the new opening words.

## Where the files are

Renders live under `data/work/<channel>/<clip>/clip.mp4`. Pressing
**I uploaded it** copies the file and its text to `data/out/<channel>/publish-queue/`
as your upload record. Retention (Settings) says how long rejected and
published renders are kept; only `factory gc` deletes. The bin hides a clip
without touching its file; **Delete forever** removes the render directory
and the record, never the publish-queue copy.

`data/` is not in git. Back it up yourself if it matters.
