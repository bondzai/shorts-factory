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
- **A finished race**: a course that stalls, or finishes under the shortest
  allowed length, is retried on a derived seed before it costs anything.

## Why similarity is the one that bites

A variant has a capacity: the number of clips it can make before new ones
start looking like old ones to the hash. Measured over 25 seeds, a zigzag race
alone accepts about 15; with the three courses mixed, 18. That is why there
are several courses and several variants, and why a fixed seed makes one clip
and not three.

## Captions and titles

The caption in the first second is measured, not written: when the runner-up
finishes inside a second, the race is captioned with its margin —
`DECIDED BY 0.4s` — because that is a fact the simulation produced. A runaway
race falls back to the default caption. **Re-render caption** on Today burns a
different caption into the same race (same seed, only the pixels change).

A title can change at any time, including after publishing. **Retitle** keeps
the old title and the metrics at that moment, so the next numbers can be read
as before/after rather than one blurred figure. On a manual channel the new
title also has to be typed into Studio; the page says when.

## Where the files are

Renders live under `data/work/<channel>/<clip>/clip.mp4`. Pressing
**I uploaded it** copies the file and its text to `data/out/<channel>/publish-queue/`
as your upload record. Retention (Settings) says how long rejected and
published renders are kept; only `factory gc` deletes. The bin hides a clip
without touching its file; **Delete forever** removes the render directory
and the record, never the publish-queue copy.

`data/` is not in git. Back it up yourself if it matters.
