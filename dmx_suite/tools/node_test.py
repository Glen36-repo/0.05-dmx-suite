"""Node link test script: send frames, read status, ping, set fallback, name nodes.

    dmx-node-test --sim check
    dmx-node-test --port COM5 check
    dmx-node-test --port COM5 chase --channels 1-24 --seconds 10
    dmx-node-test --port COM5 frame 1=255 2=128
    dmx-node-test --port COM5 fallback --rgb 1,4,7 --period 60 --level 200 --base 10=255
    dmx-node-test --port COM5 assign F4:12:FA:00:A0:01 "Left bars" --universe 0
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

from ..node import protocol as p
from ..node.health import HealthTracker, State
from ..node.link import NodeLink, SerialTransport
from ..node.sim import SimTransport, default_sim

FRAME_HZ = 40


def open_link(args: argparse.Namespace) -> NodeLink:
    if args.sim:
        return NodeLink(SimTransport(default_sim()))
    if not args.port:
        sys.exit("give --port (e.g. COM5) or --sim; `dmx-node-test ports` lists ports")
    return NodeLink(SerialTransport(args.port))


def parse_channels(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    for c in out:
        if not 1 <= c <= p.DMX_CHANNELS:
            raise argparse.ArgumentTypeError(f"channel {c} out of range 1-512")
    return out


def parse_values(items: list[str]) -> bytearray:
    frame = bytearray(p.DMX_CHANNELS)
    for item in items:
        ch, val = item.split("=")
        c, v = int(ch), int(val)
        if not (1 <= c <= p.DMX_CHANNELS and 0 <= v <= 255):
            raise SystemExit(f"bad channel value {item!r}")
        frame[c - 1] = v
    return frame


def listen(link: NodeLink, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        link.poll()
        time.sleep(0.01)


def print_status(link: NodeLink) -> None:
    s = link.stats.last_status
    if s is None:
        print("status: none received")
    else:
        print(
            f"status: mode={s.mode.name.lower()} uptime={s.uptime_ms / 1000:.1f}s "
            f"frames_rx={s.frames_rx} rate={s.frame_rate:.1f}/s crc_err={s.crc_errors} "
            f"other_err={s.other_errors} receivers_online={s.receivers_online}"
        )


def print_nodes(health: HealthTracker) -> None:
    if not health.nodes:
        print("nodes: none heard")
        return
    print(f"{'MAC':17}  {'state':7}  {'type':6}  {'name':16}  {'uni':3}  {'fw':6}  {'rssi':>5}  {'loss':>4}  {'age':>7}")
    for r in health.nodes.values():
        hb = r.heartbeat
        if hb is None:
            print(f"{r.mac:17}  {r.state.value:7}  {'-':6}  {r.name:16}")
            continue
        name = hb.name or "(new node)"
        rssi = "-" if hb.rssi is None else f"{hb.rssi}"
        loss = "-" if hb.loss_pct is None else f"{hb.loss_pct}%"
        age = "never" if hb.last_data_age_ms is None else f"{hb.last_data_age_ms}ms"
        uni = "-" if hb.universe is None else str(hb.universe)
        print(
            f"{r.mac:17}  {r.state.value:7}  {hb.node_type.name:6}  {name:16}  {uni:3}  "
            f"{hb.fw_str:6}  {rssi:>5}  {loss:>4}  {age:>7}"
        )
    for r in health.alerts():
        print(f"ALERT: {r.name or r.mac} is {r.state.value}")


def cmd_check(link: NodeLink, args: argparse.Namespace) -> int:
    rtts = [rtt for rtt in (link.ping() for _ in range(args.pings)) if rtt is not None]
    lost = args.pings - len(rtts)
    if rtts:
        ms = [r * 1000 for r in rtts]
        print(f"ping: {len(rtts)}/{args.pings} ok, min {min(ms):.2f} / avg {statistics.mean(ms):.2f} / max {max(ms):.2f} ms")
    else:
        print("ping: no reply")
    link.request_status()
    listen(link, args.listen)
    print_status(link)
    print_nodes(link.health)
    return 0 if rtts and not lost else 1


def cmd_chase(link: NodeLink, args: argparse.Namespace) -> int:
    chans = args.channels
    period = 1 / FRAME_HZ
    step_every = max(1, round(FRAME_HZ * args.step))
    n = 0
    t_next = time.perf_counter()
    end = t_next + args.seconds
    late = 0
    while time.perf_counter() < end:
        frame = bytearray(p.DMX_CHANNELS)
        frame[chans[(n // step_every) % len(chans)] - 1] = args.level
        link.send_frame(frame, args.universe)
        link.poll()
        n += 1
        t_next += period
        delay = t_next - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        else:
            late += 1
    link.blackout()
    listen(link, 1.2)
    print(f"chase: sent {n} frames in {args.seconds}s ({n / args.seconds:.1f}/s), {late} late")
    print_status(link)
    return 0


def cmd_frame(link: NodeLink, args: argparse.Namespace) -> int:
    frame = parse_values(args.values)
    end = time.monotonic() + args.hold
    while True:  # keep sending so the node doesn't drop to fallback
        link.send_frame(frame, args.universe)
        link.poll()
        if time.monotonic() >= end:
            break
        time.sleep(1 / FRAME_HZ)
    print(f"frame: sent, held {args.hold}s")
    return 0


def cmd_blackout(link: NodeLink, args: argparse.Namespace) -> int:
    link.blackout(args.universe)
    print("blackout: sent")
    return 0


def cmd_fallback(link: NodeLink, args: argparse.Namespace) -> int:
    look = p.FallbackLook(
        hold_ms=args.hold,
        period_s=args.period,
        level=args.level,
        rgb_addr=args.rgb or [],
        base=bytes(parse_values(args.base or [])),
    )
    code = link.set_fallback(look)
    print(f"fallback: {code.name if code is not None else 'no reply'}")
    return 0 if code == p.AckCode.OK else 1


def cmd_assign(link: NodeLink, args: argparse.Namespace) -> int:
    code = link.assign(p.parse_mac(args.mac), args.universe, args.name)
    print(f"assign: {code.name if code is not None else 'no reply'}")
    return 0 if code == p.AckCode.OK else 1


def cmd_identify(link: NodeLink, args: argparse.Namespace) -> int:
    code = link.identify(p.parse_mac(args.mac), args.seconds)
    print(f"identify: {code.name if code is not None else 'no reply'}")
    return 0 if code == p.AckCode.OK else 1


def cmd_ports(_: argparse.Namespace) -> int:
    from serial.tools import list_ports

    for port in list_ports.comports():
        print(f"{port.device:10}  {port.description}  [{port.hwid}]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dmx-node-test", description="0.05 node link test")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--port", help="node serial port, e.g. COM5")
    src.add_argument("--sim", action="store_true", help="use the simulated node")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ports", help="list serial ports")

    c = sub.add_parser("check", help="ping, status and node list")
    c.add_argument("--pings", type=int, default=20)
    c.add_argument("--listen", type=float, default=2.5, help="seconds to collect heartbeats")

    c = sub.add_parser("chase", help="40 Hz single-channel chase")
    c.add_argument("--channels", type=parse_channels, default=parse_channels("1-8"))
    c.add_argument("--seconds", type=float, default=10)
    c.add_argument("--step", type=float, default=0.25, help="seconds per channel")
    c.add_argument("--level", type=int, default=255)
    c.add_argument("--universe", type=int, default=0)

    c = sub.add_parser("frame", help="send CH=VAL values (others 0)")
    c.add_argument("values", nargs="+")
    c.add_argument("--hold", type=float, default=5)
    c.add_argument("--universe", type=int, default=0)

    c = sub.add_parser("blackout")
    c.add_argument("--universe", type=int, default=p.UNIVERSE_ALL)

    c = sub.add_parser("fallback", help="store the fallback look on the node")
    c.add_argument("--hold", type=int, default=2000, help="ms without frames before fallback")
    c.add_argument("--period", type=int, default=60, help="s per colour-wheel cycle")
    c.add_argument("--level", type=int, default=200)
    c.add_argument("--rgb", type=parse_channels, help="red channel addresses, e.g. 1,4,7")
    c.add_argument("--base", nargs="*", help="static CH=VAL, e.g. dimmers 10=255")

    c = sub.add_parser("assign", help="name a node and set its universe")
    c.add_argument("mac")
    c.add_argument("name")
    c.add_argument("--universe", type=int, default=0)

    c = sub.add_parser("identify", help="blink a node's LED")
    c.add_argument("mac")
    c.add_argument("--seconds", type=int, default=5)
    return ap


COMMANDS = {
    "check": cmd_check,
    "chase": cmd_chase,
    "frame": cmd_frame,
    "blackout": cmd_blackout,
    "fallback": cmd_fallback,
    "assign": cmd_assign,
    "identify": cmd_identify,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "ports":
        return cmd_ports(args)
    link = open_link(args)
    try:
        return COMMANDS[args.cmd](link, args)
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
