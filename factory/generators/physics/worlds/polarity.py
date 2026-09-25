"""World 3, polarity swap (Season 0, L22-L30): what a level's magnets do over time.

The stage kit's magnets pull, always, at one strength (stagekit.MAGNET_PULL,
measured never to hold a marble). Every level of this world is a magnet
doing something else: flipping to push at halfway, pushing at the finish,
riding an arm, gripping the whole field and letting go. The geometry is
stagekit's (the `tug`, `side-magnets`, `detour`, `arm`, `clump` sections);
this module is the time. Everything goes through one **polarity clock** per
round — a list, one number per magnet (`Rig.magnet_polarity`): 1 is the
kit's pull, -k pushes k times as hard, 0 is off. Each magnet answers to its
role (`stagekit.magnet_roles`), so the final can flip the band's magnets
while the arm keeps pulling and the finish keeps pushing.

Nothing here looks at who a marble is (docs/08 rule 2.4). A clock reacts to
the race — how far the leader has come, whether the whole field is in the
clump — which is a mechanism a viewer can watch.
"""

from __future__ import annotations

import math

from ...stagekit import MAGNET_PULL, MARBLE_R, _magnet, magnet_roles

# The flip. For KICK_S seconds the band's magnets push KICK times the kit's
# pull — the jolt that throws whoever is nearest a core — and from then on
# PUSH times. The two are apart because a push strong enough to throw a
# marble is strong enough to hold one up: from about 2.5 x the pull a
# pushing field beats gravity above its core, and a marble balanced there
# is parked, not racing. PUSH stays under that, so after the jolt nothing
# can hover; the jolt is too short to park anything. Measured on L22
# (docs/06, World 3): a steady push of 15-60 x launched but parked 8-11
# marbles in 50; this launches someone in 33 races of 48 and parks 4 in 96.
KICK = 45.0
KICK_S = 0.4
FLIP_PUSH = 2.0
# The reverse finish: a magnet under the line that pushes up, this many
# times the kit's pull, over a field this many softenings wide. It has to be
# strong: a marble reaches the line with the speed of the whole run-in. At 7 x
# it never turned one back in 24 races; at 35 x, 12 in 48; at 50 x, 22 in 48.
FINISH_PUSH = 50.0
FINISH_REACH = 3.2
FINISH_CORE_Y = 44.0  # sim px: under the line (110), clear of the floor
# The arm's magnets pull harder than the band's: the tips move, and a pull
# that only matters to a marble at rest never gets to act on one.
ARM_PULL = 2.0
# The detour's magnet lane pulls this many times the kit's pull, so the short
# lane costs something: at the kit's 1.0 the magnet lane won every one of 48
# races; at 4.0 it wins 31 and the shielded lane 17 (docs/06, World 3). Over
# the capture knee (2.5) on purpose: the lane is short, and a marble that
# circles a core for a moment is the cost of the short cut.
LANE_PULL = 4.0
# The clump: how hard the grip holds (x the kit's pull), how long it holds
# the whole field once it has it, and the latest it lets go regardless.
GRIP = 8.0
HOLD_S = 1.0
RELEASE_BY_S = 9.0
EJECT, EJECT_S = 1.5, 0.5  # the release: a push this strong, this long
BRAKE = 2.5  # 1/s of drag inside the clump's inner field while it grips
CLUMPED = 0.6  # of the clump's reach: inside this, a marble is in the clump


def _const(value):
    return lambda f: value


def install(rig, style, rules: dict) -> None:
    """The round's polarity clock: `rules` maps a role to fn(frame) -> number;
    a magnet whose role has no rule pulls as the kit's does (1). Each rule is
    called once a frame, so a rule may keep state."""
    roles = magnet_roles(style)

    def polarity(f):
        seen = {}
        out = []
        for k in range(len(style.magnets)):
            role = roles.get(k, "band")
            if role not in seen:
                rule = rules.get(role)
                seen[role] = rule(f) if rule else 1
            out.append(seen[role])
        return out

    rig.clock("polarity", polarity)
    rig.magnet_polarity("polarity")


def flip_rule(rig, flip_at: float, push: float, kick: float = KICK, kick_s: float = KICK_S):
    """1 until the leader is `flip_at` of the way down; then -kick for
    `kick_s` seconds and -push for good, with a `flipped` event at the switch."""
    flipped: list[float] = []

    def rule(f):
        if f.progress < flip_at:
            return 1
        if not flipped:
            flipped.append(f.t)
            rig.emit("flipped", None, at=flip_at)
        return -kick if f.t - flipped[0] < kick_s else -push

    return rule


def add_finish_magnet(rig, space, style, w: float, h: float) -> int:
    """A magnet's core under the finish line, in the middle, in `style.magnets`
    with the role "finish". A `repelled` event marks each marble it turns
    back: falling through the open run-in below the throat, then moving up."""
    core = w * 0.042
    soft = core + w * MARBLE_R
    reach = soft * FINISH_REACH
    x, y = w / 2, FINISH_CORE_Y
    _magnet(space, x, y, core)
    style.magnets.append((x, y, core, soft, reach, MAGNET_PULL))
    k = len(style.magnets) - 1
    magnet_roles(style)[k] = "finish"
    run_in = rig.finish_y + h * 0.085 if rig.finish_y is not None else h * 0.2
    falling: dict[int, bool] = {}
    turned: set[int] = set()

    def watch(f):
        for i, (px, py) in enumerate(f.positions):
            if not f.alive[i] or f.names[i] in f.finished or i in turned:
                continue
            if py > run_in or math.hypot(px - x, py - y) > reach:
                falling.pop(i, None)
                continue
            vy = rig.balls[i].body.velocity.y
            if vy < -10.0:
                falling[i] = True
            elif vy > 5.0 and falling.get(i):
                turned.add(i)
                rig.emit("repelled", i)

    rig.on_frame(watch)
    return k


def grip_rule(rig, style, grip: float, hold: float, latest: float):
    """The clump magnet's strength: `grip` from the start, until the whole
    field still racing has been inside its field for `hold` seconds (a
    `clumped` event when it first is) or until `latest` s, whichever comes
    first; then 0 for good, with a `released` event."""
    roles = magnet_roles(style)
    state = {"since": None, "released": False}

    def rule(f):
        if state["released"] is not False:
            # The letting go: a short push, so nothing is left balanced on
            # top of the core, then nothing at all.
            return -EJECT if f.t - state["released"] < EJECT_S else 0
        ks = [k for k, role in roles.items() if role == "clump"]
        racing = [i for i in range(len(f.names)) if f.alive[i] and f.names[i] not in f.finished]
        held = [i for i in racing
                if any(math.hypot(f.positions[i][0] - style.magnets[k][0],
                                  f.positions[i][1] - style.magnets[k][1]) <= style.magnets[k][4] * CLUMPED
                       for k in ks)]
        if racing and len(held) == len(racing) and state["since"] is None:
            state["since"] = f.t
            rig.emit("clumped", None, held=len(held))
        if (state["since"] is not None and f.t - state["since"] >= hold) or f.t >= latest:
            state["released"] = f.t
            rig.emit("released", None, held=len(held))
            return -EJECT
        return grip

    return rule


# --- the mechanics a level names (`params.section`) -----------------------------------------

def _flip(rig):
    return flip_rule(rig, float(rig.knob("flip_at", 0.5)), float(rig.knob("push", FLIP_PUSH)),
                     float(rig.knob("kick", KICK)), float(rig.knob("kick_s", KICK_S)))


def magnet_flip(rig, space, style, balls, w, h):
    """L22: the magnets pull until the leader is halfway down (`flip_at`,
    a race fraction), then push (`push` x the pull). Whoever is near a core
    at the flip is thrown off it."""
    if not style.magnets:
        raise ValueError("magnet-flip needs a stage with magnets")
    install(rig, style, {"band": _flip(rig)})


def reverse_finish(rig, space, style, balls, w, h):
    """L24: a magnet under the finish line pushes up (`finish_push`); a
    marble needs the speed to get through it. The stage's magnets still pull."""
    add_finish_magnet(rig, space, style, w, h)
    install(rig, style, {"finish": _const(-float(rig.knob("finish_push", FINISH_PUSH)))})


def rotating_arm(rig, space, style, balls, w, h):
    """L25: the arm's tip magnets pull `arm_pull` x the kit's pull."""
    if "arm" not in magnet_roles(style).values():
        raise ValueError("rotating-magnet-arm needs a stage with the arm section")
    install(rig, style, {"arm": _const(float(rig.knob("arm_pull", ARM_PULL)))})


def shielded_lane(rig, space, style, balls, w, h):
    """L26: the magnet lane's magnets pull `lane_pull` x the kit's pull."""
    if "lane" not in magnet_roles(style).values():
        raise ValueError("shielded-lane needs a stage with the detour section")
    install(rig, style, {"lane": _const(float(rig.knob("lane_pull", LANE_PULL)))})


def magnet_clump(rig, space, style, balls, w, h):
    """L28: the clump magnet grips (`grip`) until the whole field has been in
    it for `hold` s or `release_by` s have passed, then lets go."""
    if "clump" not in magnet_roles(style).values():
        raise ValueError("magnet-clump needs a stage with the clump section")
    install(rig, style, {"clump": grip_rule(rig, style, float(rig.knob("grip", GRIP)),
                                            float(rig.knob("hold", HOLD_S)),
                                            float(rig.knob("release_by", RELEASE_BY_S)))})
    # A field alone cannot catch anything: a marble falls in and climbs back
    # out with the speed it fell in with. What holds it is the brake that
    # comes with a strong magnet (a moving conductor in a field is slowed):
    # drag inside the inner field while the grip is on, and none after.
    k = next(k for k, role in magnet_roles(style).items() if role == "clump")
    x, y, _core, _soft, reach, _pull = style.magnets[k]
    rig.clock("gripping", lambda f: bool((f.value("polarity") or [0] * (k + 1))[k]))
    ring = [(x + math.cos(a) * reach * CLUMPED, y + math.sin(a) * reach * CLUMPED)
            for a in (i * 2 * math.pi / 24 for i in range(24))]
    rig.zone(poly=ring, kind="sand", damping=float(rig.knob("brake", BRAKE)), when="gripping", show=False)


def all_magnets(rig, space, style, balls, w, h):
    """L30, the world final: the band's magnets pull then flip to push at
    `flip_at`, the arm's pull throughout, and the finish pushes back."""
    roles = set(magnet_roles(style).values())
    if not style.magnets or "arm" not in roles:
        raise ValueError("all-magnets needs a stage with a magnet band and the arm")
    add_finish_magnet(rig, space, style, w, h)
    install(rig, style, {
        "band": _flip(rig),
        "arm": _const(float(rig.knob("arm_pull", ARM_PULL))),
        "finish": _const(-float(rig.knob("finish_push", FINISH_PUSH))),
    })
