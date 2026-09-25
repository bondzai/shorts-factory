"""Per-round transforms of a built stage: a mirror image, left to right.

A round's params may say `mirror: true` (`round_params` in the level). The
stage is built as usual and then reflected about x = w/2 before a marble is
placed: every static shape, every moving body, and every field of the style
the renderers draw from, so the picture and the physics stay one thing.

What a mirror cannot reflect it refuses, rather than drawing one door and
simulating another: a trapdoor hinges at its left end and its clock turns
one way (`stagekit.trap_angle`), so a stage with a trap is not mirrored.
"""

from __future__ import annotations

import math

import pymunk

from .model import Style


def mirror(space: pymunk.Space, style: Style, segments: list, w: float) -> list:
    """Reflect the built stage in place; returns the reflected `segments`."""
    if style.traps:
        raise ValueError(f"stage {style.stage!r} has a trapdoor, which cannot be mirrored")
    fx = lambda x: w - x  # noqa: E731
    pt = lambda p: (fx(p[0]), p[1])  # noqa: E731
    for shape in list(space.static_body.shapes):
        if isinstance(shape, pymunk.Segment):
            shape.unsafe_set_endpoints(pt(shape.a), pt(shape.b))
            sv = shape.surface_velocity
            if sv.x or sv.y:
                shape.surface_velocity = (-sv.x, sv.y)
        elif isinstance(shape, pymunk.Circle):
            shape.unsafe_set_offset(pt(shape.offset))
        elif isinstance(shape, pymunk.Poly):
            raise ValueError("a polygon in the stage cannot be mirrored yet")
    rockers = {id(body) for kind, body, _ in style.kinematics if kind == "rocker"}
    for body in space.bodies:
        if body.body_type != pymunk.Body.KINEMATIC:
            continue
        body.position = pt(body.position)
        if id(body) not in rockers:
            # A bar or a drum: symmetric about its centre, so turning the other
            # way from the reflected angle is its mirror image.
            body.angle = -body.angle
            body.angular_velocity = -body.angular_velocity
    # Rockers are driven by angle = bias + A sin(wt + phase); the reflection is
    # -bias + A sin(wt + phase + pi).
    style.kinematics = [(kind, body, (p[0], p[1] + math.pi, -p[2]) if kind == "rocker" else p)
                        for kind, body, p in style.kinematics]
    style.rockers = [(fx(x), y, half, omega, phase + math.pi, *[-b for b in bias])
                     for x, y, half, omega, phase, *bias in style.rockers]
    style.spinners = [(fx(x), y, half, -omega, -phase) for x, y, half, omega, phase in style.spinners]
    style.drums = [(fx(x), y, r, -omega) for x, y, r, omega in style.drums]
    style.circles = [(fx(x), y, r) for x, y, r in style.circles]
    style.magnets = [(fx(x), y, *rest) for x, y, *rest in style.magnets]
    style.belts = [(pt(a), pt(b), speed) for a, b, speed in style.belts]
    style.gates = [(pt(a), pt(b)) for a, b in style.gates]
    style.lane = [(pt(a), pt(b)) for a, b in style.lane]
    style.lane_wedges = [(pt(a), pt(b)) for a, b in style.lane_wedges]
    return [(pt(a), pt(b)) for a, b in segments]
