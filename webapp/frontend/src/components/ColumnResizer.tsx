import { useCallback, useEffect, useRef, useState } from "react";

/*
 * Resizable side columns. The layout grid reads --lw / --rw (CSS variables on .main), so the centre
 * column reflows (the chat wraps) instead of being covered; it never gets narrower than CENTER_MIN.
 * Figures in the side columns are drawn at 100% width, so they grow with their column.
 * Widths are remembered per browser and per layout (one or two respondents); double-click a handle
 * to reset it.
 */

const CENTER_MIN = 360;
const LIMITS = { left: [260, 900], right: [300, 900] } as const;
const DEFAULTS: Record<1 | 2, { left: number; right: number }> = { 1: { left: 340, right: 368 }, 2: { left: 330, right: 388 } };
const key = (mode: 1 | 2) => `dtag.layout.${mode}`;

function load(mode: 1 | 2) {
  try {
    const v = JSON.parse(window.localStorage.getItem(key(mode)) || "null");
    if (v && Number.isFinite(v.left) && Number.isFinite(v.right)) return { left: v.left as number, right: v.right as number };
  } catch {
    /* storage unavailable or corrupt: use defaults */
  }
  return DEFAULTS[mode];
}

export function useColumnLayout(mode: 1 | 2) {
  const [w, setW] = useState(() => load(mode));
  const main = useRef<HTMLDivElement>(null);

  useEffect(() => setW(load(mode)), [mode]);

  const save = useCallback(
    (v: { left: number; right: number }) => {
      try {
        window.localStorage.setItem(key(mode), JSON.stringify(v));
      } catch {
        /* the width lasts for this page only */
      }
    },
    [mode]
  );

  /** Keep both side columns within their limits and leave the centre at least CENTER_MIN. */
  const clamp = useCallback((side: "left" | "right", px: number, other: number) => {
    const total = main.current?.clientWidth ?? window.innerWidth;
    const [lo, hi] = LIMITS[side];
    return Math.round(Math.max(lo, Math.min(hi, px, total - other - CENTER_MIN)));
  }, []);

  const startDrag = (side: "left" | "right") => (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    document.body.classList.add("col-resizing");
    const box = main.current!.getBoundingClientRect();
    let cur = w;
    const move = (ev: PointerEvent) => {
      cur =
        side === "left"
          ? { ...cur, left: clamp("left", ev.clientX - box.left, cur.right) }
          : { ...cur, right: clamp("right", box.right - ev.clientX, cur.left) };
      setW(cur);
    };
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      document.body.classList.remove("col-resizing");
      save(cur);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  };

  const reset = (side: "left" | "right") => () => {
    const v = { ...w, [side]: DEFAULTS[mode][side] };
    setW(v);
    save(v);
  };

  const nudge = (side: "left" | "right") => (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 64 : 16;
    const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    const v =
      side === "left"
        ? { ...w, left: clamp("left", w.left + dir * step, w.right) }
        : { ...w, right: clamp("right", w.right - dir * step, w.left) };
    setW(v);
    save(v);
  };

  // keep the centre at its minimum when the window shrinks
  useEffect(() => {
    const fit = () => setW((v) => ({ left: clamp("left", v.left, v.right), right: clamp("right", v.right, clamp("left", v.left, v.right)) }));
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [clamp]);

  const resetAll = () => {
    setW(DEFAULTS[mode]);
    try {
      window.localStorage.removeItem(key(mode));
    } catch {
      /* nothing stored */
    }
  };
  const isDefault = w.left === DEFAULTS[mode].left && w.right === DEFAULTS[mode].right;

  const style = { "--lw": `${w.left}px`, "--rw": `${w.right}px` } as React.CSSProperties;
  const handle = (side: "left" | "right") => (
    <div
      className={`col-handle ${side}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${side} column (double-click to reset)`}
      aria-valuenow={w[side]}
      tabIndex={0}
      title="Drag to resize · double-click to reset"
      onPointerDown={startDrag(side)}
      onDoubleClick={reset(side)}
      onKeyDown={nudge(side)}
    />
  );
  return { ref: main, style, handles: <>{handle("left")}{handle("right")}</>, isDefault, resetAll };
}
