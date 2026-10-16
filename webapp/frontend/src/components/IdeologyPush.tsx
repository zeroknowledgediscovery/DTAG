import { useState } from "react";
import { fmtSigned } from "../api";
import type { PushSuggestion, PushSuggestions } from "../types";

const DIR_LABEL = { up: "↑ toward R pole", down: "↓ toward L pole" } as const;

function SuggestionCard({
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
      <div className="box push-card">
        <div className="push-dir">{DIR_LABEL[direction]}</div>
        <div className="note">{reason || "No suggestion."}</div>
      </div>
    );
  }
  return (
    <div className="box push-card">
      <div className="push-dir">
        {DIR_LABEL[direction]}
        <span className={`mono push-delta ${s.predicted_delta >= 0 ? "pos" : "neg"}`} title="Predicted change of the ideology index">
          Δ {fmtSigned(s.predicted_delta, 4)}
        </span>
      </div>
      <div className="push-q">{s.question}</div>
      <div className="note">
        survey item <span className="mono">{s.variable}</span>: {s.survey_question}
      </div>
      <div className="note">
        {s.objective === "modal" ? (
          <>
            exact if answered “{s.modal_answer}” (p = {s.p_modal.toFixed(2)}, this respondent's most likely answer, which the
            session records) · average over answers {fmtSigned(s.expected_delta, 4)}
          </>
        ) : (
          <>
            expected over the model's answer distribution · P(up) {s.P_up.toFixed(2)} · P(down) {s.P_down.toFixed(2)}
          </>
        )}
        {s.is_pole_item ? " · pole item" : ""}
        {!s.exact ? " · state is at its size limit; an older answer will be evicted, so the change may differ" : ""}
      </div>
      <div className="actions" style={{ marginTop: 6 }}>
        <button className="btn primary" disabled={disabled} onClick={() => onAsk(s)}>
          Ask this
        </button>
        <button className="link" onClick={() => setOpen((o) => !o)}>
          {open ? "hide answers" : "all answers"}
        </button>
      </div>
      {open && (
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
  return (
    <div className="push">
      <div className="note" style={{ marginBottom: 6 }}>
        The one-step optimizer scores every unanswered opinion item at this respondent's current state and suggests the
        question that moves the ideology index most in each direction. Asking it answers exactly that survey item, so the
        recorded and plotted index changes by the predicted amount.
        {push?.n_candidates ? ` ${push.n_candidates} items scored${push.seconds !== undefined ? ` in ${push.seconds.toFixed(1)} s` : ""}.` : ""}
      </div>
      {loading && !push ? (
        <div className="note">
          <span className="spinner" /> scoring items…
        </div>
      ) : push ? (
        <>
          <SuggestionCard s={push.up} reason={push.up_reason} direction="up" disabled={disabled || loading} onAsk={onAsk} />
          <SuggestionCard s={push.down} reason={push.down_reason} direction="down" disabled={disabled || loading} onAsk={onAsk} />
        </>
      ) : null}
      <label className="field" style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
        <input type="checkbox" checked={includePoles} onChange={(e) => onIncludePoles(e.target.checked)} />
        <span style={{ display: "inline", margin: 0 }}>Allow pole-defining items</span>
      </label>
      <div className="box push-auto">
        <b>Automatic push</b>
        <div className="note">Ask the optimizer's suggestion step by step, re-scoring after every answer.</div>
        <div className="row" style={{ alignItems: "flex-end", gap: 8 }}>
          <label className="field">
            <span>Direction</span>
            <select value={direction} onChange={(e) => setDirection(e.target.value as "up" | "down")}>
              <option value="up">↑ up (R)</option>
              <option value="down">↓ down (L)</option>
            </select>
          </label>
          <label className="field">
            <span>Steps</span>
            <input
              type="number"
              min={1}
              max={100}
              value={steps}
              onChange={(e) => setSteps(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
              style={{ width: 70 }}
            />
          </label>
          <button className="btn" disabled={disabled} onClick={() => onAuto(direction, steps)}>
            Run
          </button>
        </div>
      </div>
    </div>
  );
}
