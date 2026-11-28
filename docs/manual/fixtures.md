# Fixtures and rigs

## Setup wizard

The first time the app opens on a laptop, the setup wizard walks through:

1. **How your lights connect:** it spots a 0.05 node, an Enttec DMX USB Pro or an Enttec Open DMX cable when plugged in; or pick Art-Net, sACN, or no interface yet (simulator).
2. **Which lights you have:** how many of each type; they get free DMX addresses in order.
3. **How MASTER works:** Generic (most rigs) or the 0.05 band rules.
4. **A starter show** made for your lights, playing straight away.
5. **A PIN** for phones (optional).

Every step can be skipped. Run it again any time from the Setup page.

## The Fixtures page

**Patch:** every light, its type, DMX universe and start address, groups and the sub-master it follows. This is the one place universes, addresses and groups are changed (v7).

- Type a **Universe** (0-15) and **Address** (1-512); the channels it uses show beside it (e.g. 33-48).
- Addresses that overlap or run past 512 are marked red, and the patch can't be saved until they're fixed.
- **Groups**: tick the groups a light is in, or **+ New group**. A group left with no lights is flagged: if a scene or MIDI map uses it, you're told which and saving is refused until you give it a light or change them; an unused one just goes when you save.
- **Add lights** of a type (several at once); they go on the next free addresses.
- **Auto-patch** gives every light the next free addresses in list order.
- **Find** lights just that one light so you can see which it is.
- ✕ removes a light from the patch and from every rig. If a scene names it directly, you're told which; change the scene first.

### Addresses

**Address map and routing** (folded under the patch, opens where you left it) is a 32 x 16 map of each universe's 512 channels: each light's channels shaded and labelled (name, start), free channels blank, overlapping channels red. Every channel shows the value going out now (0-255, brighter = higher), taken from what the chosen interface really sent (**Values from**). If the interface hasn't sent anything, the map says so and shows no values: that's the first check when the software runs but the rig is dark. **Print** prints it for load-in.

**Outputs** under it is the routing table: universe, interface, state, fps, frames, errors and last frame, for USB interfaces and wireless nodes alike, with problems underneath (a universe with lights but no output, an output for a universe with no lights, an output with no universe given).

**Fixture types:** the channel list of each kind of light. Set each channel's role, its default value, which pixel it belongs to (bars) and whether it runs backwards (invert).

- **Test on** picks a patched light of that type and gives every channel a slider; double-click a slider to let go.
- **Colour mixing auto** makes colours from what the light has: white (and amber) are mixed in from the colour, a white-only or dimmer-only light follows the colour's brightness, and a colour-wheel light goes to the nearest wheel slot. Types from before this version are set to **off** (colours sent as written) so your shows look the same.
- **Colour wheel slots** and **gobo slots** give names to wheel positions, so scenes can say `colour_wheel: red` or `gobo: dots`.
- **Import from Open Fixture Library…** reads a fixture file from [open-fixture-library.org](https://open-fixture-library.org); colour and gobo wheels and pixel layouts come across. Check it against the manual, tick **Checked on the real light**, then save.
- **Export (OFL)** saves a type as an Open Fixture Library file to share.

Channel roles: dimmer, red, green, blue, white, amber, uv, pan, tilt, pt_speed, colour_wheel, gobo, strobe, zoom, focus, frost, prism, haze, fixed. A `_fine` channel after dimmer, pan, tilt, zoom or focus makes it 16-bit.

From the command line:

```bash
dmx-suite import-ofl fixture.json --mode 11-channel --key mhl36
dmx-suite export-ofl mhl36 -o mhl36.json
```

## Rigs

A rig (`rigs/`) says which lights are there tonight and how they're run. On the **Rig settings** tab:

- rule profile, master levels and fades
- which lights are in this rig
- moving-head limits
- haze, tempo source
- DMX outputs, MIDI inputs, OSC port

Changes apply straight away, except outputs, MIDI inputs and OSC, which apply after a restart. **Run this rig** switches to another rig (say, a small one for acoustic gigs) without stopping. Shows adapt to the rig: effects for missing lights are skipped or moved.

## Rule profiles

Each rig picks how the rules work with `profile:`:

| Profile | MASTER | Scenes | Drum flash |
| --- | --- | --- | --- |
| `generic` | No on/off role | Set colour and `intensity` (0-1) | Off |
| `0.05_band` | Owns on/off; scenes are colour only | Colour only | On while MASTER is off |

Change single settings with a block:

```yaml
profile:
  base: 0.05_band
  master_exempt: [kick]   # lights MASTER never affects
```

The safety rules apply under every profile (see [Safety and troubleshooting](troubleshooting.md)).

## Haze settings

The Live page's HAZE section has **Haze settings** (fold it open). It shows which rig you're editing and has a block per mode:

- **Manual**: the level (%).
- **Pulse**: its own pulse level, how long each puff lasts and how often (with the duty: "1 s every 61 s ≈ 2 %").
- **Boost**: the boost level, how long a press lasts (0 = while the footswitch is held) and the cooldown before the next one.
- **Safety**: the longest the machine may run without a break, the rest after it, switching off after a number of minutes, and the mode at start.

Changes apply straight away; **Save to rig** writes them to the rig file's `haze:` block, **Revert** goes back to what's saved. **Test** runs one cycle of a mode now (max on and rest still apply; not under gig lock).

Named **haze presets** (e.g. Haze 4 Med = manual 41 %) go in the rig file and are picked from the list next to the haze buttons or from MIDI (`haze_preset`):

```yaml
haze:
  level: 41
  pulse_level: 30
  pulse_on_s: 1
  pulse_every_s: 61
  presets:
    - {name: Haze 4 Med, mode: manual, level: 41}
```

This only sets up the haze controller: scenes and shows still never set haze.
