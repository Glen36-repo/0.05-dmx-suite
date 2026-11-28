"""DMX output diagnostics (v5): the break-method cycle test.

The cycle test steps an Open DMX output through each break method (D2XX when installed, serial break,
baud drop, then a long 500 µs break), 5 s each, with the "all full" test pattern running on that
output. Whoever watches the lights taps "Lights responded" on the step that worked: that method and
break length are saved to the output in the rig file. With no tap, the output goes back to what it
had. Not under gig lock.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from .output.enttec import METHOD_NAMES, EnttecOpenDriver
from .testpattern import TestPattern

STEP_S = 5.0
LONG_BREAK_US = 500


def cycle_steps(drv: EnttecOpenDriver) -> list[dict[str, Any]]:
    """The steps for this interface: d2xx only when D2XX is installed and sees it."""
    base = drv.settings["break_us"]
    methods = (["d2xx"] if drv.d2xx_ok() else []) + ["serial_break", "baud_drop"]
    steps = [{"break_method": m, "break_us": base} for m in methods]
    steps.append({"break_method": "d2xx" if drv.d2xx_ok() else "serial_break", "break_us": LONG_BREAK_US})
    for i, s in enumerate(steps):
        s["label"] = f"{METHOD_NAMES[s['break_method']]}, {s['break_us']:g} µs" + (" (long)" if i == len(steps) - 1 else "")
        s["step"] = i + 1
    return steps


class MethodCycle:
    """One run of the cycle test on output `index`. `save(index, changes)` writes the confirmed step."""

    def __init__(self, engine: Any, index: int, save: Callable[[int, dict[str, Any]], Any],
                 step_s: float = STEP_S, by: str = "ui") -> None:
        drv = engine.drivers[index] if 0 <= index < len(engine.drivers) else None
        if not isinstance(drv, EnttecOpenDriver):
            raise ValueError("the cycle test is for USB DMX (Open) outputs: pick one in the routing table")
        self.engine, self.index, self.drv, self.save, self.step_s, self.by = engine, index, drv, save, step_s, by
        self.original = {k: drv.settings[k] for k in ("break_method", "break_us")}
        self.steps = cycle_steps(drv)
        self.current = 0
        self.result: dict[str, Any] | None = None
        self.state = "running"  # running / confirmed / no_response / stopped
        self.started = time.time()
        self._confirm = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="dmx-cycle", daemon=True)

    def start(self) -> MethodCycle:
        self.engine.run_test(TestPattern("all_full", output=self.index, timeout_s=self.step_s * len(self.steps) + 10,
                                         by="cycle"))
        self._thread.start()
        return self

    def _ours(self) -> bool:
        t = self.engine.test
        return t is not None and t.by == "cycle" and t.output == self.index

    def _run(self) -> None:
        try:
            for i, s in enumerate(self.steps):
                self.current = i
                self.drv.configure(break_method=s["break_method"], break_us=s["break_us"])
                if self._confirm.wait(self.step_s) or self._stop.is_set() or not self._ours():
                    break
            if self._confirm.is_set():
                step = self.steps[self.current]
                self.result = {k: step[k] for k in ("step", "label", "break_method", "break_us")}
                self.state = "confirmed"
                self.save(self.index, {"break_method": step["break_method"], "break_us": step["break_us"]})
            else:
                self.state = "stopped" if (self._stop.is_set() or not self._ours()) else "no_response"
                self.drv.configure(**self.original)
        except Exception as e:  # noqa: BLE001 - report it, put the output back
            self.state, self.error = "stopped", str(e)
            try:
                self.drv.configure(**self.original)
            except Exception:  # noqa: BLE001
                pass
        finally:
            if self._ours():
                self.engine.stop_test("cycle test done")

    def confirm(self) -> dict[str, Any]:
        """Lights responded: keep the step running now."""
        if self.state == "running":
            self._confirm.set()
            self._thread.join(timeout=10)
        return self.view()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def wait(self, timeout: float) -> None:
        self._thread.join(timeout)

    def view(self) -> dict[str, Any]:
        cur = self.steps[self.current]
        return {"output": self.index, "state": self.state, "step": cur["step"], "of": len(self.steps),
                "label": cur["label"], "steps": [s["label"] for s in self.steps], "step_s": self.step_s,
                "result": self.result, "original": self.original, "by": self.by,
                "error": getattr(self, "error", None)}
