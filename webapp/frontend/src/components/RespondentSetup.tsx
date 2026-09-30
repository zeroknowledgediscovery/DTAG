import type { EBWave, ModelRecord, Profile } from "../types";
import type { Respondent } from "../useRespondent";
import { Controls, Section, type Geography } from "./Controls";
import { ModelChooser } from "./ModelChooser";
import { ModelPanel } from "./ModelPanel";

/** Who / where / when, model choice, behaviour and start controls for one respondent. */
export function RespondentSetup({
  r,
  label,
  profiles,
  models,
  ebWaves,
  ebDates,
  geography,
  liveState,
  onSave,
  onBuilder,
  onDeletePreset,
}: {
  r: Respondent;
  label?: string;
  profiles: Profile[];
  models: ModelRecord[];
  ebWaves: EBWave[];
  ebDates: boolean;
  geography: Geography;
  liveState: Record<string, string>;
  onSave: () => void;
  onBuilder: () => void;
  onDeletePreset: () => void;
}) {
  const { busy, rec } = r;
  const src = rec?.resolved.sources;
  const who = label ? `respondent ${label}` : "respondent";
  return (
    <>
      <Section title={label ? `Respondent ${label}` : "Respondent"}>
        <label className="field">
          <span>Start from a preset (optional)</span>
          <select value={r.preset} disabled={busy} onChange={(e) => r.applyPreset(e.target.value)}>
            <option value="">(none — describe the respondent below)</option>
            <optgroup label="Configured">
              {profiles
                .filter((p) => p.source === "configured" && !p.error)
                .map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name} — {p.description}
                  </option>
                ))}
            </optgroup>
            {profiles.some((p) => p.source === "custom") && (
              <optgroup label="Custom">
                {profiles
                  .filter((p) => p.source === "custom" && !p.error)
                  .map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name}
                    </option>
                  ))}
              </optgroup>
            )}
          </select>
        </label>
        <label className="field">
          <span>Who — description</span>
          <textarea
            rows={3}
            disabled={busy}
            value={r.persona}
            placeholder="e.g. 35 year old teacher in Nairobi, Kenya, regular news consumer"
            onChange={(e) => r.setPersona(e.target.value)}
          />
        </label>
        <div className="row">
          <label className="field">
            <span>Where — country</span>
            <input
              type="text"
              list="dtag-country-list"
              disabled={busy}
              value={r.country}
              placeholder={src?.country === "description" ? `${rec?.resolved.country} (from description)` : "any country"}
              onChange={(e) => r.setCountry(e.target.value)}
            />
          </label>
          <label className="field" style={{ maxWidth: 92 }}>
            <span>When — year</span>
            <input
              type="number"
              min={1950}
              max={2035}
              disabled={busy}
              value={r.year}
              placeholder={src?.year === "description" ? String(rec?.resolved.year) : "latest"}
              onChange={(e) => r.setYear(e.target.value)}
            />
          </label>
        </div>
        <details open={Boolean(r.date)}>
          <summary className="note" style={{ cursor: "pointer" }}>
            Exact date (routes Eurobarometer to one fieldwork wave)
          </summary>
          <input type="date" disabled={busy} value={r.date} onChange={(e) => r.setDate(e.target.value)} />
        </details>
        {rec && (src?.country === "description" || src?.year === "description") && (
          <div className="note" style={{ marginTop: 4 }}>
            From the description:{" "}
            {src?.country === "description" && (
              <span className="badge b-neutral">
                country {rec.resolved.country} ← “{rec.detected.country_evidence}”
              </span>
            )}{" "}
            {src?.year === "description" && (
              <span className="badge b-neutral">
                year {rec.resolved.year} ← “{rec.detected.year_evidence}”
              </span>
            )}{" "}
            (type in the fields to override)
          </div>
        )}
      </Section>

      <Section title="Survey model">
        <ModelChooser
          rec={rec}
          loading={r.recLoading}
          chosen={r.effectiveKey}
          manual={r.manual}
          onChoose={(k) => {
            r.setManual(null);
            r.setChosen(k);
          }}
          onManual={r.setManual}
          liveState={liveState}
          models={models}
          disabled={busy}
        />
        {(liveState[r.effectiveKey ?? ""] ?? r.model?.status.state) !== "loaded" && (
          <div style={{ marginTop: 8 }}>
            <ModelPanel
              model={r.model}
              status={r.status && r.status.key === r.effectiveKey ? r.status : undefined}
              onInstall={() => r.effectiveKey && r.load(r.effectiveKey).catch((e) => r.setError(String(e.message)))}
              busy={busy || r.modelBusy}
            />
          </div>
        )}
      </Section>

      <Controls
        only={["behaviour"]}
        resolved={r.resolved}
        overrides={r.behaviour}
        onChange={r.setBehaviour}
        models={models}
        ebWaves={ebWaves}
        ebDatesAvailable={ebDates}
        capabilities={r.resolved?.capabilities}
        geography={geography}
        disabled={busy}
      />

      {r.validationError && <div className="error">{r.validationError}</div>}
      {r.resolved && r.resolved.warnings.length > 0 && (
        <details>
          <summary className="note" style={{ cursor: "pointer" }}>
            Conditioning details ({r.resolved.warnings.length})
          </summary>
          <ul className="warn-list">
            {r.resolved.warnings.map((w) => (
              <li key={w} className={/hard-conditioned|resolves to/.test(w) ? "info" : ""}>
                {w}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="actions" style={{ marginTop: 10 }}>
        <button
          className="btn primary"
          onClick={r.start}
          disabled={busy || r.validating || !r.request || !!r.validationError}
          title={r.modelBusy ? "The model is still downloading/loading; starting will wait for it." : ""}
        >
          {r.session ? `Start new ${who}` : `Start ${who}`}
        </button>
        <button className="btn" onClick={r.reset} disabled={busy || !r.session}>
          Reset
        </button>
      </div>
      <div className="actions" style={{ marginTop: 6 }}>
        <button className="link" onClick={onSave} disabled={busy || !r.request || !!r.validationError}>
          Save as custom profile
        </button>
        <button className="link" onClick={onBuilder} disabled={busy}>
          Advanced profile builder…
        </button>
        {r.presetProfile?.source === "custom" && (
          <button className="link" onClick={onDeletePreset}>
            Delete preset
          </button>
        )}
      </div>
      {r.phase && (
        <div className="box" style={{ marginTop: 8 }}>
          <span className="spinner" /> {r.phase}
        </div>
      )}
      {r.error && (
        <div className="error" style={{ marginTop: 8 }}>
          {r.error}
        </div>
      )}
    </>
  );
}
