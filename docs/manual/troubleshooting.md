# Safety and troubleshooting

## Safety rules (always on)

- **No background glow:** a light that isn't part of the current look is fully off.
- **Haze** only comes from the Haze controls, never from scenes or shows.
- **Grand master** changes brightness only, never position or colour choice.
- **Moving-head limits** from the rig file are always kept to.

## When something goes wrong

| What you see | What it means | What to do |
| --- | --- | --- |
| Status bar: **Engine: fault** | Something in the current scene or show couldn't be drawn; the static look is on | Pick another scene or show; check the log |
| Status bar: **Show files: running the last good version** | A show file has a mistake; the version from before the last change is running | `dmx-suite check` names the file; fix it or restore it from the Files tab |
| "made by a newer 0.05 DMX Suite" | A show file was saved by a newer app | Update the app, or restore the file from `.backups` |
| An output or MIDI device "unplugged" | Cable or USB dropped | Plug it back in; it reconnects by itself |
| **Lost the connection to the lighting laptop** (phone or window) | Wi-Fi dropped, or the laptop is asleep | Nothing: the lights keep running and the screen reconnects by itself |
| Status bar: **Show file … read-only** | The `.dms` is open in the app on another computer | Close it there, or work on that computer |
| A "(recovered DD-MM-YYYY).dms" file appeared | The app stopped before a change reached the show file; the change was kept in that file | Open it if you want that change, or delete it |
| Status bar: **Show file: couldn't save** | The `.dms` couldn't be written (disk, OneDrive busy) | The change is kept on the laptop and saved with the next one; check the disk and OneDrive |
| A phone says **wrong PIN** then **wait** | Five wrong PINs in a row | Wait 30 s; the PIN is set on the laptop's Setup page |

## Log file

`%LOCALAPPDATA%\0.05 DMX Suite\logs\dmx-suite.log` (the last five are kept).
