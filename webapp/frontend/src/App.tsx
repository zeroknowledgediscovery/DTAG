import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Chat } from "./components/Chat";
import { Controls, Section, type Geography } from "./components/Controls";
import { ModelChooser } from "./components/ModelChooser";
import { ModelPanel } from "./components/ModelPanel";
import { ProfileBuilder } from "./components/ProfileBuilder";
import { StatePanel } from "./components/StatePanel";
import type {
  CountryInfo,
  EBWave,
  ModelRecord,
  ModelStatus,
  Overrides,
  Profile,
  QuestionResult,
  Readiness,
  Recommendation,
  SessionInfo,
  Suggestion,
} from "./types";

const familyOf = (key: string) => key.split("/", 1)[0];
const gssYear = (key: string) => {
  const m = /^gss\/gss_(\d{4})$/.exec(key);
  return m ? Number(m[1]) : undefined;
};
const BUSY_STATES = ["downloading", "verifying", "extracting", "loading"];

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

  // respondent: who / where / when
  const [preset, setPreset] = useState<string>("");
  const [persona, setPersona] = useState("");
  const [country, setCountry] = useState("");
  const [continent, setContinent] = useState("");
  const [year, setYear] = useState<string>("");
  const [date, setDate] = useState<string>("");

  // model choice
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  const [manual, setManual] = useState<string | null>(null);
  const [liveState, setLiveState] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<ModelStatus | undefined>();

  // behaviour + validation
  const [behaviour, setBehaviour] = useState<Overrides>({});
  const [resolved, setResolved] = useState<Profile | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);

  // session
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [history, setHistory] = useState<QuestionResult[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [phase, setPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [builder, setBuilder] = useState(false);
  const polling = useRef<Set<string>>(new Set());

  const loadReadiness = (refresh = false) => api.readiness(refresh).then(setReadiness).catch((e) => setError(String(e.message)));
  const loadProfiles = () => api.profiles().then(setProfiles);
  const loadModels = () => api.models().then(setModels);

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

  const presetProfile = profiles.find((p) => p.name === preset);

  const applyPreset = (name: string) => {
    setPreset(name);
    setManual(null);
    setChosen(null);
    setBehaviour({});
    const p = profiles.find((x) => x.name === name);
    if (!p) return;
    setPersona(p.persona || "");
    setCountry(p.country || "");
    setContinent(p.continent || "");
    setYear(p.year ? String(p.year) : "");
    setDate(p.date || "");
  };

  // Start from the first configured preset so the page opens ready to go.
  useEffect(() => {
    if (!preset && !persona && profiles.length) {
      const first = profiles.find((p) => p.name === "gss2024_cm") || profiles.find((p) => !p.error);
      if (first) applyPreset(first.name);
    }
  }, [profiles]); // eslint-disable-line react-hooks/exhaustive-deps

  // Recommend native models whenever who/where/when changes.
  useEffect(() => {
    if (!persona && !country && !year && !date) return;
    let cancelled = false;
    setRecLoading(true);
    const t = setTimeout(() => {
      api
        .recommend({
          persona,
          country,
          year: year ? Number(year) : null,
          date: date || null,
          preferred_model: presetProfile?.model_key ?? null,
        })
        .then((r) => {
          if (cancelled) return;
          setRec(r);
          setChosen((c) => (c && r.candidates.some((x) => x.model_key === c) ? c : null));
        })
        .catch((e) => !cancelled && setError(String(e.message || e)))
        .finally(() => !cancelled && setRecLoading(false));
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [persona, country, year, date, presetProfile?.model_key]);

  const effectiveKey: string | null = manual ?? (chosen && rec?.candidates.some((c) => c.model_key === chosen) ? chosen : rec?.default ?? null);
  const candidate = rec?.candidates.find((c) => c.model_key === effectiveKey);
  const model = models.find((m) => m.key === effectiveKey);

  // The exact session request for the chosen model.
  const request = useMemo(() => {
    if (!effectiveKey) return null;
    const fam = familyOf(effectiveKey);
    const base = presetProfile && presetProfile.family === fam ? presetProfile.name : undefined;
    const ov: Overrides = { ...behaviour, model_key: effectiveKey };
    if (persona.trim()) ov.persona = persona;
    const resolvedCountry = country.trim() || (rec?.resolved.sources.country === "description" ? rec.resolved.country : "");
    if (resolvedCountry) ov.country = resolvedCountry;
    if (base && continent) ov.continent = continent;
    if (!manual && candidate) Object.assign(ov, candidate.overrides);
    if (fam === "gss") ov.year = gssYear(effectiveKey);
    else if (!ov.year && !manual && year && fam !== "eurobarometer") ov.year = Number(year);
    return { base_profile: base, model_key: base ? undefined : effectiveKey, overrides: ov };
  }, [effectiveKey, presetProfile, behaviour, persona, country, continent, year, manual, candidate, rec]);

  // Resolve/validate the request (warnings, run defaults, capabilities).
  useEffect(() => {
    if (!request) return;
    let cancelled = false;
    setValidating(true);
    const t = setTimeout(() => {
      api
        .validateProfile(request)
        .then((r) => {
          if (cancelled) return;
          setResolved(r);
          setValidationError(null);
        })
        .catch((e) => !cancelled && setValidationError(String(e.message || e)))
        .finally(() => !cancelled && setValidating(false));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [request]);

  // Poll a model install/load job until it settles.
  const pollModel = useCallback(async (key: string): Promise<ModelStatus> => {
    polling.current.add(key);
    try {
      for (;;) {
        const st = await api.modelStatus(key);
        setLiveState((s) => ({ ...s, [key]: st.state }));
        setStatus((cur) => (cur?.key === key || !cur ? st : cur));
        if (!st.job_running && !BUSY_STATES.includes(st.state)) return st;
        await new Promise((r) => setTimeout(r, 600));
      }
    } finally {
      polling.current.delete(key);
    }
  }, []);

  const ensureLoaded = useCallback(
    async (key: string): Promise<void> => {
      let st = await api.modelStatus(key);
      setStatus(st);
      if (st.state === "loaded") return;
      if (!st.job_running) st = await api.installModel(key, true);
      st = await pollModel(key);
      if (st.state === "error") throw new Error(st.error || "model install failed");
      if (st.state !== "loaded") {
        await api.installModel(key, true);
        st = await pollModel(key);
        if (st.state !== "loaded") throw new Error(st.error || `model ${key} did not load`);
      }
      loadModels();
      loadReadiness();
    },
    [pollModel]
  );

  // Automatically download (if needed) and load the chosen model.
  useEffect(() => {
    if (!effectiveKey) return;
    let cancelled = false;
    setStatus(undefined);
    const t = setTimeout(() => {
      if (cancelled || polling.current.has(effectiveKey)) return;
      ensureLoaded(effectiveKey).catch((e) => !cancelled && setError(String(e.message || e)));
    }, 700);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [effectiveKey, ensureLoaded]);

  const refreshSuggestions = (sid: string) =>
    api.suggestions(sid).then(setSuggestions).catch(() => setSuggestions([]));

  const start = async () => {
    if (!request || !effectiveKey) return;
    setError(null);
    try {
      setPhase("Getting the native model ready…");
      await ensureLoaded(effectiveKey);
      setPhase("Initializing respondent (persona interpretation, conditioning, initial ideology)…");
      if (session) api.deleteSession(session.session_id).catch(() => undefined);
      const s = await api.createSession({
        profile: request.base_profile,
        model_key: request.model_key,
        overrides: request.overrides,
      });
      setSession(s);
      setHistory([]);
      refreshSuggestions(s.session_id);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setPhase(null);
      loadModels();
      loadReadiness();
    }
  };

  const ask = async (q: string) => {
    if (!session) return;
    setPending(q);
    setError(null);
    try {
      const r = await api.ask(session.session_id, q);
      setHistory((h) => [...h, r]);
      setSession(await api.session(session.session_id));
      refreshSuggestions(session.session_id);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setPending(null);
    }
  };

  const reset = async () => {
    if (!session) return;
    try {
      setSession(await api.reset(session.session_id));
      setHistory([]);
      refreshSuggestions(session.session_id);
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const saveCurrent = async () => {
    if (!request) return;
    const name = window.prompt("Name for the custom profile (letters, digits, _ - .):");
    if (!name) return;
    try {
      await api.saveProfile({
        name,
        base_profile: request.base_profile,
        model_key: request.model_key,
        overrides: request.overrides,
        description: `${resolved?.model_label ?? effectiveKey} · ${country || rec?.resolved.country || ""}`,
      });
      await loadProfiles();
      setPreset(name);
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const busy = Boolean(phase) || Boolean(pending);
  const modelBusy = effectiveKey ? BUSY_STATES.includes(liveState[effectiveKey] || "") : false;
  const src = rec?.resolved.sources;

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          DTAG<small>Digital Twin Anchored Generation · native LSM workbench</small>
        </div>
        <ReadinessBar r={readiness} onRefresh={() => loadReadiness(true)} />
        <span className="spacer" />
        <a href="/docs" target="_blank" rel="noreferrer">
          API docs
        </a>
        {readiness && (readiness as unknown as { auth?: string }).auth === "password" && (
          <a href="/api/logout">Sign out</a>
        )}
      </div>

      <div className="main">
        <div className="col left">
          <Section title="Respondent">
            <label className="field">
              <span>Start from a preset (optional)</span>
              <select value={preset} disabled={busy} onChange={(e) => applyPreset(e.target.value)}>
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
                value={persona}
                placeholder="e.g. 35 year old teacher in Nairobi, Kenya, regular news consumer"
                onChange={(e) => setPersona(e.target.value)}
              />
            </label>
            <div className="row">
              <label className="field">
                <span>Where — country</span>
                <input
                  type="text"
                  list="dtag-country-list"
                  disabled={busy}
                  value={country}
                  placeholder={src?.country === "description" ? `${rec?.resolved.country} (from description)` : "any country"}
                  onChange={(e) => setCountry(e.target.value)}
                />
                <datalist id="dtag-country-list">
                  {countries.map((c) => (
                    <option key={c.key} value={c.name}>
                      {c.families.join(", ")}
                    </option>
                  ))}
                </datalist>
              </label>
              <label className="field" style={{ maxWidth: 92 }}>
                <span>When — year</span>
                <input
                  type="number"
                  min={1950}
                  max={2035}
                  disabled={busy}
                  value={year}
                  placeholder={src?.year === "description" ? String(rec?.resolved.year) : "latest"}
                  onChange={(e) => setYear(e.target.value)}
                />
              </label>
            </div>
            <details open={Boolean(date)}>
              <summary className="note" style={{ cursor: "pointer" }}>
                Exact date (routes Eurobarometer to one fieldwork wave)
              </summary>
              <input type="date" disabled={busy} value={date} onChange={(e) => setDate(e.target.value)} />
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
              loading={recLoading}
              chosen={effectiveKey}
              manual={manual}
              onChoose={(k) => {
                setManual(null);
                setChosen(k);
              }}
              onManual={setManual}
              liveState={liveState}
              models={models}
              disabled={busy}
            />
            {(liveState[effectiveKey ?? ""] ?? model?.status.state) !== "loaded" && (
            <div style={{ marginTop: 8 }}>
              <ModelPanel
                model={model}
                status={status && status.key === effectiveKey ? status : undefined}
                onInstall={() => effectiveKey && ensureLoaded(effectiveKey).catch((e) => setError(String(e.message)))}
                busy={busy || modelBusy}
              />
            </div>
            )}
          </Section>

          <Controls
            only={["behaviour"]}
            resolved={resolved}
            overrides={behaviour}
            onChange={setBehaviour}
            models={models}
            ebWaves={ebWaves}
            ebDatesAvailable={ebDates}
            capabilities={resolved?.capabilities}
            geography={geography}
            disabled={busy}
          />

          {validationError && <div className="error">{validationError}</div>}
          {resolved && resolved.warnings.length > 0 && (
            <details>
              <summary className="note" style={{ cursor: "pointer" }}>
                Conditioning details ({resolved.warnings.length})
              </summary>
              <ul className="warn-list">
                {resolved.warnings.map((w) => (
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
              onClick={start}
              disabled={busy || validating || !request || !!validationError}
              title={modelBusy ? "The model is still downloading/loading; starting will wait for it." : ""}
            >
              {session ? "Start new respondent" : "Start respondent"}
            </button>
            <button className="btn" onClick={reset} disabled={busy || !session}>
              Reset respondent
            </button>
          </div>
          <div className="actions" style={{ marginTop: 6 }}>
            <button className="link" onClick={saveCurrent} disabled={busy || !request || !!validationError}>
              Save as custom profile
            </button>
            <button className="link" onClick={() => setBuilder(true)} disabled={busy}>
              Advanced profile builder…
            </button>
            {presetProfile?.source === "custom" && (
              <button
                className="link"
                onClick={async () => {
                  if (!window.confirm(`Delete custom profile ${presetProfile.name}?`)) return;
                  await api.deleteProfile(presetProfile.name);
                  setPreset("");
                  loadProfiles();
                }}
              >
                Delete preset
              </button>
            )}
          </div>
          {phase && (
            <div className="box" style={{ marginTop: 8 }}>
              <span className="spinner" /> {phase}
            </div>
          )}
          {error && (
            <div className="error" style={{ marginTop: 8 }}>
              {error}
            </div>
          )}
        </div>

        <div className="center">
          <Chat
            history={history}
            pending={pending}
            canAsk={Boolean(session) && !busy}
            onAsk={ask}
            suggestions={session ? suggestions : []}
            emptyHint={
              session ? (
                <>
                  Respondent ready ({session.resolved_profile.model_label}). Ask a question below or pick one of the suggested
                  questions; every answer is anchored to native LSM conditional survey-response distributions and the survey
                  state carries forward between questions.
                </>
              ) : (
                <>
                  Describe the respondent (<b>who</b>, <b>where</b>, <b>when</b>). DTAG picks the matching native survey model,
                  downloads it once if needed and loads it; then start the respondent.
                </>
              )
            }
          />
        </div>

        <div className="col right">
          <StatePanel session={session} history={history} />
        </div>
      </div>

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
            applyPreset(name);
          }}
          onUse={(d) => {
            setBuilder(false);
            const o = d.overrides;
            if (o.persona) setPersona(o.persona);
            if (o.country !== undefined) setCountry(o.country);
            setDate(o.date || "");
            setYear(o.year ? String(o.year) : "");
            setManual(d.model_key || o.model_key || null);
          }}
        />
      )}
    </div>
  );
}
