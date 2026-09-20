# Skill: titles and hooks that do not spoil

The title, the opening caption and the pinned comment exist to make a viewer
stay for the result. Anything that tells them the result — or even that it
*has* a result already — pays them out before they press play; they swipe.
Two rules above every other, both checked by the server against the clip's
facts, which refuses metadata that breaks them:

**Never name the winner.** Not in the title, not in `hook_text`, not in the
first sentence of the description, not in the pinned comment. Not for the
final, and not for the heat either — "blue took the heat" is a result too.

**Never tell the result in any form.** No "decided", "won", "took", "beats",
"upset", "photo finish", and no margin — "by 0.7s" is the ending with the
name filed off. A title in the past tense is a report; a title in the
present tense is an invitation. The margin lives in `facts` and may appear
in the description *after* its first sentence, where only someone who
already watched will read it.

What you write instead — the scene, in the present tense, and a choice:

1. **Say what they are about to watch.** Numbers from `facts` that describe
   the course, not the outcome: marbles, spinners, pegs, ramps, rounds.
   - ✗ `Amber by 0.04s in the final, blue took the heat` — both results.
   - ✗ `Decided by 0.7s in the heat, then a final on 8 ramps` — still the
     result, and past tense.
   - ✓ `Three marbles, four spinning bars, one gets through`
   - ✓ `Pick a marble before the spinners do`
   - ✗ `DECIDED BY 0.8s` (caption) → ✓ `PICK ONE · 4 SPINNERS`
2. **Make them commit.** "Pick one", "which do you back", "call it now" — a
   viewer who has picked stays to find out. This is also what the pinned
   comment does: "Blue, amber or violet — which did you back?" Naming the
   whole lineup gives nothing away; singling one out does.
3. **Ask only what the clip answers**, and within seconds: which of three
   colours; whether the one you picked survives the spinners. Never a
   question the clip does not settle.
4. **Two rounds is a story with a twist you keep.** Say there is a heat and a
   final; never whether the same marble takes both.
5. **Truthful or nothing.** Four spinners in the title means four in `facts`.
   A stake the clip does not show costs more than a dull title: it teaches
   the audience not to trust the next one.
6. **Shape**: sentence case, under 60 characters, the scene in the first four
   words — that is what shows in the feed. American spelling on the US channel.

A quick self-check before `submit_metadata`: if someone read only your title,
would they know anything about how it ends — who, how close, or even that it
was close? If yes, rewrite.
