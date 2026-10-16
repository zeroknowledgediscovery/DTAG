import { useState } from "react";
import { fmtSigned } from "../api";
import type { PushSuggestion, PushSuggestions } from "../types";

const ARROW = { up: "↑", down: "↓" } as const;
const POLE = { up: "toward the R pole", down: "toward the L pole" } as const;

const HELP =
  "The one-step optimizer scores every unanswered opinion item at this respondent's current state and suggests the " +
  "question that moves the ideology index most in each direction. Asking it answers exactly that survey item, so the " +
  "recorded and plotted index changes by the predicted amount (exactly, when the session records the most likely answer).";

function basisNote(s: PushSuggestion): string {
  return s.objective === "modal"
    ? `Exact if answered “${s.modal_answer}” (p = ${s.p_modal.toFixed(2)}, the most likely answer, which this session records). ` +
        `Average over all answers: ${fmtSigned(s.expected_delta, 4)}.`
    : `Expected change over the model's answer distribution · P(up) ${s.P_up.toFixed(2)} · P(down) ${s.P_down.toFixed(2)}.`;
}

function SuggestionRow({
  s,
  reason,
  direction,
  disabled,
  onAsk,
}: {
  s: PushSuggestion | null;
  reason?: string;
  direction: "up" | "down";
  disabled: boolean;
  onAsk: (s: PushSuggestion) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!s) {
    return (
      <div className="push-row">
        <span className="push-arrow" title={POLE[direction]}>{ARROW[direction]}</span>
        <span className="note push-text">{reason || "No suggestion."}</span>
      </div>
    );
  }
  return (
    <div className="push-row-wrap">
      <div className="push-row">
        <span className="push-arrow" title={POLE[direction]}>{ARROW[direction]}</span>
        <button className="link push-text" onClick={() => setOpen((o) => !o)} title="Show details">
          {s.question}
        </button>
        <span className="mono push-delta" title={`Predicted change of the ideology index (${POLE[direction]})`}>
          {fmtSigned(s.predicted_delta, 3)}
        </span>
        <button className="btn primary small" disabled={disabled} onClick={() => onAsk(s)}>
          Ask
        </button>
      </div>
      {open && (
        <div className="push-details note">
          <div>
            Survey item <span className="mono">{s.variable}</span>: {s.survey_question}
            {s.is_pole_item ? " · pole item" : ""}
          </div>
          <div>{basisNote(s)}</div>
          {!s.exact && <div>The state is at its size limit; an older answer will be evicted, so the change may differ.</div>}
          <table className="push-table">
            <thead>
              <tr>
                <th>answer</th>
                <th>P</th>
                <th>Δ index</th>
              </tr>
            </thead>
            <tbody>
              {s.responses.map((a) => (
                <tr key={a.answer}>
                  <td>{a.answer}</td>
                  <td className="mono">{a.p.toFixed(3)}</td>
                  <td className="mono">{fmtSigned(a.delta, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Two optimizer-suggested next questions (index up / down) and an automatic push. */
export function IdeologyPush({
  push,
  loading,
  includePoles,
  onIncludePoles,
  disabled,
  onAsk,
  onAuto,
}: {
  push: PushSuggestions | null;
  loading: boolean;
  includePoles: boolean;
  onIncludePoles: (v: boolean) => void;
  disabled: boolean;
  onAsk: (s: PushSuggestion) => void;
  onAuto: (direction: "up" | "down", steps: number) => void;
}) {
  const [direction, setDirection] = useState<"up" | "down">("up");
  const [steps, setSteps] = useState(5);

  if (push && !push.enabled) {
    return <div className="note">{push.reason || "Ideology tracking is not available for this respondent."}</div>;
  }
  const meta = push?.n_candidates
    ? `${push.n_candidates} items scored${push.seconds !== undefined ? ` in ${push.seconds.toFixed(1)} s` : ""}`
    : "";
  return (
    <div className="push">
      {loading && !push ? (
        <div className="note">
          <span className="spinner" /> scoring items…
        </div>
      ) : push ? (
        <>
          <SuggestionRow s={push.up} reason={push.up_reason} direction="up" disabled={disabled || loading} onAsk={onAsk} />
          <SuggestionRow s={push.down} reason={push.down_reason} direction="down" disabled={disabled || loading} onAsk={onAsk} />
        </>
      ) : null}
      <div className="push-auto">
        <span className="note">Push</span>
        <select value={direction} onChange={(e) => setDirection(e.target.value as "up" | "down")} aria-label="Direction">
          <option value="up">↑ up (R)</option>
          <option value="down">↓ down (L)</option>
        </select>
        <input
          type="number"
          min={1}
          max={100}
          value={steps}
          aria-label="Steps"
          onChange={(e) => setSteps(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
        />
        <span className="note">steps</span>
        <button className="btn small" disabled={disabled} onClick={() => onAuto(direction, steps)} title="Ask the optimizer's suggestion step by step, re-scoring after every answer">
          Run
        </button>
      </div>
      <details className="push-more">
        <summary className="note">
          <span title={HELP}>ⓘ how this works</span>
          {meta ? ` · ${meta}` : ""}
        </summary>
        <div className="note" style={{ margin: "4px 0" }}>{HELP}</div>
        <label className="note" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={includePoles} onChange={(e) => onIncludePoles(e.target.checked)} />
          Allow pole-defining items
        </label>
      </details>
    </div>
  );
}
