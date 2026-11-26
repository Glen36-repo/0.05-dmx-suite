# Fixtures and rigs

## Fixtures

`fixtures.yaml` in the show folder lists each fixture type (its channels in order) and each light you have (type, DMX address, universe, groups). Import a type from the [Open Fixture Library](https://open-fixture-library.org):

```bash
dmx-suite import-ofl fixture.json --mode 11-channel --key mhl36
```

Check imported types against the fixture's manual: they start as `verified: false`. `dmx-suite addresses` shows the patch and any clashes.

The on-screen fixture editor and setup wizard are coming in v2 R7.

## Rigs

A rig file (`rigs/`) says which lights are there tonight, master levels, moving-head limits, haze settings, outputs and MIDI inputs. Shows adapt to the rig: effects for missing lights are skipped or moved.

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
