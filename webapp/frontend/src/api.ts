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

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
  });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    if (body && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      msg = typeof d === "string" ? d : JSON.stringify(d);
    }
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export function cleanOverrides(o: Overrides): Overrides {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === "" || (typeof v === "number" && Number.isNaN(v))) continue;
    out[k] = v;
  }
  return out as Overrides;
}

export const api = {
  health: () => request<Record<string, unknown>>("/api/health"),
  readiness: (refresh = false) => request<Readiness>(`/api/readiness${refresh ? "?refresh=true" : ""}`),
  profiles: () => request<Profile[]>("/api/profiles"),
  validateProfile: (draft: { base_profile?: string; model_key?: string; overrides: Overrides }) =>
    post<Profile>("/api/profiles/validate", { ...draft, overrides: cleanOverrides(draft.overrides) }),
  saveProfile: (draft: {
    name: string;
    description?: string;
    base_profile?: string;
    model_key?: string;
    overrides: Overrides;
  }) => post<Profile>("/api/profiles", { ...draft, overrides: cleanOverrides(draft.overrides) }),
  deleteProfile: (name: string) => request(`/api/profiles/${encodeURIComponent(name)}`, { method: "DELETE" }),
  models: (family?: string) => request<ModelRecord[]>(`/api/models${family ? `?family=${family}` : ""}`),
  model: (key: string) => request<ModelRecord>(`/api/models/${key}`),
  modelStatus: (key: string) => request<ModelStatus>(`/api/models/${key}/status`),
  installModel: (key: string, load = true) => post<ModelStatus>(`/api/models/${key}/install?load=${load}`),
  maps: () => request<Array<{ key: string; family: string | null }>>("/api/maps"),
  ebWaves: (year?: number) =>
    request<{
      date_registry_available: boolean;
      waves: EBWave[];
      catalog_models_without_fieldwork_dates: string[];
    }>(`/api/eurobarometer/waves${year ? `?year=${year}` : ""}`),
  createSession: (body: { profile?: string; model_key?: string; overrides: Overrides }) =>
    post<SessionInfo>("/api/sessions", { ...body, overrides: cleanOverrides(body.overrides) }),
  session: (id: string) => request<SessionInfo>(`/api/sessions/${id}`),
  suggestions: (id: string, n = 6) => request<Suggestion[]>(`/api/sessions/${id}/suggestions?n=${n}`),
  countries: () => request<CountryInfo[]>("/api/countries"),
  recommend: (body: { persona: string; country: string; year?: number | null; date?: string | null; preferred_model?: string | null }) =>
    post<Recommendation>("/api/recommend", {
      persona: body.persona,
      country: body.country,
      ...(body.year ? { year: body.year } : {}),
      ...(body.date ? { date: body.date } : {}),
      ...(body.preferred_model ? { preferred_model: body.preferred_model } : {}),
    }),
  ask: (id: string, question: string) => post<QuestionResult>(`/api/sessions/${id}/questions`, { question }),
  reset: (id: string) => post<SessionInfo>(`/api/sessions/${id}/reset`),
  deleteSession: (id: string) => request(`/api/sessions/${id}`, { method: "DELETE" }),
  exportUrl: (id: string, format: "json" | "csv") => `/api/sessions/${id}/export?format=${format}`,
};

export function fmtBytes(n: number | null | undefined): string {
  if (!n && n !== 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function fmtNum(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export function fmtSigned(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}
