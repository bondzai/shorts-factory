# Playbooks

The instructions an agent gets, kept in git instead of retyped into a chat
window each time.

A playbook is markdown with `{placeholders}`. `factory playbook <name>` fills
them from the live database — the channel's own rules, what it has made in the
last fortnight, its measured retention, the current sameness ceiling — and
prints the result. That substitution is the point. A prompt pasted from a
previous session is out of date the moment a clip publishes; one rendered from
the database carries this morning's numbers, so the agent stops proposing what
was already made last week.

    factory playbook make-clip --channel main | pbcopy

There is an MCP tool of the same name, so an agent already connected to the
factory can fetch its own instructions rather than being handed them.

Guidance based on a measurement carries the measurement with it, so that when
the number moves the instruction can be argued with rather than obeyed out of
habit.
