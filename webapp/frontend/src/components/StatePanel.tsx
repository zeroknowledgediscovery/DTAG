import { useState } from "react";
import { api, fmtNum, fmtSigned } from "../api";
import type { IdeologySummary, QuestionResult, SessionInfo, TrajectoryPoint } from "../types";
import { Section } from "./Controls";
import { mappingBadge } from "./Chat";
import { statusLabel } from "./ModelPanel";
import { FigureSave } from "./FigureSave";
import { useWidth } from "../useWidth";

export interface IdeologySeries {
  name: string;
  /** CSS color (token) for the line and markers. */
  color: string;
  marker?: "circle" | "square";
  dashed?: boolean;
  points: TrajectoryPoint[];
}

type Pt = TrajectoryPoint & { ideology: number };

export function IdeologyChart({ series }: { series: IdeologySeries[] }) {
  const [hover, setHover] = useState<{ s: IdeologySeries; p: Pt; x: number; y: number } | null>(null);
  const [box, boxWidth] = useWidth<HTMLDivElement>(330);
  const all = series.map((s) => ({ s, pts: s.points.filter((p) => p.ideology !== null) as Pt[] })).filter((x) => x.pts.length);
  if (all.length === 0) return <div className="note">No ideology values yet.</div>;
  const multi = series.length > 1;
  // drawn at the container's width (1:1), so text keeps its size when the column is resized
  const W = Math.max(260, boxWidth), H = Math.round(Math.min(280, Math.max(180, W * 0.42))), L = 44, R = multi ? 22 : 10, T = 10, B = 26;
  const vals = all.flatMap((x) => x.pts.map((p) => p.ideology));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.2, 0.0005); // small floor: a flat line still gets some room
  lo -= pad; hi += pad;
  const steps = all.flatMap((x) => x.pts.map((p) => p.step));
  const maxStep = Math.max(1, ...steps);
  const x = (s: number) => L + ((W - L - R) * s) / maxStep;
  const y = (v: number) => T + ((H - T - B) * (hi - v)) / (hi - lo);
  // One distinct tick per value (a single point gives three equal ticks).
  // One distinct tick per value (a single point gives three equal ticks); drop the middle one when
  // the labels would overlap.
  let ticks = Array.from(new Set([lo + pad, (lo + hi) / 2, hi - pad].map((t) => t.toFixed(4)))).map(Number);
  if (ticks.length === 3 && Math.abs(y(ticks[0]) - y(ticks[2])) < 26) ticks = [ticks[0], ticks[2]];
  if (ticks.length === 2 && Math.abs(y(ticks[0]) - y(ticks[1])) < 12) ticks = [ticks[1]];
  const uniq = Array.from(new Set([0, ...steps])).sort((p, q) => p - q);
  const stepTicks = uniq.filter((_s, i, a) => a.length <= 12 || i % Math.ceil(a.length / 12) === 0);

  const marker = (s: IdeologySeries, p: Pt, active: boolean) => {
    const cx = x(p.step), cy = y(p.ideology);
    const hollow = p.mapping === "NO MATCH" || (p.delta === 0 && p.step > 0);
    const common = {
      fill: hollow ? "var(--panel)" : s.color,
      stroke: hollow ? s.color : "var(--panel)",
      strokeWidth: hollow ? 1.5 : 2,
      onMouseEnter: () => setHover({ s, p, x: cx, y: cy }),
    };
    const r = active ? 5.5 : 4;
    return s.marker === "square" ? (
      <rect key={p.step} x={cx - r} y={cy - r} width={2 * r} height={2 * r} rx={1} {...common} />
    ) : (
      <circle key={p.step} cx={cx} cy={cy} r={r} {...common} />
    );
  };

  return (
    <div className="chart" ref={box} onMouseLeave={() => setHover(null)}>
      <FigureSave name="ideology_trajectory" />
      {multi && (
        <div className="legend">
          {series.map((s) => (
            <span key={s.name}>
              <svg width="22" height="10" aria-hidden="true">
                <line x1="1" x2="21" y1="5" y2="5" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? "4 3" : undefined} />
                {s.marker === "square" ? <rect x="7.5" y="1.5" width="7" height="7" fill={s.color} /> : <circle cx="11" cy="5" r="3.5" fill={s.color} />}
              </svg>
              {s.name}
            </span>
          ))}
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Ideology index trajectory: ${series.map((s) => s.name).join(" vs ")}`}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" />
            <text x={L - 6} y={y(t) + 3} fontSize="9" textAnchor="end" fill="var(--faint)" style={{ fontVariantNumeric: "tabular-nums" }}>
              {t.toFixed(4)}
            </text>
          </g>
        ))}
        {lo < 0 && hi > 0 && <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="var(--faint)" strokeDasharray="3 3" />}
        {stepTicks.map((s) => (
          <text key={s} x={x(s)} y={H - B + 13} fontSize="9" textAnchor="middle" fill="var(--faint)">
            {s === 0 ? "init" : `Q${s}`}
          </text>
        ))}
        <text x={(L + W - R) / 2} y={H - 2} fontSize="9" textAnchor="middle" fill="var(--faint)">
          question number
        </text>
        {!multi &&
          all.map(({ s, pts }) => (
            <g key={`area-${s.name}`}>
              <defs>
                <linearGradient id="ideo-fill" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor={s.color} stopOpacity="0.16" />
                  <stop offset="100%" stopColor={s.color} stopOpacity="0" />
                </linearGradient>
              </defs>
              <path
                d={
                  pts.map((p, i) => `${i ? "L" : "M"}${x(p.step).toFixed(1)},${y(p.ideology).toFixed(1)}`).join(" ") +
                  ` L${x(pts[pts.length - 1].step).toFixed(1)},${H - B} L${x(pts[0].step).toFixed(1)},${H - B} Z`
                }
                fill="url(#ideo-fill)"
              />
            </g>
          ))}
        {all.map(({ s, pts }) => (
          <path
            key={s.name}
            strokeLinejoin="round"
            strokeLinecap="round"
            d={pts.map((p, i) => `${i ? "L" : "M"}${x(p.step).toFixed(1)},${y(p.ideology).toFixed(1)}`).join(" ")}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeDasharray={s.dashed ? "5 3" : undefined}
          />
        ))}
        {all.map(({ s, pts }) => (
          <g key={s.name}>{pts.map((p) => marker(s, p, hover?.s.name === s.name && hover.p.step === p.step))}</g>
        ))}
        {multi &&
          all.map(({ s, pts }) => {
            const last = pts[pts.length - 1];
            return (
              <text key={s.name} x={x(last.step) + 7} y={y(last.ideology) + 3} fontSize="10" fontWeight="700" fill="var(--text)">
                {s.name.split(" ").pop()}
              </text>
            );
          })}
      </svg>
      {hover && (
        <div className="tooltip" style={{ left: `${Math.min(55, (hover.x / W) * 100)}%`, top: `${(hover.y / H) * 100 + 6}%` }}>
          <div>
            {multi && <b>{hover.s.name} · </b>}
            <b>{hover.p.step === 0 ? "Initial state" : `Q${hover.p.step}`}</b> · I = {fmtNum(hover.p.ideology)} ({fmtSigned(hover.p.delta)})
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
    </div>
  );
}

/** How to read the ideology chart (shown as a tooltip). */
const CHART_HELP = (polarSet: string | null) =>
  "I(s) = (d(sL, s) − d(sR, s)) / d(sL, sR), native LSM qdistance. Negative is nearer the L pole, positive nearer " +
  `the R pole of the registered polar-vector set (${polarSet ?? "—"}).\n` +
  "Filled markers: questions that updated the survey state. Hollow: state unchanged (value carried forward). " +
  "Hover a marker for its question and answers.";

function ChartInfo({ polarSet }: { polarSet: string | null }) {
  return (
    <span className="info-tip" title={CHART_HELP(polarSet)} aria-label={CHART_HELP(polarSet)} tabIndex={0}>
      ⓘ
    </span>
  );
}

/** Both respondents' ideology on one chart, in contrasting colors. */
export function IdeologyCompare({ items }: { items: Array<{ label: string; color: string; marker: "circle" | "square"; dashed?: boolean; session: SessionInfo | null }> }) {
  const on = items.filter((i) => i.session?.ideology.enabled);
  const off = items.filter((i) => i.session && !i.session.ideology.enabled);
  if (on.length === 0) {
    return (
      <div className="note">
        {items.some((i) => i.session)
          ? "Ideology tracking is not available for the started respondent(s) (GSS models only)."
          : "Start the respondents to compare their ideology trajectories."}
      </div>
    );
  }
  const a = on[0]?.session?.ideology.current;
  const b = on[1]?.session?.ideology.current;
  return (
    <div>
      <table className="kv compare">
        <thead>
          <tr>
            <th />
            <th>current</th>
            <th>initial</th>
            <th>
              change <ChartInfo polarSet={on[0].session!.ideology.polar_set} />
            </th>
          </tr>
        </thead>
        <tbody>
          {on.map((i) => (
            <tr key={i.label}>
              <td>
                <span className="swatch" style={{ background: i.color }} /> {i.label}
              </td>
              <td className="num">{fmtNum(i.session!.ideology.current)}</td>
              <td className="num">{fmtNum(i.session!.ideology.initial)}</td>
              <td className="num">{fmtSigned(i.session!.ideology.change_from_initial)}</td>
            </tr>
          ))}
          {on.length === 2 && (
            <tr>
              <td className="note">gap ({on[0].label.split(" ").pop()} − {on[1].label.split(" ").pop()})</td>
              <td className="num">{fmtSigned(a !== null && b !== null && a !== undefined && b !== undefined ? a - b : null)}</td>
              <td />
              <td />
            </tr>
          )}
        </tbody>
      </table>
      <IdeologyChart
        series={on.map((i) => ({ name: i.label, color: i.color, marker: i.marker, dashed: i.dashed, points: i.session!.ideology.trajectory }))}
      />
      {off.map((i) => (
        <div key={i.label} className="note">
          {i.label}: ideology not available for {i.session!.resolved_profile.model_label}.
        </div>
      ))}
      {on.length === 2 && on[0].session!.model.key !== on[1].session!.model.key && (
        <div className="note">
          The respondents use different models ({on[0].session!.model.key} vs {on[1].session!.model.key}); each index is
          measured against its own wave's poles.
        </div>
      )}
    </div>
  );
}

function Ideology({ ide, color }: { ide: IdeologySummary; color?: string }) {
  if (!ide.enabled) {
    const extra =
      ide.disable_reason && ide.disable_reason !== "Ideology trajectory is not available for this survey/profile."
        ? ide.disable_reason
        : "";
    return (
      <div className="note" title={extra || undefined}>
        No ideology index for this survey (available for GSS models).
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
          <div className="note">
            change <ChartInfo polarSet={ide.polar_set} />
          </div>
          <div className="mono">{fmtSigned(ide.change_from_initial)}</div>
        </div>
      </div>
      <IdeologyChart series={[{ name: "Ideology", color: color ?? "var(--chart-line)", points: ide.trajectory }]} />
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

export function StatePanel({
  session,
  history,
  idPrefix = "",
  color,
  label,
  children,
  hideIdeology = false,
}: {
  session: SessionInfo | null;
  history: QuestionResult[];
  /** Rendered right below the ideology chart (the ideology-push panel). */
  children?: React.ReactNode;
  /** Omit the per-respondent chart (two-respondent mode shows the A-vs-B chart instead). */
  hideIdeology?: boolean;
  /** Respondent label (A/B) used in the ZIP archive's folder and report. */
  label?: string;
  /** Must match the ChatLog's idPrefix so timeline clicks scroll to the right message. */
  idPrefix?: string;
  color?: string;
}) {
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
      {!hideIdeology && (
        <Section title="Ideology">
          <Ideology ide={session.ideology} color={color} />
        </Section>
      )}

      {children}

      <Section title="Respondent model">
        <details>
          <summary className="note" style={{ cursor: "pointer" }}>
            {session.model.family_label} · <span className="mono">{session.model.key}</span> · {String(session.config.resp_mode)}{" "}
            responses{session.llm.mock ? " · mock LLM" : ""}
          </summary>
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
        </details>
        <div className="actions" style={{ marginTop: 8 }}>
          <a
            className="btn primary-link"
            href={api.exportUrl(session.session_id, "zip", label)}
            download
            title="Complete log since the last reset: report, persona, settings, every question, ideology trajectory, state changes"
          >
            Full log (ZIP)
          </a>
          <a className="btn" href={api.exportUrl(session.session_id, "json")} download>
            Export JSON
          </a>
          <a className="btn" href={api.exportUrl(session.session_id, "csv")} download>
            Export CSV
          </a>
        </div>
      </Section>

      <Section title="Session timeline">
        {history.length === 0 ? (
          <div className="note">No questions yet.</div>
        ) : (
          <ul className="timeline">
            {history.map((r) => (
              <li key={r.query_idx} onClick={() => document.getElementById(`${idPrefix}q-${r.query_idx}`)?.scrollIntoView({ behavior: "smooth" })}>
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
