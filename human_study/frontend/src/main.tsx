import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Question = { question_id: string; text: string; choices: { value: string; label: string }[]; required: boolean };
type View = { session_id: string; phase: string; session_version: number; question: Question | null;
  consent: string | null; receipt: string | null; progress: { completed: number; total: number } };
type Pending = { question_id: string; answer_value: string | null; missing_reason: string | null;
  idempotency_key: string; expected_session_version: number };

async function api(route: string, data?: unknown) {
  const response = await fetch('/api/human/' + route, { credentials: 'same-origin',
    method: data === undefined ? 'GET' : 'POST',
    headers: data === undefined ? {} : { 'Content-Type': 'application/json' },
    body: data === undefined ? undefined : JSON.stringify(data) });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Please refresh and try again.');
  return body;
}

function App() {
  const [view, setView] = useState<View | null>(null);
  const [selected, setSelected] = useState('');
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<Pending | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  const accept = (next: View) => {
    setView(next); setSelected('');
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
  useEffect(() => { void perform(() => api('start', {})); }, []);
  useEffect(() => { heading.current?.focus(); }, [view?.question?.question_id, view?.phase]);

  async function answer(value: string | null, reason: string | null = null) {
    if (!view?.question) return;
    pending.current ??= { question_id: view.question.question_id, answer_value: value, missing_reason: reason,
      idempotency_key: crypto.randomUUID(), expected_session_version: view.session_version };
    const record = pending.current;
    await perform(async () => {
      const result = await api('answer', record);
      pending.current = null;
      return result.current;
    });
  }
  const labels: Record<string, string> = { baseline: 'Starting questions', intervention: 'Study questions', outcome: 'Final questions' };

  return <main aria-busy={busy}>
    <header><span className="eyebrow">RESEARCH PARTICIPATION</span><h1>One question at a time</h1>
      <p>Choose the answer that best reflects your view. There are no right or wrong answers.</p></header>
    {view && !['consent', 'complete', 'declined'].includes(view.phase) && <section aria-label="Study progress" className="progress">
      <p>{labels[view.phase] || 'Finishing'} · {view.progress.completed} of {view.progress.total} questions saved</p>
      <progress value={view.progress.completed} max={view.progress.total} aria-label="Questions saved"/>
    </section>}
    {view?.phase === 'consent' && <section>
      <h2 tabIndex={-1} ref={heading}>Before you begin</h2><p className="consent">{view.consent}</p>
      <label className="ack"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>
        I have read the instructions and agree to participate.</label>
      <div className="actions"><button disabled={busy || !consent} onClick={() => void perform(() => api('consent', { accepted: true, expected_session_version: view.session_version }))}>Begin study</button>
        <button className="secondary" disabled={busy} onClick={() => void perform(() => api('consent', { accepted: false, expected_session_version: view.session_version }))}>Do not participate</button></div>
    </section>}
    {view?.question && <form onSubmit={e => { e.preventDefault(); void answer(selected); }}>
      <h2 tabIndex={-1} ref={heading} id="question-title">{view.question.text}</h2>
      <fieldset disabled={busy || pending.current !== null} aria-labelledby="question-title"><legend className="sr-only">Choose one answer</legend>
        {view.question.choices.map(choice => <label className="choice" key={choice.value}>
          <input type="radio" name="answer" value={choice.value} checked={selected === choice.value}
            onChange={() => setSelected(choice.value)} required={view.question?.required}/><span>{choice.label}</span>
        </label>)}
      </fieldset>
      <div className="actions"><button disabled={busy || !selected || pending.current !== null} type="submit">Save and continue</button>
        {!view.question.required && <button className="secondary" type="button" disabled={busy || pending.current !== null}
          onClick={() => void answer(null, 'prefer_not_to_answer')}>Prefer not to answer</button>}</div>
    </form>}
    {view?.phase === 'ready_to_complete' && <section><h2 ref={heading} tabIndex={-1}>Your questions are finished</h2>
      <p>Finish to save your study receipt.</p><button disabled={busy} onClick={() => void perform(() => api('complete', {}))}>Finish study</button></section>}
    {view?.phase === 'complete' && <section><h2 ref={heading} tabIndex={-1}>Thank you. Your session is complete.</h2>
      <p>Your internal study receipt:</p><p className="receipt" data-testid="receipt">{view.receipt}</p>
      <p className="muted">Session: {view.session_id}</p><p>This is an internal receipt, not a payment or Prolific completion code. You may close this page.</p></section>}
    {view?.phase === 'declined' && <section><h2 ref={heading} tabIndex={-1}>You have not enrolled in the study.</h2><p>You may close this page.</p></section>}
    {busy && <p role="status" className="status">Saving and preparing your next step…</p>}
    {error && <aside role="alert"><p>{error}</p><button className="secondary" disabled={busy} onClick={() => {
      if (pending.current) void answer(pending.current.answer_value, pending.current.missing_reason);
      else void perform(() => view ? api('current') : api('start', {}));
    }}>Retry</button><button className="secondary" disabled={busy} onClick={() => void perform(() => api('current'))}>Refresh saved state</button></aside>}
    {!view && !busy && !error && <p>Preparing the study…</p>}
    <footer>You can stop at any time. Keep this browser’s cookies to resume an interrupted session.</footer>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App/>);
