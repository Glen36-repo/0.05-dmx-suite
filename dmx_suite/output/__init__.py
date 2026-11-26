"""Pluggable output drivers. The engine hands every frame to each driver in the rig's `outputs`.

    outputs:
      - {driver: node, port: COM5, universe: 0}
      - {driver: usb_dmx_open, port: COM7, universe: 0}
      - {driver: artnet, host: 2.255.255.255}
      - {driver: sacn}

See network.py for the Art-Net / sACN settings.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from .base import LogDriver, NullDriver, OutputDriver
from .enttec import EnttecOpenDriver, EnttecProDriver
from .network import ArtNetDriver, SacnDriver
from .node import NodeSerialDriver

DRIVERS: dict[str, Callable[..., OutputDriver]] = {
    "null": NullDriver,
    "log": LogDriver,
    "node": NodeSerialDriver,  # 0.05 node over USB serial
    "usb_dmx_open": EnttecOpenDriver,  # FTDI raw-break interfaces (Open DMX style)
    "usb_dmx_pro": EnttecProDriver,  # DMX USB Pro protocol interfaces
    "artnet": ArtNetDriver,
    "sacn": SacnDriver,
}
# v4: driver ids say what the interface does, not who made it; the v3 ids still load
DRIVER_ALIASES = {"node_serial": "node", "enttec_open": "usb_dmx_open", "enttec_pro": "usb_dmx_pro"}


def driver_id(name: Any) -> Any:
    return DRIVER_ALIASES.get(name, name) if isinstance(name, str) else name


def make_driver(cfg: dict[str, Any]) -> OutputDriver:
    cfg = dict(cfg)
    name = driver_id(cfg.pop("driver", None))
    if name not in DRIVERS:
        raise ValueError(f"unknown output driver {name!r}; one of {sorted(DRIVERS)}")
    for k in ("device", "alias"):  # identity, not driver settings
        cfg.pop(k, None)
    if "universe" in cfg and "universe" not in inspect.signature(DRIVERS[name]).parameters:
        cfg.pop("universe")  # drivers that send every universe (node, log, null) or map them (Art-Net, sACN)
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
