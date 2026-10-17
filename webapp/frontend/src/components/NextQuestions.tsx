import type { NextQuestion, NextQuestions as Data } from "../types";

const KINDS = [
  {
    key: "open" as const,
    icon: "?",
    label: "Most open",
    why: (n: NextQuestion) =>
      `The twin is least decided here: settled ${(n.s * 100).toFixed(0)}% (likely “${n.m}”, p ${n.p.toFixed(2)}).`,
  },
  {
    key: "connected" as const,
    icon: "◎",
    label: "Most connected",
    why: (n: NextQuestion) =>
      `${n.n_dependents} other predictions depend on it in the model; answering it is the most likely to reshape the landscape.`,
  },
];

/** Two informative next questions for respondents without an ideology index (from the decision landscape). */
export function NextQuestions({
  data,
  pending,
  disabled,
  onAsk,
}: {
  data: Data | null;
  pending: boolean;
  disabled: boolean;
  onAsk: (question: string, kind: "open" | "connected") => void;
}) {
  if (!data) {
    return (
      <div className="note">
        <span className="spinner" /> {pending ? "mapping the decision landscape…" : "finding informative questions…"}
      </div>
    );
  }
  return (
    <div className="push">
      {KINDS.map((k) => {
        const n = data[k.key];
        if (!n) return null;
        return (
          <div className="push-row" key={k.key}>
            <span className="push-arrow" title={k.label}>{k.icon}</span>
            <span className="push-text" title={`${k.label} · survey item ${n.v} (${n.t}): ${n.survey_question}\n${k.why(n)}`}>
              {n.question}
              <span className="note next-why">{k.label} · {n.t}</span>
            </span>
            <button className="btn primary small" disabled={disabled} onClick={() => onAsk(n.question, k.key)}>
              Ask
            </button>
          </div>
        );
      })}
      <div className="note push-more" title="Without an ideology index there is no up/down direction; these questions are chosen to teach the twin the most. Asking one goes through the normal question-to-item mapping, like a typed question.">
        ⓘ chosen to be informative · asked like a typed question
      </div>
    </div>
  );
}
