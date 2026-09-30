import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  ModelRecord,
  ModelStatus,
  Overrides,
  Profile,
  QuestionResult,
  Recommendation,
  SequenceStatus,
  SessionInfo,
  Suggestion,
} from "./types";

export const BUSY_STATES = ["downloading", "verifying", "extracting", "loading"];
const familyOf = (key: string) => key.split("/", 1)[0];
const gssYear = (key: string) => {
  const m = /^gss\/gss_(\d{4})$/.exec(key);
  return m ? Number(m[1]) : undefined;
};

/** Model download/load shared by every respondent on the page (one job per model key). */
export interface ModelLoader {
  ensureLoaded: (key: string, onStatus?: (s: ModelStatus) => void) => Promise<void>;
  liveState: Record<string, string>;
  isPolling: (key: string) => boolean;
}

export function useModelLoader(onSettled: () => void): ModelLoader {
  const [liveState, setLiveState] = useState<Record<string, string>>({});
  const inflight = useRef<Map<string, Promise<void>>>(new Map());
  const listeners = useRef<Map<string, Set<(s: ModelStatus) => void>>>(new Map());

  const publish = (key: string, st: ModelStatus) => {
    setLiveState((s) => ({ ...s, [key]: st.state }));
    listeners.current.get(key)?.forEach((fn) => fn(st));
  };

  const poll = async (key: string): Promise<ModelStatus> => {
    for (;;) {
      const st = await api.modelStatus(key);
      publish(key, st);
      if (!st.job_running && !BUSY_STATES.includes(st.state)) return st;
      await new Promise((r) => setTimeout(r, 600));
    }
  };

  const ensureLoaded = useCallback(
    (key: string, onStatus?: (s: ModelStatus) => void) => {
      if (onStatus) {
        if (!listeners.current.has(key)) listeners.current.set(key, new Set());
        listeners.current.get(key)!.add(onStatus);
      }
      const existing = inflight.current.get(key);
      if (existing) return existing;
      const job = (async () => {
        let st = await api.modelStatus(key);
        publish(key, st);
        if (st.state === "loaded") return;
        if (!st.job_running) st = await api.installModel(key, true);
        st = await poll(key);
        if (st.state === "error") throw new Error(st.error || "model install failed");
        if (st.state !== "loaded") {
          await api.installModel(key, true);
          st = await poll(key);
          if (st.state !== "loaded") throw new Error(st.error || `model ${key} did not load`);
        }
        onSettled();
      })().finally(() => {
        inflight.current.delete(key);
        listeners.current.delete(key);
      });
      inflight.current.set(key, job);
      return job;
    },
    [] // eslint-disable-line react-hooks/exhaustive-deps
  );

  return { ensureLoaded, liveState, isPolling: (k) => inflight.current.has(k) };
}

/** Everything that belongs to one simulated respondent: who/where/when, model, session, chat, sequence. */
export function useRespondent(opts: {
  profiles: Profile[];
  models: ModelRecord[];
  loader: ModelLoader;
  defaultPreset: string;
  onChanged: () => void;
}) {
  const { profiles, models, loader, onChanged } = opts;

  const [preset, setPreset] = useState<string>("");
  const [persona, setPersona] = useState("");
  const [country, setCountry] = useState("");
  const [continent, setContinent] = useState("");
  const [year, setYear] = useState<string>("");
  const [date, setDate] = useState<string>("");

  const [rec, setRec] = useState<Recommendation | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  const [manual, setManual] = useState<string | null>(null);
  const [status, setStatus] = useState<ModelStatus | undefined>();

  const [behaviour, setBehaviour] = useState<Overrides>({});
  const [resolved, setResolved] = useState<Profile | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);

  const [session, setSession] = useState<SessionInfo | null>(null);
  const [history, setHistory] = useState<QuestionResult[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [phase, setPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seq, setSeq] = useState<SequenceStatus | null>(null);
  const seqTimer = useRef<number | null>(null);

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

  // Open on a configured preset so the respondent is ready to go.
  useEffect(() => {
    if (!preset && !persona && profiles.length) {
      const first = profiles.find((p) => p.name === opts.defaultPreset) || profiles.find((p) => !p.error);
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

  const effectiveKey: string | null =
    manual ?? (chosen && rec?.candidates.some((c) => c.model_key === chosen) ? chosen : rec?.default ?? null);
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

  const load = useCallback(
    (key: string) =>
      loader.ensureLoaded(key, (st) => setStatus((cur) => (cur?.key === key || !cur ? st : cur))),
    [loader.ensureLoaded] // eslint-disable-line react-hooks/exhaustive-deps
  );

  // Automatically download (if needed) and load the chosen model.
  useEffect(() => {
    if (!effectiveKey) return;
    let cancelled = false;
    setStatus(undefined);
    const t = setTimeout(() => {
      if (cancelled) return;
      load(effectiveKey).catch((e) => !cancelled && setError(String(e.message || e)));
    }, 700);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [effectiveKey, load]);

  const refreshSuggestions = (sid: string) =>
    api.suggestions(sid).then(setSuggestions).catch(() => setSuggestions([]));

  const start = async () => {
    if (!request || !effectiveKey) return;
    setError(null);
    try {
      setPhase("Getting the native model ready…");
      await load(effectiveKey);
      setPhase("Initializing respondent (persona interpretation, conditioning, initial ideology)…");
      if (session) api.deleteSession(session.session_id).catch(() => undefined);
      const s = await api.createSession({
        profile: request.base_profile,
        model_key: request.model_key,
        overrides: request.overrides,
      });
      setSession(s);
      setHistory([]);
      setSeq(null);
      refreshSuggestions(s.session_id);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setPhase(null);
      onChanged();
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

  const pollSequence = useCallback(async (sid: string, offset: number) => {
    try {
      const st = await api.sequence(sid, offset);
      if (st.results.length) {
        setHistory((h) => {
          const have = new Set(h.map((r) => r.query_idx));
          return [...h, ...st.results.filter((r) => !have.has(r.query_idx))];
        });
      }
      setSeq((prev) => ({ ...st, results: [...(prev?.job_id === st.job_id ? prev.results : []), ...st.results] }));
      setSession(await api.session(sid));
      if (st.status === "queued" || st.status === "running") {
        seqTimer.current = window.setTimeout(() => pollSequence(sid, offset + st.results.length), 900);
      } else {
        seqTimer.current = null;
        refreshSuggestions(sid);
      }
    } catch (e) {
      seqTimer.current = null;
      setError(String((e as Error).message));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(
    () => () => {
      if (seqTimer.current) window.clearTimeout(seqTimer.current);
    },
    []
  );

  const runSequence = async (text: string, name: string, resetFirst: boolean) => {
    if (!session) return;
    setError(null);
    try {
      const st = await api.startSequence(session.session_id, { text, name, reset_first: resetFirst });
      if (resetFirst) setHistory([]);
      setSeq({ ...st, results: [] });
      pollSequence(session.session_id, 0);
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const cancelSequence = () => {
    if (seq) api.cancelSequence(seq.session_id).catch((e) => setError(String(e.message)));
  };

  const seqRunning =
    seq !== null && (seq.status === "queued" || seq.status === "running") && seq.session_id === session?.session_id;

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

  const busy = Boolean(phase) || Boolean(pending) || seqRunning;
  const modelBusy = effectiveKey ? BUSY_STATES.includes(loader.liveState[effectiveKey] || "") : false;

  return {
    // who / where / when
    preset, setPreset, presetProfile, applyPreset,
    persona, setPersona, country, setCountry, continent, setContinent, year, setYear, date, setDate,
    // model choice
    rec, recLoading, chosen, setChosen, manual, setManual, effectiveKey, candidate, model, status, load,
    // behaviour + validation
    behaviour, setBehaviour, resolved, validationError, validating, request,
    // session
    session, history, suggestions, pending, phase, error, setError,
    start, ask, reset,
    // sequences
    seq, seqRunning, runSequence, cancelSequence,
    busy, modelBusy,
  };
}

export type Respondent = ReturnType<typeof useRespondent>;
