# Plan a week for {channel_name}

Propose clips to make. Nothing is rendered by this playbook — the output is a
list someone will run.

## Available

{modules}

## Already made

{recent}

## How it performed

{retention}

## Constraints worth knowing before you propose anything

Similarity above **{max_sameness}** against an existing clip on this channel is
rejected in code. Reseeding one variant does not escape that: the measured
capacity of a single variant before the gate starts rejecting is roughly a dozen
to twenty clips, which is why the factory has several. A week of the same
variant with new seeds will mostly fail to render, and the run will have cost
nothing but your time.

So spread the week across variants, and say for each proposal:

- generator, variant and seed
- what the viewer sees in the first second — concretely, not "something eye-catching"
- why it is worth making *now*, given the numbers above

Where the numbers do not support a proposal, say that. A week with four honest
proposals is better than seven padded ones.

## This channel's rules

{rules}
