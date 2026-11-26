# Colours and palettes

## The colour wheel

Wherever you pick a colour (scene builder, Override colour buttons, the Palettes page), the **◐** button opens the colour wheel:

- the wheel sets hue and saturation; the slider sets brightness; type a hex value or RGB 0-255 if you know it
- **White**, **Amber** and **UV** sliders appear when the lights you're colouring have those emitters
- **White temperature**: candle and incandescent through to daylight, for warm looks like the opera show
- swatches: your recent colours, the show's named colours and its palettes
- **Pick from a light** takes the colour a light is showing now
- **What the lights make** shows what each light can really do with the colour; a light with a colour wheel snaps to the nearest slot, marked in yellow
- **Show it on the rig while picking** plays it on the chosen lights as you go (not during gig lock)

## Named colours

Named colours (e.g. `band_red`, `incandescent`) are kept in `palettes.yaml`. Scenes use them by name, so changing a named colour changes every scene that uses it; renaming one renames it everywhere. A colour that's still used can't be deleted: you're told where.

## Palettes

A palette is a set of colours with tags. Seven come built in (Warm, Cool, Fire, Ice, Neon, White, Band colours); one of yours with the same name replaces it. Tags like `warm`, `cool`, `low`, `mid`, `high` let the Autopilot page and auto show (from v3.3) pick a palette that suits the mood.

On the **Palettes** page:

- **New palette**, then **Edit** to add, change, reorder (‹) and remove colours, set its name and tags
- **Generate** builds a palette from its first colour by colour theory: analogous (neighbours), complementary (opposites), triadic (three apart), split complementary, monochrome
- **Preview** shows it on the rig, one colour per light; **Preview chase** runs through it
- **Duplicate**, **Rename**, **Export** (a small file to share) and **Import…**

```yaml
palettes:
  verse: {name: Verse, tags: [cool, low], colours: [deep_blue, "#0090ff", "#7a40ff"]}
```
