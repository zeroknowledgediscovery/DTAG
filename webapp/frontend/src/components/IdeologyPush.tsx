import { useState } from "react";
import { fmtSigned } from "../api";
import type { PushCheck, PushMode, PushSuggestion, PushSuggestions } from "../types";

const ARROW = { up: "↑", down: "↓" } as const;
const POLE = { up: "toward the R pole", down: "toward the L pole" } as const;

const HELP =
  "The one-step optimizer scores every unanswered opinion item at this respondent's current state and suggests, for " +
  "each direction, the item that moves the ideology index most, with a question written for it.";

const MODE_HELP: Record<PushMode, string> = {
  realistic:
    "Realistic (default): the question is asked like any typed question. The normal mapping chooses which survey " +
    "items it updates, which may include other items or miss the suggested one, so the realized change can differ " +
    "from the prediction for the item.",
  validated:
    "Validated: the questions for the top items are first run through the normal mapping. Questions that don't map " +
    "back to their item are dropped; the rest are ranked by the exact change of all the items they map to, and the " +
    "question is answered through that checked mapping, so the realized change matches the prediction.",
  direct:
    "Push: the question is answered through exactly the suggested survey item (the question-to-item mapping is " +
    "skipped), so the index changes by the predicted amount for that item (exactly, when the session records the " +
    "most likely answer).",
};

const MODE_LABEL: Record<PushMode, string> = { realistic: "realistic", validated: "validated", direct: "push" };

function mappingNote(s: PushSuggestion): string | null {
  if (s.mode !== "validated" || !s.mapped_variables) return null;
  const others = s.mapped_variables.filter((v) => v !== s.variable);
  return (
    `Maps to ${s.mapped_variables.join(", ")}` +
    (others.length
      ? ` · predicted change of all mapped items ${fmtSigned(s.predicted_delta, 4)} (item alone ${fmtSigned(s.item_delta ?? 0, 4)})`
      : "") +
    "."
  );
}

function CheckedList({ checked }: { checked?: PushCheck[] }) {
  if (!checked || checked.length < 2) return null;
  return (
    <div>
      Checked {checked.length} candidates:{" "}
      {checked.map((c, i) => (
        <span key={c.variable} title={`${c.question}\nmaps to: ${c.mapped_variables.join(", ") || "none"}`}>
          {i ? ", " : ""}
          <span className="mono">{c.variable}</span> {c.hit ? "✓" : "✗"}
        </span>
      ))}
    </div>
  );
}

function basisNote(s: PushSuggestion): string {
  const alone = s.mode === "validated" && (s.mapped_variables?.length ?? 0) > 1 ? `${s.variable} alone: ` : "";
  return alone + (s.objective === "modal"
    ? `Exact if answered “${s.modal_answer}” (p = ${s.p_modal.toFixed(2)}, the most likely answer, which this session records). ` +
        `Average over all answers: ${fmtSigned(s.expected_delta, 4)}.`
    : `Expected change over the model's answer distribution · P(up) ${s.P_up.toFixed(2)} · P(down) ${s.P_down.toFixed(2)}.`);
}

function SuggestionRow({
  s,
  reason,
  checked,
  direction,
  disabled,
  onAsk,
}: {
  s: PushSuggestion | null;
  reason?: string;
  checked?: PushCheck[];
  direction: "up" | "down";
  disabled: boolean;
  onAsk: (s: PushSuggestion) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!s) {
    return (
      <div className="push-row">
        <span className="push-arrow" title={POLE[direction]}>{ARROW[direction]}</span>
        <span className="note push-text" title={checked?.map((c) => `${c.variable}: ${c.hit ? "maps back" : "misses"}`).join("\n")}>
          {reason || "No suggestion."}
        </span>
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
          {mappingNote(s) && <div>{mappingNote(s)}</div>}
          <div>{basisNote(s)}</div>
          <CheckedList checked={checked} />
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
  mode,
  onMode,
  disabled,
  onAsk,
  onAuto,
}: {
  push: PushSuggestions | null;
  loading: boolean;
  includePoles: boolean;
  onIncludePoles: (v: boolean) => void;
  mode: PushMode;
  onMode: (m: PushMode) => void;
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
          <span className="spinner" /> {mode === "validated" ? "scoring items and checking question mappings…" : "scoring items…"}
        </div>
      ) : push ? (
        <>
          <SuggestionRow s={push.up} reason={push.up_reason} checked={push.up_checked} direction="up" disabled={disabled || loading} onAsk={onAsk} />
          <SuggestionRow s={push.down} reason={push.down_reason} checked={push.down_checked} direction="down" disabled={disabled || loading} onAsk={onAsk} />
        </>
      ) : null}
      <div className="push-auto">
        <div className="seg push-mode" role="radiogroup" aria-label="Push mode">
          {(["realistic", "validated", "direct"] as const).map((m) => (
            <button
              key={m}
              role="radio"
              aria-checked={mode === m}
              className={`seg-btn${mode === m ? " on" : ""}`}
              disabled={disabled}
              title={MODE_HELP[m]}
              onClick={() => mode !== m && onMode(m)}
            >
              {MODE_LABEL[m]}
            </button>
          ))}
        </div>
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
        <div className="note" style={{ margin: "4px 0" }}>{MODE_HELP[mode]}</div>
        <label className="note" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={includePoles} onChange={(e) => onIncludePoles(e.target.checked)} />
          Allow pole-defining items
        </label>
      </details>
    </div>
  );
}
