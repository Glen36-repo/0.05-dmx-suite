"""Pluggable output drivers. The engine hands every frame to each driver in the rig's `outputs`.

    outputs:
      - {driver: node_serial, port: COM5}
      - {driver: enttec_open, port: COM7}
"""

from __future__ import annotations

from typing import Any, Callable

from .base import LogDriver, NullDriver, OutputDriver
from .enttec import EnttecOpenDriver, EnttecProDriver
from .node import NodeSerialDriver

DRIVERS: dict[str, Callable[..., OutputDriver]] = {
    "null": NullDriver,
    "log": LogDriver,
    "node_serial": NodeSerialDriver,
    "enttec_open": EnttecOpenDriver,
    "enttec_pro": EnttecProDriver,
}


def make_driver(cfg: dict[str, Any]) -> OutputDriver:
    cfg = dict(cfg)
    name = cfg.pop("driver", None)
    if name == "artnet":
        raise ValueError("artnet driver is planned for later (SCOPE: Art-Net / sACN)")
    if name not in DRIVERS:
        raise ValueError(f"unknown output driver {name!r}; one of {sorted(DRIVERS)}")
    return DRIVERS[name](**cfg)


__all__ = [
    "OutputDriver",
    "NullDriver",
    "LogDriver",
    "NodeSerialDriver",
    "EnttecOpenDriver",
    "EnttecProDriver",
    "make_driver",
]
