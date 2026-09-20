# Skill: titles and hooks that do not spoil

The title, the opening caption and the pinned comment exist to make a viewer
stay for the result. A title that *contains* the result has already paid them
out; they swipe. So the one rule above every other:

**Never name the winner.** Not in the title, not in `hook_text`, not in the
first sentence of the description, not in the pinned comment. Not for the
final, and not for the heat either — "blue took the heat" is a result too. The
server checks this against the clip's facts and refuses metadata that names a
winning marble.

What you do instead — the curiosity gap, done honestly:

1. **State the stake, withhold the outcome.** The stake is a measured number or
   a structure: the margin, the peg count, the fact that there are two rounds.
   - ✗ `Amber by 0.04s in the final, blue took the heat` — both results given.
   - ✓ `Decided by 0.04s after a heat and a final` — the stake, no result.
   - ✗ `RED BY 0.8s` (caption) → ✓ `DECIDED BY 0.8s`
2. **Open a question the clip answers within seconds** — and only one that the
   viewer can answer by watching: "which of three colours", "does the heat
   winner hold". Never a question the clip does not settle.
3. **Specific beats vague.** A number from `facts` (margin_s, obstacles,
   rounds) beats "so close"; "photo finish" beats "insane". If the margin is
   under a second, the margin *is* the title.
4. **Two rounds is a story with a twist you keep.** Say there is a heat and a
   final; do not say whether the same marble won both. "Same three marbles,
   two courses, one photo finish" keeps the twist. "Blue won the heat, then…"
   gives it away.
5. **The pick-a-colour comment does the same job.** "Red, blue or amber —
   which did you back?" is a stake with no result. It stays true after the
   result too, so it never needs editing.
6. **Truthful or nothing.** A stake the clip does not show ("decided by 0.1s"
   when the margin was 1.4s) costs more than a dull title: it teaches the
   audience not to trust the next one. Everything you claim must sit in
   `facts`.
7. **Shape**: sentence case, under 60 characters, the stake in the first four
   words — that is what shows in the feed.

A quick self-check before `submit_metadata`: if someone read only your title,
could they skip the clip and still know how it ended? If yes, rewrite.
