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

## Log file

`%LOCALAPPDATA%\0.05 DMX Suite\logs\dmx-suite.log` (the last five are kept).
