# Monitor, outputs and devices

## Monitor page

**Monitor** (System menu, or tap a DMX or MIDI tile in the status bar) watches what goes in and out. It only watches: nothing on it changes the lights, and it works under gig lock. Each pane has Pause, CSV and Full screen; the MIDI panes have Clear.

**DMX out.** Pick the universe and the interface. The pane shows the frame that interface really sent, after the grand master, sub-masters, MASTER and head limits:

- **Grid**: 512 channels with values and heat shading; hover for the light and channel (bar_2 red px5).
- **Per light**: each light's channels by name with a bar.
- **Changed**: only channels that moved in the last few seconds.
- **Hex**: the raw frame.

Above it: fps, frames, errors, jitter and the last frame. It says so in red when **no frames** go out on that universe, when frames go out but **every channel is 0**, or when frames stopped. *Engine (before outputs)* shows the engine's own frame instead, labelled.

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
