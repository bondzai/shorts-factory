"""The words burned into a clip: the opening caption, the second round's
caption, and the closing ask — never the same twice on a channel.

Each is held to the hooks research (docs/03, prompts/skill-hooks.md):

- **the opening caption asks for the pick**: second person or an imperative
  verb, two to five words, read in half a second at arm's length;
- **nothing the race has not produced**: no result words, no numbers, no
  colour and no marble's name — naming one is a spoiler by the server's rule;
- **the stage is a name, not a spec**: "WHO CLEARS THE RAPIDS?", never
  "4 SPINNERS";
- **every clip its own words**: a viewer scrolling the channel page should
  not read the same caption twice, and the similarity guard cannot see text.

Candidates come in order — the season level's own hook, then lines bound to
the clip's stage, then general ones — shuffled by the seed within each group,
and the first that passes the rules and is not already on the channel wins.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from dataclasses import dataclass

from . import logs
from .models import HOOK_MAX
from .pipeline.spoilers import RESULT_WORDS

COLOURS = {"red", "blue", "green", "amber", "violet", "yellow", "orange", "purple", "white", "pink",
           "teal", "brown", "gold", "silver", "black"}
ASK_CUES = ("PICK", "CALL", "BET", "BACK", "CHOOSE", "LOCK", "NAME", "WHO", "WHICH", "YOUR", "WHO'S")
MIN_WORDS, MAX_WORDS = 2, 5

HOOKS = (
    "PICK ONE", "PICK YOUR MARBLE", "CALL IT NOW", "WHICH ONE IS YOURS?", "BET ON ONE",
    "LOCK IN YOUR PICK", "CHOOSE YOUR MARBLE", "WHO ARE YOU BACKING?", "CALL IT BEFORE IT DROPS",
    "BACK ONE NOW", "PICK BEFORE THE DROP", "NAME YOUR MARBLE", "CHOOSE ONE, NO SWITCHING",
    "PICK A SIDE", "YOUR CALL, GO", "WHO GETS YOUR VOTE?", "CALL YOUR MARBLE", "WHO'S YOUR MARBLE?",
    "PICK ONE, STICK WITH IT", "YOUR PICK, RIGHT NOW",
)
HOOK_STAGE = ("WHO CLEARS THE {S}?", "PICK ONE FOR THE {S}", "CALL THE {S}", "BACK ONE ON THE {S}",
              "WHO RULES THE {S}?", "WHICH ONE TAMES THE {S}?", "YOUR PICK FOR THE {S}?")
# The final races on a stage chosen after the heat, so its line names none:
# an opener and a prompt, every pairing its own caption.
_FINAL_OPENERS = ("FINAL", "ROUND TWO", "SECOND RUN", "NEXT STAGE")
_FINAL_PROMPTS = ("PICK AGAIN", "SAME PICK?", "SWITCH OR STAY?", "CALL IT AGAIN", "STILL YOURS?", "NEW TRACK",
                  "LOCK IT IN", "WHO NOW?", "YOUR MOVE", "ONE MORE RUN", "ALL IN", "LAST CALL", "RESET",
                  "SAME FIELD", "FRESH TRACK", "KEEP YOUR PICK?", "RUN IT BACK")
FINALS = tuple(f"{o} · {p}" for o in _FINAL_OPENERS for p in _FINAL_PROMPTS) + ("SAME MARBLES, NEW STAGE",)
FINAL_STAGE = ("FINAL · THE {S}", "ROUND TWO · THE {S}", "NOW THE {S}", "NEXT UP · THE {S}")
ASKS = ("COMMENT YOUR PICK", "WHO DID YOU BACK?", "DID YOUR PICK MAKE IT?", "DROP YOUR PICK BELOW",
        "WAS YOUR CALL RIGHT?", "TELL US YOUR CALL", "WHO WAS YOURS?", "YOUR PICK? COMMENT IT",
        "CALLED IT? COMMENT", "WHO DID YOU PICK?", "DID YOU CALL IT?", "YOUR MARBLE? COMMENT IT",
        "RIGHT CALL? TELL US", "WHICH ONE DID YOU PICK?", "WHO WERE YOU BACKING?", "COMMENT YOUR MARBLE",
        "DID YOURS HOLD UP?", "PICK RIGHT? COMMENT", "YOUR CALL? DROP IT BELOW", "SAY WHO YOU PICKED",
        "NAILED IT? COMMENT", "WHO HAD YOUR VOTE?", "DID YOU SEE IT COMING?", "WHO'S YOUR PICK NEXT?",
        "SAME PICK NEXT TIME?", "WOULD YOU SWITCH NOW?", "TELL US WHO YOU BACKED", "WHO DID YOU CALL?",
        "YOUR PICK, IN THE COMMENTS", "RIGHT MARBLE? SAY SO")
ASK_STAGE = ("YOUR {S} PICK?", "WHO'D YOU BACK ON THE {S}?", "{S}: WHO WAS YOURS?", "CALLED THE {S}?")


@dataclass
class Captions:
    hook: str
    final: str | None
    ask: str | None

    def as_dict(self) -> dict:
        return {"hook": self.hook, "final": self.final, "ask": self.ask}


def key(text: str) -> str:
    """What counts as the same words: case, punctuation and spacing aside."""
    return " ".join(re.sub(r"[^A-Z0-9 ]+", "", text.upper()).split())


def problem(text: str, *, kind: str = "hook", names: tuple[str, ...] = ()) -> str | None:
    """Why a caption breaks the rules, or None. `kind` is hook, final or ask."""
    words = re.findall(r"[A-Za-z']+", text)
    if not text.strip():
        return "empty"
    if len(text) > HOOK_MAX:
        return f"{len(text)} characters; the most that fits across a phone is {HOOK_MAX}"
    if not MIN_WORDS <= len(words) <= MAX_WORDS + (1 if kind != "hook" else 0):
        return f"{len(words)} words; a caption is {MIN_WORDS} to {MAX_WORDS}, read in half a second"
    if re.search(r"\d", text):
        return "a number; the stage is a name, not a spec"
    if RESULT_WORDS.search(text):
        return "result words; the caption asks, it never tells"
    lowered = {w.lower() for w in words}
    if lowered & COLOURS or lowered & {n.lower() for n in names}:
        return "names a colour or a marble; naming one is a spoiler"
    if kind == "hook" and not any(text.upper().startswith(c) or f" {c}" in text.upper() for c in ASK_CUES):
        return "does not ask for the pick; a hook is second person or a verb (PICK, CALL, WHO, WHICH…)"
    return None


def _field(row: sqlite3.Row, kind: str) -> str | None:
    if kind == "hook":
        return row["hook_text"]
    facts = json.loads(row["facts_json"] or "{}")
    return (facts.get("captions") or {}).get(kind)


def used(conn: sqlite3.Connection, channel_id: str, kind: str, *, exclude: str | None = None) -> set[str]:
    """Captions already on this channel's live clips. A rejected, failed or
    binned clip never shipped, so its words are free again."""
    rows = conn.execute(
        """SELECT id, hook_text, facts_json FROM clips WHERE channel_id = ? AND deleted_at IS NULL
           AND status NOT IN ('qc_rejected', 'failed')""", (channel_id,)).fetchall()
    return {key(t) for r in rows if r["id"] != exclude and (t := _field(r, kind))}


def _candidates(first: list[str], stage_lines: tuple[str, ...], general: tuple[str, ...],
                stage: str | None, rng: random.Random) -> list[str]:
    bound = [line.replace("{S}", stage.upper()) for line in stage_lines] if stage else []
    loose = list(general)
    rng.shuffle(bound)
    rng.shuffle(loose)
    return [c.upper() for c in first if c] + bound + loose


def _pick(conn, channel_id, kind, candidates, *, exclude, names) -> tuple[str | None, str | None]:
    taken = used(conn, channel_id, kind, exclude=exclude)
    passing = [c for c in candidates if problem(c, kind=kind, names=names) is None]
    for c in passing:
        if key(c) not in taken:
            return c, None
    # Every line in the bank is on a live clip: repeat the one used longest ago
    # rather than ship nothing, and say so.
    return (passing[0] if passing else None), "every candidate is already on the channel"


def choose(conn: sqlite3.Connection, channel_id: str, *, seed: int, stage: str | None = None,
           level_hook: str | None = None, rounds: int = 1, names: tuple[str, ...] = (),
           final_stage: str | None = None,
           exclude: str | None = None, with_ask: bool = True) -> Captions:
    """Words for one clip. Deterministic: same seed, same channel, same words."""
    rng = random.Random(f"captions:{seed}")
    notes = {}
    hook, notes["hook"] = _pick(conn, channel_id, "hook",
                                _candidates([level_hook or ""], HOOK_STAGE, HOOKS, stage, rng),
                                exclude=exclude, names=names)
    final = ask = None
    if rounds >= 2:
        # Named only when the final's own stage is known: it races elsewhere.
        final, notes["final"] = _pick(conn, channel_id, "final",
                                      _candidates([], FINAL_STAGE, FINALS, final_stage, rng),
                                      exclude=exclude, names=names)
    if with_ask:
        ask, notes["ask"] = _pick(conn, channel_id, "ask", _candidates([], ASK_STAGE, ASKS, stage, rng),
                                  exclude=exclude, names=names)
    for kind, note in notes.items():
        if note:
            logs.event("captions.reused", level="warn", channel=channel_id, kind=kind, note=note)
    return Captions(hook or "PICK ONE", final, ask)


def check_given(conn: sqlite3.Connection, channel_id: str, text: str, *, exclude: str | None = None,
                names: tuple[str, ...] = ()) -> str | None:
    """Why an opening caption someone typed (an agent, the operator) cannot
    ship: the rules, then whether the channel already has it."""
    reason = problem(text, kind="hook", names=names)
    if reason:
        return reason
    if key(text) in used(conn, channel_id, "hook", exclude=exclude):
        return f"'{text}' is already the caption of another clip on this channel"
    return None
