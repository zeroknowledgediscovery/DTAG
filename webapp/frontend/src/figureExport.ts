/*
 * Save a figure from the page as SVG (vector), PNG (high resolution) or PDF (vector; the canvas-based
 * landscape map goes into the PDF as a 4x image).
 *
 * The figure is the first <svg> inside the given element. If the element also holds a <canvas>
 * (the landscape map), the canvas is embedded as an image under the SVG overlay. Styles come from
 * the page's CSS (theme variables, classes), so every element's computed style is inlined into a
 * standalone copy: the file looks the same outside the app, in the current light/dark theme.
 */

export type FigureFormat = "svg" | "png" | "pdf";

const SVG_NS = "http://www.w3.org/2000/svg";
const PROPS = [
  "fill", "fill-opacity", "stroke", "stroke-width", "stroke-opacity", "stroke-dasharray", "stroke-linecap",
  "stroke-linejoin", "opacity", "font-family", "font-size", "font-weight", "font-style", "text-anchor",
  "dominant-baseline", "paint-order", "visibility", "stop-color", "stop-opacity", "vector-effect",
];
const COLOR_PROPS = new Set(["fill", "stroke", "stop-color"]);

/** Any CSS colour (oklab, color-mix, color(srgb ...), named) as rgb()/rgba(), which every SVG/PDF reader understands. */
const colorCache = new Map<string, string>();
let colorCtx: CanvasRenderingContext2D | null = null;
function plainColor(v: string): string {
  if (!v || v === "none" || v.startsWith("url(") || v === "transparent" || /^rgba?\(/.test(v) || /^#[0-9a-f]{3,8}$/i.test(v)) return v;
  const hit = colorCache.get(v);
  if (hit) return hit;
  colorCtx ??= Object.assign(document.createElement("canvas"), { width: 1, height: 1 }).getContext("2d", { willReadFrequently: true });
  if (!colorCtx) return v;
  colorCtx.clearRect(0, 0, 1, 1);
  colorCtx.fillStyle = "#000";
  colorCtx.fillStyle = v;
  colorCtx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = colorCtx.getImageData(0, 0, 1, 1).data;
  const out = a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`;
  colorCache.set(v, out);
  return out;
}

/** Copy computed styles of `src` (and descendants) onto `dst` as presentation attributes. */
function inlineStyles(src: Element, dst: Element) {
  const cs = getComputedStyle(src);
  for (const p of PROPS) {
    const v = cs.getPropertyValue(p);
    if (v && v !== "normal" && !(p === "visibility" && v === "visible")) dst.setAttribute(p, COLOR_PROPS.has(p) ? plainColor(v) : v);
  }
  // geometry set through CSS (animated doughnut wedges: style="d: path(...)")
  const d = cs.getPropertyValue("d");
  if (d && d.startsWith("path(")) dst.setAttribute("d", d.slice(5, -1).trim().replace(/^["']|["']$/g, ""));
  // a figure saved mid-animation should look settled
  if ((src as HTMLElement).style?.animationName || cs.animationName !== "none") dst.setAttribute("opacity", "1");
  dst.removeAttribute("class");
  dst.removeAttribute("style");
  const sk = src.children;
  const dk = dst.children;
  for (let i = 0; i < sk.length && i < dk.length; i++) inlineStyles(sk[i], dk[i]);
}

function background(): string {
  return plainColor(getComputedStyle(document.documentElement).getPropertyValue("--panel").trim() || "#ffffff");
}

/** Standalone SVG string for the figure in `el`, plus its size in CSS pixels. */
export function figureSvg(el: HTMLElement): { svg: string; width: number; height: number; raster: boolean } {
  // the figure is the largest <svg> in the element (not the save button's icon or legend swatches)
  const svgs = Array.from(el.querySelectorAll("svg")).filter((s) => !s.closest("[data-export-ignore]"));
  const area = (s: Element) => s.getBoundingClientRect().width * s.getBoundingClientRect().height;
  const src = svgs.sort((a, b) => area(b) - area(a))[0];
  if (!src) throw new Error("No figure found");
  const canvas = el.querySelector("canvas");
  const box = (canvas ?? src).getBoundingClientRect();
  const width = Math.round(box.width);
  const height = Math.round(canvas ? box.height : src.getBoundingClientRect().height);

  // hover highlights are not part of the figure: drop them while the styles are copied
  const hovered = Array.from(src.querySelectorAll(".on"));
  hovered.forEach((n) => n.classList.remove("on"));
  const clone = src.cloneNode(true) as SVGSVGElement;
  try {
    inlineStyles(src, clone);
  } finally {
    hovered.forEach((n) => n.classList.add("on"));
  }
  clone.querySelectorAll("[data-export-ignore]").forEach((n) => n.remove());
  const vb = src.getAttribute("viewBox") || `0 0 ${width} ${height}`;

  const root = document.createElementNS(SVG_NS, "svg");
  root.setAttribute("xmlns", SVG_NS);
  root.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
  root.setAttribute("width", String(width));
  root.setAttribute("height", String(height));
  root.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const bg = document.createElementNS(SVG_NS, "rect");
  bg.setAttribute("width", "100%");
  bg.setAttribute("height", "100%");
  bg.setAttribute("fill", background());
  root.appendChild(bg);
  if (canvas) {
    const img = document.createElementNS(SVG_NS, "image");
    img.setAttribute("href", canvas.toDataURL("image/png"));
    img.setAttribute("width", String(width));
    img.setAttribute("height", String(height));
    img.setAttribute("preserveAspectRatio", "none");
    img.setAttribute("style", "image-rendering:auto");
    root.appendChild(img);
  }
  clone.setAttribute("x", "0");
  clone.setAttribute("y", "0");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  clone.setAttribute("viewBox", vb);
  if (canvas) clone.setAttribute("preserveAspectRatio", "none");
  clone.setAttribute("overflow", "visible");
  root.appendChild(clone);
  return { svg: new XMLSerializer().serializeToString(root), width, height, raster: Boolean(canvas) };
}

function download(blob: Blob, filename: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

async function svgToPng(svg: string, width: number, height: number, scale: number): Promise<Blob> {
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const img = new Image();
    img.decoding = "async";
    await new Promise<void>((ok, fail) => {
      img.onload = () => ok();
      img.onerror = () => fail(new Error("Could not render the figure"));
      img.src = url;
    });
    const cv = document.createElement("canvas");
    cv.width = Math.round(width * scale);
    cv.height = Math.round(height * scale);
    const ctx = cv.getContext("2d")!;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(img, 0, 0, cv.width, cv.height);
    return await new Promise<Blob>((ok, fail) => cv.toBlob((b) => (b ? ok(b) : fail(new Error("PNG encoding failed"))), "image/png"));
  } finally {
    URL.revokeObjectURL(url);
  }
}

async function svgToPdf(svg: string, width: number, height: number, raster: boolean): Promise<Blob> {
  const orientation = width > height ? "landscape" : "portrait";
  if (raster) {
    // figures drawn on a canvas (the landscape map) go into the PDF as a 4x image
    const { jsPDF } = await import("jspdf");
    const png = await svgToPng(svg, width, height, 4);
    const data = new Uint8Array(await png.arrayBuffer());
    const doc = new jsPDF({ unit: "pt", format: [width, height], orientation });
    doc.addImage(data, "PNG", 0, 0, width, height);
    return doc.output("blob");
  }
  const [{ jsPDF }, { svg2pdf }] = await Promise.all([import("jspdf"), import("svg2pdf.js")]);
  const el = new DOMParser().parseFromString(svg, "image/svg+xml").documentElement as unknown as SVGSVGElement;
  // svg2pdf measures text, so the element has to be in the document while it is converted
  const holder = document.createElement("div");
  holder.style.cssText = "position:fixed;left:-10000px;top:0;visibility:hidden";
  holder.appendChild(el);
  document.body.appendChild(holder);
  try {
    const doc = new jsPDF({ unit: "pt", format: [width, height], orientation });
    await svg2pdf(el, doc, { x: 0, y: 0, width, height });
    return doc.output("blob");
  } finally {
    holder.remove();
  }
}

/** Save the figure in `el` as `name`.{svg,png,pdf}; PNG is rendered at `scale`x. */
export async function exportFigure(el: HTMLElement, format: FigureFormat, name: string, scale = 4): Promise<void> {
  const { svg, width, height, raster } = figureSvg(el);
  const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "").replace(/(\d{8})(\d{6})/, "$1_$2");
  const base = `${name.replace(/[^A-Za-z0-9._-]+/g, "_")}_${stamp}`;
  if (format === "svg") return download(new Blob([svg], { type: "image/svg+xml" }), `${base}.svg`);
  if (format === "png") return download(await svgToPng(svg, width, height, scale), `${base}.png`);
  return download(await svgToPdf(svg, width, height, raster), `${base}.pdf`);
}
