// Copy and paste a look between lights (scene builder). A copied look is a layer's settings
// without its lights; pasting it onto a selection makes one layer per kind of light in the
// selection, keeping only what each kind can do: position and movement only on heads that move,
// gobo and colour wheel only where fitted. Colours are copied as they are (RGB) until fixtures
// learn colour mixing (R7).

const NOT_A_LOOK = ["fixtures", "fallback", "mute", "name"];
const MOVE_KEYS = ["position", "speed"]; // speed = pan/tilt speed
const KEEP_WITH_EFFECT = ["colour", "colours", "pixels"]; // still useful if a movement effect is dropped
const SPREAD_KEYS = ["mapping", "direction", "angle", "groups_of", "spread", "period_s", "rate_hz", "beats"];

export function copyLook(layer) {
  const look = structuredClone(layer);
  for (const k of NOT_A_LOOK) delete look[k];
  return look;
}

// the layer (later layers win) that sets the look of light `id`, or null
export function layerFor(layers, id, expand) {
  for (let i = layers.length - 1; i >= 0; i--) if (!layers[i].mute && expand(layers[i].fixtures || []).includes(id)) return layers[i];
  return null;
}

function trim(look, can, effects) {
  const out = structuredClone(look);
  const fx = out.effect ? effects.find((e) => e.name === out.effect) : null;
  if (fx?.movement && !can.moves) {
    for (const p of fx.params) if (!KEEP_WITH_EFFECT.includes(p.key)) delete out[p.key];
    for (const k of SPREAD_KEYS) delete out[k];
    delete out.effect;
  }
  if (!can.moves) for (const k of MOVE_KEYS) delete out[k];
  if (!can.gobo) delete out.gobo;
  if (!can.wheel) delete out.colour_wheel;
  const settings = Object.keys(out).filter((k) => !["level", "blend"].includes(k));
  return settings.length ? out : null;
}

// layers for pasting `look` onto the lights `ids`; `names` is how to write the whole selection
// (e.g. a group name) when every light takes the full look
export function pasteLayers(look, ids, names, fixtures, effects) {
  const byId = Object.fromEntries(fixtures.map((f) => [f.id, f]));
  const kinds = new Map();
  for (const id of ids) {
    const f = byId[id];
    if (!f) continue;
    const can = { moves: !!f.moves, gobo: !!f.gobo, wheel: !!f.wheel };
    const k = JSON.stringify(can);
    if (!kinds.has(k)) kinds.set(k, { can, ids: [] });
    kinds.get(k).ids.push(id);
  }
  const out = [];
  for (const { can, ids: group } of kinds.values()) {
    const body = trim(look, can, effects);
    if (!body) continue;
    out.push({ fixtures: kinds.size === 1 ? names : group, ...body });
  }
  return out;
}
