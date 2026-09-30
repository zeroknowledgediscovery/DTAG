import { useId } from "react";
import { fmtBytes } from "../api";
import type { Candidate, Family, ModelRecord, Recommendation } from "../types";

const GEO_LABEL: Record<Candidate["geo"]["mode"], string> = {
  categorical: "country hard-conditioned",
  national_survey: "national sample",
  coverage_only: "country in survey (contextual)",
  coordinates: "coordinate proxy",
  assumed: "assumed country",
};

function stateBadge(c: { loaded: boolean; installed: boolean; archive_bytes: number | null }, live?: string) {
  const st = live || (c.loaded ? "loaded" : c.installed ? "installed" : "not_installed");
  if (st === "loaded") return <span className="badge b-direct">loaded</span>;
  if (["downloading", "verifying", "extracting", "loading"].includes(st))
    return (
      <span className="badge b-neutral">
        <span className="spinner" /> {st}
      </span>
    );
  if (st === "installed") return <span className="badge b-muted">installed</span>;
  if (st === "error") return <span className="badge b-nomatch">error</span>;
  return <span className="badge b-muted">download {fmtBytes(c.archive_bytes)}</span>;
}

export function ModelChooser({
  rec,
  loading,
  chosen,
  manual,
  onChoose,
  onManual,
  liveState,
  models,
  disabled,
}: {
  rec: Recommendation | null;
  loading: boolean;
  chosen: string | null;
  manual: string | null;
  onChoose: (key: string) => void;
  onManual: (key: string | null) => void;
  liveState: Record<string, string>;
  models: ModelRecord[];
  disabled?: boolean;
}) {
  const group = useId(); // one radio group per chooser (two respondents can be on the page)
  const families: Family[] = ["gss", "afrobarometer", "wvs", "eurobarometer"];
  const manualRec = manual ? models.find((m) => m.key === manual) : undefined;

  return (
    <div>
      {loading && !rec && (
        <div className="note">
          <span className="spinner" /> finding native models for this respondent…
        </div>
      )}
      {rec?.messages.map((m) => (
        <div key={m} className="note" style={{ color: "var(--warn)" }}>
          {m}
        </div>
      ))}

      {manualRec ? (
        <div className="cand selected">
          <div className="cand-h">
            <input type="radio" checked readOnly />
            <b>{manualRec.label}</b>
            <span className="badge b-neutral">MANUAL</span>
            <span style={{ marginLeft: "auto" }}>{stateBadge(manualRec, liveState[manualRec.key])}</span>
          </div>
          <div className="note">Chosen manually; the recommendation is ignored.</div>
          <button className="link" onClick={() => onManual(null)} disabled={disabled}>
            ← back to recommended model
          </button>
        </div>
      ) : (
        rec?.candidates.map((c) => {
          const isDefault = c.model_key === rec.default;
          const sel = c.model_key === chosen;
          return (
            <label key={c.model_key} className={`cand ${sel ? "selected" : ""}`}>
              <div className="cand-h">
                <input type="radio" name={`dtag-model-${group}`} checked={sel} disabled={disabled} onChange={() => onChoose(c.model_key)} />
                <b>{c.label}</b>
                {isDefault && <span className="badge b-direct">DEFAULT</span>}
                <span style={{ marginLeft: "auto" }}>{stateBadge(c, liveState[c.model_key])}</span>
              </div>
              <div className="cand-d">
                <span className="mono">when</span> {c.time.note}
                {c.time.mode === "nearest" && <span className="badge b-sem"> nearest</span>}
              </div>
              <div className="cand-d">
                <span className="mono">where</span> <b>{GEO_LABEL[c.geo.mode]}</b> · {c.geo.note}
              </div>
              {!c.ideology_available && <div className="cand-d note">no ideology index for this survey</div>}
            </label>
          );
        })
      )}

      {rec && !manualRec && rec.candidates.length > 1 && (
        <div className="note" style={{ marginTop: 4 }}>
          {rec.candidates.length} surveys cover this respondent. The default is chosen by time fit first, then by how directly
          the country conditions the model; pick another above if you prefer.
        </div>
      )}

      <details style={{ marginTop: 6 }}>
        <summary className="note" style={{ cursor: "pointer" }}>
          Choose a specific native model…
        </summary>
        <div className="row" style={{ marginTop: 6 }}>
          <select
            disabled={disabled}
            value={manual ?? ""}
            onChange={(e) => onManual(e.target.value || null)}
          >
            <option value="">(use recommendation)</option>
            {families.map((f) => (
              <optgroup key={f} label={f}>
                {models
                  .filter((m) => m.family === f)
                  .map((m) => (
                    <option key={m.key} value={m.key}>
                      {m.label}
                      {m.fieldwork ? ` · ${m.fieldwork.fieldwork_start}` : ""}
                      {m.loaded ? " · loaded" : m.installed ? " · installed" : ""}
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
        </div>
      </details>
    </div>
  );
}
