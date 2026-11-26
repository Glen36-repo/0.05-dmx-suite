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
