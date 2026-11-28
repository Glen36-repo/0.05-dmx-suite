"""Guided fault-find (v5): "Rig not responding". One tree, used by the Monitor page wizard and by Claude
(`fault_find`), so both walk the same steps.

1. Automatic: the USB DMX (Open) checks (output/ftdi.py). A fail stops here with its fix.
2. Question: are the lights in auto / sound / standalone mode?
   - yes: no valid DMX reaches them. Cycle break methods, bypass wireless, swap the lead / check a
     5-pin to 3-pin adaptor, DMX IN not THRU, the interface in another program, then suspect the
     interface itself.
   - no: DMX arrives. Pick the dark light; the live frame first says whether the app sends it anything;
     then find fixture, start address, channel mode, IN/THRU order and termination, and MASTER / grand
     master / head limits in the live frame.

Each step is one instruction, a test where there is one, and Pass / Fail: Pass ends the hunt there
("found"), Fail moves to the next likely cause. The summary is kept and logged. Nothing here changes
settings apart from the tests it starts (and the cycle test, which saves only what's confirmed);
under gig lock the tests that need it are off.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("dmx_suite.faultfind")

NO_DMX: list[dict[str, Any]] = [
    {"id": "cycle", "text": "Run the break-method cycle test on the USB DMX interface and watch the lights. Did one "
                            "step bring them out of auto / sound mode?", "test": "cycle", "open_only": True},
    {"id": "wireless", "text": "Take the wireless out of the path: a DMX cable straight from the interface to the "
                               "first light (Beamz / wireless nodes unplugged). With All full running, do the lights "
                               "come on?", "test": "all_full"},
    {"id": "lead", "text": "Swap the DMX lead. If there's a 5-pin to 3-pin adaptor, check pins 2 and 3 aren't swapped "
                           "(pin 2 Data-, pin 3 Data+ at both ends). Do the lights come on now?", "test": "all_full"},
    {"id": "in_thru", "text": "Check the lead goes into the first light's DMX IN, not THRU / OUT. Do the lights come "
                              "on now?", "test": "all_full"},
    {"id": "other_app", "text": "Try the interface in another program: QLC+ or FreeStyler drive an Open DMX "
                                "(Daslight can't). Quit this program first so the port is free. Do the lights "
                                "work from the other program?",
     "pass_note": "The interface, lead and lights are fine: this program's timing is the likely cause. Set the "
                  "break method / timings to what works (Monitor › Cycle break methods) and tell Claude what "
                  "the other program used."},
    {"id": "interface", "kind": "end", "text": "Nothing works from any program: suspect the interface itself (the "
                                               "FTDI chip shows up on USB but its RS-485 driver chip is dead). "
                                               "Swap in another interface."},
]

DMX_ARRIVES: list[dict[str, Any]] = [
    {"id": "find", "text": "Find fixture on {fx}: does it flash?", "test": "find"},
    {"id": "address", "text": "On {fx} itself, set the start address to {address} (1-based, universe {universe}) "
                              "if it isn't already. Does {fx} work now?"},
    {"id": "mode", "text": "Set {fx}'s channel mode to {channels} channels (fixture type {type}) if it isn't "
                           "already. Does it work now?"},
    {"id": "chain", "text": "Check the DMX chain: each lead from a light's THRU / OUT to the next one's IN, and a "
                            "120 Ω terminator at the end of a long run. Does {fx} work after fixing the chain?"},
    {"id": "levels", "kind": "auto", "text": "Live frame: {fx}'s values with MASTER, grand master and head limits "
                                             "applied."},
]


@dataclass
class FaultFind:
    started: float = field(default_factory=time.time)
    branch: str = ""  # "" (checks / question) / no_dmx / dmx_arrives
    i: int = 0  # index into the branch
    fixture: str | None = None
    stage: str = "checks"  # checks / question / pick / steps / done
    history: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = ""
    by: str = "ui"

    def record(self, step: str, result: str, detail: str = "") -> None:
        self.history.append({"step": step, "result": result, "detail": detail, "time": time.time()})

    def summary(self) -> str:
        lines = [f"Fault-find {time.strftime('%d/%m/%Y %H:%M', time.localtime(self.started))}"]
        lines += [f"- {h['step']}: {h['result']}" + (f" ({h['detail']})" if h["detail"] else "") for h in self.history]
        lines.append(f"Result: {self.outcome or 'not finished'}")
        return "\n".join(lines)


class FaultFinder:
    """Walks the tree against a running App (checks, live frame, tests)."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.ff: FaultFind | None = None

    # ------------------------------------------------------------------ helpers

    def _steps(self) -> list[dict[str, Any]]:
        return NO_DMX if self.ff and self.ff.branch == "no_dmx" else DMX_ARRIVES

    def _has_open(self) -> bool:
        return bool(self.app._open_outputs())

    def _fx_info(self) -> dict[str, Any]:
        rig = self.app.engine.rig
        fx = rig.patch.fixtures.get(self.ff.fixture or "") if self.ff else None
        if fx is None:
            return {"fx": "the dark light", "address": "?", "universe": "?", "channels": "?", "type": "?"}
        return {"fx": fx.id, "address": fx.address, "universe": fx.universe, "channels": fx.type.footprint,
                "type": fx.type.name}

    def _sent(self, fid: str) -> dict[str, int] | None:
        """What the interface carrying this light really sent on its channels (role -> value), or None."""
        rig = self.app.engine.rig
        fx = rig.patch.fixtures[fid]
        frame = None
        for d in self.app.engine.drivers:
            if d.carries(fx.universe):
                frame = d.wire.frame(fx.universe)
                if frame is not None:
                    break
        if frame is None:
            return None
        out: dict[str, int] = {}
        for ch in fx.type.channels:
            key = ch.role + (f" px{ch.pixel + 1}" if ch.pixel is not None else "")
            out[key] = frame[fx.slot(ch)]
        return out

    def _zero_flag(self) -> str:
        fid = self.ff.fixture if self.ff else None
        if not fid:
            return ""
        sent = self._sent(fid)
        if sent is None:
            return f"No frames have gone out on {fid}'s universe: nothing reaches the hardware. Check the routing table."
        from .fixtures import EMITTERS

        lit = [k for k, v in sent.items() if v and (k.split(" ")[0] in EMITTERS or k.startswith("dimmer"))]
        if not lit:
            e = self.app.engine
            why = [w for w, on in (("MASTER is off", not e.master), ("blackout is on", e.blackout),
                                   ("the grand master is at 0", e.masters.grand.target <= 0.0)) if on]
            return (f"The app is sending 0 on every light channel of {fid}" + (f": {', '.join(why)}" if why else
                    ": nothing playing lights it") + ". Fix that before checking the hardware.")
        return ""

    # ------------------------------------------------------------------ the tree

    def start(self, by: str = "ui") -> dict[str, Any]:
        self.ff = FaultFind(by=by)
        return self._advance()

    def _advance(self) -> dict[str, Any]:
        ff = self.ff
        assert ff is not None
        if ff.stage == "checks":
            res = self.app.check_outputs()
            fails = [(r["interface"], c) for r in res for c in r["checks"] if c["result"] == "fail"]
            warns = [(r["interface"], c) for r in res for c in r["checks"] if c["result"] == "warn"]
            if fails:
                iface, c = fails[0]
                ff.record("Interface checks", "fail", f"{iface}: {c['name']}: {c['detail']}")
                ff.stage, ff.outcome = "done", f"stopped at the interface checks: {c['name']} ({c['detail']}). Fix: {c['fix']}"
                self._log()
                return self.view()
            detail = "; ".join(f"{i}: {c['name']}: {c['detail']}" for i, c in warns) or (
                "all pass" if res else "no USB DMX (Open) outputs to check")
            ff.record("Interface checks", "warn" if warns else "pass", detail)
            ff.stage = "question"
        return self.view()

    def answer(self, answer: str, fixture: str | None = None) -> dict[str, Any]:
        """yes / no (question), a fixture id (pick), pass / fail (steps), restart."""
        ff = self.ff
        if ff is None or answer == "restart":
            return self.start(ff.by if ff else "ui")
        a = answer.strip().lower()
        if ff.stage == "done":
            return self.view()
        if ff.stage == "question":
            if a not in ("yes", "no"):
                raise ValueError("answer yes (lights in auto / sound / standalone mode) or no")
            ff.record("Lights in auto / sound mode?", a)
            if a == "yes":
                ff.branch, ff.stage, ff.i = "no_dmx", "steps", 0
                if not self._has_open():
                    ff.i = 1  # the cycle test is for USB DMX (Open) only
            else:
                ff.branch, ff.stage = "dmx_arrives", "pick"
            return self.view()
        if ff.stage == "pick":
            fid = fixture or answer
            if fid not in self.app.engine.rig.present:
                raise ValueError(f"pick a light in this rig ({', '.join(self.app.engine.rig.present)})")
            ff.fixture, ff.stage, ff.i = fid, "steps", 0
            flag = self._zero_flag()
            ff.record(f"Dark light: {fid}", "picked", flag)
            if flag:
                ff.stage, ff.outcome = "done", flag
                self._log()
            return self.view()
        # steps
        if a not in ("pass", "fail"):
            raise ValueError("answer pass or fail")
        step = self._steps()[ff.i]
        text = step["text"].format(**self._fx_info())
        ff.record(step["id"], a)
        if a == "pass":  # that fixed it / that's where it works
            ff.stage, ff.outcome = "done", step.get("pass_note") or f"found at '{step['id']}': {text}"
            self._log()
            return self.view()
        ff.i += 1
        if ff.i >= len(self._steps()) or self._steps()[ff.i].get("kind") == "end":
            if ff.i < len(self._steps()):
                ff.outcome = self._steps()[ff.i]["text"]
            else:
                ff.outcome = "every step done without finding it"
            if self._steps() is DMX_ARRIVES and ff.fixture:
                ff.outcome = f"{ff.outcome}. Live frame for {ff.fixture}: {self._levels()}"
            ff.stage = "done"
            self._log()
        elif self._steps()[ff.i].get("kind") == "auto":  # levels: read from the live frame, then finish
            ff.record("levels", "info", self._levels())
            ff.stage, ff.outcome = "done", f"not found by the steps. Live frame for {ff.fixture}: {self._levels()}"
            self._log()
        return self.view()

    def _levels(self) -> str:
        fid = self.ff.fixture if self.ff else None
        if not fid:
            return ""
        sent = self._sent(fid)
        if sent is None:
            return "no frames sent"
        e = self.app.engine
        vals = ", ".join(f"{k} {v}" for k, v in sent.items())
        return (f"{vals} (MASTER {'on' if e.master else 'off'}, grand master {round(e.masters.grand.target * 100)} %"
                f"{', blackout' if e.blackout else ''})")

    def run_test(self) -> dict[str, Any]:
        """Start the current step's test (pattern on the first output carrying the universe, or the cycle)."""
        ff = self.ff
        if ff is None or ff.stage != "steps":
            raise ValueError("no step with a test right now")
        step = self._steps()[ff.i]
        test = step.get("test")
        if test is None:
            raise ValueError("this step has no test")
        if test == "cycle":
            idx = self.app._open_outputs()[0][0]
            return {"cycle": self.app.start_cycle(idx, ff.by)}
        args: dict[str, Any] = {"pattern": test, "timeout_s": 120}
        if test == "find":
            args["fixture"] = ff.fixture
        return {"test": self.app.run_test(args, ff.by)}

    def _log(self) -> None:
        if self.ff is not None:
            log.info("%s", self.ff.summary())

    def view(self) -> dict[str, Any]:
        ff = self.ff
        if ff is None:
            return {"stage": "idle"}
        out: dict[str, Any] = {"stage": ff.stage, "branch": ff.branch, "fixture": ff.fixture,
                               "history": ff.history, "summary": ff.summary(), "outcome": ff.outcome}
        locked = bool(self.app.gig_lock)
        if ff.stage == "question":
            out.update(instruction="Are the lights in auto / sound / standalone mode (doing their own thing)?",
                       answers=["yes", "no"])
        elif ff.stage == "pick":
            out.update(instruction="Which light is dark or wrong?", answers=list(self.app.engine.rig.present))
        elif ff.stage == "steps":
            step = self._steps()[ff.i]
            out.update(step=step["id"], number=ff.i + 1, of=len([s for s in self._steps() if s.get("kind") != "end"]),
                       instruction=step["text"].format(**self._fx_info()), answers=["pass", "fail"],
                       test=step.get("test"), test_allowed=bool(step.get("test")) and not locked,
                       flag=self._zero_flag() if ff.branch == "dmx_arrives" else "")
        elif ff.stage == "done":
            out.update(instruction=ff.outcome, answers=["restart"])
        return out
