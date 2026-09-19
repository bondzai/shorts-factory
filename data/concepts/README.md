# Concept library

One file per concept. Hand-written, on purpose.

Every clip `sysviz` makes is an explanation, and a wrong explanation is worse
than no clip — a viewer cannot check it, so they either learn something false or
learn not to trust the channel. So the split here is strict:

* **The prose is hand-written.** Headlines, row labels and the claim line live in
  these files. No model writes them, per clip or otherwise.
* **The numbers are computed.** Hashes, primes, exponents and bit counts come
  from `hashlib` and `pow()` at render time, from the clip's seed. Nothing on
  screen is typed in by hand or invented by a model.

That leaves nothing for either party to get wrong. A reviewer can re-run any
frame's arithmetic in a Python shell in ten seconds, which is the only claim
this module makes about itself.

## Adding one

`engine` names a function in `sysviz.ENGINES` that returns the slot values. A
new concept that fits an existing engine is a file and nothing else. A new
engine is Python, and it has to be arithmetic the viewer could reproduce.
