# Getting started

## Install

Run `0.05-DMX-Suite-Setup-<version>.exe`. It installs the app, asks where to keep your show file (default `OneDrive\Music\0.05 DMX Suite\0.05 shows.dms`), starts a new one from the starter shows, and can connect Claude Desktop (optional). Python isn't needed.

Open **0.05 DMX Suite** from the Start menu. The lights keep running when you close the window; quit from the tray icon.

## Try it without lights

The simulator runs everything with no DMX interface or MIDI devices:

```bash
dmx-suite run --sim
```

Type `help` at the `dmx>` prompt, or open http://localhost:8505/ for the screens.

## What's where

- **Show file (`.dms`):** your fixtures, rigs, scenes, shows, setlists, busk panels and MIDI maps in one file. Every change is saved into it straight away; back it up like any document (OneDrive does this for you). Double-click a `.dms` to open it. On the **Files** page: Open, Save as, New from starter show, Download / Upload (from a phone) and recent files, plus undo and redo for every change since the app started, and the backups. Older versions kept a show folder instead; that still works, and Files → Save as makes a `.dms` of it.
- **App data** (`%LOCALAPPDATA%\0.05 DMX Suite`): the log file and where the show was up to, for carrying on after a restart.

## Finding your way round

The menu on the left is grouped: **Perform** (Live, Ride, Busk), **Build** (Scenes, Shows, Review, Palettes), **Rig** (Layout, Fixtures, Heads, MIDI) and **System** (Setup, Files). ☰ folds it to icons. On a phone it's a bar along the bottom with Live, Ride, Busk, Scenes and Shows; **More** opens the rest. Folding sections (Addresses, the MIDI mapping table, the generator) stay as you last left them on that screen.

## Phones and the PIN

The app only answers the laptop until you allow phones. On the **Setup** page:

1. Type a PIN (4 or more characters) and **Save PIN**.
2. Tick **Phones and other computers can connect**.
3. On a phone on the same Wi-Fi, scan the QR code (or type the address) and sign in with the PIN.

A phone stays signed in until it's unused for 12 hours (changeable), the PIN changes, or phone access is turned off. Tick **Ask for the PIN on this computer too** to lock the laptop's screen as well.

## Updates

```bash
dmx-suite update-check
```

It only checks; installing a new version is up to you. Show files from an older version are upgraded automatically the first time the new version runs, and the originals are kept in `.backups`.

## Connect to Claude (optional)

Claude Desktop or Claude Code on the laptop can read and change your show in plain words ("make a slow blue scene with the heads on the kit", "five moody scenes for the slow songs"). Everything Claude changes is checked against the rules like your own changes, backed up and undoable, and gig lock stops it.

On the **Setup** page, **Connect to Claude** shows a checklist for a new laptop:

1. Install 0.05 DMX Suite (the Claude tools come with it)
2. Install Claude Desktop or Claude Code and open it once
3. Press **Connect**
4. Restart Claude: 0.05 DMX Suite then shows in its connectors list

Under the checklist, each Claude app on the laptop says whether it's connected to this show. **Update** points it at the show you have open now; **Disconnect** takes the 0.05 tools out again. Your other Claude settings are kept, and the previous settings file is saved next to it as `.bak`. The **Claude** light in the status strip shows whether Claude is connected and when it last checked in; tap it to open this section. Once Claude is connected the section is folded; tap its heading to open it. Connecting can only be done on the laptop itself, not from a phone, and Claude can't connect or disconnect itself.

The installer's Claude option and `dmx-suite claude-setup` connect Claude Desktop the same way.

