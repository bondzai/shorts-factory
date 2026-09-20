# Retitle what is underperforming on {channel_name}

A published clip has one lever left: its title. This playbook pulls it with a
gauge attached — `retitle` keeps the old title and the metrics at the moment of
the change, so the next metrics pull can be read as before/after.

## What is published, worst swipe-away first

{published}

## How to read those numbers

A high "average viewed" with a high "swiped away" is a clip that holds the
viewers who start it and loses the ones deciding whether to. That is a title
and first-second problem, and the title is the half you can still touch.

Propose a retitle only where the numbers make a case. For each:

- the clip id and the new title (20-90 characters, English, sentence case)
- what specific thing the new title states that the old one did not — a
  course number from the clip's facts (spinners, pegs, marbles) beats a
  question; the winner and the margin are never in a title
- what you would expect to move, and by roughly how much, so the next pull can
  say whether it did

Do not retitle a clip whose numbers are fine to see what happens. Every change
resets the before/after clock, and with n this small each one is expensive.

Where the numbers do not support a change, say so. "Nothing to retitle" is a
complete answer.

## Hard limits

- 20-90 characters. A title that promises something the clip does not show is
  the one mistake that costs more than a weak title; check the claim against
  `get_clip` facts.
- On a manual-driver channel the change has to be typed into Studio by a
  person; the tool result says when that is the case. Say it in your summary.

## This channel's rules

{rules}
