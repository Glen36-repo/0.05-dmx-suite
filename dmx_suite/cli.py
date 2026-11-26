"""dmx-suite: run the engine, simulate, monitor MIDI, check show files.

    dmx-suite run --sim                     simulator: fake MIDI + log output + console
    dmx-suite run --rig full                live: real MIDI ports + the rig's outputs
    dmx-suite midi-ports
    dmx-suite midi-monitor                  live MIDI list with what each message triggers
    dmx-suite check                         validate every show file
"""

from __future__ import annotations

import argparse
import shlex
import sys
import time
from pathlib import Path

from .engine import Engine
from .fixtures import EMITTERS, ConfigError, Kind
from .midi.inputs import FakeMidiIn, MidiInputs, port_names
from .midi.map import save_map
from .midi.monitor import MidiMonitor
from .midi.router import MidiRouter
from .output import LogDriver, NodeSerialDriver, make_driver
from .showfiles import check_all, load_show

DEFAULT_SHOWS = Path(__file__).resolve().parents[1] / "shows"


# --------------------------------------------------------------------------- on-screen rig (text)


def rig_view(engine: Engine) -> str:
    lines = [
        f"MASTER {'ON ' if engine.master else 'off'}  blackout {'ON' if engine.blackout else 'off'}  "
        f"grand {engine.masters.grand.value * 100:3.0f}%  flash level {engine.masters.flash.value * 100:3.0f}%  "
        f"subs " + " ".join(f"{k.value}={v.value * 100:.0f}%" for k, v in engine.masters.subs.items() if k != Kind.HAZE)
    ]
    hz = engine.haze.status(engine.clock())
    extra = []
    if hz.auto_off_in_s is not None:
        extra.append(f"auto-off {hz.auto_off_in_s / 60:.0f} min")
    if hz.next_pulse_in_s is not None:
        extra.append(f"next pulse {hz.next_pulse_in_s:.0f}s")
    if hz.boost_cooldown_s:
        extra.append(f"boost cooldown {hz.boost_cooldown_s:.0f}s")
    if hz.resting:
        extra.append("resting (max on-time)")
    lines.append(
        f"HAZE {'disabled' if not hz.enabled else hz.mode.value}  output {'ON' if hz.output_on else 'off'}"
        f"{' (boost)' if hz.boosting else ''}  {'  '.join(extra)}"
    )
    lines.append(f"{'fixture':9} {'kind':5} {'dim':>4}  {'colour':24}  pan/tilt")
    for fx in engine.rig.fixtures:
        frame = engine.frames.get(fx.universe)
        if frame is None:
            continue
        vals = {ch: frame[fx.slot(ch)] for ch in fx.type.channels}
        dim = next((v for ch, v in vals.items() if ch.role == "dimmer"), None)
        if fx.kind == Kind.HAZE:
            colour = f"haze {next(iter(vals.values()))}"
        elif fx.type.pixels:
            px = []
            for i in range(fx.type.pixels):
                rgb = [v for ch, v in vals.items() if ch.pixel == i and ch.role in ("red", "green", "blue")]
                px.append("".join(f"{x:02x}" for x in rgb))
            colour = " ".join(px[:3]) + (" …" if len(px) > 3 else "")
        else:
            colour = " ".join(f"{ch.role[0].upper()}{v}" for ch, v in vals.items() if ch.role in EMITTERS)
        pt = ""
        if fx.type.has("pan"):
            pan = next(v for ch, v in vals.items() if ch.role == "pan")
            tilt = next(v for ch, v in vals.items() if ch.role == "tilt")
            pt = f"{pan}/{tilt}"
        lines.append(f"{fx.id:9} {fx.kind.value:5} {'' if dim is None else dim:>4}  {colour:24}  {pt}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- simulator console

HELP = """commands:
  master on|off|toggle        blackout on|off|toggle
  hit NOTE [VEL]              drum note on ch 10 (e.g. hit 38 110)
  pc N [CH]                   program change (FCB1010, ch 1)
  cc N VALUE [CH]             control change (e.g. cc 7 64 = expression pedal)
  gm PCT | sub KIND PCT       grand master / sub-master (head bar wash kick)
  haze off|manual|pulse|boost|release
  rig                         show the rig          monitor [N]   last N MIDI lines
  learn ACTION [k=v ...]      next MIDI message maps to ACTION (e.g. learn flash fixtures=bars)
  save                        write the MIDI map    map           list mappings
  status                      outputs + counters    quit"""


def console(engine: Engine, router: MidiRouter, fake: FakeMidiIn, map_path: Path) -> None:
    print(rig_view(engine))
    print("\ntype 'help' for commands")
    while True:
        try:
            line = input("dmx> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        try:
            args = shlex.split(line)
            cmd, rest = args[0].lower(), args[1:]
            if cmd in ("quit", "exit", "q"):
                return
            elif cmd == "help":
                print(HELP)
            elif cmd == "master":
                {"on": lambda: engine.set_master(True), "off": lambda: engine.set_master(False)}.get(
                    rest[0] if rest else "toggle", engine.toggle_master
                )()
                print(rig_view(engine))
            elif cmd == "blackout":
                {"on": lambda: engine.set_blackout(True), "off": lambda: engine.set_blackout(False)}.get(
                    rest[0] if rest else "toggle", engine.toggle_blackout
                )()
                print(rig_view(engine))
            elif cmd == "hit":
                t0 = time.perf_counter()
                result = fake.note(int(rest[0]), int(rest[1]) if len(rest) > 1 else 100)
                dt = (time.perf_counter() - t0) * 1000
                print(f"{result}  (hit to frame sent: {dt:.2f} ms)")
                print(rig_view(engine))
                fake.note_off(int(rest[0]))
            elif cmd == "pc":
                print(fake.program(int(rest[0]), int(rest[1]) if len(rest) > 1 else 1))
            elif cmd == "cc":
                print(fake.cc(int(rest[0]), int(rest[1]), int(rest[2]) if len(rest) > 2 else 1))
            elif cmd == "gm":
                engine.set_grand(float(rest[0]) / 100)
                print(f"grand master -> {rest[0]}% (fading)")
            elif cmd == "sub":
                engine.set_sub(rest[0], float(rest[1]) / 100)
                print(f"{rest[0]} sub-master -> {rest[1]}%")
            elif cmd == "haze":
                sub = rest[0] if rest else ""
                if sub == "boost":
                    print("boost on" if engine.haze_boost(True) else "boost refused (disabled or cooling down)")
                elif sub == "release":
                    engine.haze_boost(False)
                elif sub == "off":
                    engine.haze_stop()
                elif sub in ("manual", "pulse"):
                    engine.haze_mode(sub)
                else:
                    print("haze off|manual|pulse|boost|release")
                print(rig_view(engine).splitlines()[1])
            elif cmd == "rig":
                print(rig_view(engine))
            elif cmd == "monitor":
                n = int(rest[0]) if rest else 15
                for e in list(router.monitor.entries)[-n:]:
                    print(e.format())
            elif cmd == "learn":
                params: dict = {}
                for kv in rest[1:]:
                    k, v = kv.split("=", 1)
                    params[k] = v.split(",") if k == "fixtures" else (int(v) if v.isdigit() else v)
                router.learn(rest[0], params)
                print(f"learning {rest[0]}: send a MIDI message (hit/pc/cc)")
            elif cmd == "map":
                for m in router.map.mappings:
                    print(f"  {m.type:15} ch{m.channel:<2} #{m.number:<3} -> {m.describe()}")
            elif cmd == "save":
                save_map(router.map, map_path)
                print(f"saved {map_path}")
            elif cmd == "status":
                for d in engine.drivers:
                    print(" ", d.status())
                print(f"  frames rendered {engine.frames_sent}, driver errors {engine.driver_errors}")
            else:
                print(f"unknown command {cmd!r}; type help")
        except (IndexError, ValueError, ConfigError) as e:
            print(f"error: {e}")


# --------------------------------------------------------------------------- commands


def cmd_run(args: argparse.Namespace) -> int:
    show = load_show(args.shows, args.rig, args.look, args.midi)
    if args.sim:
        drivers = [LogDriver()] + ([make_driver({"driver": "node_serial", "port": "sim"})] if args.sim_node else [])
    else:
        drivers = [make_driver(o) for o in show.rig.outputs]
    for d in drivers:  # rig config lists the nodes expected, so a missing one shows at setup
        if isinstance(d, NodeSerialDriver):
            d.link.health.expect(show.rig.nodes)
    engine = Engine(show.rig, drivers, show.look)
    router = MidiRouter(engine, show.midimap, MidiMonitor())
    fake = FakeMidiIn(router.handle_mido)
    real = None
    if not args.sim:
        real = MidiInputs(args.midi_port or None, router.handle_mido)
        print("MIDI in:", ", ".join(p.name for p in real.ports) or "none")
    engine.start()
    try:
        if args.sim or sys.stdin.isatty():
            console(engine, router, fake, show.midimap_path)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if real:
            real.close()
        engine.stop()
    return 0


def cmd_midi_ports(_: argparse.Namespace) -> int:
    try:
        names = port_names()
    except Exception as e:  # no rtmidi backend
        print(f"can't list MIDI ports: {e}")
        return 1
    for n in names:
        print(n)
    return 0


def cmd_midi_monitor(args: argparse.Namespace) -> int:
    show = load_show(args.shows, args.rig, args.look, args.midi)
    from .output import NullDriver

    engine = Engine(show.rig, [NullDriver()], show.look)  # resolves what each message would trigger
    monitor = MidiMonitor()
    monitor.listeners.append(
        lambda e: (args.channel is None or e.channel == args.channel) and print(e.format(), flush=True)
    )
    router = MidiRouter(engine, show.midimap, monitor)
    inputs = MidiInputs(args.midi_port or None, router.handle_mido)
    print(f"listening on: {', '.join(p.name for p in inputs.ports) or 'none'}  (ctrl+c to stop)")
    print(f"{'time':12}  {'port':20}  {'ch':3}  {'type':14}  {'num':3}  {'val':3}  result")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        inputs.close()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    problems = check_all(args.shows)
    errors = [p for p in problems if not p.startswith("warning")]
    for p in problems:
        print(p)
    print("ok" if not errors else f"{len(errors)} problem(s)")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dmx-suite", description="0.05 DMX Suite")
    ap.add_argument("--shows", type=Path, default=DEFAULT_SHOWS, help="show folder")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def show_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--rig", default="full")
        p.add_argument("--look", default="default")
        p.add_argument("--midi", default="default", help="MIDI map name")
        p.add_argument("--midi-port", action="append", help="MIDI input port (repeat; default all)")

    p = sub.add_parser("run", help="run the engine")
    show_args(p)
    p.add_argument("--sim", action="store_true", help="simulator: fake MIDI, log output, no hardware")
    p.add_argument("--sim-node", action="store_true", help="with --sim, also drive the simulated node")

    sub.add_parser("midi-ports", help="list MIDI inputs")
    p = sub.add_parser("midi-monitor", help="live MIDI list with what each message triggers")
    show_args(p)
    p.add_argument("--channel", type=int, help="only this channel (1-16)")

    sub.add_parser("check", help="validate show files")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {
            "run": cmd_run,
            "midi-ports": cmd_midi_ports,
            "midi-monitor": cmd_midi_monitor,
            "check": cmd_check,
        }[args.cmd](args)
    except ConfigError as e:
        print(f"show file error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
