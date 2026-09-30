import { useState } from "react";
import { fmtNum, fmtSigned } from "../api";
import type { SequenceStatus } from "../types";

/** Same rules as the server: one per line; skip blanks, # comments, a "question" header. */
export function parseQuestions(text: string): string[] {
  const out: string[] = [];
  text.split(/\r?\n/).forEach((line, i) => {
    const q = line.trim().replace(/^"|"$/g, "").trim();
    if (!q || q.startsWith("#")) return;
    if (i === 0 && q.toLowerCase() === "question") return;
    out.push(q);
  });
  return out;
}

export function SequenceDialog({
  modelLabel,
  ideology,
  questionCount,
  onClose,
  onRun,
}: {
  modelLabel: string;
  ideology: boolean;
  questionCount: number;
  onClose: () => void;
  onRun: (text: string, name: string, resetFirst: boolean) => void;
}) {
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [resetFirst, setResetFirst] = useState(questionCount > 0);
  const [err, setErr] = useState<string | null>(null);
  const qs = parseQuestions(text);

  const onFile = (f: File | undefined) => {
    if (!f) return;
    if (f.size > 500_000) {
      setErr("File is larger than 500 KB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setText(String(reader.result || ""));
      setName((n) => n || f.name.replace(/\.[^.]+$/, ""));
      setErr(null);
    };
    reader.readAsText(f);
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <h2>Run a question sequence</h2>
          <button className="link" onClick={onClose}>
            close ✕
          </button>
        </div>
        <div className="note" style={{ marginBottom: 10 }}>
          Questions are asked in order to the current respondent ({modelLabel}); the survey state carries forward from each
          answer to the next.{" "}
          {ideology ? "The ideology index is tracked after every question." : "This survey has no ideology index; answers and state changes are still recorded."}
        </div>

        <label className="field">
          <span>Upload a text file — one question per line (blank lines and lines starting with # are ignored)</span>
          <input type="file" accept=".txt,.csv,text/plain,text/csv" onChange={(e) => onFile(e.target.files?.[0])} />
        </label>
        <label className="field">
          <span>…or paste questions</span>
          <textarea
            rows={8}
            value={text}
            placeholder={"Should the government reduce income differences between rich and poor?\nDo immigrants increase crime rates?\n..."}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        <div className="row">
          <label className="field">
            <span>Name (optional)</span>
            <input type="text" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field" style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 14 }}>
            <input type="checkbox" checked={resetFirst} onChange={(e) => setResetFirst(e.target.checked)} />
            <span style={{ display: "inline", margin: 0 }}>
              Reset respondent first {questionCount > 0 ? `(${questionCount} questions asked so far)` : ""}
            </span>
          </label>
        </div>

        <div className="note">
          <b>{qs.length}</b> question{qs.length === 1 ? "" : "s"} detected
          {qs.length > 500 && <span style={{ color: "var(--err)" }}> — at most 500 per sequence</span>}
        </div>
        {qs.length > 0 && (
          <ol className="seq-preview">
            {qs.slice(0, 6).map((q, i) => (
              <li key={i}>{q}</li>
            ))}
            {qs.length > 6 && <li className="note">… {qs.length - 6} more</li>}
          </ol>
        )}
        {err && <div className="error">{err}</div>}
        <div className="actions" style={{ marginTop: 10 }}>
          <button
            className="btn primary"
            disabled={qs.length === 0 || qs.length > 500}
            onClick={() => onRun(text, name, resetFirst)}
          >
            Run {qs.length || ""} question{qs.length === 1 ? "" : "s"}
          </button>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export function SequenceCard({
  seq,
  onCancel,
  onJump,
}: {
  seq: SequenceStatus;
  onCancel: () => void;
  onJump: (queryIdx: number) => void;
}) {
  const running = seq.status === "queued" || seq.status === "running";
  const pct = seq.total ? (100 * seq.completed) / seq.total : 0;
  const ide = seq.ideology;
  const last = seq.first_query_idx !== null ? seq.first_query_idx + seq.completed - 1 : null;
  return (
    <div className="box seq-card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
        <b>Question sequence{seq.name ? ` · ${seq.name}` : ""}</b>
        <span className={`badge ${seq.status === "done" ? "b-direct" : seq.status === "error" ? "b-nomatch" : "b-neutral"}`}>
          {running && <span className="spinner" />} {seq.status}
        </span>
      </div>
      <div className="note">
        {seq.completed}/{seq.total} questions
        {seq.first_query_idx !== null && seq.completed > 0 ? ` (Q${seq.first_query_idx}–Q${last})` : ""} · {seq.elapsed_seconds.toFixed(0)} s
        {seq.reset_first ? " · started from a reset respondent" : ""}
      </div>
      <div className="progress">
        <div style={{ width: `${pct}%` }} />
      </div>
      {running && (
        <button className="link" onClick={onCancel} style={{ marginTop: 4 }}>
          Cancel after the current question
        </button>
      )}
      {seq.error && <div className="error">{seq.error}</div>}

      {ide.enabled ? (
        <>
          <div className="row" style={{ marginTop: 8, alignItems: "baseline" }}>
            <div>
              <div className="note">start</div>
              <div className="mono">{fmtNum(ide.start)}</div>
            </div>
            <div>
              <div className="note">{running ? "now" : "end"}</div>
              <div className="mono">{fmtNum(ide.end)}</div>
            </div>
            <div>
              <div className="note">net change</div>
              <div className="bignum" style={{ fontSize: 18 }}>
                {fmtSigned(ide.net_change)}
              </div>
            </div>
          </div>
          <div className="note">
            range {fmtNum(ide.min)} … {fmtNum(ide.max)}
          </div>
          {ide.top_movers.length > 0 && (
            <>
              <div className="note" style={{ marginTop: 6 }}>
                Questions that moved the index most:
              </div>
              <ul className="movers">
                {ide.top_movers.map((m) => (
                  <li key={m.query_idx} onClick={() => onJump(m.query_idx)} title={Object.entries(m.anchors).map(([k, v]) => `${k}=${v}`).join("; ")}>
                    <span className="mono">Q{m.query_idx}</span>
                    <span className={`mono ${m.delta < 0 ? "neg" : "pos"}`}>{fmtSigned(m.delta)}</span>
                    <span className="qt">{m.question}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      ) : (
        <div className="note" style={{ marginTop: 6 }}>
          Ideology trajectory is not available for this survey/profile.
        </div>
      )}
    </div>
  );
}
