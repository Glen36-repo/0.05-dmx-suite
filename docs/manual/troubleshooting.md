# Safety and troubleshooting

## Safety rules (always on)

- **No background glow:** a light that isn't part of the current look is fully off.
- **Haze** only comes from the Haze controls, never from scenes or shows.
- **Grand master** changes brightness only, never position or colour choice.
- **Moving-head limits** from the rig file are always kept to.

## Alerts and banners

When something drops out (a MIDI interface unplugged, a DMX output down, a node offline or weak, an engine fault) a banner appears over the top of the page and the laptop beeps. Banners lie over the page, so buttons never move under your finger.

- **✕** dismisses a banner. It stays hidden while the problem lasts and comes back only if the device recovers and then drops out again
- **10 min** hides it for ten minutes; the alerts list also has 1 hour and the rest of the gig
- banners clear by themselves when the problem is fixed
- **Critical** alerts (engine fault, a DMX output down, every output lost) can only be minimised (**–**) to the red bell while the fault lasts
- the **bell** shows how many alerts are open and opens the alerts list: time, device, message and state
- **Not using this today** mutes a device's alerts for this rig config (greyed in the status strip); switching rig clears it
- **Quiet** (in the alerts list): only critical alerts make banners; the rest go quietly to the list

Every alert is kept in the gig log (`logs/alerts-YYYY-MM-DD.jsonl` in app data), and Claude can read the list.

## When something goes wrong

| What you see | What it means | What to do |
| --- | --- | --- |
| The software runs but **the rig is dark** | | Monitor page, DMX out: **No frames** = nothing goes out that interface (check the routing table and the device); **every channel is 0** = MASTER, blackout, grand master or the look; values going out = the cable, the fixture's DMX mode or its address. See [Monitor](monitor.md). A USB DMX (Open DMX) interface can't report the DMX line itself: "ok" means the USB side is taking frames. Lights dropping to auto / sound mode = no valid DMX reaching them: use **Rig not responding** on the Monitor page, which runs the interface checks (latency timer 1 ms, port not held by another program, USB power saving off) and the break-method cycle test |
| A pedal or pad **does nothing** | | Monitor page, MIDI in: no event = the port or cable; *unmapped* = map the named input (Learn); an action listed = check what that action does |
| Amber **missing: Stage DMX (…)** | A USB interface the rig uses isn't plugged in | Plug it in, or Setup > Plugged in: **Use this instead** on another one (works under gig lock) |
| **Layout: … in the same place** | Lights share a spot, so spatial effects show them the same | Layout page: move them apart |
| Status bar: **Engine: fault** | Something in the current scene or show couldn't be drawn; the static look is on | Pick another scene or show; check the log |
| Status bar: **Show files: running the last good version** | A show file has a mistake; the version from before the last change is running | `dmx-suite check` names the file; fix it or restore it from the Files tab |
| "made by a newer 0.05 DMX Suite" | A show file was saved by a newer app | Update the app, or restore the file from `.backups` |
| An output or MIDI device "unplugged" | Cable or USB dropped | Plug it back in; it reconnects by itself (a new COM number doesn't matter: it's known by its serial number) |
| **Lost the connection to the lighting laptop** (phone or window) | Wi-Fi dropped, or the laptop is asleep | Nothing: the lights keep running and the screen reconnects by itself |
| Status bar: **Show file … read-only** | The `.dms` is open in the app on another computer | Close it there, or work on that computer |
| A "(recovered DD-MM-YYYY).dms" file appeared | The app stopped before a change reached the show file; the change was kept in that file | Open it if you want that change, or delete it |
| Status bar: **Show file: couldn't save** | The `.dms` couldn't be written (disk, OneDrive busy) | The change is kept on the laptop and saved with the next one; check the disk and OneDrive |
| A phone says **wrong PIN** then **wait** | Five wrong PINs in a row | Wait 30 s; the PIN is set on the laptop's Setup page |
| Status bar: **node firmware … is older** | The node runs firmware 0.1 | It still works; flash firmware 0.2 for fallback on every universe and the radio fixes (`firmware/README.md`) |
| Status bar: **development pairing key** | The node was built without the band's key | Rebuild and flash it with `PAIRING_KEY` set; until then, any other development build nearby can join |
| A receiver blinks purple | It lost the node and is looking on every radio channel | Wait about 15 s; if it doesn't find it, check the node is on and the pairing key matches |
| A receiver died mid-gig | | Switch on a spare; Setup page: **Replace with spare…** on the dead one. The spare takes its name and universe |

## Log file

`%LOCALAPPDATA%\0.05 DMX Suite\logs\dmx-suite.log` (the last five are kept).
