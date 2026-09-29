export type Family = "gss" | "afrobarometer" | "wvs" | "eurobarometer";

export interface ModelStatus {
  key: string;
  state:
    | "not_installed"
    | "downloading"
    | "verifying"
    | "extracting"
    | "installed"
    | "loading"
    | "loaded"
    | "error";
  done_bytes: number;
  total_bytes: number;
  error: string | null;
  job_running: boolean;
}

export interface Fieldwork {
  za: string;
  fieldwork_start: string;
  fieldwork_end: string;
  fieldwork_raw: string;
  auto_select: boolean;
}

export interface ModelRecord {
  key: string;
  family: Family;
  family_label: string;
  name: string;
  label: string;
  year: number | null;
  za: string | null;
  installed: boolean;
  loaded: boolean;
  status: ModelStatus;
  map_available: boolean;
  map_key: string | null;
  ideology_available: boolean;
  polar_sets: string[];
  in_public_release: boolean;
  archive_bytes: number | null;
  sha256: string | null;
  release: string | null;
  configured_profiles: string[];
  fieldwork?: Fieldwork | null;
  capabilities?: Capabilities | null;
  runtime?: { runtime: string; features: number; usable_trees: number; load_seconds: number };
}

export interface Capabilities {
  features: number;
  country_features: string[];
  country_values: string[];
  coordinate_features: string[];
  year_feature: string | null;
  year_values: string[];
  geography_mode: string;
}

export interface RunParams {
  semantic_fallback?: "off" | "answer_only" | "update_state";
  resp_mode?: "max" | "draw";
  semantic_resp_mode?: "max" | "draw";
  seed?: number;
  k?: number;
  prefilter?: number;
  min_map_score?: number;
  semantic_k?: number;
  semantic_prefilter?: number;
  semantic_min_confidence?: number;
  max_assign?: number;
  assign_prefilter?: number;
  state_keep?: number;
  openai_model?: string;
  [k: string]: unknown;
}

export interface Profile {
  name: string;
  source: "configured" | "custom" | "adhoc";
  description: string;
  family: Family;
  model_key: string;
  model_label: string;
  map_key: string;
  persona: string;
  country: string;
  continent: string;
  year: number | null;
  date: string | null;
  za: string | null;
  polar_set: string | null;
  ideology: boolean;
  base_profile: string | null;
  run: RunParams;
  temporal: Record<string, unknown>;
  warnings: string[];
  model_status?: string;
  model_installed?: boolean;
  model_loaded?: boolean;
  capabilities?: Capabilities | null;
  error?: string;
}

export interface Overrides {
  persona?: string;
  country?: string;
  continent?: string;
  year?: number | null;
  date?: string;
  za?: string;
  model_key?: string;
  map_key?: string;
  ideology?: boolean;
  polar_set?: string;
  semantic_fallback?: string;
  resp_mode?: string;
  semantic_resp_mode?: string;
  seed?: number;
  k?: number;
  prefilter?: number;
  min_map_score?: number;
  semantic_k?: number;
  semantic_prefilter?: number;
  semantic_min_confidence?: number;
  max_assign?: number;
  assign_prefilter?: number;
  state_keep?: number;
}

export interface Anchor {
  variable: string;
  survey_question: string;
  response: string;
  distribution: Record<string, number>;
  map_provenance: Record<string, string> | null;
}

export interface Mapping {
  type: string;
  label: string;
  direct_mapping: boolean;
  semantic_fallback: boolean;
  semantic_fallback_mode: string;
  semantic_trigger: string | null;
  state_updated: boolean;
  skipped: boolean;
  skip_reason: string | null;
  semantic_bridge_items: Array<{
    variable: string;
    confidence: number;
    relation_type: string;
    rationale: string;
    accepted: boolean;
  }>;
}

export interface GeoConditioning {
  requested_country: string | null;
  requested_continent: string | null;
  resolved_country: string | null;
  conditioning_mode: string;
  conditioned_variables: Record<string, string>;
  target_coordinates: { longitude: number; latitude: number } | null;
  warnings: string[];
  context_text?: { note: string };
}

export interface TemporalConditioning {
  family: string;
  mode: string;
  requested_year?: number | null;
  requested_date?: string | null;
  resolved_za?: string | null;
  fieldwork?: Fieldwork | null;
  selected_model: string;
  wave: string;
  conditioned_variables: Record<string, string>;
  warnings: string[];
  note?: string;
}

export interface IdeologyStep {
  enabled: boolean;
  before: number | null;
  after: number | null;
  delta: number | null;
  initial: number | null;
}

export interface QuestionResult {
  query_idx: number;
  question: string;
  answer: string;
  selected_variables: string[];
  selection_rationale: string;
  display_rationale: string;
  anchors: Anchor[];
  mapping: Mapping;
  state_updates: Record<string, string>;
  state_evicted: string[];
  state_changed: boolean;
  state_size: number;
  ideology: IdeologyStep;
  timings: Record<string, number>;
  geographic_conditioning: GeoConditioning;
  temporal_conditioning: TemporalConditioning;
  semantic_candidates?: Array<{ variable: string; similarity: number }>;
  lexical_candidates?: number;
}

export interface TrajectoryPoint {
  step: number;
  ideology: number | null;
  delta: number | null;
  question: string | null;
  selected_variables: string[];
  anchors: Record<string, string>;
  mapping: string;
}

export interface IdeologySummary {
  enabled: boolean;
  initial: number | null;
  current: number | null;
  change_from_initial: number | null;
  disable_reason: string | null;
  polar_set: string | null;
  convention: string;
  trajectory: TrajectoryPoint[];
}

export interface SessionInfo {
  session_id: string;
  created_at: string;
  resolved_profile: Profile;
  model: ModelRecord;
  map: {
    key: string;
    rows?: number;
    provenance_counts?: Record<string, number> | null;
    has_fallback_provenance?: boolean;
  };
  persona_text: string;
  initial_state: Record<string, string>;
  current_state: Record<string, string>;
  question_count: number;
  persona_assignments: {
    llm_raw: Record<string, string>;
    dropped: string[];
    rationale: string;
    forced: Record<string, string>;
  };
  geographic_conditioning: GeoConditioning;
  temporal_conditioning: TemporalConditioning;
  ideology: IdeologySummary;
  config: RunParams;
  llm: { backend: string; openai_model: string; mock: boolean; note: string | null };
  init_timings: Record<string, number>;
  history: QuestionResult[];
}

export interface Readiness {
  status: string;
  dtag_version: string;
  native_runtime: { available: boolean; runtime?: string; error?: string };
  public_catalog: {
    reachable: boolean;
    error: string | null;
    release: string;
    models: number;
    by_family: Record<string, number>;
  };
  semantic_maps: { maps: number; matched_to_catalog: number; by_family: Record<string, number> };
  model_cache: { root: string; installed: number };
  models_resident: { loaded: number; keys: string[] };
  configured_profiles: { count: number; names: string[] };
  eurobarometer_dates: { available: boolean; waves: number };
  llm: { backend: string; openai_configured: boolean; ready: boolean; default_openai_model: string };
  sessions: number;
}

export interface EBWave extends Fieldwork {
  model_key: string | null;
  installed: boolean;
}

export interface Candidate {
  model_key: string;
  family: Family;
  family_label: string;
  label: string;
  geo: { mode: "categorical" | "national_survey" | "coverage_only" | "coordinates" | "assumed"; note: string; value: string | null };
  time: { mode: "exact" | "nearest" | "latest"; note: string; distance_years: number };
  overrides: { year?: number; date?: string; za?: string };
  installed: boolean;
  loaded: boolean;
  status: ModelStatus["state"];
  archive_bytes: number | null;
  ideology_available: boolean;
}

export interface Recommendation {
  resolved: {
    country: string;
    country_key: string;
    year: number | null;
    date: string | null;
    sources: { country: "input" | "description" | "default" | null; year: "input" | "description" | "date" | null };
  };
  detected: { country: string | null; country_evidence: string | null; year: number | null; year_evidence: string | null };
  candidates: Candidate[];
  default: string | null;
  choice_required: boolean;
  reason: string | null;
  messages: string[];
}

export interface CountryInfo {
  key: string;
  name: string;
  families: Family[];
}

export interface Suggestion {
  question: string;
  top_variables: string[];
}
