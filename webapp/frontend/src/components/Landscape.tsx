import { useMemo, useRef, useState } from "react";
import { fmtNum } from "../api";
import type { Landscape as LandscapeData, LandscapeItem } from "../types";

/*
 * Decision landscape doughnut.
 *
 * Outer ring: one thin wedge per askable item, grouped into topic arcs. Wedge length = how settled
 * the twin's predicted answer is (1 - normalized entropy); colour = lean (blue toward the L pole,
 * red toward R, grey neutral or no poles). Items moved by the last interaction(s) pulse, with a
 * delay that grows with angular distance from the newly answered item(s): a ripple.
 * Inner ring: answered (anchored) items as beads in their topic's arc; new ones are larger.
 */

const SIZE = 340;
const C = SIZE / 2;
const R0 = 76; // wedge base
const R1 = 126; // wedge max
const RB = 60; // anchored bead ring
const RT = 70; // topic band
const RL = 150; // topic labels
const PADX = 26; // horizontal room for side labels
const GAP = 4.5; // degrees between topic arcs
const SHORT: Record<string, string> = {
  "Trust & confidence": "Trust",
  "Abortion & sexuality": "Sexuality",
  Religion: "Religion",
  "Race & immigration": "Race",
  "Family & gender": "Family",
  "Government & spending": "Govt",
  "Politics & civil liberties": "Politics",
  "Science & environment": "Science",
  "Work & economy": "Work",
  "Health & wellbeing": "Health",
  "Social life & media": "Social",
  Other: "Other",
  Background: "Backgr.",
};
const MUTED = new Set(["Background", "Other"]);
const WEIGHT = (t: string) => (MUTED.has(t) ? 0.45 : 1);
const SHIFT_REF = 0.05; // bits; spike length reference

const rad = (deg: number) => ((deg - 90) * Math.PI) / 180;
const pt = (r: number, deg: number) => [C + r * Math.cos(rad(deg)), C + r * Math.sin(rad(deg))];

function wedge(r0: number, r1: number, a0: number, a1: number): string {
  const [x0, y0] = pt(r0, a0);
  const [x1, y1] = pt(r1, a0);
  const [x2, y2] = pt(r1, a1);
  const [x3, y3] = pt(r0, a1);
  const large = a1 - a0 > 180 ? 1 : 0;
  return `M${x0.toFixed(2)},${y0.toFixed(2)}L${x1.toFixed(2)},${y1.toFixed(2)}A${r1},${r1} 0 ${large} 1 ${x2.toFixed(2)},${y2.toFixed(2)}L${x3.toFixed(2)},${y3.toFixed(2)}A${r0},${r0} 0 ${large} 0 ${x0.toFixed(2)},${y0.toFixed(2)}Z`;
}

function arc(r: number, a0: number, a1: number): string {
  const [x0, y0] = pt(r, a0);
  const [x1, y1] = pt(r, a1);
  return `M${x0.toFixed(2)},${y0.toFixed(2)}A${r},${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)},${y1.toFixed(2)}`;
}

function leanFill(it: LandscapeItem, scale: number | null): string {
  if (MUTED.has(it.t)) return "var(--land-muted)";
  if (it.l === null || !scale) return "var(--land-plain)";
  const t = Math.max(-1, Math.min(1, it.l / scale));
  const pct = Math.round(Math.abs(t) * 100);
  return `color-mix(in oklab, var(${t >= 0 ? "--lean-r" : "--lean-l"}) ${pct}%, var(--lean-mid))`;
}

type Hover = { x: number; y: number; key: string; html: JSX.Element };

export function LandscapeView({ data, loading }: { data: LandscapeData | null; loading: boolean }) {
  const [hover, setHover] = useState<Hover | null>(null);
  // Wedge order within a topic: L -> R lean (then settledness) at this respondent's first landscape,
  // kept for later updates so every item keeps its place and changes are comparable.
  const order = useRef<Record<string, number>>({});

  const layout = useMemo(() => {
    if (!data) return null;
    if (data.since_step === null || !Object.keys(order.current).length) {
      const sorted = [...data.items].sort((a, b) => (a.l ?? 0) - (b.l ?? 0) || a.s - b.s || (a.v < b.v ? -1 : 1));
      order.current = Object.fromEntries(sorted.map((it, i) => [it.v, i]));
    }
    const rank = (v: string) => order.current[v] ?? 1e9;
    const topics = data.topics.map((t) => t.name);
    const items = [...data.items].sort((a, b) => rank(a.v) - rank(b.v));
    const totalW = items.reduce((a, it) => a + WEIGHT(it.t), 0) || 1;
    const usable = 360 - GAP * topics.length;
    const unit = usable / totalW;
    const span: Record<string, [number, number]> = {};
    const pos: Record<string, [number, number]> = {};
    let a = GAP / 2;
    for (const t of topics) {
      const start = a;
      for (const it of items) {
        if (it.t !== t) continue;
        const w = unit * WEIGHT(t);
        pos[it.v] = [a, a + w];
        a += w;
      }
      // a topic with only anchored items still gets a sliver so its beads have a place
      if (a === start) a += 3;
      span[t] = [start, a];
      a += GAP;
    }
    // anchored beads: spread evenly inside their topic's arc
    const beads: Array<{ v: string; t: string; q: string; a: string; new: boolean; ang: number }> = [];
    for (const t of topics) {
      const list = data.anchored.filter((x) => x.t === t);
      const [s0, s1] = span[t] || [0, 0];
      list.forEach((x, i) => beads.push({ ...x, ang: s0 + ((i + 0.5) * (s1 - s0)) / list.length }));
    }
    const newAngles = beads.filter((b) => b.new).map((b) => b.ang);
    const byAngle = items.map((it) => ({ it, a0: pos[it.v][0], a1: pos[it.v][1] }));
    return { span, pos, beads, newAngles, topics, byAngle };
  }, [data]);

  if (!data || !layout) {
    return (
      <div className="land">
        <div className="note land-loading">{loading ? <><span className="spinner" /> mapping the decision landscape…</> : null}</div>
      </div>
    );
  }

  const eps = data.shift_eps;
  const ripple = (ang: number) => {
    if (!layout.newAngles.length) return 0;
    const d = Math.min(...layout.newAngles.map((b) => Math.min(Math.abs(b - ang), 360 - Math.abs(b - ang))));
    return (d / 180) * 0.9;
  };
  const len = (s: number) => R0 + (R1 - R0) * Math.sqrt(Math.max(0, Math.min(1, s)));
  const itemTip = (it: LandscapeItem) => {
    const moved = it.d !== null && it.d > eps;
    return (
      <>
        <b className="mono">{it.v}</b> <span className="note">· {it.t}</span>
        <div>{it.q}</div>
        <div className="note">
          likely “{it.m}” (p {it.p.toFixed(2)}) · settled {(it.s * 100).toFixed(0)}%
          {it.l !== null && !MUTED.has(it.t) ? ` · lean ${it.l >= 0 ? "R" : "L"} ${fmtNum(Math.abs(it.l))}` : ""}
        </div>
        {it.d !== null && (
          <div className="note">
            {moved ? `moved ${it.d.toFixed(4)} bits since ${stepLabel(data.since_step!)}` : "unchanged by the last answer"}
          </div>
        )}
      </>
    );
  };
  const topicTip = (t: string) => {
    const info = data.topics.find((x) => x.name === t)!;
    return (
      <>
        <b>{t}</b>
        <div className="note">
          {info.n} predicted · {info.anchored} answered
          {info.settled !== null ? ` · settled ${(info.settled * 100).toFixed(0)}%` : ""}
          {data.since_step !== null ? ` · ${info.moved} moved` : ""}
        </div>
      </>
    );
  };
  /** Hover by polar position: any point on an item's ring sector, bead or topic band counts. */
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const k = (SIZE + 2 * PADX) / box.width;
    const dx = (e.clientX - box.left) * k - PADX - C;
    const dy = (e.clientY - box.top) * k - C;
    const r = Math.hypot(dx, dy);
    const ang = ((Math.atan2(dy, dx) * 180) / Math.PI + 90 + 360) % 360;
    const at = { x: e.clientX - box.left, y: e.clientY - box.top };
    if (r >= R0 - 2 && r <= R1 + 20) {
      const hit = layout.byAngle.find((b) => ang >= b.a0 && ang < b.a1);
      if (hit) return setHover({ ...at, key: hit.it.v, html: itemTip(hit.it) });
    }
    if (r >= RB - 7 && r <= RB + 6) {
      const near = layout.beads
        .map((b) => ({ b, d: Math.min(Math.abs(b.ang - ang), 360 - Math.abs(b.ang - ang)) }))
        .sort((p, q) => p.d - q.d)[0];
      if (near && near.d < 6) {
        const b = near.b;
        return setHover({
          ...at,
          key: `bead-${b.v}`,
          html: (
            <>
              <b className="mono">{b.v}</b> <span className="note">· {b.t} · answered</span>
              <div>{b.q}</div>
              <div className="note">“{b.a}”</div>
            </>
          ),
        });
      }
    }
    if ((r >= RT - 4 && r <= RT + 4) || r > R1 + 20) {
      const t = layout.topics.find((x) => ang >= layout.span[x][0] - GAP / 2 && ang < layout.span[x][1] + GAP / 2);
      if (t) return setHover({ ...at, key: `topic-${t}`, html: topicTip(t) });
    }
    setHover(null);
  };
  const s = data.summary;
  const stepLabel = (n: number) => (n === 0 ? "the start" : `Q${n}`);

  return (
    <div className="land" onMouseLeave={() => setHover(null)}>
      <div className="land-h">
        <span className="section-title" style={{ margin: 0 }}>Decision landscape</span>
        <span
          className="info-tip"
          tabIndex={0}
          title={
            "The survey model's predicted answer to every askable item, for this respondent's digital twin.\n" +
            "Each wedge is one item, grouped by topic. Length: how settled the predicted answer is. " +
            (data.has_lean ? "Colour: which pole the likely answer leans to (blue L, red R, grey neutral). " : "") +
            "Pulsing wedges and dots: predictions moved by the last answer; the pulse ripples out from the newly answered item.\n" +
            "Inner beads: answered items (larger = just answered). Hover anything for details."
          }
        >
          ⓘ
        </span>
        {loading && <span className="spinner" style={{ marginLeft: "auto" }} />}
      </div>
      <div className="land-chart">
        <svg viewBox={`${-PADX} 0 ${SIZE + 2 * PADX} ${SIZE}`} onMouseMove={onMove} role="img" aria-label={`Decision landscape: ${s.n_items} predicted answers in ${data.topics.length} topics`}>
          {/* topic band + labels */}
          {layout.topics.map((t) => {
            const [a0, a1] = layout.span[t];
            const info = data.topics.find((x) => x.name === t)!;
            const mid = (a0 + a1) / 2;
            const [lx, ly] = pt(RL, mid);
            const anchor = mid < 8 || mid > 352 || (mid > 172 && mid < 188) ? "middle" : mid < 180 ? "start" : "end";
            const on = hover?.key === `topic-${t}`;
            return (
              <g key={t}>
                <path d={arc(RT, a0, a1)} className={`land-topic${MUTED.has(t) ? " muted" : ""}${info.moved ? " moved" : ""}${on ? " on" : ""}`} />
                {a1 - a0 > 9 && (
                  <text x={lx} y={ly + 3} textAnchor={anchor} className={`land-tlab${info.moved ? " moved" : ""}${on ? " on" : ""}`}>
                    {SHORT[t] ?? t}
                  </text>
                )}
              </g>
            );
          })}
          {/* item wedges */}
          <g key={`w-${data.step}`}>
            {data.items.map((it) => {
              const [a0, a1] = layout.pos[it.v];
              const moved = it.d !== null && it.d > eps;
              const on = hover?.key === it.v;
              return (
                <path
                  key={it.v}
                  data-v={it.v}
                  d={wedge(R0, len(it.s), a0, a1)}
                  fill={leanFill(it, data.lean_scale)}
                  className={`land-w${moved ? " moved" : ""}${on ? " on" : ""}`}
                  style={moved ? { animationDelay: `${ripple((a0 + a1) / 2).toFixed(2)}s` } : undefined}
                />
              );
            })}
            {/* shift spikes just outside the moved wedges: length ~ sqrt(shift) */}
            {data.items.map((it) => {
              if (it.d === null || it.d <= eps) return null;
              const [a0, a1] = layout.pos[it.v];
              const a = (a0 + a1) / 2;
              const L = 3 + 15 * Math.min(1, Math.sqrt(it.d / SHIFT_REF));
              const [x0, y0] = pt(R1 + 3, a);
              const [x1, y1] = pt(R1 + 3 + L, a);
              return (
                <line
                  key={`d-${it.v}`}
                  x1={x0}
                  y1={y0}
                  x2={x1}
                  y2={y1}
                  className="land-spike"
                  style={{ animationDelay: `${ripple(a).toFixed(2)}s` }}
                />
              );
            })}
          </g>
          {/* anchored beads */}
          {layout.beads.map((b) => {
            const [x, y] = pt(RB, b.ang);
            return (
              <circle
                key={b.v}
                cx={x}
                cy={y}
                r={b.new ? 4.6 : 2.8}
                className={`land-bead${b.new ? " new" : ""}${hover?.key === `bead-${b.v}` ? " on" : ""}`}
              />
            );
          })}
          {/* centre */}
          {data.ideology !== null ? (
            <>
              <text x={C} y={C - 4} textAnchor="middle" className="land-c-num">
                {data.ideology.toFixed(3)}
              </text>
              <text x={C} y={C + 12} textAnchor="middle" className="land-c-lab">
                ideology
              </text>
            </>
          ) : (
            <>
              <text x={C} y={C - 4} textAnchor="middle" className="land-c-num">
                {data.anchored.length}
              </text>
              <text x={C} y={C + 12} textAnchor="middle" className="land-c-lab">
                answered
              </text>
            </>
          )}
          <text x={C} y={C + 25} textAnchor="middle" className="land-c-lab">
            {data.step === 0 ? "start" : `after Q${data.step}`}
          </text>
        </svg>
        {hover && (
          <div className="tooltip land-tip" style={{ left: Math.min(hover.x + 12, 110), top: hover.y + 14 }}>
            {hover.html}
          </div>
        )}
      </div>
      <div className="land-cap">
        {data.since_step === null ? (
          <>
            {s.n_items} predicted answers in {data.topics.length} topics. Ask a question to see which predictions it moves.
          </>
        ) : s.n_moved === 0 ? (
          <>Since {stepLabel(data.since_step)}: no predicted answer moved.</>
        ) : (
          <>
            Since {stepLabel(data.since_step)}
            {data.new_anchored.length ? <> (answered <span className="mono">{data.new_anchored.join(", ")}</span>)</> : null}:{" "}
            <b>{s.n_moved}</b> predicted answer{s.n_moved === 1 ? "" : "s"} moved
            {s.top_topics.length ? <>, most in {s.top_topics.join(", ")}</> : null}.
          </>
        )}
      </div>
      {s.top_items.length > 0 && (
        <ul className="land-top">
          {s.top_items.slice(0, 3).map((x) => (
            <li key={x.v} title={`${x.q}\nnow likely “${x.m}”`}>
              <span className="mono">{x.v}</span>
              <span className="qt">{x.q}</span>
              <span className="mono note">{x.d.toFixed(3)}</span>
            </li>
          ))}
        </ul>
      )}
      {data.has_lean && (
        <div className="land-legend note">
          <span>L</span>
          <span className="land-grad" />
          <span>R</span>
          <span style={{ marginLeft: "auto" }}>length = settled</span>
        </div>
      )}
    </div>
  );
}
