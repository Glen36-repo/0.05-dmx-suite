"""v6 Part B: the beat tracker against synthetic grooves (tests/groove.py). The brief's acceptance tests:
steady 120 settles within 4 bars with no wobble; a 2-bar fill doesn't move it and shows freewheel; 1 %
drift doesn't move it, a sustained 5 % push does after 4 beats with a glide; half-time feel doesn't halve
it; tap / count-in override at once. Plus phase, bar, jump guard and parameters."""

import pytest
from groove import fill, groove, run

from dmx_suite.beat import BeatParams, BeatTracker


def tracked(seed_bpm, hits, until=None, params=None, seed_at=0.0):
    tr = BeatTracker(seed_at, params)
    tr.seed(seed_bpm, seed_at, "tap", beat_at=seed_at)
    log = []
    run(tr, hits, until=until or hits[-1][0], t0=seed_at, probe=lambda t: log.append((t, tr.status(t))))
    return tr, log


def after(log, t):
    return [s for tt, s in log if tt >= t]


def test_steady_120_settles_within_4_bars_no_wobble():
    tr, log = tracked(114, groove(120, 16))  # tapped a little slow
    settled = after(log, 8.0)  # 4 bars at 120
    assert all(abs(s["bpm"] - 120) <= 1 for s in settled), {s["bpm"] for s in settled}
    assert len({s["bpm"] for s in after(log, 10.0)}) <= 2  # no visible wobble
    assert not settled[-1]["freewheel"] and settled[-1]["confidence"] >= 0.4


def test_phase_lines_up_with_the_groove():
    tr, log = tracked(120, groove(120, 12), seed_at=0.1)  # tapped 100 ms late
    # at each true beat, our clock is near a whole beat
    errs = []
    for k in range(32, 46):
        t = k * 0.5
        st = next(s for tt, s in log if tt >= t)
        errs.append(min(st["phase"], 1 - st["phase"]))
    assert max(errs) < 0.1  # within 50 ms at 120


def test_bar_follows_kick_and_snare():
    tr, log = tracked(120, groove(120, 12), seed_at=0.0)
    for k in range(16, 44, 4):  # downbeats of the groove (kick on 1)
        st = next(s for tt, s in log if tt >= k * 0.5 + 0.05)
        assert st["beat"] == 1


def test_two_bar_fill_does_not_move_it_and_freewheels():
    hits = groove(120, 8) + fill(120, 2, 16.0) + groove(120, 6, start=20.0)
    tr, log = tracked(120, hits)
    during = [s for t, s in log if 17.0 <= t <= 20.0]
    assert any(s["freewheel"] for s in during)
    assert all(abs(s["bpm"] - 120) <= 1 for t, s in log if t >= 4)  # never moved


def test_drums_stopped_freewheels_at_last_tempo():
    tr, log = tracked(120, groove(120, 8), until=40.0)
    late = after(log, 25.0)
    assert all(s["freewheel"] and s["bpm"] == 120.0 for s in late)
    assert tr.beats(40.0) > tr.beats(30.0) + 19  # still counting beats at 120


def test_one_percent_drift_does_not_move_it():
    hits = groove(120, 16)
    hits = [(t * 0.99, r, v) for t, r, v in hits]  # the band 1 % faster
    tr, log = tracked(120, hits)
    assert all(s["bpm"] == 120.0 for s in after(log, 2.0))


def test_sustained_5_percent_push_moves_after_4_beats_with_a_glide():
    hits = groove(120, 8) + groove(126, 12, start=16.0)
    tr, log = tracked(120, hits)
    before = [s["bpm"] for t, s in log if 16.0 <= t < 17.8]  # under 4 beats into the push
    assert all(b == 120.0 for b in before)
    later = after(log, 16.0 + 8 * 60 / 126)
    assert abs(later[-1]["bpm"] - 126) <= 1.5
    moving = sorted({s["bpm"] for t, s in log if 16.0 <= t <= 26.0})
    assert len([b for b in moving if 120.5 < b < 125]) >= 2  # glided, not stepped


def test_half_time_feel_does_not_halve_it():
    hits = groove(120, 6) + groove(120, 8, start=12.0, feel="half")
    tr, log = tracked(120, hits)
    assert all(abs(s["bpm"] - 120) <= 1 for s in after(log, 2.0))


def test_sixteenth_hats_still_track():
    tr, log = tracked(116, groove(120, 12, hats="16ths"))
    assert abs(after(log, 10.0)[-1]["bpm"] - 120) <= 1


def test_tap_overrides_immediately():
    tr, log = tracked(120, groove(120, 8))
    tr.seed(100, 16.5, "tap", beat_at=16.5)
    st = tr.status(16.5)
    assert st["bpm"] == 100.0 and st["seed_source"] == "tap" and len(tr.onsets) == 0


def test_count_in_after_silence_seeds():
    tr = BeatTracker(0.0)
    tr.seed(120, 0.0)
    for k in range(3):
        assert tr.count_in_hit(10.0 + k * 0.6) is None
    assert tr.count_in_hit(11.8) == pytest.approx(100.0)
    assert tr.status(11.8)["seed_source"] == "count-in" and tr.status(11.8)["bpm"] == 100.0


def test_count_in_ignored_inside_a_groove():
    tr, _ = tracked(120, groove(120, 4))
    t = 7.9
    assert all(tr.count_in_hit(t + k * 0.6) is None for k in range(4))


def test_big_jump_ignored_until_it_holds_then_reseeds():
    hits = groove(120, 8) + groove(140, 10, start=16.0)
    tr, log = tracked(120, hits)
    early = [s["bpm"] for t, s in log if 16.0 <= t < 16.0 + 7 * 60 / 140]
    assert all(b == 120.0 for b in early)
    assert abs(after(log, 26.0)[-1]["bpm"] - 140) <= 1.5


def test_ghost_notes_and_merging():
    tr = BeatTracker(0.0)
    assert not tr.hit(["snare"], 20, 1.0)  # under the velocity floor
    assert tr.hit(["hat"], 80, 1.0) and tr.hit(["kick"], 100, 1.01)  # within 30 ms: one onset, kick weight
    assert len(tr.onsets) == 1 and tr.onsets[0].w == 1.0 and tr.onsets[0].role == "kick"
    assert not tr.hit(["activity"], 100, 2.0)  # not a tempo role


def test_params_checked():
    p = BeatParams().update({"deadband_pct": 2, "weights": {"hat": 0.3}})
    assert p.deadband_pct == 2 and p.weights["hat"] == 0.3 and p.weights["kick"] == 1.0
    for bad in ({"deadband_pct": 50}, {"weights": {"cowbell": 1}}, {"nope": 1}):
        with pytest.raises(ValueError):
            BeatParams().update(bad)
