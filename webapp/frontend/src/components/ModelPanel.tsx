import { fmtBytes } from "../api";
import type { ModelRecord, ModelStatus } from "../types";

const STAGES: Array<[ModelStatus["state"], string]> = [
  ["downloading", "Downloading"],
  ["verifying", "Verifying"],
  ["extracting", "Extracting"],
  ["loading", "Loading native LSM"],
  ["loaded", "Ready"],
];

export function statusLabel(s: ModelStatus["state"] | undefined): string {
  switch (s) {
    case "not_installed":
      return "available publicly · not installed";
    case "installed":
      return "installed · not resident";
    case "loaded":
      return "installed · loaded in server memory";
    case "downloading":
    case "verifying":
    case "extracting":
    case "loading":
      return s;
    case "error":
      return "error";
    default:
      return "unknown";
  }
}

export function ModelPanel({
  model,
  status,
  onInstall,
  busy,
}: {
  model: ModelRecord | undefined;
  status: ModelStatus | undefined;
  onInstall: () => void;
  busy: boolean;
}) {
  if (!model) return null;
  const st = status?.state ?? model.status.state;
  const idx = STAGES.findIndex(([k]) => k === st);
  const inProgress = ["downloading", "verifying", "extracting", "loading"].includes(st) || status?.job_running;
  const pct =
    st === "downloading" && status && status.total_bytes > 0
      ? Math.min(100, (100 * status.done_bytes) / status.total_bytes)
      : idx >= 0
        ? ((idx + 1) / STAGES.length) * 100
        : 0;

  return (
    <div className="box" style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <b>{model.label}</b>
        <span className={`badge ${st === "loaded" ? "b-direct" : st === "error" ? "b-nomatch" : "b-muted"}`}>
          {st.replace("_", " ")}
        </span>
      </div>
      <div className="note mono">{model.key}</div>
      {st === "not_installed" && !inProgress && (
        <div style={{ marginTop: 6 }}>
          <div className="note">
            Model not installed locally.
            <br />
            {fmtBytes(model.archive_bytes)} compressed · Public DTAG model release {model.release ?? "—"}
          </div>
          <button className="btn" style={{ marginTop: 6 }} onClick={onInstall} disabled={busy}>
            Install model
          </button>
        </div>
      )}
      {st === "installed" && !inProgress && (
        <div className="note" style={{ marginTop: 4 }}>
          Installed on disk; it will be loaded into server memory once on first use.{" "}
          <button className="link" onClick={onInstall} disabled={busy}>
            Preload now
          </button>
        </div>
      )}
      {st === "loaded" && model.runtime && (
        <div className="note" style={{ marginTop: 4 }}>
          Resident: {model.runtime.features} features · {model.runtime.usable_trees} usable trees · preload{" "}
          {model.runtime.load_seconds.toFixed(1)} s (once per server process)
        </div>
      )}
      {(inProgress || st === "loaded") && (
        <>
          <div className="stages">
            {STAGES.map(([k, label], i) => (
              <span key={k} className={i < idx || st === "loaded" ? "done" : i === idx ? "active" : ""}>
                {label}
              </span>
            ))}
          </div>
          {inProgress && (
            <div className="progress">
              <div style={{ width: `${pct}%` }} />
            </div>
          )}
          {st === "downloading" && status && (
            <div className="note">
              {fmtBytes(status.done_bytes)} / {fmtBytes(status.total_bytes)}
            </div>
          )}
        </>
      )}
      {st === "error" && <div className="error">{status?.error || model.status.error}</div>}
    </div>
  );
}
