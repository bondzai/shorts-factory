# Courses and themes

## Courses

A race needs a descent, and each shape of descent is a different picture to
the similarity gate and a different question to the viewer.

| course | what the viewer sees | measured (24 seeds) |
|---|---|---|
| **zigzag** | six to nine full-width ramps, alternating sides | 19 finish inside the window |
| **pegboard** | a Galton board: rows of small pegs, nothing to rest on | 19 |
| **bumpers** | pinball: a lattice of large elastic bumpers | 19 |

Pace is set with gravity per course, not geometry — the geometry is what keeps
the solver honest (slopes near 0.4, throats measured in radii), and gravity is
a dial that cannot jam. A seed picks a course by weight unless a task names
one (`make-clip` has a `course` parameter).

A fourth course, wedges, was built and cut: marbles balanced on an apex, or
wedged between an arm and the next row's wall lip, or sat in a wall corner —
three traps, and fixing one opened another. Seven finishes in 24 at best. It
is not offered.

## Themes

A theme is colours, marble names, a caption colour and a decoration, with an
optional window in the calendar. Settings → Themes edits them. The active
theme is whatever is forced there; else the theme whose window contains today;
else the default. Nothing else in the factory knows what month it is.

Marble names matter beyond looks: they appear in descriptions, facts and
titles — "the gold marble reaches the bottom first" — so a theme's names are
words a viewer would use, and a colour that vanishes against its backdrop is
not offered.

Decorations are a few dozen particles behind the marbles — snow, embers,
sparks, drops — deterministic from the seed so a re-render matches. They never
touch the physics.

Shipped: Default, Halloween (Oct 15–31), Christmas (Dec 1–26), New Year
(Dec 27–Jan 3), Valentine (Feb 7–14), Songkran (Apr 10–16).
