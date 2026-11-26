# Contributing

Thanks for helping. 0.05 DMX Suite runs lights at live shows, so changes have to be safe first.

## Before you start

- Read `docs/SCOPE.md` (requirements and every design decision) and `CLAUDE.md` (rules and conventions).
- For anything bigger than a small fix, open an issue first so the approach can be agreed.

## The rules come first

The rule layer (`dmx_suite/rules.py`) enforces the safety rules for everyone and the profile rules per rig. A change must never let a scene, effect, MIDI/OSC input or the UI get around them. Every rule has tests under both shipped profiles ("generic" and "0.05 band"); a change that touches output adds or updates those tests.

## Setting up

```bash
pip install -e .[dev]
```

Everything runs without hardware in simulator mode:

```bash
dmx-suite run --sim
```

## Checks (CI runs the same)

```bash
ruff check dmx_suite tests installer
```

```bash
mypy dmx_suite
```

```bash
pytest
```

Firmware must compile:

```bash
pio run -d firmware
```

## Changes

- One feature or fix per pull request, small commits, each with tests.
- Show file format changes: bump `FORMAT` in `dmx_suite/versions.py` and add an upgrade step, with a test that loads the old format.
- A design change updates the decisions table in `docs/SCOPE.md`; user-visible changes go in `CHANGELOG.md` and the manual (`docs/manual/`).
- Australian English in UI text and docs. Metric units. Dates DD/MM/YYYY.
- No telemetry, and no network access the user didn't ask for.

## Licence

By contributing you agree your work is released under the MIT licence (`LICENSE`).
