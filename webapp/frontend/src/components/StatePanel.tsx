import { useState } from "react";
import { api, fmtNum, fmtSigned } from "../api";
import type { IdeologySummary, QuestionResult, SessionInfo, TrajectoryPoint } from "../types";
import { Section } from "./Controls";
import { mappingBadge } from "./Chat";
import { statusLabel } from "./ModelPanel";

function IdeologyChart({ points }: { points: TrajectoryPoint[] }) {
  const [hover, setHover] = useState<{ p: TrajectoryPoint; x: number; y: number } | null>(null);
  const pts = points.filter((p) => p.ideology !== null) as Array<TrajectoryPoint & { ideology: number }>;
  if (pts.length === 0) return <div className="note">No ideology values yet.</div>;
  const W = 330, H = 170, L = 44, R = 10, T = 10, B = 26;
  const vals = pts.map((p) => p.ideology);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.2, 0.002);
  lo -= pad; hi += pad;
  const maxStep = Math.max(1, ...pts.map((p) => p.step));
  const x = (s: number) => L + ((W - L - R) * s) / maxStep;
  const y = (v: number) => T + ((H - T - B) * (hi - v)) / (hi - lo);
  const ticks = [lo + pad, (lo + hi) / 2, hi - pad];
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(p.step).toFixed(1)},${y(p.ideology).toFixed(1)}`).join(" ");
  const stepTicks = Array.from(new Set([0, ...pts.map((p) => p.step)])).filter((_s, i, a) => a.length <= 12 || i % Math.ceil(a.length / 12) === 0);

  return (
    <div className="chart" onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Ideology index trajectory">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" />
            <text x={L - 4} y={y(t) + 3} fontSize="9" textAnchor="end" fill="var(--muted)" fontFamily="var(--mono)">
              {t.toFixed(4)}
            </text>
          </g>
        ))}
        {lo < 0 && hi > 0 && (
          <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="var(--faint)" strokeDasharray="3 3" />
        )}
        {stepTicks.map((s) => (
          <text key={s} x={x(s)} y={H - B + 12} fontSize="9" textAnchor="middle" fill="var(--muted)" fontFamily="var(--mono)">
            {s === 0 ? "init" : `Q${s}`}
          </text>
        ))}
        <text x={(L + W - R) / 2} y={H - 3} fontSize="9" textAnchor="middle" fill="var(--muted)">
          question number
        </text>
        <path d={path} fill="none" stroke="var(--chart-line)" strokeWidth={1.8} />
        {pts.map((p) => (
          <circle
            key={p.step}
            cx={x(p.step)}
            cy={y(p.ideology)}
            r={hover?.p.step === p.step ? 5 : 3.2}
            fill={p.mapping === "NO MATCH" || (p.delta === 0 && p.step > 0) ? "var(--panel)" : "var(--chart-line)"}
            stroke="var(--chart-line)"
            strokeWidth={1.5}
            onMouseEnter={() => setHover({ p, x: x(p.step), y: y(p.ideology) })}
          />
        ))}
      </svg>
      {hover && (
        <div
          className="tooltip"
          style={{ left: `${Math.min(55, (hover.x / W) * 100)}%`, top: `${(hover.y / H) * 100 + 6}%` }}
        >
          <div>
            <b>{hover.p.step === 0 ? "Initial state" : `Q${hover.p.step}`}</b> · I = {fmtNum(hover.p.ideology)} (
            {fmtSigned(hover.p.delta)})
          </div>
          {hover.p.question && <div>{hover.p.question}</div>}
          <div className="note">{hover.p.mapping}</div>
          {hover.p.selected_variables.length > 0 && (
            <div className="mono">
              {Object.entries(hover.p.anchors)
                .map(([k, v]) => `${k}=${v}`)
                .join("; ")}
            </div>
          )}
        </div>
      )}
      <div className="note">Filled points: state-updating steps; hollow: state unchanged (value carried forward).</div>
    </div>
  );
}

function Ideology({ ide }: { ide: IdeologySummary }) {
  if (!ide.enabled) {
    return (
      <div className="note">
        Ideology trajectory is not available for this survey/profile.
        {ide.disable_reason && ide.disable_reason !== "Ideology trajectory is not available for this survey/profile." && (
          <div className="mono">{ide.disable_reason}</div>
        )}
      </div>
    );
  }
  return (
    <div>
      <div className="row" style={{ alignItems: "baseline" }}>
        <div>
          <div className="note">current</div>
          <div className="bignum">{fmtNum(ide.current)}</div>
        </div>
        <div>
          <div className="note">initial</div>
          <div className="mono">{fmtNum(ide.initial)}</div>
        </div>
        <div>
          <div className="note">change</div>
          <div className="mono">{fmtSigned(ide.change_from_initial)}</div>
        </div>
      </div>
      <IdeologyChart points={ide.trajectory} />
      <div className="note" title={ide.convention}>
        I(s) = (d(s<sub>L</sub>, s) − d(s<sub>R</sub>, s)) / d(s<sub>L</sub>, s<sub>R</sub>) with native qdistance; negative is
        nearer the L pole, positive nearer the R pole of the registered polar-vector set ({ide.polar_set}).
      </div>
    </div>
  );
}

function StateTable({ state, highlight }: { state: Record<string, string>; highlight: Set<string> }) {
  const entries = Object.entries(state);
  return (
    <div className="statelist">
      <table className="kv">
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <td className={`mono ${highlight.has(k) ? "chg" : ""}`}>{k}</td>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StatePanel({ session, history }: { session: SessionInfo | null; history: QuestionResult[] }) {
  if (!session) {
    return (
      <div className="note">
        Start a respondent to see the survey model, conditioning, ideology trajectory and the current DTAG survey-state
        representation.
      </div>
    );
  }
  const p = session.resolved_profile;
  const geo = session.geographic_conditioning;
  const tmp = session.temporal_conditioning;
  const last = history[history.length - 1];
  const changed = new Set(last ? Object.keys(last.state_updates) : []);

  return (
    <div>
      <Section title="Respondent model">
        <dl className="summary">
          <dt>Survey family</dt>
          <dd>{session.model.family_label}</dd>
          <dt>Native model</dt>
          <dd className="mono">{session.model.key}</dd>
          <dt>Semantic map</dt>
          <dd className="mono">
            {session.map.key}
            {session.map.has_fallback_provenance && <span className="badge b-sem"> fallback provenance</span>}
          </dd>
          <dt>Wave / time</dt>
          <dd>
            {tmp.wave}
            {tmp.fieldwork ? ` · fieldwork ${tmp.fieldwork.fieldwork_start} … ${tmp.fieldwork.fieldwork_end}` : ""}
            {tmp.requested_date ? ` · requested ${tmp.requested_date}` : ""}
            <div className="note mono">{tmp.mode}</div>
          </dd>
          <dt>Country</dt>
          <dd>{p.country || "—"}{p.continent ? ` · ${p.continent}` : ""}</dd>
          <dt>Geography</dt>
          <dd>
            <span className="mono">{geo.conditioning_mode}</span>
            {Object.keys(geo.conditioned_variables).length > 0 && (
              <div className="mono note">
                {Object.entries(geo.conditioned_variables).map(([k, v]) => `${k}=${v}`).join(", ")}
              </div>
            )}
          </dd>
          <dt>Model status</dt>
          <dd>{statusLabel(session.model.status.state)}</dd>
          <dt>Response mode</dt>
          <dd className="mono">
            {String(session.config.resp_mode)} · seed {String(session.config.seed)} · fallback{" "}
            {String(session.config.semantic_fallback)}
          </dd>
          <dt>LLM</dt>
          <dd className="mono">
            {session.llm.backend} · {session.llm.openai_model}
            {session.llm.mock && <span className="badge b-nomatch"> MOCK</span>}
          </dd>
        </dl>
        {[...geo.warnings, ...tmp.warnings].length > 0 && (
          <details>
            <summary className="note" style={{ cursor: "pointer" }}>
              Conditioning notes ({geo.warnings.length + tmp.warnings.length})
            </summary>
            <ul className="warn-list">
              {[...geo.warnings, ...tmp.warnings].map((w) => (
                <li key={w} className="info">
                  {w}
                </li>
              ))}
            </ul>
          </details>
        )}
        <div className="actions" style={{ marginTop: 8 }}>
          <a className="btn" href={api.exportUrl(session.session_id, "json")} download>
            Export JSON
          </a>
          <a className="btn" href={api.exportUrl(session.session_id, "csv")} download>
            Export CSV
          </a>
        </div>
      </Section>

      <Section title="Ideology">
        <Ideology ide={session.ideology} />
      </Section>

      <Section title="Session timeline">
        {history.length === 0 ? (
          <div className="note">No questions yet.</div>
        ) : (
          <ul className="timeline">
            {history.map((r) => (
              <li key={r.query_idx} onClick={() => document.getElementById(`q-${r.query_idx}`)?.scrollIntoView({ behavior: "smooth" })}>
                <span className="qn">Q{r.query_idx}</span>
                <span className={`badge ${mappingBadge(r.mapping.label)}`}>{r.mapping.label}</span>
                <span className={`badge ${r.state_changed ? "b-neutral" : "b-muted"}`}>{r.state_changed ? "Δ" : "="}</span>
                <span className="qt" title={r.question}>{r.question}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Current respondent state">
        <details>
          <summary className="note" style={{ cursor: "pointer" }}>
            DTAG survey-state representation · {Object.keys(session.current_state).length} assigned variables
            {changed.size ? ` · ${changed.size} updated by last question` : ""}
          </summary>
          <StateTable state={session.current_state} highlight={changed} />
        </details>
        <details>
          <summary className="note" style={{ cursor: "pointer" }}>
            Initial state (persona + forced assignments) · {Object.keys(session.initial_state).length}
          </summary>
          <StateTable state={session.initial_state} highlight={new Set(Object.keys(session.persona_assignments.forced))} />
          {session.persona_assignments.dropped.length > 0 && (
            <div className="note">Dropped (not in model support): {session.persona_assignments.dropped.join("; ")}</div>
          )}
          <div className="note">Persona interpretation: {session.persona_assignments.rationale}</div>
        </details>
      </Section>
    </div>
  );
}
