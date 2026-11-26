# Getting started

## Install

Run `0.05-DMX-Suite-Setup-<version>.exe`. It installs the app, asks where to keep your show folder (default `OneDrive\Music\0.05 DMX Suite\shows`), fills a new folder with starter shows, and can connect Claude Desktop (optional). Python isn't needed.

Open **0.05 DMX Suite** from the Start menu. The lights keep running when you close the window; quit from the tray icon.

## Try it without lights

The simulator runs everything with no DMX interface or MIDI devices:

```bash
dmx-suite run --sim
```

Type `help` at the `dmx>` prompt, or open http://localhost:8505/ for the screens.

## What's where

- **Show folder:** your fixtures, rigs, scenes, shows, setlists and MIDI maps, as plain text files. Back it up like any documents folder (OneDrive does this for you). Every change made in the app keeps the previous copy in `.backups`.
- **App data** (`%LOCALAPPDATA%\0.05 DMX Suite`): the log file and where the show was up to, for carrying on after a restart.

## Updates

```bash
dmx-suite update-check
```

It only checks; installing a new version is up to you. Show files from an older version are upgraded automatically the first time the new version runs, and the originals are kept in `.backups`.
