import { useEffect, useRef, useState } from "react";
import { exportFigure, type FigureFormat } from "../figureExport";

/**
 * Tiny save button for a figure (shown on hover, top-right of the figure). Place it inside the
 * element that holds the figure's <svg> (and <canvas> for the map), which must be position: relative.
 */
export function FigureSave({ name, title = "Save figure" }: { name: string; title?: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<FigureFormat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const save = async (fmt: FigureFormat) => {
    const fig = ref.current?.parentElement;
    if (!fig) return;
    setBusy(fmt);
    setError(null);
    try {
      await exportFigure(fig, fmt, name);
      setOpen(false);
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={`fig-save${open ? " open" : ""}`} ref={ref} data-export-ignore="">
      <button className="fig-save-btn" title={title} aria-label={title} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M8 2.5v7.5M4.8 7l3.2 3.2L11.2 7M3 12.5h10" />
        </svg>
      </button>
      {open && (
        <div className="fig-save-menu" role="menu">
          {(
            [
              ["svg", "SVG", "vector"],
              ["png", "PNG", "4× resolution"],
              ["pdf", "PDF", "vector"],
            ] as const
          ).map(([fmt, label, note]) => (
            <button key={fmt} role="menuitem" disabled={busy !== null} onClick={() => save(fmt)}>
              <b>{label}</b> <span className="note">{busy === fmt ? "saving…" : note}</span>
            </button>
          ))}
          {error && <div className="error">{error}</div>}
        </div>
      )}
    </div>
  );
}
