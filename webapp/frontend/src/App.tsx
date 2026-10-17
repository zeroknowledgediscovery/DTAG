import { useEffect, useState } from "react";
import { api, fmtSigned } from "./api";
import { ChatLog, Composer, type ComposerChip } from "./components/Chat";
import { Section, type Geography } from "./components/Controls";
import { ProfileBuilder } from "./components/ProfileBuilder";
import { RespondentSetup } from "./components/RespondentSetup";
import { SequenceCard, SequenceDialog } from "./components/Sequence";
import { IdeologyPush } from "./components/IdeologyPush";
import { IdeologyCompare, StatePanel } from "./components/StatePanel";
import type { CountryInfo, EBWave, ModelRecord, Profile, Readiness } from "./types";
import { useModelLoader, useRespondent, type Respondent } from "./useRespondent";

/** Respondent identity: label, color token and marker (color is never the only cue). */
const SLOTS = [
  { id: "A", label: "Respondent A", color: "var(--resp-a)", marker: "circle" as const, dashed: false, prefix: "a-" },
  { id: "B", label: "Respondent B", color: "var(--resp-b)", marker: "square" as const, dashed: true, prefix: "b-" },
];
type Target = "both" | "A" | "B";

function ReadinessPill({ r, onRefresh }: { r: Readiness | null; onRefresh: () => void }) {
  const [open, setOpen] = useState(false);
  if (!r) return <div className="readiness note">checking…</div>;
  const ok = r.status === "ready";
  const llm =
    r.llm.backend === "mock" ? "mock LLM" : r.llm.openai_configured ? `OpenAI · ${r.llm.default_openai_model}` : "no OpenAI key";
  const llmWarn = r.llm.backend !== "mock" && !r.llm.openai_configured;
  return (
    <div className="readiness-wrap">
      <button
        className={`status-pill ${ok && !llmWarn ? "ok" : "bad"}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title="System status"
      >
        <span className="dot" /> {ok ? "Ready" : "Degraded"} · {llm}
      </button>
      {open && (
        <div className="status-pop" role="dialog" aria-label="System status">
          <dl className="summary">
            <dt>Native runtime</dt>
            <dd>{r.native_runtime.available ? r.native_runtime.runtime : "unavailable"}</dd>
            <dt>Public catalog</dt>
            <dd>{r.public_catalog.reachable ? `${r.public_catalog.models} models (${r.public_catalog.release})` : "unreachable"}</dd>
            <dt>Semantic maps</dt>
            <dd>{r.semantic_maps.matched_to_catalog} matched</dd>
            <dt>Installed</dt>
            <dd>{r.model_cache.installed}</dd>
            <dt>Loaded</dt>
            <dd>{r.models_resident.loaded}</dd>
            <dt>LLM</dt>
            <dd>{r.llm.backend === "mock" ? "MOCK (no OpenAI calls)" : llm}</dd>
          </dl>
          <button className="link" onClick={onRefresh}>
            refresh
          </button>
        </div>
      )}
    </div>
  );
}

/** Compact card replacing the setup form once a respondent is running. */
function RespondentSummary({ r, onEdit }: { r: Respondent; onEdit: () => void }) {
  const s = r.session!;
  const ide = s.ideology;
  // The session's persona text carries appended context lines (country/year); show the description only.
  const persona = s.persona_text.split(/\n(?:Region context|Country context|Survey year):/)[0].trim();
  return (
    <div className="box resp-summary">
      <div className="resp-summary-h">
        <b>{s.resolved_profile.model_label}</b>
        {ide.enabled && ide.current !== null && <span className="mono">I {ide.current.toFixed(4)}</span>}
      </div>
      <div className="resp-persona" title={persona}>
        {persona}
      </div>
      <div className="note">
        {[s.resolved_profile.country, s.temporal_conditioning.wave].filter(Boolean).join(" · ")} · {s.question_count} question
        {s.question_count === 1 ? "" : "s"}
      </div>
      <div className="actions" style={{ marginTop: 8 }}>
        <button className="btn" onClick={onEdit} disabled={r.busy}>
          Edit / new respondent
        </button>
        <button className="btn" onClick={r.reset} disabled={r.busy}>
          Reset
        </button>
      </div>
      {r.error && <div className="error">{r.error}</div>}
    </div>
  );
}

/** One-step optimizer suggestions for a respondent whose survey has an ideology index. */
function pushPanel(r: Respondent) {
  if (!r.session || !r.session.ideology.enabled) return null;
  return (
    <Section title="Next question">
      <IdeologyPush
        push={r.push}
        loading={r.pushLoading}
        includePoles={r.pushPoles}
        onIncludePoles={r.setPushPoles}
        disabled={r.busy}
        onAsk={r.askPush}
        onAuto={r.runAutoPush}
      />
    </Section>
  );
}

/** Progress / summary card of the respondent's latest question sequence or automatic push. */
function seqCard(r: Respondent, sl: (typeof SLOTS)[number], labelled: boolean) {
  if (!r.seq || !r.session || r.seq.session_id !== r.session.session_id) return null;
  return (
    <div key={`seq-${sl.id}`}>
      {labelled && (
        <div className="note">
          <span className="swatch" style={{ background: sl.color }} /> {sl.label}
        </div>
      )}
      <SequenceCard
        seq={r.seq}
        onCancel={r.cancelSequence}
        onJump={(i) => document.getElementById(`${sl.prefix}q-${i}`)?.scrollIntoView({ behavior: "smooth" })}
      />
    </div>
  );
}

/** Subtle mark shown in the left column once the setup form has collapsed. */
function LabMark() {
  return (
    <div className="lab-mark" aria-hidden="true">
      <svg viewBox="0 0 64 64" width="44" height="44">
        <g fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
          <path d="M32 12 L16 34 M32 12 L48 34 M16 34 L24 52 M16 34 L8 52 M48 34 L40 52 M48 34 L56 52" />
        </g>
        <g fill="currentColor">
          <circle cx="32" cy="12" r="5" />
          <circle cx="16" cy="34" r="4" />
          <circle cx="48" cy="34" r="4" />
          <circle cx="8" cy="52" r="3" />
          <circle cx="24" cy="52" r="3" />
          <circle cx="40" cy="52" r="3" />
          <circle cx="56" cy="52" r="3" />
        </g>
      </svg>
      <div className="lab-name">DTAG Lab</div>
      <div className="lab-sub">Digital Twin Anchored Generation</div>
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
  // Setup form collapses to a summary once a respondent runs; "Edit" reopens it until the next start.
  const [editOpen, setEditOpen] = useState<Record<string, boolean>>({});
  const aSid = A.session?.session_id;
  const bSid = B.session?.session_id;
  useEffect(() => setEditOpen((e) => ({ ...e, A: false })), [aSid]);
  useEffect(() => setEditOpen((e) => ({ ...e, B: false })), [bSid]);

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

  // Composer chips: the next ideology-push questions of the respondent being asked (not for "both").
  const chipSource = count === 1 ? A : target === "A" ? A : target === "B" ? B : null;
  const composerChips: ComposerChip[] = [];
  if (chipSource?.session && chipSource.push?.enabled) {
    for (const s of [chipSource.push.up, chipSource.push.down]) {
      if (!s) continue;
      composerChips.push({
        key: s.direction,
        label: (
          <>
            <span className="push-arrow">{s.direction === "up" ? "↑" : "↓"}</span>
            {s.question}
            <span className="mono push-delta">{fmtSigned(s.predicted_delta, 3)}</span>
          </>
        ),
        title: `Ideology push ${s.direction === "up" ? "toward the R pole" : "toward the L pole"}: asks survey item ${s.variable}`,
        onClick: () => chipSource.askPush(s),
      });
    }
  }

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
        <ReadinessPill r={readiness} onRefresh={() => loadReadiness(true)} />
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
              {r.session && !editOpen[sl.id] && !r.phase ? (
                <>
                  <RespondentSummary r={r} onEdit={() => setEditOpen((e) => ({ ...e, [sl.id]: true }))} />
                  <LabMark />
                </>
              ) : (
                <>
                  {r.session && (
                    <button className="link" style={{ marginBottom: 6 }} onClick={() => setEditOpen((e) => ({ ...e, [sl.id]: false }))}>
                      ← back to the running respondent
                    </button>
                  )}
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
                </>
              )}
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
            chips={composerChips}
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
          {count === 2 ? (
            <>
              <Section title="Ideology · A vs B">
                <IdeologyCompare
                  items={pair.map(([r, sl]) => ({ label: sl.label, color: sl.color, marker: sl.marker, dashed: sl.dashed, session: r.session }))}
                />
              </Section>
              {pair.map(([r, sl]) => seqCard(r, sl, true))}
              {A.session && B.session && (
                <div className="actions" style={{ marginBottom: 10 }}>
                  <a
                    className="btn primary-link"
                    href={api.bundleUrl([A.session.session_id, B.session.session_id], ["A", "B"])}
                    download
                    title="One ZIP with each respondent's complete log and an aligned ideology comparison"
                  >
                    Download both logs (ZIP)
                  </a>
                </div>
              )}
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
                  <StatePanel session={r.session} history={r.history} idPrefix={sl.prefix} color={sl.color} label={sl.id} hideIdeology>
                    {pushPanel(r)}
                  </StatePanel>
                </div>
              ))}
            </>
          ) : (
            <StatePanel session={A.session} history={A.history} idPrefix={SLOTS[0].prefix}>
              {pushPanel(A)}
              {seqCard(A, SLOTS[0], false)}
            </StatePanel>
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
