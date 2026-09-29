import { useEffect, useMemo, useState } from "react";
import { api, fmtBytes } from "../api";
import type { EBWave, Family, ModelRecord, Overrides, Profile } from "../types";
import { Controls, type Geography } from "./Controls";

export interface Draft {
  base_profile?: string;
  model_key?: string;
  overrides: Overrides;
}

const FAMILY_LABEL: Record<Family, string> = {
  gss: "GSS",
  afrobarometer: "Afrobarometer",
  wvs: "World Values Survey",
  eurobarometer: "Eurobarometer",
};

export function ProfileBuilder(props: {
  profiles: Profile[];
  models: ModelRecord[];
  maps: Array<{ key: string; family: string | null }>;
  ebWaves: EBWave[];
  ebDatesAvailable: boolean;
  geography: Geography;
  initial?: Draft;
  onClose: () => void;
  onSaved: (name: string) => void;
  onUse: (d: Draft) => void;
}) {
  const [family, setFamily] = useState<Family>("gss");
  const [modelKey, setModelKey] = useState<string>("");
  const [template, setTemplate] = useState<string>("");
  const [mapKey, setMapKey] = useState<string>("");
  const [overrides, setOverrides] = useState<Overrides>({});
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [resolved, setResolved] = useState<Profile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const famModels = useMemo(() => props.models.filter((m) => m.family === family), [props.models, family]);
  const famProfiles = props.profiles.filter((p) => !p.error && p.family === family);
  const famMaps = props.maps.filter((m) => m.family === family);

  useEffect(() => {
    // pick a sensible default model for the family: installed first, then newest
    const installed = famModels.filter((m) => m.installed);
    const pick = (installed.length ? installed : famModels)[(installed.length ? installed : famModels).length - 1];
    setModelKey(pick?.key ?? "");
    setTemplate("");
    setOverrides({});
  }, [family]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const m = props.models.find((x) => x.key === modelKey);
    setMapKey(m?.map_key ?? "");
  }, [modelKey, props.models]);

  const draft: Draft = useMemo(() => {
    const ov: Overrides = { ...overrides };
    if (mapKey) ov.map_key = mapKey;
    if (template) {
      const t = props.profiles.find((p) => p.name === template);
      if (t && t.model_key !== modelKey && !ov.za && !ov.date && ov.year === undefined) ov.model_key = modelKey;
      return { base_profile: template, overrides: ov };
    }
    return { model_key: modelKey, overrides: ov };
  }, [overrides, mapKey, template, modelKey, props.profiles]);

  useEffect(() => {
    if (!modelKey) return;
    const t = setTimeout(() => {
      api
        .validateProfile(draft)
        .then((r) => {
          setResolved(r);
          setError(null);
        })
        .catch((e) => setError(String(e.message || e)));
    }, 300);
    return () => clearTimeout(t);
  }, [draft, modelKey]);

  const model = props.models.find((m) => m.key === (resolved?.model_key || modelKey));

  const save = async () => {
    setSaving(true);
    try {
      const p = await api.saveProfile({ name, description, ...draft });
      props.onSaved(p.name);
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-bg" onClick={props.onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <h2>Create profile</h2>
          <button className="link" onClick={props.onClose}>
            close ✕
          </button>
        </div>
        <div className="note">
          Custom profiles are stored by the web application only; configs/dtag_config.yaml is never modified.
        </div>
        <div className="steps">
          <div className="step">
            <div className="step-h">Model family</div>
            <select value={family} onChange={(e) => setFamily(e.target.value as Family)}>
              {(Object.keys(FAMILY_LABEL) as Family[]).map((f) => (
                <option key={f} value={f}>
                  {FAMILY_LABEL[f]} ({props.models.filter((m) => m.family === f).length} native models)
                </option>
              ))}
            </select>
          </div>
          <div className="step">
            <div className="step-h">Native model (installed or public)</div>
            <select value={modelKey} onChange={(e) => setModelKey(e.target.value)}>
              {famModels.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label} · {m.installed ? (m.loaded ? "loaded" : "installed") : `public ${fmtBytes(m.archive_bytes)}`}
                  {m.fieldwork ? ` · ${m.fieldwork.fieldwork_start}` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="step">
            <div className="step-h">Template profile (optional)</div>
            <select value={template} onChange={(e) => setTemplate(e.target.value)}>
              <option value="">(none — start from model defaults)</option>
              {famProfiles.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} — {p.description}
                </option>
              ))}
            </select>
          </div>
          <div className="step">
            <div className="step-h">Semantic map</div>
            <select value={mapKey} onChange={(e) => setMapKey(e.target.value)}>
              {famMaps.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.key}
                  {m.key === model?.map_key ? " (canonical)" : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="step">
            <div className="step-h">Persona, geography, time, ideology, fallback, response behaviour</div>
            {resolved ? (
              <Controls
                resolved={resolved}
                overrides={overrides}
                onChange={setOverrides}
                models={props.models}
                ebWaves={props.ebWaves}
                ebDatesAvailable={props.ebDatesAvailable}
                capabilities={resolved.capabilities}
                geography={props.geography}
              />
            ) : (
              <div className="note">Resolving…</div>
            )}
          </div>
          <div className="step">
            <div className="step-h">Validation</div>
            {error && <div className="error">{error}</div>}
            {resolved && (
              <>
                <div className="note">
                  Resolves to <span className="mono">{resolved.model_key}</span> with map{" "}
                  <span className="mono">{resolved.map_key}</span>
                  {resolved.za ? ` · ${resolved.za}` : ""}
                </div>
                <ul className="warn-list">
                  {resolved.warnings.map((w) => (
                    <li key={w} className={/hard-conditioned|resolves to/.test(w) ? "info" : ""}>
                      {w}
                    </li>
                  ))}
                  {!model?.installed && <li className="info">The model will be downloaded from the public release when first used.</li>}
                </ul>
              </>
            )}
          </div>
          <div className="step">
            <div className="step-h">Name and save</div>
            <div className="row">
              <label className="field">
                <span>Profile name</span>
                <input type="text" value={name} placeholder="e.g. eb2019_france_moderate" onChange={(e) => setName(e.target.value)} />
              </label>
              <label className="field">
                <span>Description</span>
                <input type="text" value={description} onChange={(e) => setDescription(e.target.value)} />
              </label>
            </div>
            <div className="actions">
              <button className="btn primary" disabled={!resolved || !!error || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(name) || saving} onClick={save}>
                Save profile
              </button>
              <button className="btn" disabled={!resolved || !!error} onClick={() => props.onUse(draft)}>
                Use without saving
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
