# Layout and patch

The **Layout** page is a full-width page for where the lights are on stage. Universes, addresses, groups, the address map and the routing table are on the [Fixtures](fixtures.md#the-fixtures-page) page (v7: one place for them).

Across the top: the **universe** tabs (All, U0, U1 ...) filter the stage and the list; a status strip says which interface sends that universe, its frames a second, frames sent, errors and the last frame; and **Save / Undo / Redo / Revert to saved** for the layout, with a dot when there are unsaved changes. **PNG** makes a patch sheet (stage and address map) for load-in.

The stage takes the width; beside it a narrow list of the lights.

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

## Fixture list

Each light's name and type. Tap a row to select it on the stage. **Find** lights it full white; **Test** flashes it and nods a moving head (tap again to stop). To change a light's universe, address or groups, use the [Fixtures](fixtures.md#the-fixtures-page) page.

## Groups

Groups are names for sets of lights (bars, front, movers); scenes and drum flashes use them. On the stage, groups are made from a selection; on the Fixtures page, each light's **Groups** has a tick per group.

- **New group from selection:** pick lights, type a name, press the button.
- **Set group to selection:** open the group's tab, change the selection, press the button.
- **Rename group:** every scene, step, look, rig and MIDI map using the old name changes with it (pixel selections on it too).
- **Delete group:** refused while a scene or MIDI map still uses it.

A group name can't be a light's name, a kind of light (head, bar, wash, kick, haze) or "all".

## Theme and button size

Setup page, **Appearance**: the theme (Neutral or 0.05) and **Button size**: Compact (the default) or Comfortable. Each laptop remembers its own choice. MASTER, BLACKOUT, haze boost, the mood buttons and pads stay big either way. Phones and touch tablets always get finger-sized controls (44 px, MASTER and BLACKOUT bigger still), whatever the laptop is set to.

**Motion** (Setup, Appearance, per screen): *Follow this device* uses the computer's or phone's "reduce motion" setting; *Reduce* stops beat pulses, activity glows and fades on this screen; *Full* keeps them. The stage view still shows every light's state either way.

On a phone the status strip is one chip (**All OK**, or how many need attention); tap it for every device. What's playing shows on its own line under MASTER. On the Live page **Hide stage / Show stage** folds the stage view away so shows, scenes and the setlist start at the top; each screen remembers it, and it starts folded on a phone.
