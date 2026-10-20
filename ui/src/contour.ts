export type Pt = readonly [number, number];

/**
 * Iso-lines of a scalar field sampled at grid cell centres (marching squares, linear interpolation).
 * values[i][j] is column i, row j; "inside" means value > level. Saddles are resolved by the mean of
 * the four corners. Returns polylines in grid units (closed loops repeat their first point).
 */
export function isolines(values: number[][], level: number): Pt[][] {
  const nx = values.length;
  const ny = values[0]?.length ?? 0;
  const segs: [Pt, Pt][] = [];
  const at = (a: number, b: number) => (level - a) / (b - a);
  for (let i = 0; i < nx - 1; i++) {
    for (let j = 0; j < ny - 1; j++) {
      const v0 = values[i][j], v1 = values[i + 1][j], v2 = values[i + 1][j + 1], v3 = values[i][j + 1];
      if (![v0, v1, v2, v3].every(Number.isFinite)) continue;
      const idx = (v0 > level ? 1 : 0) | (v1 > level ? 2 : 0) | (v2 > level ? 4 : 0) | (v3 > level ? 8 : 0);
      if (idx === 0 || idx === 15) continue;
      const e = {
        b: [i + at(v0, v1), j] as Pt,
        r: [i + 1, j + at(v1, v2)] as Pt,
        t: [i + at(v3, v2), j + 1] as Pt,
        l: [i, j + at(v0, v3)] as Pt,
      };
      const add = (p: keyof typeof e, q: keyof typeof e) => segs.push([e[p], e[q]]);
      switch (idx) {
        case 1: case 14: add("l", "b"); break;
        case 2: case 13: add("b", "r"); break;
        case 3: case 12: add("l", "r"); break;
        case 4: case 11: add("r", "t"); break;
        case 6: case 9: add("b", "t"); break;
        case 7: case 8: add("l", "t"); break;
        default: {
          const centre = (v0 + v1 + v2 + v3) / 4 > level;
          if ((idx === 5) === centre) { add("l", "t"); add("b", "r"); } else { add("l", "b"); add("r", "t"); }
        }
      }
    }
  }
  return join(segs);
}

/** Chaikin corner cutting for display; open lines keep their endpoints, closed loops stay closed. */
export function smooth(line: readonly Pt[], iterations = 2): Pt[] {
  let p = [...line];
  const closed = p.length > 3 && p[0][0] === p[p.length - 1][0] && p[0][1] === p[p.length - 1][1];
  for (let k = 0; k < iterations && p.length > 2; k++) {
    const q: Pt[] = closed ? [] : [p[0]];
    for (let i = 0; i < p.length - 1; i++) {
      const [a, b] = [p[i], p[i + 1]];
      q.push([0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]], [0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]]);
    }
    q.push(closed ? q[0] : p[p.length - 1]);
    p = q;
  }
  return p;
}

/** Outline of a set of grid cells along cell edges, as segments in grid units (cell i spans [i, i+1]). */
export function cellOutline(inside: boolean[][]): [Pt, Pt][] {
  const nx = inside.length, ny = inside[0]?.length ?? 0;
  const out: [Pt, Pt][] = [];
  const at = (i: number, j: number) => i >= 0 && j >= 0 && i < nx && j < ny && inside[i][j];
  for (let i = 0; i < nx; i++) {
    for (let j = 0; j < ny; j++) {
      if (!inside[i][j]) continue;
      if (i > 0 && !at(i - 1, j)) out.push([[i, j], [i, j + 1]]);
      if (i < nx - 1 && !at(i + 1, j)) out.push([[i + 1, j], [i + 1, j + 1]]);
      if (j > 0 && !at(i, j - 1)) out.push([[i, j], [i + 1, j]]);
      if (j < ny - 1 && !at(i, j + 1)) out.push([[i, j + 1], [i + 1, j + 1]]);
    }
  }
  return out;
}

function join(segs: [Pt, Pt][]): Pt[][] {
  const key = (p: Pt) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`;
  const ends = new Map<string, number[]>();
  segs.forEach(([a, b], k) => {
    for (const p of [a, b]) {
      const s = key(p);
      const list = ends.get(s);
      if (list) list.push(k); else ends.set(s, [k]);
    }
  });
  const used = new Uint8Array(segs.length);
  const lines: Pt[][] = [];
  for (let k = 0; k < segs.length; k++) {
    if (used[k]) continue;
    used[k] = 1;
    const line: Pt[] = [segs[k][0], segs[k][1]];
    for (const forward of [true, false]) {
      for (;;) {
        const end = forward ? line[line.length - 1] : line[0];
        const n = (ends.get(key(end)) ?? []).find((s) => !used[s]);
        if (n === undefined) break;
        used[n] = 1;
        const [a, b] = segs[n];
        const p = key(a) === key(end) ? b : a;
        if (forward) line.push(p); else line.unshift(p);
      }
    }
    lines.push(line);
  }
  return lines;
}
