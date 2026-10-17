import { useState } from "react";
import { api, fmtSigned } from "../api";
import type { ExperimentJob, ExperimentRecipe, ExperimentStats } from "../types";
import { FigureSave } from "./FigureSave";

const HELP =
  "Everything you do to this respondent (questions, pushes, auto-pushes, sequences, suggested questions) is recorded " +
  "as a recipe. Rerun replays it on fresh respondents built from the same profile: the persona interpretation can " +
  "differ, each run has its own random seed, and pushes / suggested questions are re-chosen at each run's own state " +
  "(the questions actually asked are logged). Results and statistics are saved to a folder on the server. " +
  "Resetting the respondent starts a new recipe.";

/** Mean ideology after each action with its 95% bootstrap CI band, plus every run as a faint line. */
function BandChart({ st, color }: { st: ExperimentStats; color: string }) {
  const cps = st.checkpoints.filter((c) => c.mean !== null);
  if (cps.length < 2) return null;
  const W = 330, H = 150, L = 46, R = 10, T = 8, B = 26;
  const vals: number[] = [];
  for (const c of cps) vals.push(c.ci_lo ?? c.mean!, c.ci_hi ?? c.mean!, c.min ?? c.mean!, c.max ?? c.mean!);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.1, 0.002);
  lo -= pad;
  hi += pad;
  const n = st.checkpoints.length - 1;
  const x = (a: number) => L + ((W - L - R) * a) / Math.max(1, n);
  const y = (v: number) => T + ((H - T - B) * (hi - v)) / (hi - lo);
  const band = cps.filter((c) => c.ci_lo !== null && c.ci_hi !== null);
  const area =
    band.map((c, i) => `${i ? "L" : "M"}${x(c.action).toFixed(1)},${y(c.ci_hi!).toFixed(1)}`).join("") +
    [...band].reverse().map((c) => `L${x(c.action).toFixed(1)},${y(c.ci_lo!).toFixed(1)}`).join("") +
    "Z";
  const mean = cps.map((c, i) => `${i ? "L" : "M"}${x(c.action).toFixed(1)},${y(c.mean!).toFixed(1)}`).join("");
  const ticks = [lo + pad, (lo + hi) / 2, hi - pad];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="exp-chart" role="img" aria-label="Ideology after each action across runs (mean and 95% CI)">
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" />
          <text x={L - 6} y={y(t) + 3} fontSize="9" textAnchor="end" fill="var(--faint)">
            {t.toFixed(3)}
          </text>
        </g>
      ))}
      {st.checkpoints.map((c) => (
        <text key={c.action} x={x(c.action)} y={H - B + 13} fontSize="9" textAnchor="middle" fill="var(--faint)">
          <title>{c.label}</title>
          {c.action === 0 ? "start" : `A${c.action}`}
        </text>
      ))}
      <text x={(L + W - R) / 2} y={H - 2} fontSize="9" textAnchor="middle" fill="var(--faint)">
        after action
      </text>
      {st.per_run.map((r) => (
        <path
          key={r.run}
          d={r.ideology
            .map((v, i) => (v === null ? "" : `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`))
            .join("")}
          fill="none"
          stroke={color}
          strokeOpacity={0.18}
          strokeWidth={1}
        />
      ))}
      {band.length > 1 && <path d={area} fill={color} fillOpacity={0.18} />}
      <path d={mean} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
      {cps.map((c) => (
        <circle key={c.action} cx={x(c.action)} cy={y(c.mean!)} r={3.2} fill={color} stroke="var(--panel)" strokeWidth={1.5}>
          <title>
            {`${c.label}\nmean ${c.mean!.toFixed(4)} · 95% CI [${c.ci_lo?.toFixed(4) ?? "—"}, ${c.ci_hi?.toFixed(4) ?? "—"}] · n ${c.n}`}
          </title>
        </circle>
      ))}
    </svg>
  );
}

export function ExperimentPanel({
  sessionId,
  recipe,
  job,
  busy,
  color,
  onRun,
  onCancel,
}: {
  sessionId: string;
  recipe: ExperimentRecipe | null;
  job: ExperimentJob | null;
  busy: boolean;
  color: string;
  onRun: (runs: number, name: string) => void;
  onCancel: () => void;
}) {
  const [runs, setRuns] = useState(20);
  const [name, setName] = useState("");
  const n = recipe?.actions.length ?? 0;
  const running = job !== null && (job.status === "queued" || job.status === "running");
  const st = job?.stats ?? null;
  const pct = job ? Math.round((100 * (job.completed + (running && job.current.of ? (job.current.action ?? 0) / job.current.of : 0))) / job.runs) : 0;

  return (
    <div className="exp">
      <details className="exp-actions">
        <summary className="note">
          <b>{n}</b> recorded action{n === 1 ? "" : "s"} <span className="info-tip" title={HELP}>ⓘ</span>
        </summary>
        {n ? (
          <ol className="exp-list">
            {recipe!.descriptions.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ol>
        ) : (
          <div className="note">Ask questions or push; every action is recorded here.</div>
        )}
      </details>
      <div className="exp-run">
        <input type="text" placeholder="experiment name (optional)" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
        <input
          type="number"
          min={1}
          max={200}
          value={runs}
          aria-label="Runs"
          onChange={(e) => setRuns(Math.max(1, Math.min(200, Number(e.target.value) || 1)))}
        />
        <button className="btn primary small" disabled={!n || busy || running} onClick={() => onRun(runs, name)}>
          Rerun ×{runs}
        </button>
      </div>
      <div className="exp-links note">
        {n ? <a href={api.recipeUrl(sessionId, name)}>recipe (JSON)</a> : null}
      </div>
      {job && (
        <div className="exp-job">
          <div className="exp-job-h">
            <span className={`badge ${job.status === "done" ? "b-direct" : job.status === "error" ? "b-nomatch" : "b-neutral"}`}>
              {running && <span className="spinner" />} {job.status}
            </span>
            <span className="note">
              {job.completed}/{job.runs} runs · {job.elapsed_seconds.toFixed(0)} s
              {running && job.current.label ? ` · run ${job.current.run}: ${job.current.label}` : ""}
            </span>
            {running && (
              <button className="link" style={{ marginLeft: "auto" }} onClick={onCancel}>
                cancel
              </button>
            )}
          </div>
          {running && (
            <div className="progress">
              <div style={{ width: `${pct}%` }} />
            </div>
          )}
          {job.error && <div className="error">{job.error}</div>}
          {st && st.runs > 0 && (
            <>
              {st.ideology_enabled ? (
                <>
                  <div className="exp-fig">
                    <BandChart st={st} color={color} />
                    <FigureSave name={`experiment_${job.folder}`} />
                  </div>
                  <div className="note">
                    Net change: <b className="mono">{fmtSigned(st.net_change.mean, 4)}</b> · 95% CI [
                    <span className="mono">{fmtSigned(st.net_change.ci_lo, 4)}</span>,{" "}
                    <span className="mono">{fmtSigned(st.net_change.ci_hi, 4)}</span>] · sd{" "}
                    <span className="mono">{st.net_change.sd?.toFixed(4) ?? "—"}</span> · n {st.net_change.n}
                    {st.push.n ? (
                      <>
                        {" "}· pushes {st.push.n}
                        {st.push.hit_rate !== null ? `, hit ${(st.push.hit_rate * 100).toFixed(0)}%` : ""}
                      </>
                    ) : null}
                  </div>
                </>
              ) : (
                <div className="note">{st.runs} runs completed (no ideology index: see the folder for answers and questions).</div>
              )}
              <details className="exp-q">
                <summary className="note">Questions asked per action</summary>
                <ul>
                  {st.questions.map((q) => (
                    <li key={q.action}>
                      <b>A{q.action}</b> {q.label}: {q.distinct} distinct of {q.asked}
                      {q.skipped ? `, ${q.skipped} skipped` : ""}
                      {q.distinct > 1 && (
                        <ul>
                          {q.top.slice(0, 3).map((t) => (
                            <li key={t.question} className="note">
                              {t.count}× {t.question}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              </details>
              {!running && (
                <div className="exp-links note">
                  <a href={api.experimentZipUrl(job.folder)}>Download results (ZIP)</a> · saved in{" "}
                  <span className="mono" title={job.path}>
                    experiments/{job.folder}
                  </span>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
