"""Several threads at once (engine, MIDI, OSC, web, node reader) must never trip over each other."""

import random
import threading
from pathlib import Path

from dmx_suite.app import App
from dmx_suite.fixtures import ConfigError
from dmx_suite.midi.monitor import MidiMonitor, MonitorEntry
from dmx_suite.node.health import HealthTracker
from dmx_suite.node.protocol import Heartbeat, NodeType
from dmx_suite.output import LogDriver
from dmx_suite.showfiles import load_show

SHOWS = Path(__file__).resolve().parents[1] / "shows"


def hammer(n_threads, fn, rounds=200):
    errors = []

    def run(seed):
        rng = random.Random(seed)
        try:
            for _ in range(rounds):
                fn(rng)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=run, args=(i,)) for i in range(n_threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    return errors


def test_show_control_from_many_threads():
    app = App(load_show(SHOWS, "full"), [LogDriver()])
    app.engine.start()
    ctl = app.ctl
    shows = list(app.files.shows)
    scenes = list(app.files.scenes)

    def poke(rng):
        r = rng.random()
        if r < 0.3:
            ctl.select_show(rng.choice(shows))
        elif r < 0.5:
            ctl.select_scene(rng.choice(scenes))
        elif r < 0.6:
            try:
                ctl.next_step()
            except ConfigError:
                pass  # a scene is playing, not a show: refused, as it should be
        elif r < 0.7:
            ctl.tap()
        else:
            ctl.describe()
            app.snapshot()

    try:
        assert hammer(8, poke) == []
        assert ctl.describe()  # still consistent afterwards
    finally:
        app.engine.stop()


def test_nodes_appear_while_the_ui_reads_them():
    h = HealthTracker()

    def beat(rng):
        mac = bytes([0xF4, 0x12, 0, 0, rng.randrange(256), rng.randrange(256)])
        h.update(Heartbeat(mac=mac, node_type=NodeType.DMX_RX, fw=(0, 1, 0), uptime_s=1, rssi=-50, loss_pct=0,
                           last_data_age_ms=10, universe=0, name=""))

    def read(rng):
        for r in h.records():
            _ = r.state
        h.alerts()
        h.tick()

    errors = []
    t1 = threading.Thread(target=lambda: errors.extend(hammer(4, beat, 500)))
    t2 = threading.Thread(target=lambda: errors.extend(hammer(4, read, 500)))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors == [] and len(h.records()) > 100


def test_monitor_reads_while_messages_arrive():
    m = MidiMonitor(size=300)

    def add(rng):
        m.add(MonitorEntry(0.0, "p", 10, "note", rng.randrange(128), 100, "x"))

    def read(rng):
        rows = m.since(rng.randrange(1000))
        assert all(a.seq < b.seq for a, b in zip(rows, rows[1:]))

    assert hammer(6, lambda rng: add(rng) if rng.random() < 0.6 else read(rng), 500) == []
