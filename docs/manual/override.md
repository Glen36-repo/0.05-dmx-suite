# Override

The **Override** page (called Busk before v4) is a panel of buttons and faders you lay out yourself, for playing the lights by hand on top of whatever show is running. Each show can have its own panel; `default` is used otherwise.

## Widgets

- **Colour**: turn lights a colour, on/off or only while held
- **Flash**: lights a colour while held
- **Solo**: only these lights while held, everything else dark
- **Effect**: add a scene's effect over the show, on/off
- **Go**: start a scene, or a show and set
- **Fader**: grand master, a sub-master, flash level or speed
- **Haze**: off, on/off, pulse or boost while held

The rules still apply: under the 0.05 band profile Override buttons only change colour (MASTER still owns on/off), lights not lit stay fully off, and solo leaves the kick light alone unless it's in the solo.

When you let go, the lights fade back to the show (the panel's release fade, 0.5 s by default). Lights held by a Override button get a dashed outline on the layout. **Release all** lets go of everything.

## Making a panel

1. Tick **Edit panels**.
2. Type a panel name (use a show's name to tie it to that show) and a title, then **New panel**.
3. Pick a widget type and **Add**; fill in its label, lights or groups, colour, scene or target.
4. Use ↑ ↓ to reorder and ✕ to remove.
5. **Save panels**.

## MIDI and OSC

Any widget can be played from a pedal, pad or OSC control: map it on the MIDI page with the action `override` (`Override` still works), the panel name and the widget's id. A fader widget takes a fader or knob.
