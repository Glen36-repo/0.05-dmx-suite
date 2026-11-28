## What and why

<!-- What this changes and the reason. Link the issue if there is one. -->

## Rules

- [ ] Doesn't let anything get around the safety rules or the rig's profile rules (`dmx_suite/rules.py`)
- [ ] Rule tests added or updated for anything that changes output (both profiles)

## Checks

- [ ] `ruff check dmx_suite tests installer`
- [ ] `mypy dmx_suite`
- [ ] `pytest`
- [ ] `pio run -d firmware` (if firmware changed)

## Docs

- [ ] `docs/SCOPE.md` decisions updated if a design choice changed
- [ ] `CHANGELOG.md` and the manual updated for user-visible changes
