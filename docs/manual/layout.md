# Layout and patch

The **Layout** page is a full-width page for where the lights are on stage and on the DMX universes.

Across the top: the **universe** tabs (All, U0, U1 ...) filter everything below; a status strip says which interface sends that universe, its frames a second, frames sent, errors and the last frame; and **Save / Undo / Redo / Revert to saved** for the layout, with a dot when there are unsaved changes. **Print** and **PNG** make a patch sheet for load-in.

Two views: **Stage** and **Addresses**. Beside them: the fixture list and the outputs.

## Stage

Every light is drawn in its live colour. The view fits the rig (zoom to fit) and fits again when the patch changes; the wheel zooms round the pointer, the middle button or Space + drag pans, **Fit** (or 0) goes back to the whole rig.

- A pixel bar (LCB803) is one outlined object with its segments inside; bars end to end still show a gap.
- Names sit under each light and never overlap: crowded ones move down, use a short name (UK L) or get a leader line. Hover for the full id and type.
- The smoke machine isn't drawn among the lights; a box in the top right corner shows the haze level and state.
- Lights in the same place or touching are listed in red under the stage (tap a line to select both). Spread them out: spatial effects (spatial mapping, linear wave, radial, gradient, bars, noise, split) use where the lights are, so two lights in one place always show the same part of an effect. The same warning shows in the status bar, the alerts and the show check.

To arrange the lights:

1. Pick lights: tap (shift-tap to add), drag a box, **Lasso**, or a group tab. Ctrl+A all, Esc none.
2. **Move** and drag them.
3. The **ARRANGE** panel beside the stage, in groups of buttons:
   - **Align**: left, centre, right, top, middle, bottom (needs two or more; Alt + arrows).
   - **Distribute**: space evenly across or down (three or more).
   - **Shape**: make a row, ring or grid, with spacing and columns.
   - **Rotate**: turn by the step (45° unless you change it; R / Shift+R), set an exact angle, flip left-right (H) or front-back (V).
   - **Pixels** (bars only): pixels in a row, ring or grid (with columns), and reverse the pixel order for a bar mounted backwards.
   A button the selection can't use is greyed out and its tooltip says why.
4. **Save** (Ctrl+S) writes the layout to the rig file. **Undo** (Ctrl+Z), **Redo** (Ctrl+Shift+Z); **Revert to saved** throws away the changes after a confirm.

**Beams** shows where moving heads point; **Names** hides or shows the labels.

## Addresses

A 32 x 16 map of each universe's 512 channels: each light's channels shaded and labelled (name, start), free channels blank, overlapping channels red. Every channel shows the value going out now (0-255, brighter = higher), taken from what the chosen interface really sent (**Values from**). If the interface hasn't sent anything, the map says so and shows no values: that's the first check when the software runs but the rig is dark.

## Fixture list and outputs

The list shows each light's type, channel count, universe, address, channels, groups and the interface it goes out. Click a row to select it on the stage and in the address map. Change a universe or address in the list: clashes turn red and **Save addresses** stays off until they're fixed.

**Outputs** is the routing table: universe, interface, state, fps, frames, errors and last frame, for USB interfaces and wireless nodes alike, with problems underneath (a universe with lights but no output, an output for a universe with no lights, an output with no universe given).

## Groups

Groups are names for sets of lights (bars, front, movers); scenes and drum flashes use them.

- **New group from selection:** pick lights, type a name, press the button.
- **Set group to selection:** open the group's tab, change the selection, press the button.
- **Rename group:** every scene, step, look, rig and MIDI map using the old name changes with it (pixel selections on it too).
- **Delete group:** refused while a scene or MIDI map still uses it.

A group name can't be a light's name, a kind of light (head, bar, wash, kick, haze) or "all".

## Theme and button size

Setup page, **Appearance**: the theme (Neutral or 0.05) and **Button size**: Compact (the default) or Comfortable. Each laptop remembers its own choice. MASTER, BLACKOUT, haze boost, the mood buttons and pads stay big either way. Phones and touch tablets always get finger-sized controls (44 px, MASTER and BLACKOUT bigger still), whatever the laptop is set to.

On a phone the status strip is one chip (**All OK**, or how many need attention); tap it for every device. What's playing shows on its own line under MASTER. On the Live page **Hide stage / Show stage** folds the stage view away so shows, scenes and the setlist start at the top; each screen remembers it, and it starts folded on a phone.
