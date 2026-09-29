import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Chat } from "./components/Chat";
import { Controls, Section, type Geography } from "./components/Controls";
import { ModelPanel } from "./components/ModelPanel";
import { ProfileBuilder, type Draft } from "./components/ProfileBuilder";
import { StatePanel } from "./components/StatePanel";
import type { EBWave, ModelRecord, ModelStatus, Overrides, Profile, QuestionResult, Readiness, SessionInfo } from "./types";

type Selection = { kind: "profile"; name: string } | { kind: "draft"; draft: Draft };

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
        Profiles <b>{r.configured_profiles.count}</b>
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
          {r.llm.backend === "mock" ? "MOCK (no OpenAI calls)" : r.llm.openai_configured ? `OpenAI configured · ${r.llm.default_openai_model}` : "OpenAI not configured"}
        </b>
      </span>
      <span>
        EB dates <b>{r.eurobarometer_dates.available ? `${r.eurobarometer_dates.waves} waves` : "unavailable"}</b>
      </span>
      <button className="link" onClick={onRefresh}>
        refresh
      </button>
    </div>
  );
}

export default function App() {
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [maps, setMaps] = useState<Array<{ key: string; family: string | null }>>([]);
  const [ebWaves, setEbWaves] = useState<EBWave[]>([]);
  const [ebDates, setEbDates] = useState(false);
  const [geography, setGeography] = useState<Geography>({ countries: [], continents: [] });

  const [selection, setSelection] = useState<Selection | null>(null);
  const [overrides, setOverrides] = useState<Overrides>({});
  const [resolved, setResolved] = useState<Profile | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [status, setStatus] = useState<ModelStatus | undefined>();

  const [session, setSession] = useState<SessionInfo | null>(null);
  const [history, setHistory] = useState<QuestionResult[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [phase, setPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [builder, setBuilder] = useState(false);
  const pollRef = useRef<number | null>(null);

  const loadReadiness = (refresh = false) => api.readiness(refresh).then(setReadiness).catch((e) => setError(String(e.message)));
  const loadProfiles = () => api.profiles().then(setProfiles);
  const loadModels = () => api.models().then(setModels);

  useEffect(() => {
    loadReadiness();
    loadModels();
    api.maps().then(setMaps);
    api.ebWaves().then((r) => {
      setEbWaves(r.waves);
      setEbDates(r.date_registry_available);
    });
    fetch("/api/geography")
      .then((r) => r.json())
      .then(setGeography)
      .catch(() => undefined);
    loadProfiles().then(() => undefined);
  }, []);

  useEffect(() => {
    if (!selection && profiles.length) {
      const pref = profiles.find((p) => p.name === "gss2024_cm") || profiles.find((p) => !p.error);
      if (pref) setSelection({ kind: "profile", name: pref.name });
    }
  }, [profiles, selection]);

  const request = useMemo(() => {
    if (!selection) return null;
    if (selection.kind === "profile") return { base_profile: selection.name, overrides };
    return {
      base_profile: selection.draft.base_profile,
      model_key: selection.draft.model_key,
      overrides: { ...selection.draft.overrides, ...overrides },
    };
  }, [selection, overrides]);

  // Validate/resolve the profile + overrides on the server (debounced).
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

  const model = models.find((m) => m.key === resolved?.model_key);

  const refreshStatus = useCallback(async (key: string) => {
    const st = await api.modelStatus(key);
    setStatus(st);
    return st;
  }, []);

  useEffect(() => {
    if (resolved?.model_key) refreshStatus(resolved.model_key).catch(() => undefined);
  }, [resolved?.model_key, refreshStatus]);

  const waitForModel = async (key: string): Promise<void> => {
    let st = await refreshStatus(key);
    if (st.state === "loaded") return;
    st = await api.installModel(key, true);
    setStatus(st);
    for (;;) {
      await new Promise((r) => (pollRef.current = window.setTimeout(r, 600)));
      st = await refreshStatus(key);
      setPhase(
        {
          downloading: "Downloading native model…",
          verifying: "Verifying SHA256…",
          extracting: "Extracting…",
          loading: "Loading native LSM (one-time preload)…",
          installed: "Installed; loading…",
          not_installed: "Starting download…",
          loaded: "Ready",
          error: "Error",
        }[st.state]
      );
      if (st.state === "loaded") return;
      if (st.state === "error") throw new Error(st.error || "model install failed");
    }
  };

  const install = async () => {
    if (!resolved) return;
    setError(null);
    try {
      await waitForModel(resolved.model_key);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setPhase(null);
      loadModels();
      loadReadiness();
    }
  };

  const start = async () => {
    if (!resolved || !request) return;
    setError(null);
    try {
      await waitForModel(resolved.model_key);
      setPhase("Initializing respondent (persona interpretation, conditioning, initial ideology)…");
      if (session) api.deleteSession(session.session_id).catch(() => undefined);
      const s = await api.createSession({
        profile: request.base_profile,
        model_key: request.base_profile ? undefined : request.model_key,
        overrides: request.overrides,
      });
      setSession(s);
      setHistory([]);
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
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const saveCurrent = async () => {
    if (!request) return;
    const name = window.prompt("Name for the custom profile (letters, digits, _ - .):");
    if (!name) return;
    try {
      await api.saveProfile({ name, ...request, description: resolved?.description });
      await loadProfiles();
      setSelection({ kind: "profile", name });
      setOverrides({});
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const selectedProfile = selection?.kind === "profile" ? profiles.find((p) => p.name === selection.name) : undefined;
  const busy = Boolean(phase) || Boolean(pending);

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
      </div>

      <div className="main">
        <div className="col left">
          <Section title="Profile">
            <label className="field">
              <span>Configured / custom profile</span>
              <select
                value={selection?.kind === "profile" ? selection.name : "__draft__"}
                disabled={busy}
                onChange={(e) => {
                  setOverrides({});
                  setSelection({ kind: "profile", name: e.target.value });
                }}
              >
                {selection?.kind === "draft" && <option value="__draft__">(unsaved draft profile)</option>}
                <optgroup label="Configured (configs/dtag_config.yaml)">
                  {profiles
                    .filter((p) => p.source === "configured")
                    .map((p) => (
                      <option key={p.name} value={p.name} disabled={!!p.error}>
                        {p.name}
                        {p.model_loaded ? " · loaded" : p.model_installed ? "" : " · not installed"}
                      </option>
                    ))}
                </optgroup>
                {profiles.some((p) => p.source === "custom") && (
                  <optgroup label="Custom (web application)">
                    {profiles
                      .filter((p) => p.source === "custom")
                      .map((p) => (
                        <option key={p.name} value={p.name} disabled={!!p.error}>
                          {p.name}
                        </option>
                      ))}
                  </optgroup>
                )}
              </select>
            </label>
            {selectedProfile?.description && <div className="note">{selectedProfile.description}</div>}
            <div className="actions" style={{ marginTop: 6 }}>
              <button className="btn" onClick={() => setBuilder(true)} disabled={busy}>
                Create profile…
              </button>
              <button className="btn" onClick={saveCurrent} disabled={busy || !resolved || !!validationError}>
                Save custom profile
              </button>
              {selectedProfile?.source === "custom" && (
                <button
                  className="btn"
                  onClick={async () => {
                    if (!window.confirm(`Delete custom profile ${selectedProfile.name}?`)) return;
                    await api.deleteProfile(selectedProfile.name);
                    setSelection(null);
                    loadProfiles();
                  }}
                >
                  Delete
                </button>
              )}
            </div>
          </Section>

          <Section title="Survey / model">
            {resolved && (
              <div className="note" style={{ marginBottom: 6 }}>
                <span className="mono">{resolved.model_key}</span> · map <span className="mono">{resolved.map_key}</span>
              </div>
            )}
            <ModelPanel model={model} status={status} onInstall={install} busy={busy} />
          </Section>

          <Controls
            resolved={resolved}
            overrides={overrides}
            onChange={setOverrides}
            models={models}
            ebWaves={ebWaves}
            ebDatesAvailable={ebDates}
            capabilities={resolved?.capabilities}
            geography={geography}
            disabled={busy}
          />

          {validationError && <div className="error">{validationError}</div>}
          {resolved && resolved.warnings.length > 0 && (
            <ul className="warn-list">
              {resolved.warnings.map((w) => (
                <li key={w} className={/hard-conditioned|resolves to/.test(w) ? "info" : ""}>
                  {w}
                </li>
              ))}
            </ul>
          )}

          <div className="actions" style={{ marginTop: 10 }}>
            <button className="btn primary" onClick={start} disabled={busy || validating || !resolved || !!validationError}>
              {session ? "Start new respondent" : "Start respondent"}
            </button>
            <button className="btn" onClick={reset} disabled={busy || !session}>
              Reset respondent
            </button>
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
            emptyHint={
              session ? (
                <>
                  Respondent ready ({session.resolved_profile.model_label}). Ask a question below; every answer is anchored to
                  native LSM conditional survey-response distributions and the respondent's survey state carries forward
                  between questions.
                </>
              ) : (
                <>
                  Select or create a profile, adjust <b>who</b>, <b>where</b> and <b>when</b>, then start a respondent. Missing
                  native models are downloaded once from the public DTAG model release and kept resident in server memory.
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
            setOverrides({});
            setSelection({ kind: "profile", name });
          }}
          onUse={(d) => {
            setBuilder(false);
            setOverrides({});
            setSelection({ kind: "draft", draft: d });
          }}
        />
      )}
    </div>
  );
}
