# Monitor, outputs and devices

## Monitor page

**Monitor** (System menu, or tap a DMX or MIDI tile in the status bar) watches what goes in and out. Watching changes nothing and works under gig lock; only the test patterns, the cycle test and Test send change what goes out (see below). Each pane has Pause, CSV and Full screen; the MIDI panes have Clear.

**DMX out.** Pick the universe and the interface. The pane shows the frame that interface really sent, after the grand master, sub-masters, MASTER and head limits:

- **Grid**: 512 channels with values and heat shading; hover for the light and channel (bar_2 red px5).
- **Per light**: each light's channels by name with a bar.
- **Changed**: only channels that moved in the last few seconds.
- **Hex**: the raw frame.

Above it: fps, frames, errors, jitter and the last frame. It says so in red when **no frames** go out on that universe, when frames go out but **every channel is 0**, or when frames stopped. *Engine (before outputs)* shows the engine's own frame instead, labelled.

For a **USB DMX (Open)** interface a second line shows the driver (VCP COM port or D2XX), the break method, and the break, MAB, fps, write time and jitter the laptop measured beside the targets. It turns amber when the break is under 88 µs, the MAB under 8 µs or the rate under 80 % of the target. These are timed on the laptop, best effort: an Open DMX interface has no processor, so what actually reached the DMX line can't be checked. Below it, any interface check that isn't passing, with its fix, and **Check now**.

### Test patterns

Straight to one universe (every interface carrying it) or one interface, bypassing scenes, the autopilot, Override, the grand master and MASTER. Head limits still apply, U'King heads stay home, the haze stays off and strobe channels stay off.

- **All full**: every light at full (tick *patched only* to leave unpatched channels at 0).
- **Fixture chase**: one light at a time at full white, its name shown large (seconds per light, default 2).
- **Find fixture**: one light flashes once a second; a moving head also nods.
- **Channel ramp**: one channel 0-255-0, or held at a value. Not the haze or a head's pan / tilt.
- **Keep-alive**: a fixed frame (all 0, or a value) sent continuously: do the lights stay in DMX mode with nothing in it?

A big **Stop test** brings the show's output back; so does leaving the Monitor page or the timeout (default 60 s). While a test runs the DMX pane says TEST and the status bar shows a TEST tile. Under gig lock only Keep-alive runs.

### Cycle break methods (USB DMX Open)

Pick the interface (*U0: Stage DMX only*) and **Cycle break methods**: All full runs on it while it tries each way of making the DMX break, 5 s each, the one running shown in large text: D2XX (only when FTDI's D2XX driver is installed), Serial break, Baud drop, then a long 500 µs break. Tap **Lights responded** when the lights come on: that method is saved to the output. No tap and the output goes back to what it had. Not under gig lock.

Each output can also be set by hand in the rig file or by Claude (`set_output`): `break_method` (`auto`, `d2xx`, `serial_break`, `baud_drop`), `break_us` (88-1000, default 176), `mab_us` (8-100, default 12), `fps` (default 40) and `channels` (512, or `patched` to send only up to the last patched channel).

### Interface checks

Every USB DMX (Open) interface is checked at start, when something is plugged in or out, when outputs change and every minute: driver (VCP or D2XX), **FTDI latency timer** (amber over 1 ms: Device Manager › Ports › COMx › Port Settings › Advanced › Latency Timer = 1; when the output runs on D2XX there's a **Set latency to 1 ms** button), the port held by another program (red, naming Daslight, QLC+ or FreeStyler when one is running), 250000 baud 8N2, **USB selective suspend** (amber: Windows can switch the interface off mid-gig) and the measured timing. A problem shows as a tile in the status bar with the reason and fix on hover, and in the routing table.

### Rig not responding

**Rig not responding** (DMX out pane, or tap a red or amber DMX tile in the status bar) walks the likely causes one at a time: one instruction, a **Run test** where there is one, and **Pass** (works now: stop here) or **Fail** (next likely cause).

1. The interface checks, automatically. A fail stops here with its fix.
2. **Are the lights in auto / sound / standalone mode?**
   - **Yes**: no valid DMX reaches them. Cycle break methods; a DMX cable straight to the first light (wireless out of the path); swap the lead and check a 5-pin to 3-pin adaptor (pins 2 and 3 not swapped); the lead in the first light's DMX IN, not THRU; the interface in QLC+ or FreeStyler (Daslight can't drive an Open DMX). Nothing works anywhere: suspect the interface.
   - **No**: DMX arrives. Pick the dark light. If the app is sending it 0 (MASTER off, blackout, grand master) it says so first. Then Find fixture; its start address (the patch value is shown); its channel mode; the IN/THRU order and a terminator on long runs; and the light's values in the live frame.

**Copy summary** copies what passed and where it stopped; it's also written to the log. Claude can run the same steps with you in chat (`fault_find`).

**MIDI in.** Each port with its state and a light that flickers on activity. Every event: time, port, channel, type, number and note name, velocity or value, the named input it matched (with its roles), and what it did, or *unmapped*. Filter by port, channel, type or unmapped only; MIDI clock is counted, not listed. A note heat map shows the last velocity per note (check drum pads), with hits a second, the clock rate and the autopilot's energy. **Learn** on an event makes a named input from it.

**MIDI out.** Everything the app sends, per port. Turn a port on in Setup > Plugged in (MIDI out); **Test send** sends a note, CC or program change (not under gig lock).

## Outputs: which universe goes where

Each output in the rig has a `universe:` (0-15):

```yaml
outputs:
  - {device: usb:0403:6001:A1B2C3, alias: Stage DMX, driver: usb_dmx_open, port: COM3, universe: 0}
  - {driver: usb_dmx_pro, port: COM4, universe: 0}    # a second interface mirroring U0
  - {driver: node, port: COM5}                         # the 0.05 node link: each wireless node has its own universe
```

An output with no `universe:` sends universe 0 and raises a warning until you confirm it. The routing table (Layout page, and Claude's `list_outputs`) shows universe, interface, state, fps, frames, errors and last frame for wired outputs and wireless nodes. Changes apply straight away: the outputs are rebuilt between frames, no restart.

Driver names say what the interface does: `usb_dmx_open` (FTDI "Open DMX" style), `usb_dmx_pro` (DMX USB Pro protocol), `node`, `artnet`, `sacn`. The old `enttec_open`, `enttec_pro` and `node_serial` still work.

## Devices

**Setup > Plugged in** lists what's connected, by the name each device reports: a USB DMX interface's product name (or "USB DMX interface (FTDI, SN A1B2C3)" when it only reports its chip), manufacturer, serial number, VID:PID and COM port; MIDI ports by the name Windows gives them. It updates as you plug and unplug.

Give a device your own name (**Stage DMX**, **Pedalboard**) and say what it's for: a DMX universe, MIDI in or MIDI out. A USB interface is kept by its serial number, so it keeps its universe when Windows gives it another COM number. One without a serial number is kept by its port (marked).

**A device has gone missing** (amber notice): pick a plugged-in one under it, **Use this instead**. Its universe, name and settings move to the new one at once. This works under gig lock, for mid-gig recovery; nothing else about outputs and devices does.

**A new device** (not used yet) raises a notice so you can assign it.
