import type { Capabilities, EBWave, ModelRecord, Overrides, Profile } from "../types";

export interface Geography {
  countries: string[];
  continents: string[];
}

interface Props {
  resolved: Profile | null;
  overrides: Overrides;
  onChange: (o: Overrides) => void;
  models: ModelRecord[];
  ebWaves: EBWave[];
  ebDatesAvailable: boolean;
  capabilities: Capabilities | null | undefined;
  geography: Geography;
  disabled?: boolean;
}

const ADVANCED: Array<{ key: keyof Overrides; label: string; step?: number }> = [
  { key: "seed", label: "Seed" },
  { key: "k", label: "Max direct variables (k)" },
  { key: "prefilter", label: "Lexical prefilter" },
  { key: "min_map_score", label: "Min map score", step: 0.25 },
  { key: "state_keep", label: "State keep" },
  { key: "max_assign", label: "Max persona assignments" },
  { key: "assign_prefilter", label: "Persona prefilter" },
  { key: "semantic_k", label: "Semantic k" },
  { key: "semantic_prefilter", label: "Semantic prefilter" },
  { key: "semantic_min_confidence", label: "Semantic min confidence", step: 0.05 },
];

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="section">
      <div className="section-title">
        {title}
        <span className="rule" />
      </div>
      {children}
    </div>
  );
}

export function Controls(props: Props) {
  const { resolved, overrides: o, onChange, models, capabilities, disabled } = props;
  if (!resolved) return null;
  const set = (patch: Partial<Overrides>) => onChange({ ...o, ...patch });
  const val = <K extends keyof Overrides>(k: K, fallback: unknown) =>
    (o[k] !== undefined ? o[k] : fallback) as Overrides[K];
  const family = resolved.family;
  const model = models.find((m) => m.key === resolved.model_key);
  const run = resolved.run || {};

  const gssModels = models.filter((m) => m.family === "gss" && m.year).sort((a, b) => (a.year! - b.year!));
  const afroModels = models.filter((m) => m.family === "afrobarometer");
  const ebModels = models.filter((m) => m.family === "eurobarometer");
  const ebByZa = new Map(props.ebWaves.map((w) => [w.za, w]));
  const ebMode = o.za !== undefined ? "za" : o.date !== undefined ? "date" : resolved.date ? "date" : "za";

  return (
    <div>
      <Section title="Who">
        <label className="field">
          <span>Persona / demographic description</span>
          <textarea
            disabled={disabled}
            value={val("persona", resolved.persona) as string}
            onChange={(e) => set({ persona: e.target.value })}
            rows={4}
          />
        </label>
        <div className="note">
          The persona is interpreted by the language model into survey-variable assignments; only
          assignments valid in the native model's support hard-condition the state.
        </div>
      </Section>

      <Section title="Where">
        <div className="row">
          <label className="field">
            <span>Country</span>
            <input
              type="text"
              list="dtag-countries"
              disabled={disabled}
              value={val("country", resolved.country) as string}
              onChange={(e) => set({ country: e.target.value })}
            />
            <datalist id="dtag-countries">
              {(capabilities?.country_values?.length ? capabilities.country_values : props.geography.countries).map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </label>
          <label className="field">
            <span>Continent / region</span>
            <select
              disabled={disabled}
              value={val("continent", resolved.continent) as string}
              onChange={(e) => set({ continent: e.target.value })}
            >
              <option value="">(none)</option>
              {props.geography.continents.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
              {resolved.continent && !props.geography.continents.includes(resolved.continent.toLowerCase()) && (
                <option value={resolved.continent}>{resolved.continent}</option>
              )}
            </select>
          </label>
        </div>
        {capabilities && (
          <div className="note">
            Model geography:{" "}
            <b>
              {capabilities.geography_mode === "categorical_country"
                ? `categorical (${capabilities.country_features[0]})`
                : capabilities.geography_mode === "coordinates"
                  ? "coordinate proxy (O1_LONGITUDE / O2_LATITUDE)"
                  : "survey context only"}
            </b>
          </div>
        )}
      </Section>

      <Section title="When">
        {family === "gss" && (
          <label className="field">
            <span>GSS survey wave (selects the native wave model)</span>
            <select
              disabled={disabled}
              value={String(val("year", resolved.year) ?? "")}
              onChange={(e) => set({ year: Number(e.target.value), model_key: undefined })}
            >
              {gssModels.map((m) => (
                <option key={m.key} value={m.year!}>
                  {m.year} {m.installed ? "· installed" : ""}
                  {m.loaded ? " · loaded" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {family === "wvs" && (
          <label className="field">
            <span>Survey year (hard-conditions A_YEAR when supported)</span>
            <select
              disabled={disabled}
              value={String(val("year", resolved.year) ?? "")}
              onChange={(e) => set({ year: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">(not conditioned)</option>
              {(capabilities?.year_values?.length ? capabilities.year_values : [String(resolved.year ?? "")])
                .filter(Boolean)
                .map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
            </select>
          </label>
        )}
        {family === "afrobarometer" && (
          <label className="field">
            <span>Afrobarometer round (each round is a separate native model)</span>
            <select
              disabled={disabled}
              value={(val("model_key", resolved.model_key) as string) ?? ""}
              onChange={(e) => set({ model_key: e.target.value })}
            >
              {afroModels.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label} {m.installed ? "· installed" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {family === "eurobarometer" && (
          <div>
            <div className="row" style={{ marginBottom: 6 }}>
              <label>
                <input
                  type="radio"
                  disabled={disabled || !props.ebDatesAvailable}
                  checked={ebMode === "date"}
                  onChange={() => set({ date: resolved.date || "", za: undefined })}
                />{" "}
                By survey date
              </label>
              <label>
                <input
                  type="radio"
                  disabled={disabled}
                  checked={ebMode === "za"}
                  onChange={() => set({ za: resolved.za || "", date: undefined })}
                />{" "}
                Explicit ZA
              </label>
            </div>
            {ebMode === "date" ? (
              <label className="field">
                <span>Fieldwork date (routes to one discrete wave)</span>
                <input
                  type="date"
                  disabled={disabled}
                  value={(val("date", resolved.date) as string) || ""}
                  onChange={(e) => set({ date: e.target.value, za: undefined })}
                />
              </label>
            ) : (
              <label className="field">
                <span>Eurobarometer study (ZA)</span>
                <select
                  disabled={disabled}
                  value={(val("za", resolved.za) as string) || ""}
                  onChange={(e) => set({ za: e.target.value, date: undefined })}
                >
                  {ebModels.map((m) => {
                    const w = m.za ? ebByZa.get(m.za) : undefined;
                    return (
                      <option key={m.key} value={m.za || ""}>
                        {m.za} {w ? `· ${w.fieldwork_start} … ${w.fieldwork_end}` : "· no fieldwork dates"}
                        {m.installed ? " · installed" : ""}
                      </option>
                    );
                  })}
                </select>
              </label>
            )}
            {!props.ebDatesAvailable && (
              <div className="note">Date routing unavailable: no fieldwork-date registry on the server.</div>
            )}
            <div className="note">
              Resolved: <b className="mono">{resolved.za || "—"}</b>
              {(() => {
                const fw = (resolved.temporal as { fieldwork?: EBWave | null })?.fieldwork;
                return fw ? ` · fieldwork ${fw.fieldwork_start} … ${fw.fieldwork_end}` : "";
              })()}
            </div>
          </div>
        )}
      </Section>

      <Section title="Survey response behaviour">
        <div className="row">
          <label className="field">
            <span>Semantic fallback</span>
            <select
              disabled={disabled}
              value={(val("semantic_fallback", run.semantic_fallback) as string) || "answer_only"}
              onChange={(e) => set({ semantic_fallback: e.target.value })}
            >
              <option value="off">off</option>
              <option value="answer_only">answer_only</option>
              <option value="update_state">update_state</option>
            </select>
          </label>
          <label className="field">
            <span>Response mode (anchor)</span>
            <select
              disabled={disabled}
              value={(val("resp_mode", run.resp_mode) as string) || "max"}
              onChange={(e) => set({ resp_mode: e.target.value })}
            >
              <option value="max">max (modal response)</option>
              <option value="draw">draw (sample distribution)</option>
            </select>
          </label>
        </div>
        <label className="field" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input
            type="checkbox"
            disabled={disabled || !model?.ideology_available}
            checked={Boolean(val("ideology", resolved.ideology)) && Boolean(model?.ideology_available)}
            onChange={(e) => set({ ideology: e.target.checked })}
          />
          <span style={{ display: "inline", margin: 0 }}>
            Ideology tracking{" "}
            {model?.ideology_available ? `(${model.polar_sets.join(", ")})` : "— polar vectors unavailable for this survey"}
          </span>
        </label>
        <details>
          <summary className="note" style={{ cursor: "pointer" }}>
            Advanced parameters
          </summary>
          <div className="grid2" style={{ marginTop: 6 }}>
            {ADVANCED.map((a) => (
              <label className="field" key={a.key}>
                <span>{a.label}</span>
                <input
                  type="number"
                  step={a.step ?? 1}
                  disabled={disabled}
                  value={String(val(a.key, run[a.key as string]) ?? "")}
                  onChange={(e) => set({ [a.key]: e.target.value === "" ? undefined : Number(e.target.value) })}
                />
              </label>
            ))}
            <label className="field">
              <span>Semantic response mode</span>
              <select
                disabled={disabled}
                value={(val("semantic_resp_mode", run.semantic_resp_mode) as string) || "max"}
                onChange={(e) => set({ semantic_resp_mode: e.target.value })}
              >
                <option value="max">max</option>
                <option value="draw">draw</option>
              </select>
            </label>
          </div>
          <div className="note">
            LLM model: <span className="mono">{String(run.openai_model ?? "server default")}</span> (server-configured)
          </div>
        </details>
      </Section>
    </div>
  );
}
