"""Windows timer resolution for the output loop.

Windows wakes sleeping threads on a ~15.6 ms system tick unless a program asks for 1 ms, which
would make the 40 Hz loop (25 ms) and flash cut-offs jitter by most of a frame. `high_res()`
asks for 1 ms while the engine runs and gives it back when it stops. Elsewhere it does nothing.
"""

from __future__ import annotations

import sys
from typing import Callable


def high_res() -> Callable[[], None]:
    """Ask for 1 ms timer resolution; returns the function that gives it back."""
    if sys.platform != "win32":
        return lambda: None
    try:
        import ctypes

        winmm = ctypes.WinDLL("winmm")
        if winmm.timeBeginPeriod(1) != 0:
            return lambda: None
        return lambda: winmm.timeEndPeriod(1)
    except (OSError, AttributeError):
        return lambda: None
