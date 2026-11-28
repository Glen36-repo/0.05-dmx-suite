"""v9 A1: stage geometry - head model, calibration solve, aiming, planes, room boxes (synthetic data only)."""

from __future__ import annotations

import math
import random
import time

import pytest

from dmx_suite import stagegeo as g

SQUARE = {"M1": (-1.0, 1.0, 0.0), "M2": (1.0, 1.0, 0.0), "M3": (1.0, 3.0, 0.0), "M4": (-1.0, 3.0, 0.0)}
SQUARE5 = {**SQUARE, "M5": (0.0, 4.0, 0.0)}
WIDE = {"M1": (-3.0, 0.5, 0.0), "M2": (3.0, 0.5, 0.0), "M3": (3.0, 4.0, 0.0), "M4": (-3.0, 4.0, 0.0),
        "M5": (0.0, 4.5, 2.5), "M6": (0.0, 0.5, 0.0)}
KIT = (0.0, 2.6, 0.8)

BASES = {"upright": (0.0, 0.0, 0.0), "hung": (math.pi, 0.0, 0.0), "side_a": (0.0, math.pi / 2, 0.0),
         "side_b": (0.0, -math.pi / 2, 0.0)}


def q16(v: float) -> float:
    return round(v * 65535) / 65535


def pose_for(base: str, rng: random.Random, **kw: float) -> g.HeadPose:
    rv = g.rotvec(g.mat_mul(g.rot_z(rng.uniform(-3.0, 3.0)), g.rotation(BASES[base])))
    pos = (rng.uniform(-3.0, 3.0), rng.uniform(-1.0, 4.0), rng.uniform(1.5, 4.0))  # on a stand or truss
    return g.HeadPose(pos, rv, kw.get("tilt_zero", 0.5), kw.get("pan_range", 540.0), kw.get("tilt_range", 270.0))


def aims_at(pose: g.HeadPose, marks: dict[str, g.Vec3], rng: random.Random, noise_deg: float = 0.0
            ) -> dict[str, tuple[float, float]] | None:
    out = {}
    for k, m in marks.items():
        a = g.aim(pose, m)
        if not a.reachable:
            return None
        out[k] = (q16(a.pan + rng.gauss(0, noise_deg) / pose.pan_range),
                  q16(a.tilt + rng.gauss(0, noise_deg) / pose.tilt_range))
    return out


def cases(marks: dict[str, g.Vec3], n: int, seed: int, noise_deg: float = 0.0, **kw: float):
    """n reachable random heads, cycling through the four mounts: (true pose, aims)."""
    rng = random.Random(seed)
    names = list(BASES)
    out = []
    i = 0
    while len(out) < n:
        pose = pose_for(names[i % 4], rng, **kw)
        i += 1
        a = aims_at(pose, marks, rng, noise_deg)
        if a is not None:
            out.append((pose, a))
    return out


def hit_error(true: g.HeadPose, est: g.HeadPose, target: g.Vec3) -> float:
    """Where the real head's beam lands (metres from the target) when aimed with the solved pose. 0 for a target
    outside the head's range (nothing to compare)."""
    a = g.aim(est, target)
    if not a.reachable:
        return 0.0
    hit = g.beam_hit(true, a.pan, a.tilt, g.height_plane(target[2]))
    assert hit is not None
    return g.norm(g.sub(hit, target))


# --- maths basics ---------------------------------------------------------------------------------------------

def test_rotation_round_trip():
    rng = random.Random(1)
    for _ in range(50):
        rv = (rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(-2, 2))
        if g.norm(rv) > math.pi - 0.01:
            continue
        back = g.rotvec(g.rotation(rv))
        assert g.norm(g.sub(back, rv)) < 1e-9


def test_aim_points_the_beam_at_the_target_for_every_mount():
    rng = random.Random(2)
    for base in BASES:
        for _ in range(10):
            pose = pose_for(base, rng)
            target = (rng.uniform(-3, 3), rng.uniform(0, 4), rng.uniform(0, 2))
            a = g.aim(pose, target)
            if a.reachable:
                assert g.angle(g.beam(pose, a.pan, a.tilt), g.sub(target, pose.pos)) < 1e-9


def test_mount_from_the_yoke_axis():
    assert g.mount_of(BASES["upright"]) == "upright"
    assert g.mount_of(BASES["hung"]) == "hung"
    assert g.mount_of((0.0, math.pi / 2, 0.0)) == "side_l"  # yoke points stage right (+x)
    assert g.mount_of((0.0, -math.pi / 2, 0.0)) == "side_r"


def test_pose_dict_round_trip():
    p = g.HeadPose((-2.1, 0.4, 1.8), (0.02, -3.11, 0.05), 0.49, 545.0, 268.0)
    d = p.to_dict()
    assert d["mount"] == "hung"
    back = g.HeadPose.from_dict(d)
    assert g.norm(g.sub(back.pos, p.pos)) < 1e-3 and back.pan_range == 545.0


# --- solve ----------------------------------------------------------------------------------------------------

def test_solve_without_noise_recovers_the_pose():
    for true, aims in cases(SQUARE, 12, seed=3):
        s = g.solve(SQUARE, aims)
        assert g.norm(g.sub(s.pose.pos, true.pos)) < 0.03, true
        assert g.angle(g.mat_vec(s.pose.matrix, (0, 0, 1)), g.mat_vec(true.matrix, (0, 0, 1))) < math.radians(0.5)
        assert s.pose.mount == true.mount
        assert s.error_cm < 1.0
        assert not s.refined_ranges and s.marks_used == 4


def test_solve_with_aiming_noise_lands_the_beams_on_the_marks():
    """0.2 degree aiming noise and 16-bit pan / tilt, the standard 2 m square: the solved heads hit the marks and
    the kit within 10 cm (brief acceptance), and the reported error is in the same range as the real one."""
    for true, aims in cases(SQUARE, 16, seed=4, noise_deg=0.2):
        s = g.solve(SQUARE, aims)
        worst = max(hit_error(true, s.pose, m) for m in [*SQUARE.values(), KIT])
        assert worst < 0.10, (true, worst)
        assert s.error_cm < 10.0


def test_three_marks_fit_with_a_warning():
    marks = {k: SQUARE[k] for k in ("M1", "M2", "M3")}
    true, aims = cases(marks, 1, seed=5)[0]
    s = g.solve(marks, aims)
    assert s.marks_used == 3 and s.warnings
    assert all(hit_error(true, s.pose, m) < 0.05 for m in marks.values())


def test_skipped_marks_are_left_out():
    true, aims = cases(SQUARE5, 1, seed=6)[0]
    del aims["M3"]
    s = g.solve(SQUARE5, aims)
    assert s.marks_used == 4 and "M3" not in s.mark_error_cm


def test_a_mis_aimed_mark_is_flagged():
    rng = random.Random(7)
    flagged = 0
    for true, aims in cases(SQUARE5, 8, seed=8, noise_deg=0.2):
        bad = rng.choice(list(aims))
        p, t = aims[bad]
        aims[bad] = (p + 3.0 / true.pan_range, t + 2.0 / true.tilt_range)  # ~3.6 degrees off
        s = g.solve(SQUARE5, aims)
        assert set(s.flagged) <= {bad}
        flagged += s.flagged == [bad]
    assert flagged >= 6  # a few bad aims happen to land near their mark anyway


def test_good_aims_flag_nothing():
    for _true, aims in cases(SQUARE5, 8, seed=9, noise_deg=0.2):
        assert g.solve(SQUARE5, aims).flagged == []


def test_wide_marks_measure_the_real_ranges_and_tilt_zero():
    """The fixture type says 540 / 270 and tilt zero 0.5; the heads are really 594 / 256.5 and 0.53."""
    assert g.can_refine(WIDE) and not g.can_refine(SQUARE5)
    for true, aims in cases(WIDE, 8, seed=10, noise_deg=0.1, pan_range=594.0, tilt_range=256.5, tilt_zero=0.53):
        s = g.solve(WIDE, aims)
        assert s.refined_ranges
        assert abs(s.pose.pan_range / 594.0 - 1) < 0.03
        assert abs(s.pose.tilt_range / 256.5 - 1) < 0.03
        assert abs(s.pose.tilt_zero - 0.53) < 0.01
        assert max(hit_error(true, s.pose, m) for m in [*WIDE.values(), KIT]) < 0.10


def test_small_square_keeps_the_fixture_type_ranges():
    _true, aims = cases(SQUARE5, 1, seed=11)[0]
    s = g.solve(SQUARE5, aims)
    assert not s.refined_ranges and s.pose.pan_range == 540.0 and s.pose.tilt_zero == 0.5


@pytest.mark.parametrize("marks, msg", [
    ({"M1": (0.0, 0.0, 0.0), "M2": (1.0, 0.0, 0.0)}, "at least 3"),
    ({"M1": (0.0, 0.0, 0.0), "M2": (1.0, 0.0, 0.0), "M3": (2.0, 0.0, 0.0), "M4": (3.0, 0.05, 0.0)}, "in a line"),
    ({"M1": (0.0, 0.0, 0.0), "M2": (0.05, 0.0, 0.0), "M3": (0.0, 0.05, 0.0)}, "one spot"),
])
def test_bad_mark_sets_are_refused(marks, msg):
    with pytest.raises(g.CalibrationError, match=msg):
        g.check_marks(marks)


def test_solve_is_quick():
    _true, aims = cases(SQUARE5, 1, seed=12, noise_deg=0.2)[0]
    t = time.perf_counter()
    g.solve(SQUARE5, aims)
    assert time.perf_counter() - t < 2.0


# --- aiming ---------------------------------------------------------------------------------------------------

def test_slow_path_never_flips_the_head():
    """A target walked slowly round the stage: each frame's pan / tilt stays next to the last (no 180 / 360
    degree swings to an equivalent solution)."""
    rng = random.Random(13)
    for base in BASES:
        pose = pose_for(base, rng)
        cur = None
        for i in range(400):
            a_ = 2 * math.pi * i / 400
            target = (2.0 * math.cos(a_), 2.0 + 1.5 * math.sin(a_), 0.0)
            a = g.aim(pose, target, cur)
            if cur is not None and a.reachable:
                assert abs(a.pan - cur[0]) * pose.pan_range < 20
                assert abs(a.tilt - cur[1]) * pose.tilt_range < 20
            cur = (a.pan, a.tilt)


def test_aim_stays_inside_the_limits():
    pose = g.HeadPose((0.0, 0.0, 3.0), BASES["hung"])
    limits = ((0.4, 0.6), (0.45, 0.7))
    a = g.aim(pose, (0.0, 2.0, 0.0), limits=limits)
    assert 0.4 <= a.pan <= 0.6 and 0.45 <= a.tilt <= 0.7


def test_unreachable_target_holds_at_the_nearest_reachable_point():
    pose = g.HeadPose((0.0, 0.0, 3.0), BASES["hung"])
    limits = ((0.45, 0.55), (0.5, 0.55))
    a = g.aim(pose, (4.0, 4.0, 0.0), limits=limits)
    assert not a.reachable
    assert 0.45 <= a.pan <= 0.55 and 0.5 <= a.tilt <= 0.55
    assert a.error > 0
    # nothing inside the limits points closer
    for i in range(11):
        for j in range(11):
            p, t = 0.45 + 0.01 * i, 0.5 + 0.005 * j
            assert g.angle(g.beam(pose, p, t), g.sub((4.0, 4.0, 0.0), pose.pos)) >= a.error - 1e-6


# --- quick re-cal ---------------------------------------------------------------------------------------------

def test_quick_recal_finds_where_the_rig_moved():
    rng = random.Random(14)
    poses = {"mh_a": g.HeadPose((-2.0, 4.0, 3.5), BASES["hung"]), "mh_b": g.HeadPose((2.0, 0.0, 3.0), BASES["hung"])}
    real = g.move_rig(poses, 0.7, -0.4, math.radians(12))
    marks = {"M1": SQUARE["M1"], "M3": SQUARE["M3"]}
    assert all(g.aim(p, m).reachable for p in real.values() for m in marks.values())
    aims = {fid: {k: (q16(g.aim(p, m).pan + rng.gauss(0, 0.1) / 540), q16(g.aim(p, m).tilt + rng.gauss(0, 0.1) / 270))
                  for k, m in marks.items()} for fid, p in real.items()}
    moved, (dx, dy, yaw), rms = g.quick_recal(poses, marks, aims)
    assert abs(dx - 0.7) < 0.05 and abs(dy + 0.4) < 0.05 and abs(math.degrees(yaw) - 12) < 1
    for fid in poses:
        assert max(hit_error(real[fid], moved[fid], m) for m in [*SQUARE.values(), KIT]) < 0.15
    assert rms < 10


def test_quick_recal_needs_two_marks():
    poses = {"mh_a": g.HeadPose((0.0, 0.0, 3.0), BASES["hung"])}
    with pytest.raises(g.CalibrationError, match="2 marks"):
        g.quick_recal(poses, SQUARE, {"mh_a": {"M1": (0.5, 0.6)}})


# --- planes, boxes, beams -------------------------------------------------------------------------------------

def test_plane_points_and_uv_round_trip():
    for plane in (g.FLOOR, g.height_plane(1.2), g.wall_plane(5.0)):
        c = (0.5, 2.0, 0.8)
        p = plane.point(c, 0.3, -0.2)
        assert abs(g.dot(plane.normal, p) - plane.offset) < 1e-12
        u, v = plane.uv(c, p)
        assert abs(u - 0.3) < 1e-12 and abs(v + 0.2) < 1e-12
    assert g.plane_named("wall", depth=6.0).offset == 6.0
    with pytest.raises(g.CalibrationError):
        g.plane_named("sky")


def test_arc_param_gives_constant_speed():
    def ellipse(t: float) -> tuple[float, float]:
        return (2.0 * math.cos(2 * math.pi * t), 0.5 * math.sin(2 * math.pi * t))

    at = g.arc_param(ellipse)
    steps = []
    prev = ellipse(at(0.0))
    for i in range(1, 201):
        cur = ellipse(at(i / 200))
        steps.append(math.hypot(cur[0] - prev[0], cur[1] - prev[1]))
        prev = cur
    mean = sum(steps) / len(steps)
    assert max(abs(s / mean - 1) for s in steps) < 0.05


def test_segment_box():
    box = g.Box((-1.0, 1.0), (-1.0, 0.0), (1.0, 2.0))
    assert g.segment_hits_box((0.0, 2.0, 1.5), (0.0, -2.0, 1.5), box)
    assert not g.segment_hits_box((0.0, 2.0, 2.5), (0.0, -2.0, 2.5), box)  # over the audience's heads
    assert not g.segment_hits_box((0.0, 2.0, 1.5), (0.0, 0.5, 1.5), box)  # stops short
    assert g.segment_hits_box((0.0, -0.5, 1.5), (0.0, -0.5, 1.6), box)  # inside


def test_beam_into_the_audience_is_caught_and_onto_the_stage_is_not():
    audience = g.Box((-4.0, 4.0), (-6.0, 0.0), (1.0, 2.0), name="Audience eyes")
    pose = g.HeadPose((0.0, 3.0, 3.0), BASES["hung"])
    a = g.aim(pose, (0.0, -3.0, 1.5))
    assert g.beam_crosses(pose, a.pan, a.tilt, [audience]) == [audience]
    a = g.aim(pose, (0.0, 2.0, 0.0))
    assert g.beam_crosses(pose, a.pan, a.tilt, [audience]) == []


def test_beam_hit_and_nearest_point_of_beams():
    a = g.HeadPose((-2.0, 0.5, 3.0), BASES["hung"])
    b = g.HeadPose((2.0, 0.5, 2.0), BASES["upright"])
    target = (0.3, 2.5, 0.0)
    rays = []
    for p in (a, b):
        aa = g.aim(p, target)
        hit = g.beam_hit(p, aa.pan, aa.tilt)
        assert hit is not None and g.norm(g.sub(hit, target)) < 1e-9
        rays.append((p.pos, g.beam(p, aa.pan, aa.tilt)))
    pt, spread = g.nearest_point(rays)
    assert g.norm(g.sub(pt, target)) < 1e-6 and spread < 1e-6
    up = g.aim(b, (2.0, 0.5, 10.0))  # straight up: never meets the floor
    assert g.beam_hit(b, up.pan, up.tilt) is None
