"""Stage geometry for moving heads (v9 A1): head pose model, calibration solve, aiming, planes, room boxes.

Pure Python (no numpy), no imports from the rest of the app, so it can be tested on synthetic data alone.

Stage frame (metres): origin front-centre of the stage at floor level; x stage left -> right (audience
view), y downstage -> upstage, z up.

Head model. A head at position P with orientation R (rotation vector, head frame -> stage frame). In the
head frame z is the yoke axis (out of the base). For pan p and tilt t (0-1 of the channel, after the fixture
type's `invert`):

    phi   = (p - 0.5) * pan_range           (radians)
    theta = (t - tilt_zero) * tilt_range
    beam  = R . (sin theta cos phi, sin theta sin phi, cos theta)

Pan zero is absorbed by R's turn about the yoke axis, so it isn't a separate unknown. tilt_zero is the tilt
value at which the beam runs along the yoke axis.

Solve: each head aimed at N measured marks gives N (pan, tilt) pairs; a least-squares fit (Levenberg-Marquardt,
numeric Jacobian) finds the pose, P (3) and R (3), with tilt_zero and the pan / tilt ranges taken from the fixture
type. 3 marks fit it exactly (no error check); 4+ marks leave spare equations, so the error is real.

Refining tilt_zero and the ranges as well (9 unknowns) only works when the marks are spread wide: from a few
metres away a 2 m square spans ~30 degrees, and a range 10 % out looks almost the same as the head being 10 %
further away, so with 0.2 degree aiming noise the "refined" ranges land anywhere and the aim gets worse.
Synthetic tests (28/11/2026): 6 marks over the stage corners plus one 2.5 m up recover the ranges to about
2 % and tilt zero to about 0.003. So refining is automatic only for mark sets like that (`can_refine`).

Aim: the reverse. For a target T the head-frame direction gives (phi, theta); the candidates
(phi + 2 pi k, theta) and (phi + pi + 2 pi k, -theta) all point the same way. The one inside the head's limits
nearest the head's current pan / tilt wins, so a slow path never flips the head round.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

Vec3 = tuple[float, float, float]
Mat3 = tuple[Vec3, Vec3, Vec3]
Limits = tuple[tuple[float, float], tuple[float, float]]  # ((pan lo, hi), (tilt lo, hi)), 0-1

FULL: Limits = ((0.0, 1.0), (0.0, 1.0))
MOUNTS = ("upright", "hung", "side_l", "side_r")
FLAG_FACTOR = 3.0  # a mark is suspect when its error is this many times the median ...
FLAG_MIN_CM = 10.0  # ... and above this


class CalibrationError(ValueError):
    pass


# --- vectors ---------------------------------------------------------------------------------------------

def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec3) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec3) -> Vec3:
    n = norm(a)
    if n < 1e-12:
        raise CalibrationError("zero-length direction")
    return scale(a, 1.0 / n)


def angle(a: Vec3, b: Vec3) -> float:
    """Angle between two directions, radians (stable for small angles)."""
    return math.atan2(norm(cross(a, b)), dot(a, b))


def mat_vec(m: Mat3, v: Vec3) -> Vec3:
    return (dot(m[0], v), dot(m[1], v), dot(m[2], v))


def mat_t_vec(m: Mat3, v: Vec3) -> Vec3:
    """Transpose(m) . v (the inverse rotation)."""
    return (m[0][0] * v[0] + m[1][0] * v[1] + m[2][0] * v[2],
            m[0][1] * v[0] + m[1][1] * v[1] + m[2][1] * v[2],
            m[0][2] * v[0] + m[1][2] * v[1] + m[2][2] * v[2])


def mat_mul(a: Mat3, b: Mat3) -> Mat3:
    cols = [(b[0][j], b[1][j], b[2][j]) for j in range(3)]
    return ((dot(a[0], cols[0]), dot(a[0], cols[1]), dot(a[0], cols[2])),
            (dot(a[1], cols[0]), dot(a[1], cols[1]), dot(a[1], cols[2])),
            (dot(a[2], cols[0]), dot(a[2], cols[1]), dot(a[2], cols[2])))


def rotation(rv: Vec3) -> Mat3:
    """Rotation matrix from a rotation vector (axis * angle, radians) - Rodrigues."""
    th = norm(rv)
    if th < 1e-12:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    x, y, z = scale(rv, 1.0 / th)
    c, s = math.cos(th), math.sin(th)
    C = 1.0 - c
    return ((c + x * x * C, x * y * C - z * s, x * z * C + y * s),
            (y * x * C + z * s, c + y * y * C, y * z * C - x * s),
            (z * x * C - y * s, z * y * C + x * s, c + z * z * C))


def rotvec(m: Mat3) -> Vec3:
    """Rotation vector of a rotation matrix (inverse of rotation())."""
    return quat_to_rotvec(mat_to_quat(m))


def mat_to_quat(m: Mat3) -> tuple[float, float, float, float]:
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        w, x, y, z = (m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        w, x, y, z = (m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        w, x, y, z = (m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s
    return (w, x, y, z)


def quat_to_rotvec(q: tuple[float, float, float, float]) -> Vec3:
    w, x, y, z = q
    if w < 0:
        w, x, y, z = -w, -x, -y, -z
    s = math.sqrt(x * x + y * y + z * z)
    if s < 1e-12:
        return (0.0, 0.0, 0.0)
    th = 2.0 * math.atan2(s, w)
    return (x / s * th, y / s * th, z / s * th)


def quat_to_mat(q: tuple[float, float, float, float]) -> Mat3:
    w, x, y, z = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def rot_z(a: float) -> Mat3:
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


# --- head pose ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class HeadPose:
    pos: Vec3
    rot: Vec3  # rotation vector, head frame -> stage frame
    tilt_zero: float = 0.5
    pan_range: float = 540.0  # degrees
    tilt_range: float = 270.0

    @property
    def matrix(self) -> Mat3:
        return rotation(self.rot)

    @property
    def mount(self) -> str:
        return mount_of(self.rot)

    def to_dict(self) -> dict[str, Any]:
        return {"pos": [round(v, 4) for v in self.pos], "rot": [round(v, 5) for v in self.rot],
                "tilt_zero": round(self.tilt_zero, 5), "pan_range": round(self.pan_range, 2),
                "tilt_range": round(self.tilt_range, 2), "mount": self.mount}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> HeadPose:
        pos, rot = d["pos"], d["rot"]
        return cls(pos=(float(pos[0]), float(pos[1]), float(pos[2])), rot=(float(rot[0]), float(rot[1]), float(rot[2])),
                   tilt_zero=float(d.get("tilt_zero", 0.5)), pan_range=float(d.get("pan_range", 540.0)),
                   tilt_range=float(d.get("tilt_range", 270.0)))


def mount_of(rv: Vec3) -> str:
    """Upright / hung / side_l / side_r from which way the yoke axis (head z) points in the room.
    side_l = mounted on the stage-left side, yoke pointing towards stage right (+x); side_r the reverse."""
    ax = mat_vec(rotation(rv), (0.0, 0.0, 1.0))
    if ax[2] >= 0.7:
        return "upright"
    if ax[2] <= -0.7:
        return "hung"
    return "side_l" if ax[0] >= 0 else "side_r"


def head_dir(pan: float, tilt: float, pose: HeadPose) -> Vec3:
    """Beam direction in the head frame for channel values pan / tilt (0-1)."""
    phi = (pan - 0.5) * math.radians(pose.pan_range)
    th = (tilt - pose.tilt_zero) * math.radians(pose.tilt_range)
    st = math.sin(th)
    return (st * math.cos(phi), st * math.sin(phi), math.cos(th))


def beam(pose: HeadPose, pan: float, tilt: float) -> Vec3:
    """Beam direction in the stage frame (unit vector)."""
    return mat_vec(pose.matrix, head_dir(pan, tilt, pose))


def beam_hit(pose: HeadPose, pan: float, tilt: float, plane: Plane | None = None) -> Vec3 | None:
    """Where the beam meets a plane (default the floor); None if it points away from it."""
    plane = plane or FLOOR
    d = beam(pose, pan, tilt)
    den = dot(plane.normal, d)
    if abs(den) < 1e-9:
        return None
    s = (plane.offset - dot(plane.normal, pose.pos)) / den
    if s <= 0:
        return None
    return add(pose.pos, scale(d, s))


# --- aiming -------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Aim:
    pan: float
    tilt: float
    reachable: bool  # False: the target is outside the limits; pan / tilt is the nearest reachable point
    error: float = 0.0  # angle (radians) between where it points and the target


def _candidates(pose: HeadPose, d: Vec3) -> list[tuple[float, float]]:
    th = math.acos(max(-1.0, min(1.0, d[2])))
    phi = math.atan2(d[1], d[0])
    pr, tr = math.radians(pose.pan_range), math.radians(pose.tilt_range)
    out = []
    if th < 1e-9:  # along the yoke axis: any pan works; keep pan where it would be for phi = 0
        phis = [0.0]
    else:
        phis = [phi]
    for base_phi, base_th in [(p, th) for p in phis] + [(p + math.pi, -th) for p in phis]:
        for k in range(-3, 4):
            ph = base_phi + 2 * math.pi * k
            pan = ph / pr + 0.5
            tilt = base_th / tr + pose.tilt_zero
            out.append((pan, tilt))
    return out


def aim(pose: HeadPose, target: Vec3, current: tuple[float, float] | None = None, limits: Limits = FULL) -> Aim:
    """Pan / tilt (0-1) that point the head at `target`, inside `limits`, nearest `current` (degrees moved).
    If nothing inside the limits points at it, the reachable pan / tilt pointing closest to it, reachable=False."""
    v = sub(target, pose.pos)
    if norm(v) < 1e-9:
        raise CalibrationError("target is at the head")
    d = unit(mat_t_vec(pose.matrix, v))
    (plo, phi_), (tlo, thi) = limits
    cur = current if current is not None else (0.5, pose.tilt_zero)
    pr, tr = pose.pan_range, pose.tilt_range

    def moved(c: tuple[float, float]) -> float:
        return math.hypot((c[0] - cur[0]) * pr, (c[1] - cur[1]) * tr)

    eps = 1e-9
    inside = [c for c in _candidates(pose, d) if plo - eps <= c[0] <= phi_ + eps and tlo - eps <= c[1] <= thi + eps]
    if inside:
        best = min(inside, key=moved)
        return Aim(min(max(best[0], plo), phi_), min(max(best[1], tlo), thi), True, 0.0)
    return _nearest_reachable(pose, d, limits, cur)


def _nearest_reachable(pose: HeadPose, d: Vec3, limits: Limits, cur: tuple[float, float]) -> Aim:
    (plo, phi_), (tlo, thi) = limits

    def err(p: float, t: float) -> float:
        return angle(head_dir(p, t, pose), d)

    # coarse grid over the allowed box, then a local refine
    best = (cur[0], cur[1])
    best_e = math.inf
    n = 48
    for i in range(n + 1):
        p = plo + (phi_ - plo) * i / n
        for j in range(n + 1):
            t = tlo + (thi - tlo) * j / n
            e = err(p, t)
            if e < best_e - 1e-12:
                best, best_e = (p, t), e
    step_p, step_t = (phi_ - plo) / n, (thi - tlo) / n
    for _ in range(40):
        moved = False
        for dp, dt in ((step_p, 0), (-step_p, 0), (0, step_t), (0, -step_t)):
            p = min(max(best[0] + dp, plo), phi_)
            t = min(max(best[1] + dt, tlo), thi)
            e = err(p, t)
            if e < best_e - 1e-12:
                best, best_e, moved = (p, t), e, True
        if not moved:
            step_p, step_t = step_p / 2, step_t / 2
            if max(step_p, step_t) < 1e-7:
                break
    return Aim(best[0], best[1], False, best_e)


# --- planes and shapes --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Plane:
    """A plane `normal . X = offset`, with in-plane axes u, v (metres) for drawing shapes on it."""

    normal: Vec3
    offset: float
    u_axis: Vec3
    v_axis: Vec3

    def point(self, centre: Vec3, u: float, v: float) -> Vec3:
        """Point (u, v) metres from `centre` (projected onto the plane) along the plane's axes."""
        c = sub(centre, scale(self.normal, dot(self.normal, centre) - self.offset))
        return add(c, add(scale(self.u_axis, u), scale(self.v_axis, v)))

    def uv(self, centre: Vec3, p: Vec3) -> tuple[float, float]:
        c = sub(centre, scale(self.normal, dot(self.normal, centre) - self.offset))
        r = sub(p, c)
        return (dot(r, self.u_axis), dot(r, self.v_axis))


FLOOR = Plane((0.0, 0.0, 1.0), 0.0, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))


def height_plane(h: float) -> Plane:
    return Plane((0.0, 0.0, 1.0), h, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))


def wall_plane(depth: float) -> Plane:
    """The back wall at y = depth: u across the stage (x), v up (z)."""
    return Plane((0.0, 1.0, 0.0), depth, (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))


def plane_named(kind: str, *, height: float = 0.0, depth: float = 4.0) -> Plane:
    if kind == "floor":
        return FLOOR
    if kind == "height":
        return height_plane(height)
    if kind == "wall":
        return wall_plane(depth)
    raise CalibrationError(f"plane must be floor, wall or height, not {kind!r}")


def arc_param(shape: Callable[[float], tuple[float, float]], samples: int = 720) -> Callable[[float], float]:
    """For a closed shape s(t), t in 0-1 (u, v metres), a map from 0-1 of the path length to t, so a shape
    driven by it moves at constant speed on its plane (the 'constant floor speed' option)."""
    pts = [shape(i / samples) for i in range(samples + 1)]
    cum = [0.0]
    for i in range(samples):
        cum.append(cum[-1] + math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]))
    total = cum[-1] or 1.0

    def at(f: float) -> float:
        s = (f % 1.0) * total
        lo, hi = 0, samples
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        seg = cum[hi] - cum[lo]
        frac = (s - cum[lo]) / seg if seg > 0 else 0.0
        return (lo + frac) / samples

    return at


# --- room boxes ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Box:
    """An axis-aligned box in the stage frame (metres): a room zone, e.g. the audience at eye height."""

    x: tuple[float, float]
    y: tuple[float, float]
    z: tuple[float, float]
    name: str = ""
    black: bool = False

    def contains(self, p: Vec3) -> bool:
        return (self.x[0] <= p[0] <= self.x[1] and self.y[0] <= p[1] <= self.y[1]
                and self.z[0] <= p[2] <= self.z[1])


def segment_hits_box(a: Vec3, b: Vec3, box: Box) -> bool:
    """True if the segment a -> b passes through (or touches) the box (slab method)."""
    t0, t1 = 0.0, 1.0
    for i, (lo, hi) in enumerate((box.x, box.y, box.z)):
        d = b[i] - a[i]
        if abs(d) < 1e-12:
            if a[i] < lo or a[i] > hi:
                return False
            continue
        ta, tb = (lo - a[i]) / d, (hi - a[i]) / d
        if ta > tb:
            ta, tb = tb, ta
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return False
    return True


def beam_segment(pose: HeadPose, pan: float, tilt: float, max_len: float = 30.0) -> tuple[Vec3, Vec3]:
    """The visible beam: from the head to where it meets the floor, or max_len metres if it never does."""
    d = beam(pose, pan, tilt)
    end = add(pose.pos, scale(d, max_len))
    if d[2] < -1e-9:
        s = -pose.pos[2] / d[2]
        if 0 < s < max_len:
            end = add(pose.pos, scale(d, s))
    return pose.pos, end


def beam_crosses(pose: HeadPose, pan: float, tilt: float, boxes: Sequence[Box], max_len: float = 30.0) -> list[Box]:
    a, b = beam_segment(pose, pan, tilt, max_len)
    return [bx for bx in boxes if segment_hits_box(a, b, bx)]


# --- least squares ------------------------------------------------------------------------------------------

def _solve_linear(a: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-15:
            return None
        m[c], m[piv] = m[piv], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            if f:
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


def levenberg_marquardt(fn: Callable[[list[float]], list[float]], x0: Sequence[float], iters: int = 200,
                        tol: float = 1e-14) -> tuple[list[float], float]:
    """Minimise sum(fn(x)^2). Numeric Jacobian; small problems only (a handful of parameters)."""
    x = list(x0)
    r = fn(x)
    cost = sum(v * v for v in r)
    lam = 1e-3
    n = len(x)
    for _ in range(iters):
        jac: list[list[float]] = []  # columns
        for i in range(n):
            h = 1e-7 * (1.0 + abs(x[i]))
            xp = x[:]
            xp[i] += h
            rp = fn(xp)
            jac.append([(rp[k] - r[k]) / h for k in range(len(r))])
        jtj = [[sum(jac[i][k] * jac[j][k] for k in range(len(r))) for j in range(n)] for i in range(n)]
        jtr = [sum(jac[i][k] * r[k] for k in range(len(r))) for i in range(n)]
        improved = False
        for _ in range(12):
            a = [[jtj[i][j] + (lam * (jtj[i][i] + 1e-12) if i == j else 0.0) for j in range(n)] for i in range(n)]
            step = _solve_linear(a, [-v for v in jtr])
            if step is None:
                lam *= 10
                continue
            xn = [x[i] + step[i] for i in range(n)]
            rn = fn(xn)
            cn = sum(v * v for v in rn)
            if cn < cost:
                done = cost - cn < tol * (1 + cost)
                x, r, cost = xn, rn, cn
                lam = max(lam / 3, 1e-12)
                improved = True
                if done:
                    return x, cost
                break
            lam *= 10
        if not improved:
            break
    return x, cost


# --- calibration solve --------------------------------------------------------------------------------------

@dataclass
class Solution:
    pose: HeadPose
    error_cm: float  # rms over the marks used
    mark_error_cm: dict[str, float]
    flagged: list[str] = field(default_factory=list)  # marks that look mis-aimed or mis-measured
    marks_used: int = 0
    refined_ranges: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def mount(self) -> str:
        return self.pose.mount


REFINE_MIN_MARKS = 6
REFINE_MIN_WIDTH = 4.0  # metres across the floor marks
REFINE_MIN_HEIGHT = 1.0  # at least one mark this far off the floor


def can_refine(marks: Mapping[str, Vec3]) -> bool:
    """Whether marks are spread wide enough to measure tilt zero and the pan / tilt ranges as well as the
    pose: 6+ marks, at least 4 m across, at least one 1 m or more off the floor."""
    pts = list(marks.values())
    if len(pts) < REFINE_MIN_MARKS:
        return False
    width = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a in pts for b in pts)
    return width >= REFINE_MIN_WIDTH and max(abs(p[2]) for p in pts) >= REFINE_MIN_HEIGHT


def check_marks(marks: Mapping[str, Vec3]) -> None:
    """Refuse mark sets that can't calibrate anything: fewer than 3, or all on one line."""
    pts = list(marks.values())
    if len(pts) < 3:
        raise CalibrationError("needs at least 3 marks")
    a = pts[0]
    best = 0.0
    far = max(pts, key=lambda p: norm(sub(p, a)))
    if norm(sub(far, a)) < 0.2:
        raise CalibrationError("the marks are all in one spot: spread them at least a metre apart")
    for p in pts:
        best = max(best, norm(cross(unit(sub(far, a)), sub(p, a))))
    if best < 0.2:
        raise CalibrationError("the marks are in a line: put at least one mark off that line (20 cm or more)")


def _residuals(params: Sequence[float], marks: list[Vec3], aims: list[tuple[float, float]], fixed: HeadPose,
               free_t0: bool, free_ranges: bool) -> list[float]:
    pose = _pose_from(params, fixed, free_t0, free_ranges)
    m = pose.matrix
    out: list[float] = []
    for mk, (p, t) in zip(marks, aims, strict=True):
        d = mat_vec(m, head_dir(p, t, pose))
        v = sub(mk, pose.pos)
        n = norm(v)
        u = scale(v, 1.0 / n) if n > 1e-9 else (0.0, 0.0, 0.0)
        out.extend(sub(d, u))
    out.append(10.0 * min(pose.pos[2], 0.0))  # below the floor isn't a real place for a head
    return out


def _pose_from(params: Sequence[float], fixed: HeadPose, free_t0: bool, free_ranges: bool) -> HeadPose:
    pos = (params[0], params[1], params[2])
    rv = (params[3], params[4], params[5])
    i = 6
    t0 = fixed.tilt_zero
    if free_t0:
        t0 = params[i]
        i += 1
    pr, tr = fixed.pan_range, fixed.tilt_range
    if free_ranges:
        pr, tr = fixed.pan_range * params[i], fixed.tilt_range * params[i + 1]
    return HeadPose(pos, rv, t0, pr, tr)


def _horn(src: list[Vec3], dst: list[Vec3]) -> Mat3:
    """Rotation R that best maps directions src onto dst (max sum dst . R src), Horn's quaternion method."""
    s = [[sum(a[i] * b[j] for a, b in zip(src, dst, strict=True)) for j in range(3)] for i in range(3)]
    sxx, sxy, sxz = s[0]
    syx, syy, syz = s[1]
    szx, szy, szz = s[2]
    n = [[sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
         [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
         [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
         [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz]]
    shift = sum(abs(v) for row in n for v in row) + 1.0
    for i in range(4):
        n[i][i] += shift
    q = [1.0, 0.3, 0.2, 0.1]
    for _ in range(200):
        nq = [sum(n[i][j] * q[j] for j in range(4)) for i in range(4)]
        ln = math.sqrt(sum(v * v for v in nq))
        q = [v / ln for v in nq]
    return quat_to_mat((q[0], q[1], q[2], q[3]))


def _starts(marks: list[Vec3]) -> list[Vec3]:
    cx = sum(m[0] for m in marks) / len(marks)
    cy = sum(m[1] for m in marks) / len(marks)
    out = []
    for dx in (-4.0, -2.0, 0.0, 2.0, 4.0):
        for dy in (-3.0, -1.0, 1.0, 3.0, 5.0):
            for z in (0.5, 1.5, 3.0, 5.0):
                out.append((cx + dx, cy + dy, z))
    return out


def solve(marks: Mapping[str, Vec3], aims: Mapping[str, tuple[float, float]], *, pan_range: float = 540.0,
          tilt_range: float = 270.0, tilt_zero: float = 0.5, refine: bool | None = None,
          loo: bool = True) -> Solution:
    """Fit one head's pose from its aims (pan, tilt 0-1) at measured marks (metres). Marks it skipped are
    simply missing from `aims`. refine: also solve tilt zero and the pan / tilt ranges; None = when the aimed
    marks allow it (`can_refine`), True = when there are 6+ marks whatever their spread."""
    names = [k for k in aims if k in marks]
    if len(names) < 3:
        raise CalibrationError(f"needs at least 3 aimed marks, has {len(names)}")
    check_marks({k: marks[k] for k in names})
    mk = [marks[k] for k in names]
    am = [aims[k] for k in names]
    n = len(names)
    free = can_refine(dict(zip(names, mk, strict=True))) if refine is None else (refine and n >= REFINE_MIN_MARKS)
    free_t0 = free_ranges = free
    fixed = HeadPose((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), tilt_zero, pan_range, tilt_range)

    def fn(x: list[float]) -> list[float]:
        return _residuals(x, mk, am, fixed, free_t0, free_ranges)

    # starting guesses: a grid of positions, each with the best rotation for it (Horn), tilt zero as given
    t0s = (tilt_zero,) if not free_t0 else (tilt_zero, tilt_zero - 0.15, tilt_zero + 0.15)
    seeds: list[tuple[float, list[float]]] = []
    for t0 in t0s:
        hd = [head_dir(p, t, HeadPose(fixed.pos, fixed.rot, t0, pan_range, tilt_range)) for p, t in am]
        for pos in _starts(mk):
            try:
                dst = [unit(sub(m, pos)) for m in mk]
            except CalibrationError:
                continue
            rv = rotvec(_horn(hd, dst))
            x = [pos[0], pos[1], pos[2], rv[0], rv[1], rv[2]]
            if free_t0:
                x.append(t0)
            if free_ranges:
                x += [1.0, 1.0]
            r = fn(x)
            seeds.append((sum(v * v for v in r), x))
    seeds.sort(key=lambda s: s[0])
    best_x: list[float] | None = None
    best_c = math.inf
    for _, x in seeds[:6]:
        # pose first (ranges fixed), then everything
        if free_ranges:
            x6 = x[:-2]
            xs, _c = levenberg_marquardt(lambda y: _residuals(y, mk, am, fixed, free_t0, False), x6, iters=80)
            x = xs + [1.0, 1.0]
        xs, c = levenberg_marquardt(fn, x)
        if c < best_c:
            best_x, best_c = xs, c
        if best_c < 1e-12:
            break
    assert best_x is not None
    pose = _pose_from(best_x, fixed, free_t0, free_ranges)
    errs = {k: _mark_error_cm(pose, marks[k], aims[k]) for k in names}
    rms = math.sqrt(sum(e * e for e in errs.values()) / n)
    sol = Solution(pose=pose, error_cm=rms, mark_error_cm=errs, marks_used=n, refined_ranges=free_ranges)
    if n == 3:
        sol.warnings.append("3 marks: no error check (aim at a 4th mark to check the result)")
    if loo:
        sol.flagged = _flag(marks, aims, names, pose, errs)
    if pose.pos[2] < 0:
        sol.warnings.append("solved position is below the floor: check the marks")
    return sol


def _mark_error_cm(pose: HeadPose, mark: Vec3, a: tuple[float, float]) -> float:
    v = sub(mark, pose.pos)
    return angle(beam(pose, a[0], a[1]), v) * norm(v) * 100.0


def _flag(marks: Mapping[str, Vec3], aims: Mapping[str, tuple[float, float]], names: list[str], pose: HeadPose,
          errs: Mapping[str, float]) -> list[str]:
    """The mark that doesn't fit, if one stands out. With 5+ marks: solve again without each mark in turn; the
    bad one is the mark whose removal makes the rest fit far better, and which the rest then miss by a lot.
    (A plain "biggest error" test doesn't work: the fit spreads one bad aim over all the marks.) With 4 marks
    there's too little spare to tell, so only an error far above the others is flagged."""
    n = len(names)
    rms_all = math.sqrt(sum(e * e for e in errs.values()) / n)
    if n >= 5:
        best: tuple[float, str, float] | None = None
        for k in names:
            rest = {j: aims[j] for j in names if j != k}
            s = solve(marks, rest, pan_range=pose.pan_range, tilt_range=pose.tilt_range, tilt_zero=pose.tilt_zero,
                      refine=False, loo=False)
            if best is None or s.error_cm < best[0]:
                best = (s.error_cm, k, _mark_error_cm(s.pose, marks[k], aims[k]))
        assert best is not None
        rms_rest, k, miss = best
        if miss > FLAG_MIN_CM and rms_all > FLAG_FACTOR * max(rms_rest, 0.5):
            return [k]
        return []
    vals = sorted(errs.values())
    med = vals[len(vals) // 2]
    return [k for k in names if errs[k] > FLAG_MIN_CM and errs[k] > FLAG_FACTOR * max(med, 1.0)]


# --- quick re-cal -------------------------------------------------------------------------------------------

def move_rig(poses: Mapping[str, HeadPose], dx: float, dy: float, yaw: float) -> dict[str, HeadPose]:
    """Every head moved together: turned `yaw` radians about the stage z axis, then shifted (dx, dy)."""
    rz = rot_z(yaw)
    out = {}
    for fid, p in poses.items():
        pos = add(mat_vec(rz, p.pos), (dx, dy, 0.0))
        out[fid] = HeadPose(pos, rotvec(mat_mul(rz, p.matrix)), p.tilt_zero, p.pan_range, p.tilt_range)
    return out


RigMove = tuple[float, float, float]  # dx, dy (metres), yaw (radians)


def quick_recal(poses: Mapping[str, HeadPose], marks: Mapping[str, Vec3],
                aims: Mapping[str, Mapping[str, tuple[float, float]]]) -> tuple[dict[str, HeadPose], RigMove, float]:
    """Same rig, new room: the heads keep their poses relative to each other; aims at 2+ marks re-fit only where
    the rig stands (x, y shift and turn about z). Returns (new poses, (dx, dy, yaw), rms error cm)."""
    obs = [(fid, marks[m], a) for fid, per in aims.items() if fid in poses for m, a in per.items() if m in marks]
    if len({m for per in aims.values() for m in per if m in marks}) < 2 or len(obs) < 2:
        raise CalibrationError("quick re-cal needs aims at 2 marks")

    def fn(x: list[float]) -> list[float]:
        moved = move_rig(poses, x[0], x[1], x[2])
        out: list[float] = []
        for fid, mk, (p, t) in obs:
            pose = moved[fid]
            out.extend(sub(beam(pose, p, t), unit(sub(mk, pose.pos))))
        return out

    best: tuple[list[float], float] | None = None
    for yaw0 in (0.0, math.pi / 2, math.pi, -math.pi / 2):
        x, c = levenberg_marquardt(fn, [0.0, 0.0, yaw0])
        if best is None or c < best[1]:
            best = (x, c)
    assert best is not None
    x = best[0]
    yaw = math.atan2(math.sin(x[2]), math.cos(x[2]))
    moved = move_rig(poses, x[0], x[1], yaw)
    errs = [_mark_error_cm(moved[fid], mk, a) for fid, mk, a in obs]
    rms = math.sqrt(sum(e * e for e in errs) / len(errs))
    return moved, (x[0], x[1], yaw), rms


# --- beams to points ----------------------------------------------------------------------------------------

def nearest_point(rays: Sequence[tuple[Vec3, Vec3]]) -> tuple[Vec3, float]:
    """The point closest to several rays (origin, unit direction) - where calibrated heads' beams meet - and the
    rms distance (metres) of the rays from it (the spread). Needs 2+ rays that aren't parallel."""
    if len(rays) < 2:
        raise CalibrationError("needs 2 or more beams")
    a = [[0.0] * 3 for _ in range(3)]
    b = [0.0, 0.0, 0.0]
    for o, d in rays:
        for i in range(3):
            for j in range(3):
                m = (1.0 if i == j else 0.0) - d[i] * d[j]
                a[i][j] += m
                b[i] += m * o[j]
    x = _solve_linear(a, b)
    if x is None:
        raise CalibrationError("the beams are parallel")
    p = (x[0], x[1], x[2])
    dists = []
    for o, d in rays:
        v = sub(p, o)
        dists.append(norm(sub(v, scale(d, dot(v, d)))))
    return p, math.sqrt(sum(e * e for e in dists) / len(dists))
