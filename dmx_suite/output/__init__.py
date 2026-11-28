"""Pluggable output drivers. The engine hands every frame to each driver in the rig's `outputs`.

    outputs:
      - {driver: node_serial, port: COM5}
      - {driver: enttec_open, port: COM7}
      - {driver: artnet, host: 2.255.255.255}
      - {driver: sacn}

See network.py for the Art-Net / sACN settings.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import LogDriver, NullDriver, OutputDriver
from .enttec import EnttecOpenDriver, EnttecProDriver
from .network import ArtNetDriver, SacnDriver
from .node import NodeSerialDriver

DRIVERS: dict[str, Callable[..., OutputDriver]] = {
    "null": NullDriver,
    "log": LogDriver,
    "node_serial": NodeSerialDriver,
    "enttec_open": EnttecOpenDriver,
    "enttec_pro": EnttecProDriver,
    "artnet": ArtNetDriver,
    "sacn": SacnDriver,
}


def make_driver(cfg: dict[str, Any]) -> OutputDriver:
    cfg = dict(cfg)
    name = cfg.pop("driver", None)
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
    "ArtNetDriver",
    "SacnDriver",
    "make_driver",
]
