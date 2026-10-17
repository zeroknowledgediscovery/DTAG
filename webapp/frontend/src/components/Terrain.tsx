import { useEffect, useMemo, useRef, useState } from "react";
import type { Landscape as LandscapeData, LandscapeItem } from "../types";

/*
 * Decision landscape as terrain.
 *
 * Items sit on a fixed 2D map (server layout: topic regions, items the model links pulled together).
 * The surface is a kernel-smoothed field over that map:
 *   height = uncertainty of the predicted answers (1 - settled); answered items pin the floor,
 *   so settled opinions are valleys and each answer deepens the ground around it;
 *   colour = lean of the likely answers (blue L, red R, grey neutral; plain accent without poles),
 *   paler where the ground is high (undecided), fading out where there are no items.
 * Contours mark height levels. Items moved by the last answer get an expanding ring.
 */

const G = 84; // field grid (cells per side); the canvas is scaled up smoothly by the browser
const SIGMA = 0.034; // kernel width in map units
const MUTED = new Set(["Background", "Other"]);
const LEVELS = [0.2, 0.4, 0.6, 0.8];
const SHIFT_REF = 0.05;

type Pt = { x: number; y: number };

function hexRgb(v: string): [number, number, number] {
  const h = v.trim().replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const n = parseInt(full.slice(0, 6), 16);
  return Number.isFinite(n) ? [(n >> 16) & 255, (n >> 8) & 255, n & 255] : [128, 128, 128];
}
const mix = (a: number[], b: number[], t: number) => a.map((x, i) => x + (b[i] - x) * t);

/** Theme colours from CSS variables; re-read when <html data-theme> changes. */
function useThemeColours() {
  const read = () => {
    const cs = getComputedStyle(document.documentElement);
    const g = (n: string) => hexRgb(cs.getPropertyValue(n) || "#888888");
    return { l: g("--lean-l"), r: g("--lean-r"), ink: g("--terrain-ink"), plain: g("--accent"), surf: g("--panel") };
  };
  const [c, setC] = useState(read);
  useEffect(() => {
    const mo = new MutationObserver(() => setC(read()));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  return c;
}

/** Marching squares: line segments of the iso-level through a G x G grid (cell-centre coordinates). */
function contour(f: Float32Array, mask: Float32Array, level: number): string {
  let d = "";
  const v = (i: number, j: number) => f[j * G + i];
  const lerp = (a: number, b: number) => (level - a) / (b - a || 1e-9);
  for (let j = 0; j < G - 1; j++) {
    for (let i = 0; i < G - 1; i++) {
      if (mask[j * G + i] < 0.35) continue;
      const a = v(i, j), b = v(i + 1, j), c = v(i + 1, j + 1), e = v(i, j + 1);
      const idx = (a > level ? 8 : 0) | (b > level ? 4 : 0) | (c > level ? 2 : 0) | (e > level ? 1 : 0);
      if (idx === 0 || idx === 15) continue;
      const top = [i + lerp(a, b), j], right = [i + 1, j + lerp(b, c)];
      const bottom = [i + lerp(e, c), j + 1], left = [i, j + lerp(a, e)];
      const segs: number[][][] = {
        1: [[left, bottom]], 2: [[bottom, right]], 3: [[left, right]], 4: [[top, right]],
        5: [[left, top], [bottom, right]], 6: [[top, bottom]], 7: [[left, top]], 8: [[left, top]],
        9: [[top, bottom]], 10: [[left, bottom], [top, right]], 11: [[top, right]], 12: [[left, right]],
        13: [[bottom, right]], 14: [[left, bottom]],
      }[idx] as number[][][];
      for (const [p, q] of segs) d += `M${(p[0] + 0.5).toFixed(2)},${(p[1] + 0.5).toFixed(2)}L${(q[0] + 0.5).toFixed(2)},${(q[1] + 0.5).toFixed(2)}`;
    }
  }
  return d;
}

export function TerrainView({
  data,
  tip,
  anchoredTip,
}: {
  data: LandscapeData;
  tip: (it: LandscapeItem) => JSX.Element;
  anchoredTip: (a: LandscapeData["anchored"][number]) => JSX.Element;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const colours = useThemeColours();
  const [hover, setHover] = useState<{ x: number; y: number; key: string; html: JSX.Element } | null>(null);

  const field = useMemo(() => {
    const pts: Array<Pt & { h: number; w: number; t: number | null }> = [];
    const scale = data.lean_scale || 0;
    for (const it of data.items) {
      if (it.x === undefined || it.y === undefined) continue;
      const lean = it.l !== null && scale && !MUTED.has(it.t) ? Math.max(-1, Math.min(1, it.l / scale)) : null;
      pts.push({ x: it.x, y: it.y, h: 1 - it.s, w: MUTED.has(it.t) ? 0.5 : 1, t: lean });
    }
    for (const a of data.anchored) if (a.x !== undefined && a.y !== undefined) pts.push({ x: a.x, y: a.y, h: 0, w: 2, t: null });
    const H = new Float32Array(G * G), Lf = new Float32Array(G * G), D = new Float32Array(G * G), LW = new Float32Array(G * G);
    const r = Math.ceil(3 * SIGMA * G);
    for (const p of pts) {
      const ci = Math.floor(p.x * G), cj = Math.floor(p.y * G);
      for (let j = Math.max(0, cj - r); j <= Math.min(G - 1, cj + r); j++) {
        for (let i = Math.max(0, ci - r); i <= Math.min(G - 1, ci + r); i++) {
          const dx = (i + 0.5) / G - p.x, dy = (j + 0.5) / G - p.y;
          const k = p.w * Math.exp(-(dx * dx + dy * dy) / (2 * SIGMA * SIGMA));
          const n = j * G + i;
          H[n] += k * p.h;
          D[n] += k;
          if (p.t !== null) {
            Lf[n] += k * p.t;
            LW[n] += k;
          }
        }
      }
    }
    let lo = Infinity, hi = -Infinity;
    const mask = new Float32Array(G * G);
    for (let n = 0; n < G * G; n++) {
      mask[n] = 1 - Math.exp(-D[n] / 0.45);
      H[n] = D[n] > 1e-6 ? H[n] / D[n] : 1;
      Lf[n] = LW[n] > 1e-6 ? Lf[n] / LW[n] : 0;
      if (mask[n] > 0.35) {
        lo = Math.min(lo, H[n]);
        hi = Math.max(hi, H[n]);
      }
    }
    const span = hi > lo ? hi - lo : 1;
    for (let n = 0; n < G * G; n++) H[n] = Math.max(0, Math.min(1, (H[n] - lo) / span));
    // Smoothing shrinks the lean; scale colour by the field's own 90th percentile of |lean|.
    const absL = Array.from(Lf).filter((_, n) => mask[n] > 0.35).map(Math.abs).sort((a, b) => a - b);
    const lscale = absL.length ? absL[Math.floor(0.9 * (absL.length - 1))] || 1 : 1;
    return { H, Lf, lscale, mask, contours: LEVELS.map((lv) => contour(H, mask, lv)) };
  }, [data]);

  // Last drawn field, so each update morphs smoothly from what is on screen (live, not snapping).
  const shown = useRef<{ H: Float32Array; L: Float32Array; M: Float32Array } | null>(null);
  useEffect(() => {
    const cv = canvas.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const target = { H: field.H, L: new Float32Array(field.Lf.map((x) => Math.max(-1, Math.min(1, x / field.lscale)))), M: field.mask };
    const from = shown.current;
    const img = ctx.createImageData(G, G);
    const cur = { H: new Float32Array(G * G), L: new Float32Array(G * G), M: new Float32Array(G * G) };
    const draw = (k: number) => {
      for (let n = 0; n < G * G; n++) {
        const h = from ? from.H[n] + (target.H[n] - from.H[n]) * k : target.H[n];
        const t = from ? from.L[n] + (target.L[n] - from.L[n]) * k : target.L[n];
        const m = from ? from.M[n] + (target.M[n] - from.M[n]) * k : target.M[n];
        cur.H[n] = h;
        cur.L[n] = t;
        cur.M[n] = m;
        const base = data.has_lean ? mix(colours.ink, t >= 0 ? colours.r : colours.l, Math.abs(t)) : colours.plain;
        const c = mix(base, colours.surf, 0.08 + 0.84 * Math.pow(h, 0.8)); // valleys (settled) deep, high ground (undecided) pale
        img.data[n * 4] = c[0];
        img.data[n * 4 + 1] = c[1];
        img.data[n * 4 + 2] = c[2];
        img.data[n * 4 + 3] = Math.round(255 * m);
      }
      ctx.putImageData(img, 0, 0);
      shown.current = { H: cur.H.slice(), L: cur.L.slice(), M: cur.M.slice() };
    };
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!from || reduce) {
      draw(1);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / 600);
      draw(1 - Math.pow(1 - k, 3)); // ease-out
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [field, colours, data.has_lean]);

  const eps = data.shift_eps;
  const pendingSet = new Set(data.pending_items || []);
  const waiting = data.items.filter((it) => pendingSet.has(it.v) && it.x !== undefined);
  const moved = data.items.filter((it) => it.d !== null && it.d > eps && it.x !== undefined);
  const newPins = data.anchored.filter((a) => a.new && a.x !== undefined);
  const delay = (p: Pt) => {
    if (!newPins.length) return 0;
    const d = Math.min(...newPins.map((a) => Math.hypot(a.x! - p.x, a.y! - p.y)));
    return Math.min(1.2, d * 2);
  };

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const mx = (e.clientX - box.left) / box.width, my = (e.clientY - box.top) / box.height;
    const at = { x: e.clientX - box.left, y: e.clientY - box.top };
    let best: { d: number; key: string; html: JSX.Element } | null = null;
    for (const a of data.anchored) {
      if (a.x === undefined) continue;
      const d = Math.hypot(a.x - mx, a.y! - my) * 0.7; // pins win ties
      if (d < 0.03 && (!best || d < best.d)) best = { d, key: `pin-${a.v}`, html: anchoredTip(a) };
    }
    for (const it of data.items) {
      if (it.x === undefined) continue;
      const d = Math.hypot(it.x - mx, it.y! - my);
      if (d < 0.03 && (!best || d < best.d)) best = { d, key: it.v, html: tip(it) };
    }
    setHover(best ? { ...at, key: best.key, html: best.html } : null);
  };

  const hovered = hover && !hover.key.startsWith("pin-") ? data.items.find((it) => it.v === hover.key) : null;

  return (
    <div className="terrain" onMouseLeave={() => setHover(null)}>
      <canvas ref={canvas} width={G} height={G} className="terrain-field" />
      <svg viewBox="0 0 1 1" className="terrain-over" onMouseMove={onMove} role="img"
        aria-label={`Decision landscape map: ${data.items.length} predicted answers; ${moved.length} moved`}>
        <g transform={`scale(${1 / G})`}>
          {field.contours.map((d, i) => (
            <path key={i} d={d} className="terrain-contour" style={{ opacity: 0.12 + 0.07 * i }} />
          ))}
        </g>
        {Object.entries(data.topic_xy || {}).map(([t, [x, y]]) => (
          <text key={t} x={x} y={y} className={`terrain-tlab${MUTED.has(t) ? " muted" : ""}`} textAnchor="middle">
            {t.split(" & ")[0].split(" ")[0]}
          </text>
        ))}
        <g className="terrain-pending">
          {waiting.map((it) => (
            <circle key={it.v} cx={it.x} cy={it.y} r={0.007} style={{ animationDelay: `${delay({ x: it.x!, y: it.y! }).toFixed(2)}s` }} />
          ))}
        </g>
        <g key={`m-${data.step}`}>
          {moved.map((it) => {
            const r = 0.012 + 0.028 * Math.min(1, Math.sqrt(it.d! / SHIFT_REF));
            const style = { animationDelay: `${delay({ x: it.x!, y: it.y! }).toFixed(2)}s` };
            return (
              <g key={it.v}>
                <circle cx={it.x} cy={it.y} r={r} className="terrain-ring" style={style} />
                <circle cx={it.x} cy={it.y} r={0.006} className="terrain-moved" style={style} />
              </g>
            );
          })}
        </g>
        {data.anchored.map((a) =>
          a.x === undefined ? null : (
            <circle key={a.v} cx={a.x} cy={a.y} r={a.new ? 0.014 : 0.009} className={`terrain-pin${a.new ? " new" : ""}`} />
          )
        )}
        {hovered && <circle cx={hovered.x} cy={hovered.y} r={0.016} className="terrain-hover" />}
      </svg>
      {hover && (
        <div className="tooltip land-tip" style={{ left: Math.min(hover.x + 12, 110), top: hover.y + 14 }}>
          {hover.html}
        </div>
      )}
    </div>
  );
}
