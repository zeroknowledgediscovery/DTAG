import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Question = { question_id: string; text: string; choices: { value: string; label: string }[]; required: boolean; response_mode?: "click" | "free_text_llm" | "free_text_multi" };
const isWrittenMode = (q: Question | null | undefined) =>
  q?.response_mode === 'free_text_llm' || q?.response_mode === 'free_text_multi';

type View = { session_id: string; phase: string; session_version: number; question: Question | null;
  consent: string | null; receipt: string | null; progress: { completed: number; total: number };
  completion_code?: string | null; completion_url?: string | null;
  test_restart_allowed?: boolean };
type Pending = { question_id: string; answer_value: string | null; text_answer: string | null; missing_reason: string | null;
  idempotency_key: string; expected_session_version: number };

// Prolific appends these to the study URL; they link the session to the participant.
function prolificParams() {
  const query = new URLSearchParams(window.location.search);
  const fields: Record<string, string> = {};
  for (const [param, field] of [['PROLIFIC_PID', 'prolific_pid'], ['STUDY_ID', 'prolific_study_id'],
    ['SESSION_ID', 'prolific_session_id']]) {
    const value = query.get(param);
    if (value && /^[A-Za-z0-9]{1,64}$/.test(value)) fields[field] = value;
  }
  return fields;
}

async function api(route: string, data?: unknown) {
  const response = await fetch('/api/human/' + route, { credentials: 'same-origin',
    method: data === undefined ? 'GET' : 'POST',
    headers: data === undefined ? {} : { 'Content-Type': 'application/json' },
    body: data === undefined ? undefined : JSON.stringify(data) });
  // A Cloud Run 500 may be plain text ("Internal Server Error"), not JSON.
  // Preserve the last question and retry token instead of exposing a JSON
  // parser failure that obscures the actual HTTP status.
  const raw = await response.text();
  let body: any;
  try {
    body = JSON.parse(raw);
  } catch {
    throw new Error(response.ok
      ? 'Invalid response from the study server. Refresh saved state.'
      : `Study server error (HTTP ${response.status}). Refresh saved state; the answer may already be saved.`);
  }
  if (!response.ok) throw new Error(typeof body.detail === 'string'
    ? body.detail : `Study server error (HTTP ${response.status}). Refresh saved state.`);
  return body;
}

function App() {
  const [view, setView] = useState<View | null>(null);
  const [selected, setSelected] = useState('');
  const [written, setWritten] = useState('');
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<Pending | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  const accept = (next: View) => {
    const sameQuestion = view?.question?.question_id === next.question?.question_id;
    setView(next); setSelected('');
    if (!sameQuestion) setWritten('');
    // Refresh/restart may have reconciled the prior answer. Never reapply it to a new item.
    if (pending.current?.question_id !== next.question?.question_id) pending.current = null;
  };
  async function perform(operation: () => Promise<View>) {
    if (busy) return;
    setBusy(true); setError('');
    try { accept(await operation()); }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to save. Please retry.'); }
    finally { setBusy(false); }
  }
  useEffect(() => { void perform(() => api('start', prolificParams())); }, []);

  async function startNewTestSession() {
    if (busy || !view?.test_restart_allowed) return;
    if (!window.confirm(
      'Start a new test session from question 1? Your previous answers will remain archived, but this browser will switch to a new session.'
    )) return;
    await perform(async () => {
      // Only discard local draft and retry tokens AFTER the server has
      // created the new session and sent a replacement signed cookie.
      const fresh = await api('restart', {});
      pending.current = null;
      setSelected('');
      setWritten('');
      setConsent(false);
      return fresh;
    });
  }
  useEffect(() => { heading.current?.focus(); }, [view?.question?.question_id, view?.phase]);

  // An answer may be securely committed while the NEXT LLM question is
  // preparing. Never present a stale answer field as though saving failed.
  // A bounded 10-second poll resumes the same signed session automatically.
  const nextQuestionPending = !!view && !view.question &&
    ['baseline', 'intervention', 'attention', 'outcome'].includes(view.phase);
  useEffect(() => {
    if (!nextQuestionPending || busy) return;
    const timer = window.setTimeout(() => {
      void perform(() => api('current'));
    }, 10000);
    return () => window.clearTimeout(timer);
  }, [nextQuestionPending, view?.progress?.completed, busy, error]);

  async function answer(value: string | null, reason: string | null = null) {
    if (!view?.question) return;
    const freeText = isWrittenMode(view.question);
    pending.current ??= { question_id: view.question.question_id,
      answer_value: freeText ? null : value,
      text_answer: freeText ? written.trim() : null, missing_reason: reason,
      idempotency_key: crypto.randomUUID(), expected_session_version: view.session_version };
    const record = pending.current;
    await perform(async () => {
      try {
        const result = await api('answer', record);
        pending.current = null;
        return result.current;
      } catch (err) {
        // Ambiguous prose was not accepted or saved. Allow participant to
        // revise it rather than locking the text box behind a retry token.
        if (err instanceof Error && (
          err.message.includes('could not confidently interpret') ||
          err.message.includes('needs an opinion') ||
          err.message.includes('Please clarify') ||
          err.message.includes('No valid survey-category interpretation') ||
          err.message.includes('Please write')
        )) pending.current = null;
        throw err;
      }
    });
  }
  const labels: Record<string, string> = { baseline: 'Starting questions', intervention: 'Study questions', outcome: 'Final questions', attention: 'Attention check' };

  return <main aria-busy={busy}>
    <header><span className="eyebrow">RESEARCH PARTICIPATION</span><h1>One question at a time</h1>
      <p>{isWrittenMode(view?.question)
        ? "Please write your answer in your own words. There are no right or wrong opinions."
        : "Choose the answer that best reflects your view. There are no right or wrong answers."}</p></header>
    {view && !['consent', 'complete', 'declined'].includes(view.phase) && <section aria-label="Study progress" className="progress">
      <p>{labels[view.phase] || 'Finishing'} · {view.progress.completed} of {view.progress.total} questions saved</p>
      <progress value={view.progress.completed} max={view.progress.total} aria-label="Questions saved"/>
    </section>}
    {view?.test_restart_allowed && <section className="test-session-controls" aria-label="Test session controls">
      <span>Internal testing</span>
      <button type="button" className="secondary" disabled={busy}
        onClick={() => void startNewTestSession()}>Start new test session</button>
      <p className="muted">Starts from question 1. Your existing test data will remain saved.</p>
    </section>}
    {view?.phase === 'consent' && <section>
      <h2 tabIndex={-1} ref={heading}>Before you begin</h2><p className="consent">{view.consent}</p>
      <label className="ack"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>
        I have read the instructions and agree to participate.</label>
      <div className="actions"><button disabled={busy || !consent} onClick={() => void perform(() => api('consent', { accepted: true, expected_session_version: view.session_version }))}>Begin study</button>
        <button className="secondary" disabled={busy} onClick={() => void perform(() => api('consent', { accepted: false, expected_session_version: view.session_version }))}>Do not participate</button></div>
    </section>}
    {view?.question && <form onSubmit={e => { e.preventDefault(); void answer(isWrittenMode(view.question) ? null : selected); }}>
      <h2 tabIndex={-1} ref={heading} id="question-title">{view.question.text}</h2>
      {isWrittenMode(view.question) ? <>
        <label className="written-label" htmlFor="written-answer">Your answer, in your own words</label>
        <textarea id="written-answer" value={written} maxLength={2000} rows={5}
          aria-describedby="written-help" placeholder="Write what you think and why…"
          disabled={busy || pending.current !== null} required
          onChange={e => setWritten(e.target.value)}/>
        <p id="written-help" className="muted">Please avoid names or identifying details. Write a clear opinion so the study can interpret it accurately.</p>
      </> : <>
        <fieldset disabled={busy || pending.current !== null} aria-labelledby="question-title"><legend className="sr-only">Choose one answer</legend>
          {view.question.choices.map(choice => <label className="choice" key={choice.value}>
            <input type="radio" name="answer" value={choice.value} checked={selected === choice.value}
              onChange={() => setSelected(choice.value)} required={view.question?.required}/><span>{choice.label}</span>
          </label>)}
        </fieldset>
      </>}
      <div className="actions">
        <button disabled={busy || pending.current !== null ||
          (isWrittenMode(view.question) ? !written.trim() : !selected)}
          type="submit">Save and continue</button>
        {!isWrittenMode(view.question) && !view.question.required &&
          <button className="secondary" type="button" disabled={busy || pending.current !== null}
            onClick={() => void answer(null, 'prefer_not_to_answer')}>Prefer not to answer</button>}
      </div>
    </form>}
    {nextQuestionPending && <section aria-live="polite" className="preparing-next">
      <h2>Answer saved. Preparing your next question.</h2>
      <p>Question generation may take another attempt. Your previous answer is already saved; there is no need to resubmit it.</p>
      <button className="secondary" type="button" disabled={busy}
        onClick={() => void perform(() => api('current'))}>Check for next question</button>
    </section>}
    {view?.phase === 'ready_to_complete' && <section><h2 ref={heading} tabIndex={-1}>Your questions are finished</h2>
      <p>Finish to save your study receipt.</p><button disabled={busy} onClick={() => void perform(() => api('complete', {}))}>Finish study</button></section>}
    {view?.phase === 'complete' && (view.completion_code ? <section>
      <h2 ref={heading} tabIndex={-1}>Thank you. Your session is complete.</h2>
      <p>Your Prolific completion code:</p><p className="receipt" data-testid="completion-code">{view.completion_code}</p>
      {view.completion_url && <div className="actions"><a className="button" href={view.completion_url}>Return to Prolific</a></div>}
      <p className="muted">If the button does not work, copy the code above into Prolific. Session: {view.session_id}</p></section>
    : <section><h2 ref={heading} tabIndex={-1}>Thank you. Your session is complete.</h2>
      <p>Your internal study receipt:</p><p className="receipt" data-testid="receipt">{view.receipt}</p>
      <p className="muted">Session: {view.session_id}</p><p>This is an internal receipt, not a payment or Prolific completion code. You may close this page.</p></section>)}
    {view?.phase === 'declined' && <section>
      <h2 ref={heading} tabIndex={-1}>You did not consent to participate.</h2>
      <p>No study questions will be presented. Please return to Prolific and return your submission. The study reward is not paid for a no-consent return.</p>
      {view.completion_url ? <>
        <div className="actions"><a className="button" href={view.completion_url}>Return to Prolific (no consent)</a></div>
        <p className="muted">No-consent return code: <span data-testid="no-consent-code">{view.completion_code}</span>. This is not a paid-completion code.</p>
      </> : <p>You may close this page.</p>}
    </section>}
    {busy && <p role="status" className="status">Saving and preparing your next step…</p>}
    {error && <aside role="alert"><p>{error}</p><button className="secondary" disabled={busy} onClick={() => {
      if (pending.current) void answer(pending.current.answer_value, pending.current.missing_reason);
      else void perform(() => view ? api('current') : api('start', prolificParams()));
    }}>Retry</button><button className="secondary" disabled={busy} onClick={() => void perform(() => api('current'))}>Refresh saved state</button></aside>}
    {!view && !busy && !error && <p>Preparing the study…</p>}
    <footer>You can stop at any time. Refresh this page to resume the saved session.
      {view?.test_restart_allowed && ' To begin again with a fresh test session, use Start new test session above.'}
    </footer>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App/>);
