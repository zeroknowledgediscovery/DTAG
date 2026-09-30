import { useEffect, useState } from "react";
import { api } from "./api";
import { ChatLog, Composer } from "./components/Chat";
import { Section, type Geography } from "./components/Controls";
import { ProfileBuilder } from "./components/ProfileBuilder";
import { RespondentSetup } from "./components/RespondentSetup";
import { SequenceCard, SequenceDialog } from "./components/Sequence";
import { IdeologyCompare, StatePanel } from "./components/StatePanel";
import type { CountryInfo, EBWave, ModelRecord, Profile, Readiness } from "./types";
import { useModelLoader, useRespondent, type Respondent } from "./useRespondent";

/** Respondent identity: label, color token and marker (color is never the only cue). */
const SLOTS = [
  { id: "A", label: "Respondent A", color: "var(--resp-a)", marker: "circle" as const, dashed: false, prefix: "a-" },
  { id: "B", label: "Respondent B", color: "var(--resp-b)", marker: "square" as const, dashed: true, prefix: "b-" },
];
type Target = "both" | "A" | "B";

function ReadinessBar({ r, onRefresh }: { r: Readiness | null; onRefresh: () => void }) {
  if (!r) return <div className="readiness">checking readiness…</div>;
  const ok = r.status === "ready";
  return (
    <div className="readiness">
      <span>
        <span className={`badge ${ok ? "b-direct" : "b-nomatch"}`}>{ok ? "DTAG READY" : "DEGRADED"}</span>
      </span>
      <span>
        Native runtime <b>{r.native_runtime.available ? r.native_runtime.runtime : "unavailable"}</b>
      </span>
      <span>
        Public catalog <b>{r.public_catalog.reachable ? `${r.public_catalog.models} models` : "unreachable"}</b> ({r.public_catalog.release})
      </span>
      <span>
        Semantic maps <b>{r.semantic_maps.matched_to_catalog}</b> matched
      </span>
      <span>
        Installed <b>{r.model_cache.installed}</b>
      </span>
      <span>
        Resident <b>{r.models_resident.loaded}</b>
      </span>
      <span>
        LLM{" "}
        <b>
          {r.llm.backend === "mock"
            ? "MOCK (no OpenAI calls)"
            : r.llm.openai_configured
              ? `OpenAI · ${r.llm.default_openai_model}`
              : "OpenAI not configured"}
        </b>
      </span>
      <button className="link" onClick={onRefresh}>
        refresh
      </button>
    </div>
  );
}

export default function App() {
  // catalog / environment
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [maps, setMaps] = useState<Array<{ key: string; family: string | null }>>([]);
  const [ebWaves, setEbWaves] = useState<EBWave[]>([]);
  const [ebDates, setEbDates] = useState(false);
  const [geography, setGeography] = useState<Geography>({ countries: [], continents: [] });
  const [countries, setCountries] = useState<CountryInfo[]>([]);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const loadReadiness = (refresh = false) =>
    api.readiness(refresh).then(setReadiness).catch((e) => setGlobalError(String(e.message)));
  const loadProfiles = () => api.profiles().then(setProfiles);
  const loadModels = () => api.models().then(setModels);
  const refreshCatalog = () => {
    loadModels();
    loadReadiness();
  };

  useEffect(() => {
    loadReadiness();
    loadModels();
    loadProfiles();
    api.maps().then(setMaps);
    api.countries().then(setCountries).catch(() => undefined);
    api.ebWaves().then((r) => {
      setEbWaves(r.waves);
      setEbDates(r.date_registry_available);
    });
    fetch("/api/geography")
      .then((r) => r.json())
      .then(setGeography)
      .catch(() => undefined);
  }, []);

  // One shared model loader; two fully independent respondents.
  const loader = useModelLoader(refreshCatalog);
  const A = useRespondent({ profiles, models, loader, defaultPreset: "gss2024_cm", onChanged: refreshCatalog });
  const B = useRespondent({ profiles, models, loader, defaultPreset: "gss2024_wf", onChanged: refreshCatalog });

  const [count, setCount] = useState<1 | 2>(() => {
    try {
      return window.localStorage.getItem("dtag.respondents") === "2" ? 2 : 1;
    } catch {
      return 1;
    }
  });
  const [tab, setTab] = useState<"A" | "B">("A");
  const [target, setTarget] = useState<Target>("both");
  const [builder, setBuilder] = useState(false);
  const [seqOpen, setSeqOpen] = useState(false);

  const setMode = (n: 1 | 2) => {
    setCount(n);
    if (n === 1) setTab("A");
    try {
      window.localStorage.setItem("dtag.respondents", String(n));
    } catch {
      /* per-viewer convenience only */
    }
  };

  const pair: Array<[Respondent, (typeof SLOTS)[number]]> = [[A, SLOTS[0]], [B, SLOTS[1]]];
  const active = count === 2 ? pair : pair.slice(0, 1);
  const editing = tab === "B" && count === 2 ? B : A;

  // Who a question goes to: in single mode A; in split mode the target selector.
  const targets = (): Respondent[] => {
    if (count === 1) return [A];
    const want = target === "both" ? [A, B] : target === "A" ? [A] : [B];
    return want.filter((r) => r.session);
  };
  const askTargets = targets();
  const canAsk = askTargets.length > 0 && askTargets.every((r) => r.session && !r.busy);
  const ask = (q: string) => {
    // Simultaneous: each respondent answers independently on its own session.
    askTargets.forEach((r) => r.ask(q));
  };

  const saveCurrent = async (r: Respondent) => {
    if (!r.request) return;
    const name = window.prompt("Name for the custom profile (letters, digits, _ - .):");
    if (!name) return;
    try {
      await api.saveProfile({
        name,
        base_profile: r.request.base_profile,
        model_key: r.request.model_key,
        overrides: r.request.overrides,
        description: `${r.resolved?.model_label ?? r.effectiveKey} · ${r.country || r.rec?.resolved.country || ""}`,
      });
      await loadProfiles();
      r.setPreset(name);
    } catch (e) {
      r.setError(String((e as Error).message));
    }
  };

  const deletePreset = async (r: Respondent) => {
    const p = r.presetProfile;
    if (!p || !window.confirm(`Delete custom profile ${p.name}?`)) return;
    await api.deleteProfile(p.name);
    r.setPreset("");
    loadProfiles();
  };

  const startBoth = () => {
    [A, B].forEach((r) => {
      if (!r.busy && r.request && !r.validationError && !r.validating) r.start();
    });
  };
  const canStartBoth = [A, B].every((r) => !r.busy && r.request && !r.validationError);

  const emptyHint = (r: Respondent, label: string) =>
    r.session ? (
      <>
        {label} ready ({r.session.resolved_profile.model_label}). Ask a question below
        {count === 1 ? " or pick one of the suggested questions" : ""}; every answer is anchored to native LSM conditional
        survey-response distributions and the survey state carries forward between questions.
      </>
    ) : (
      <>
        Describe {count === 2 ? label.toLowerCase() : "the respondent"} (<b>who</b>, <b>where</b>, <b>when</b>). DTAG picks the
        matching native survey model, downloads it once if needed and loads it; then start the respondent.
      </>
    );

  // Suggestions for the composer row: from A in single mode or when targeting A; from B when targeting B.
  const sugSource = count === 2 && target === "B" ? B : A;
  const composerSuggestions =
    count === 1 ? (A.history.length > 0 ? A.suggestions : []) : sugSource.session ? sugSource.suggestions : [];

  const seqTargets = askTargets;
  const seqLabel = seqTargets
    .map((r) => `${count === 2 ? (r === A ? "A: " : "B: ") : ""}${r.session?.resolved_profile.model_label ?? ""}`)
    .join(" and ");

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          DTAG<small>Digital Twin Anchored Generation · native LSM workbench</small>
        </div>
        <ReadinessBar r={readiness} onRefresh={() => loadReadiness(true)} />
        <span className="spacer" />
        <div className="seg" role="radiogroup" aria-label="Number of respondents">
          <span className="note">Respondents</span>
          {[1, 2].map((n) => (
            <button
              key={n}
              role="radio"
              aria-checked={count === n}
              className={count === n ? "on" : ""}
              disabled={n === 1 && B.busy}
              onClick={() => setMode(n as 1 | 2)}
            >
              {n}
            </button>
          ))}
        </div>
        <a href="/docs" target="_blank" rel="noreferrer">
          API docs
        </a>
        {readiness && (readiness as unknown as { auth?: string }).auth === "password" && <a href="/api/logout">Sign out</a>}
      </div>

      <div className={`main ${count === 2 ? "two" : ""}`}>
        <div className="col left">
          {count === 2 && (
            <>
              <div className="tabs" role="tablist">
                {SLOTS.map((sl) => {
                  const r = sl.id === "A" ? A : B;
                  return (
                    <button
                      key={sl.id}
                      role="tab"
                      aria-selected={tab === sl.id}
                      className={tab === sl.id ? "on" : ""}
                      onClick={() => setTab(sl.id as "A" | "B")}
                    >
                      <span className="swatch" style={{ background: sl.color }} />
                      {sl.label}
                      {r.session ? <span className="tab-ok" title="started">✓</span> : r.phase ? <span className="spinner" /> : null}
                    </button>
                  );
                })}
              </div>
              <div className="actions" style={{ marginBottom: 10 }}>
                <button className="btn primary" onClick={startBoth} disabled={!canStartBoth}>
                  {A.session || B.session ? "Restart both" : "Start both respondents"}
                </button>
              </div>
            </>
          )}
          {pair.map(([r, sl]) => (
            <div key={sl.id} className="setup" hidden={editing !== r}>
              <RespondentSetup
                r={r}
                label={count === 2 ? sl.id : undefined}
                profiles={profiles}
                models={models}
                ebWaves={ebWaves}
                ebDates={ebDates}
                geography={geography}
                liveState={loader.liveState}
                onSave={() => saveCurrent(r)}
                onBuilder={() => setBuilder(true)}
                onDeletePreset={() => deletePreset(r)}
              />
            </div>
          ))}
          <datalist id="dtag-country-list">
            {countries.map((c) => (
              <option key={c.key} value={c.name}>
                {c.families.join(", ")}
              </option>
            ))}
          </datalist>
          {globalError && (
            <div className="error" style={{ marginTop: 8 }}>
              {globalError}
            </div>
          )}
        </div>

        <div className="center">
          <div className={count === 2 ? "split" : "single"}>
            {active.map(([r, sl]) => (
              <div key={sl.id} className="pane" style={count === 2 ? ({ "--pane": sl.color } as React.CSSProperties) : undefined}>
                {count === 2 && (
                  <div className="pane-h">
                    <span className="swatch" style={{ background: sl.color }} />
                    <b>{sl.label}</b>
                    <span className="note pane-sub" title={r.persona}>
                      {r.session ? r.session.resolved_profile.model_label : r.effectiveKey ?? "no model yet"} · {r.persona || "—"}
                    </span>
                    {r.session?.ideology.enabled && r.session.ideology.current !== null && (
                      <span className="mono pane-i">I {r.session.ideology.current.toFixed(4)}</span>
                    )}
                  </div>
                )}
                <ChatLog
                  history={r.history}
                  pending={r.pending}
                  canAsk={Boolean(r.session) && !r.busy}
                  onAsk={r.ask}
                  idPrefix={sl.prefix}
                  suggestions={r.session && count === 1 ? r.suggestions : []}
                  emptyHint={emptyHint(r, sl.label)}
                />
              </div>
            ))}
          </div>
          <Composer
            canAsk={canAsk}
            onAsk={ask}
            suggestions={composerSuggestions}
            onSequence={askTargets.length ? () => setSeqOpen(true) : undefined}
            placeholder={
              count === 1 ? "Ask this respondent a question..." : target === "both" ? "Ask both respondents the same question..." : `Ask respondent ${target} only...`
            }
            target={
              count === 2 ? (
                <select className="target" value={target} onChange={(e) => setTarget(e.target.value as Target)} aria-label="Ask whom">
                  <option value="both">Both</option>
                  <option value="A">A only</option>
                  <option value="B">B only</option>
                </select>
              ) : undefined
            }
          />
        </div>

        <div className="col right">
          {active.map(([r, sl]) =>
            r.seq && r.session && r.seq.session_id === r.session.session_id ? (
              <div key={sl.id}>
                {count === 2 && <div className="note"><span className="swatch" style={{ background: sl.color }} /> {sl.label}</div>}
                <SequenceCard
                  seq={r.seq}
                  onCancel={r.cancelSequence}
                  onJump={(i) => document.getElementById(`${sl.prefix}q-${i}`)?.scrollIntoView({ behavior: "smooth" })}
                />
              </div>
            ) : null
          )}
          {count === 2 ? (
            <>
              <Section title="Ideology · A vs B">
                <IdeologyCompare
                  items={pair.map(([r, sl]) => ({ label: sl.label, color: sl.color, marker: sl.marker, dashed: sl.dashed, session: r.session }))}
                />
              </Section>
              <div className="tabs" role="tablist">
                {SLOTS.map((sl) => (
                  <button key={sl.id} role="tab" aria-selected={tab === sl.id} className={tab === sl.id ? "on" : ""} onClick={() => setTab(sl.id as "A" | "B")}>
                    <span className="swatch" style={{ background: sl.color }} />
                    {sl.label}
                  </button>
                ))}
              </div>
              {pair.map(([r, sl]) => (
                <div key={sl.id} hidden={tab !== sl.id}>
                  <StatePanel session={r.session} history={r.history} idPrefix={sl.prefix} color={sl.color} />
                </div>
              ))}
            </>
          ) : (
            <StatePanel session={A.session} history={A.history} idPrefix={SLOTS[0].prefix} />
          )}
        </div>
      </div>

      {seqOpen && seqTargets.length > 0 && (
        <SequenceDialog
          modelLabel={seqLabel}
          ideology={seqTargets.some((r) => r.session?.ideology.enabled)}
          questionCount={Math.max(...seqTargets.map((r) => r.session?.question_count ?? 0))}
          onClose={() => setSeqOpen(false)}
          onRun={(text, name, resetFirst) => {
            setSeqOpen(false);
            seqTargets.forEach((r) => r.runSequence(text, name, resetFirst));
          }}
        />
      )}

      {builder && (
        <ProfileBuilder
          profiles={profiles}
          models={models}
          maps={maps}
          ebWaves={ebWaves}
          ebDatesAvailable={ebDates}
          geography={geography}
          onClose={() => setBuilder(false)}
          onSaved={async (name) => {
            setBuilder(false);
            await loadProfiles();
            editing.applyPreset(name);
          }}
          onUse={(d) => {
            setBuilder(false);
            const o = d.overrides;
            if (o.persona) editing.setPersona(o.persona);
            if (o.country !== undefined) editing.setCountry(o.country);
            editing.setDate(o.date || "");
            editing.setYear(o.year ? String(o.year) : "");
            editing.setManual(d.model_key || o.model_key || null);
          }}
        />
      )}
    </div>
  );
}
