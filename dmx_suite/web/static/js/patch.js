// Patch helpers shared by the Fixtures page and the Layout/Patch page (v4): channel counts, address
// clashes and next free addresses. Rows are fixtures.yaml entries: {id, type, universe, address, groups}.

export const footprintOf = (types, type) => (types?.[type]?.channels || []).length;

// ids whose channels overlap another light's (or run past 512)
export function clashes(rows, types) {
  const out = new Set();
  const used = new Map();
  for (const f of rows) {
    const n = footprintOf(types, f.type);
    const u = +f.universe || 0;
    if (!n || !f.address) continue;
    if (f.address < 1 || f.address + n - 1 > 512) out.add(f.id);
    for (let c = f.address; c < f.address + n; c++) {
      const k = `${u}:${c}`;
      if (used.has(k)) { out.add(f.id); out.add(used.get(k)); }
      else used.set(k, f.id);
    }
  }
  return out;
}

// next free addresses, in patch order, for the rows that need one (or all)
export function autoPatch(rows, types, all = false) {
  const size = (r) => footprintOf(types, r.type);
  const taken = new Map(); // universe -> list of [start, end]
  const fits = (u, a, n) => a >= 1 && a + n - 1 <= 512 && !(taken.get(u) || []).some(([s, e]) => a <= e && a + n - 1 >= s);
  const place = (u, a, n) => { if (!taken.has(u)) taken.set(u, []); taken.get(u).push([a, a + n - 1]); };
  const keep = all ? [] : rows.filter((r) => r.address && fits(+r.universe || 0, r.address, size(r)));
  for (const r of keep) place(+r.universe || 0, r.address, size(r));
  for (const r of rows) {
    if (keep.includes(r)) continue;
    const n = size(r);
    let u = +r.universe || 0;
    let a = 1;
    while (!fits(u, a, n)) {
      a += 1;
      if (a + n - 1 > 512) { u += 1; a = 1; }
      if (u > 15) break;
    }
    r.universe = u;
    r.address = a;
    place(u, a, n);
  }
  return rows;
}

// channel -> fixture id per universe, with overlapping channels listed: {u: {cells: [512 x [ids]], blocks: [...]}}
export function addressMap(rows, types, universe) {
  const cells = Array.from({ length: 512 }, () => []);
  const blocks = [];
  for (const f of rows) {
    if ((+f.universe || 0) !== universe || !f.address) continue;
    const n = footprintOf(types, f.type);
    blocks.push({ id: f.id, type: f.type, start: f.address, end: f.address + n - 1 });
    for (let c = f.address; c < f.address + n && c <= 512; c++) cells[c - 1].push(f.id);
  }
  return { cells, blocks: blocks.sort((a, b) => a.start - b.start) };
}
