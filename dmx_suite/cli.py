"""dmx-suite: run the engine, simulate, monitor MIDI, check show files.

    dmx-suite run --sim                     simulator: fake MIDI + log output + console
    dmx-suite run --rig full                live: real MIDI ports + the rig's outputs
    dmx-suite app [--sim]                   desktop app window (needs the `desktop` extra)
    dmx-suite midi-ports
    dmx-suite midi-monitor                  live MIDI list with what each message triggers
    dmx-suite check                         validate every show file
    dmx-suite addresses                     patch / address check
    dmx-suite import-ofl FILE [--mode M]    fixture type from an Open Fixture Library file
    dmx-suite claude-setup                  add the 0.05 tools to Claude Desktop
"""

from __future__ import annotations

import argparse
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .engine import Engine
from .fixtures import EMITTERS, ConfigError, Kind
from .midi.inputs import FakeMidiIn, MidiInputs, port_names
from .midi.monitor import MidiMonitor
from .midi.router import MidiRouter
from .output import LogDriver, NodeSerialDriver, make_driver
from .ofl import import_ofl
from .paths import data_dir, default_shows, log_dir, move_old_state, prepare
from .setup import format_report, patch_report
from .app import App
from .showctl import ShowController
from .store import ShowStore
from .showfiles import ShowFiles, check_all, load_show



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
  scene NAME | scenes | look  play a scene / list scenes / back to the static look
  show NAME [SET] | shows     play a show (e.g. show band high)   set low|mid|high
  next                        next step now       now   what's playing
  setlist NAME | song next|prev|N | setlists      setlist mode
  tap | tempo BPM|off         tap tempo (effects follow it; step timers stay fixed)
  rig                         show the rig          monitor [N]   last N MIDI lines
setup / test:
  find FIXTURE | find off     light one fixture (ignores MASTER)
  chan CH VALUE [UNI] | chan CH off    raw channel tester
  setup off                   clear find and channel tests
  addresses                   patch / address check   nodes   node + receiver health
  learn ACTION [k=v ...]      next MIDI message maps to ACTION (e.g. learn flash fixtures=bars)
  save                        write the MIDI map    map           list mappings
  status                      outputs + counters    quit"""


def console(engine: Engine, router: MidiRouter, fake: FakeMidiIn, map_path: Path, show: ShowFiles | None = None,
            ctl: ShowController | None = None, store: ShowStore | None = None) -> None:
    print(rig_view(engine))
    if ctl:
        print(ctl.describe())
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
                if ctl:
                    ctl.save()
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
            elif cmd == "scenes":
                for k, sc in (show.scenes if show else {}).items():
                    mark = "*" if engine.scene is sc else " "
                    print(f" {mark} {k:16} {sc.name}  ({len(sc.layers)} layers)")
            elif cmd == "scene" and ctl:
                ctl.select_scene(rest[0])
                print(rig_view(engine))
            elif cmd == "look" and ctl:
                ctl.select_look()
                print(rig_view(engine))
            elif cmd == "shows" and show:
                for k, sh in show.shows.items():
                    print(f"  {k:12} {sh.name}  sets: {', '.join(sh.sets)}  (default {sh.default_set})")
            elif cmd == "show" and ctl:
                ctl.select_show(rest[0], rest[1] if len(rest) > 1 else None)
                print(ctl.describe())
            elif cmd == "set" and ctl:
                ctl.select_set(rest[0])
                print(ctl.describe())
            elif cmd == "next" and ctl:
                ctl.next_step()
                print(ctl.describe())
            elif cmd == "now" and ctl:
                print(ctl.describe())
            elif cmd == "setlists" and show:
                for k, sl in show.setlists.items():
                    print(f"  {k:12} {sl.name} ({len(sl.songs)} songs)")
            elif cmd == "setlist" and ctl and show:
                ctl.load_setlist(rest[0])
                for i, sg in enumerate(show.setlists[rest[0]].songs):
                    print(f"  {'>' if i == ctl.song else ' '} {i + 1:2}. {sg.name}")
                print(ctl.describe())
            elif cmd == "song" and ctl:
                arg = rest[0] if rest else "next"
                {"next": ctl.next_song, "prev": ctl.prev_song}.get(arg, lambda: ctl.go_song(int(arg) - 1))()
                print(ctl.describe())
            elif cmd == "tap" and ctl:
                bpm = ctl.tap()
                print(f"{bpm:.0f} BPM" if bpm else "tap again")
            elif cmd == "tempo" and ctl:
                ctl.set_tempo(None if rest[0] == "off" else float(rest[0]))
                print(ctl.describe())
            elif cmd == "find":
                engine.find_fixture(None if rest[0] == "off" else rest[0])
                print(rig_view(engine))
            elif cmd == "chan":
                uni = int(rest[2]) if len(rest) > 2 else 0
                engine.test_channel(int(rest[0]), None if rest[1] == "off" else int(rest[1]), uni)
                print(f"channel {rest[0]} = {rest[1]}  (setup off to clear)")
            elif cmd == "setup" and rest and rest[0] == "off":
                engine.clear_setup()
                print("setup cleared")
            elif cmd == "addresses":
                print(format_report(*patch_report(engine.rig.patch, engine.rig)))
            elif cmd == "nodes":
                nodes = [d for d in engine.drivers if isinstance(d, NodeSerialDriver)]
                if not nodes:
                    print("no node output in use (third-party interfaces show as connected/disconnected only)")
                for d in nodes:
                    for r in d.link.health.nodes.values():
                        hb = r.heartbeat
                        sig = f"rssi {hb.rssi} loss {hb.loss_pct}%" if hb and hb.rssi is not None else ""
                        print(f"  {r.mac}  {r.state.value:7}  {r.name or '(new node)':16}  {sig}")
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
                st = store or ShowStore(map_path.parent.parent)  # validated, backed up, comments kept
                bid = st.put("midi", map_path.stem, router.map.to_dict(), f"save MIDI map {map_path.stem}")
                print(f"saved {map_path} (previous copy in backup {bid})")
            elif cmd == "status":
                for d in engine.drivers:
                    print(" ", d.status())
                print(f"  frames rendered {engine.frames_sent}, driver errors {engine.driver_errors}")
            else:
                print(f"unknown command {cmd!r}; type help")
        except (IndexError, ValueError, ConfigError) as e:
            print(f"error: {e}")


# --------------------------------------------------------------------------- commands


@dataclass
class Session:
    """A running engine with its MIDI inputs and web server (shared by the console and the desktop app)."""

    app: App
    show: object
    router: MidiRouter
    fake: FakeMidiIn
    web: object | None = None
    real: MidiInputs | None = None

    @property
    def engine(self) -> Engine:
        return self.app.engine

    def stop(self) -> None:
        if self.real:
            self.real.close()
        if self.web:
            self.web.stop()
        self.engine.stop()


def start_session(args: argparse.Namespace, out=print) -> Session:
    _, upgraded = ShowStore(args.shows).upgrade()  # older show files -> current format, originals backed up
    if upgraded:
        out(f"show files upgraded to the current format (originals in .backups): {', '.join(upgraded)}")
    problem = None
    try:
        show = load_show(args.shows, args.rig, args.look, args.midi)
    except ConfigError as e:  # a broken show file must not leave the rig dark: run the last good version
        fb = ShowStore(args.shows).last_good(lambda root: load_show(root, args.rig, args.look, args.midi),
                                            data_dir() / "last-good")
        if fb is None:
            raise
        show, bid = fb
        show.root = args.shows  # edits, restore and reload still go to the real folder
        problem = {"problem": str(e), "backup": bid}
        out(f"SHOW FILE PROBLEM: {e}")
        out(f"running the last good version (from before backup {bid}); fix it (dmx-suite check) or restore it, "
            "and the show reloads")
    if args.sim:
        drivers = [LogDriver()] + ([make_driver({"driver": "node_serial", "port": "sim"})] if args.sim_node else [])
    else:
        drivers = [make_driver(o) for o in show.rig.outputs]
    for d in drivers:  # rig config lists the nodes expected, so a missing one shows at setup
        if isinstance(d, NodeSerialDriver):
            d.link.health.expect(show.rig.nodes)
    state_path = None if args.sim else move_old_state(args.shows)  # app data, not the (OneDrive) show folder
    app = App(show, drivers, state_path, log_dir=log_dir(), rig=args.rig, look=args.look, midi=args.midi)
    app.show_problem = problem
    ctl, router = app.ctl, app.router
    resumed = False if args.fresh else ctl.restore()  # laptop restarted mid-gig: carry on
    if resumed:
        out("resumed:", ctl.describe())
    elif args.setlist:
        ctl.load_setlist(args.setlist)
    elif args.show:
        ctl.select_show(args.show, args.set)
    elif args.scene:
        ctl.select_scene(args.scene)
    session = Session(app, show, router, FakeMidiIn(router.handle_mido))
    try:
        if not args.no_web:
            from .web.server import WebServer

            session.web = WebServer(app, "0.0.0.0" if args.lan else "127.0.0.1", args.port)
            session.web.start()
            out(f"browser UI: http://localhost:{session.web.port}/")
            if args.lan:
                out(f"from a phone on the same network: http://<this laptop's IP>:{session.web.port}/?t={session.web.token}")
        if not args.sim:
            session.real = MidiInputs(args.midi_port or show.rig.midi_inputs or None, router.handle_mido)
            app.midi_inputs = session.real
            out("MIDI in:", ", ".join(session.real.open) or "none yet (plug in and it connects by itself)")
        session.engine.start()
    except BaseException:
        session.stop()
        raise
    return session


def cmd_run(args: argparse.Namespace) -> int:
    session = start_session(args)
    try:
        if not args.headless and (args.sim or sys.stdin.isatty()):
            console(session.engine, session.router, session.fake, session.show.midimap_path, session.show, session.app.ctl,
                    session.app.store)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    from .desktop import run_desktop

    return run_desktop(args)


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
    inputs = MidiInputs(args.midi_port or show.rig.midi_inputs or None, router.handle_mido)
    print(f"listening on: {', '.join(inputs.open) or 'none yet'}  (ctrl+c to stop; new ports connect by themselves)")
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
    ap.add_argument("--shows", type=Path, default=None, help="show folder (default: DMX_SUITE_SHOWS, else the app's own)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def show_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--rig", default="full")
        p.add_argument("--look", default="default")
        p.add_argument("--midi", default="default", help="MIDI map name")
        p.add_argument("--midi-port", action="append", help="MIDI input port (repeat; default all)")

    def run_args(p: argparse.ArgumentParser) -> None:
        show_args(p)
        p.add_argument("--sim", action="store_true", help="simulator: fake MIDI, log output, no hardware")
        p.add_argument("--sim-node", action="store_true", help="with --sim, also drive the simulated node")
        p.add_argument("--scene", help="scene to start with (default: the static look)")
        p.add_argument("--show", help="show to start with, e.g. band")
        p.add_argument("--set", help="set within the show, e.g. mid")
        p.add_argument("--setlist", help="start a setlist at song 1")
        p.add_argument("--fresh", action="store_true", help="don't resume what was playing before a restart")
        p.add_argument("--port", type=int, default=8505, help="browser UI port")
        p.add_argument("--lan", action="store_true", help="let phones on the network open the UI (needs the token link)")
        p.add_argument("--no-web", action="store_true", help="no browser UI")
        p.add_argument("--headless", action="store_true", help="no console; run until stopped (e.g. as a service)")

    p = sub.add_parser("run", help="run the engine (console)")
    run_args(p)
    p = sub.add_parser("app", help="desktop app: the lighting UI in its own window, with a tray icon")
    run_args(p)
    p.add_argument("--smoke-test", type=float, metavar="S", help=argparse.SUPPRESS)  # build check: quit after S s

    sub.add_parser("midi-ports", help="list MIDI inputs")
    p = sub.add_parser("midi-monitor", help="live MIDI list with what each message triggers")
    show_args(p)
    p.add_argument("--channel", type=int, help="only this channel (1-16)")

    sub.add_parser("check", help="validate show files")
    sub.add_parser("mcp", help="MCP server for Claude Desktop (stdio)")
    p = sub.add_parser("claude-setup", help="add the 0.05 tools to Claude Desktop's config")
    p.add_argument("--config", type=Path, help="config file (default: every Claude Desktop config found)")
    p = sub.add_parser("addresses", help="patch / address check")
    p.add_argument("--rig", default="full")
    p = sub.add_parser("import-ofl", help="fixture type YAML from an Open Fixture Library JSON file")
    p.add_argument("file", type=Path)
    p.add_argument("--mode", help="OFL mode name (needed if the fixture has several)")
    p.add_argument("--key", help="type key to use in fixtures.yaml")
    p.add_argument("--kind", choices=[k.value for k in Kind], help="override the guessed kind")
    return ap


def cmd_mcp(args: argparse.Namespace) -> int:
    import os

    os.environ.setdefault("DMX_SUITE_SHOWS", str(args.shows))
    from .mcp_server import main as mcp_main

    mcp_main()
    return 0


def cmd_claude_setup(args: argparse.Namespace) -> int:
    from .claude_setup import setup

    try:
        results = setup(args.shows.resolve(), [args.config] if args.config else None)
    except (OSError, ValueError) as e:
        print(f"couldn't update Claude Desktop config: {e}", file=sys.stderr)
        return 1
    for path, changed in results:
        print(f"{'updated' if changed else 'already set'}: {path}")
    print(f"show folder: {args.shows.resolve()}")
    print("restart Claude Desktop to load the 0.05 tools")
    return 0


def cmd_addresses(args: argparse.Namespace) -> int:
    from .fixtures import load_patch
    from .rig import load_rig

    patch = load_patch(args.shows / "fixtures.yaml")
    rig = load_rig(args.shows / "rigs" / f"{args.rig}.yaml", patch)
    print(format_report(*patch_report(patch, rig)))
    return 0


def cmd_import_ofl(args: argparse.Namespace) -> int:
    print(import_ofl(args.file, args.mode, args.key, args.kind), end="")
    return 0


def resolve_shows(args: argparse.Namespace) -> argparse.Namespace:
    """Fill in the show folder when --shows wasn't given (see paths.default_shows)."""
    args.shows = default_shows() if args.shows is None else prepare(args.shows)
    return args


def main(argv: list[str] | None = None) -> int:
    args = resolve_shows(build_parser().parse_args(argv))
    try:
        return {
            "run": cmd_run,
            "app": cmd_app,
            "midi-ports": cmd_midi_ports,
            "midi-monitor": cmd_midi_monitor,
            "check": cmd_check,
            "mcp": cmd_mcp,
            "claude-setup": cmd_claude_setup,
            "addresses": cmd_addresses,
            "import-ofl": cmd_import_ofl,
        }[args.cmd](args)
    except ConfigError as e:
        print(f"show file error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
