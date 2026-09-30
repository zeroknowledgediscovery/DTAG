import { useEffect, useRef, useState } from "react";
import { fmtNum, fmtSigned } from "../api";
import type { Anchor, QuestionResult, Suggestion } from "../types";

export function mappingBadge(label: string): string {
  if (label === "DIRECT") return "b-direct";
  if (label === "SEMANTIC / STATE UPDATE") return "b-semupd";
  if (label.startsWith("SEMANTIC")) return "b-sem";
  if (label === "NO MATCH") return "b-nomatch";
  return "b-muted";
}

function Distribution({ anchor }: { anchor: Anchor }) {
  const entries = Object.entries(anchor.distribution);
  const shown = entries.slice(0, 12);
  return (
    <div className="anchor">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span className="var">{anchor.variable}</span>
        {anchor.map_provenance?.map_provenance && (
          <span className="badge b-muted" title={JSON.stringify(anchor.map_provenance, null, 1)}>
            map: {anchor.map_provenance.map_provenance}
            {anchor.map_provenance.fallback_resolution ? ` · ${anchor.map_provenance.fallback_resolution}` : ""}
          </span>
        )}
      </div>
      <div className="q">{anchor.survey_question || <i>(no survey wording in map; native variable name)</i>}</div>
      {shown.map(([lab, p]) => (
        <div key={lab} className={`dist-row ${lab === anchor.response ? "sel" : ""}`} title={lab}>
          <span className="lab">
            {lab === anchor.response ? "▸ " : ""}
            {lab}
          </span>
          <span className="bar">
            <div style={{ width: `${Math.max(0, Math.min(1, p)) * 100}%` }} />
          </span>
          <span className="mono" style={{ textAlign: "right" }}>
            {p.toFixed(3)}
          </span>
        </div>
      ))}
      {entries.length > shown.length && <div className="note">… {entries.length - shown.length} more categories</div>}
      {anchor.map_provenance?.fallback_sources && (
        <div className="note" style={{ marginTop: 4 }}>
          Fallback documentation from: {anchor.map_provenance.fallback_sources}
          {anchor.map_provenance.fallback_consensus_fraction
            ? ` · consensus ${anchor.map_provenance.fallback_consensus_fraction}`
            : ""}
        </div>
      )}
    </div>
  );
}

function Evidence({ r }: { r: QuestionResult }) {
  const geo = r.geographic_conditioning;
  const tmp = r.temporal_conditioning;
  return (
    <details className="evidence">
      <summary>Model evidence</summary>
      <div className="ev-grid">
        <div className="ev-block">
          <h4>Mapping</h4>
          <table className="kv">
            <tbody>
              <tr>
                <th>type</th>
                <td>
                  <span className={`badge ${mappingBadge(r.mapping.label)}`}>{r.mapping.label}</span>{" "}
                  <span className="mono">{r.mapping.type}</span>
                </td>
              </tr>
              <tr>
                <th>semantic fallback mode</th>
                <td className="mono">{r.mapping.semantic_fallback_mode}</td>
              </tr>
              {r.mapping.semantic_trigger && (
                <tr>
                  <th>trigger</th>
                  <td className="mono">{r.mapping.semantic_trigger}</td>
                </tr>
              )}
              <tr>
                <th>state updated</th>
                <td>{r.mapping.state_updated ? "yes" : "no"}</td>
              </tr>
              <tr>
                <th>selected variables</th>
                <td className="mono">{r.selected_variables.join(", ") || "—"}</td>
              </tr>
              {r.lexical_candidates !== undefined && (
                <tr>
                  <th>lexical candidates</th>
                  <td className="mono">{r.lexical_candidates}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="ev-block">
          <h4>Selection rationale</h4>
          <div className="note" style={{ whiteSpace: "pre-wrap" }}>
            {r.display_rationale || r.selection_rationale || "—"}
          </div>
        </div>
        {r.anchors.length > 0 && (
          <div className="ev-block">
            <h4>Survey-response anchors (native LSM conditional distributions)</h4>
            <div className="ev-grid">
              {r.anchors.map((a) => (
                <Distribution key={a.variable} anchor={a} />
              ))}
            </div>
          </div>
        )}
        {r.mapping.semantic_bridge_items?.length > 0 && (
          <div className="ev-block">
            <h4>Semantic bridge</h4>
            <table className="kv">
              <thead>
                <tr>
                  <th>variable</th>
                  <th>relation</th>
                  <th>confidence</th>
                  <th>rationale</th>
                </tr>
              </thead>
              <tbody>
                {r.mapping.semantic_bridge_items.map((b) => (
                  <tr key={b.variable}>
                    <td className="mono">{b.variable}</td>
                    <td>{b.relation_type}</td>
                    <td className="num">{b.confidence.toFixed(2)}</td>
                    <td>{b.rationale}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="ev-block">
          <h4>State updates</h4>
          {Object.keys(r.state_updates).length === 0 ? (
            <div className="note">No persistent survey-state change.</div>
          ) : (
            <table className="kv">
              <tbody>
                {Object.entries(r.state_updates).map(([k, v]) => (
                  <tr key={k}>
                    <td className="mono">{k}</td>
                    <td>{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {r.state_evicted.length > 0 && <div className="note">Evicted (state_keep): {r.state_evicted.join(", ")}</div>}
          <div className="note">
            Ideology: {r.ideology.enabled ? `${fmtNum(r.ideology.before)} → ${fmtNum(r.ideology.after)} (${fmtSigned(r.ideology.delta)})` : "not available"}
          </div>
        </div>
        <div className="ev-block">
          <h4>Conditioning</h4>
          <table className="kv">
            <tbody>
              <tr>
                <th>geography</th>
                <td>
                  <span className="mono">{geo.conditioning_mode}</span>{" "}
                  {Object.keys(geo.conditioned_variables).length
                    ? Object.entries(geo.conditioned_variables).map(([k, v]) => `${k}=${v}`).join(", ")
                    : "(no model variable conditioned)"}
                </td>
              </tr>
              <tr>
                <th>time</th>
                <td>
                  <span className="mono">{tmp.mode}</span> · {tmp.wave}
                  {tmp.resolved_za ? ` · ${tmp.resolved_za}` : ""}
                  {Object.keys(tmp.conditioned_variables || {}).length
                    ? ` · ${Object.entries(tmp.conditioned_variables).map(([k, v]) => `${k}=${v}`).join(", ")}`
                    : ""}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="ev-block">
          <h4>Timings (s)</h4>
          <table className="kv">
            <tbody>
              {Object.entries(r.timings).map(([k, v]) => (
                <tr key={k}>
                  <td className="mono">{k}</td>
                  <td className="num">{v.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </details>
  );
}

export function ChatLog({
  history,
  pending,
  canAsk,
  onAsk,
  emptyHint,
  suggestions = [],
  idPrefix = "",
}: {
  history: QuestionResult[];
  pending: string | null;
  canAsk: boolean;
  onAsk: (q: string) => void;
  emptyHint: React.ReactNode;
  suggestions?: Suggestion[];
  /** Prefix for message anchors (`${idPrefix}q-N`) so two logs on one page never collide. */
  idPrefix?: string;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history.length, pending]);

  return (
    <div className="chat">
      {history.length === 0 && !pending && (
        <div className="empty">
          {emptyHint}
          {suggestions.length > 0 && (
            <div className="suggest-grid">
              {suggestions.map((sg) => (
                <button
                  key={sg.question}
                  className="suggest"
                  disabled={!canAsk}
                  title={`Maps directly to: ${sg.top_variables.join(", ")}`}
                  onClick={() => onAsk(sg.question)}
                >
                  {sg.question}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {history.map((r) => {
        const cls = r.mapping.label === "NO MATCH" ? "nomatch" : r.mapping.label.startsWith("SEMANTIC") ? "sem" : "";
        return (
          <div className="msg" key={r.query_idx} id={`${idPrefix}q-${r.query_idx}`}>
            <div className="msg-q">
              <span className="qn">Q{r.query_idx}</span>
              <span className="qt">{r.question}</span>
            </div>
            <div className={`msg-a ${cls}`}>
              <div className="meta">
                <span className={`badge ${mappingBadge(r.mapping.label)}`}>{r.mapping.label}</span>
                <span className={`badge ${r.state_changed ? "b-neutral" : "b-muted"}`}>
                  {r.state_changed ? "STATE CHANGED" : "STATE UNCHANGED"}
                </span>
                {r.ideology.enabled && r.ideology.delta !== null && r.ideology.delta !== 0 && (
                  <span className="mono">I {fmtSigned(r.ideology.delta)}</span>
                )}
                {r.anchors.slice(0, 4).map((a) => (
                  <span key={a.variable} className="mono">
                    {a.variable}={a.response}
                  </span>
                ))}
                <span style={{ marginLeft: "auto" }}>{r.timings.total?.toFixed(2)} s</span>
              </div>
              <div className="answer">
                {r.answer || (
                  <i className="note">
                    No semantically relevant survey variable was found. The respondent state was not updated.
                  </i>
                )}
              </div>
              <Evidence r={r} />
            </div>
          </div>
        );
      })}
      {pending && (
        <div className="msg">
          <div className="msg-q">
            <span className="qn">Q{history.length + 1}</span>
            <span className="qt">{pending}</span>
          </div>
          <div className="msg-a">
            <span className="spinner" /> selecting survey variables · native LSM inference · rendering answer…
          </div>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}

export function Composer({
  canAsk,
  onAsk,
  suggestions = [],
  onSequence,
  placeholder = "Ask this respondent a question...",
  target,
}: {
  canAsk: boolean;
  onAsk: (q: string) => void;
  suggestions?: Suggestion[];
  onSequence?: () => void;
  placeholder?: string;
  /** Optional "ask whom" selector shown before the input (two-respondent mode). */
  target?: React.ReactNode;
}) {
  const [q, setQ] = useState("");
  return (
    <div className="composer">
      {suggestions.length > 0 && (
        <div className="suggest-row">
          <span className="note">Try:</span>
          {suggestions.slice(0, 4).map((sg) => (
            <button
              key={sg.question}
              className="suggest small"
              disabled={!canAsk}
              title={`Maps directly to: ${sg.top_variables.join(", ")}`}
              onClick={() => onAsk(sg.question)}
            >
              {sg.question}
            </button>
          ))}
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const t = q.trim();
          if (!t || !canAsk) return;
          onAsk(t);
          setQ("");
        }}
      >
        {target}
        <input
          type="text"
          placeholder={placeholder}
          value={q}
          disabled={!canAsk}
          onChange={(e) => setQ(e.target.value)}
          maxLength={2000}
        />
        <button className="btn primary" disabled={!canAsk || !q.trim()}>
          Ask
        </button>
        {onSequence && (
          <button type="button" className="btn" disabled={!canAsk} onClick={onSequence} title="Run many questions in order from a file or pasted list">
            Run sequence…
          </button>
        )}
      </form>
    </div>
  );
}
