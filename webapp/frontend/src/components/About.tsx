import { useEffect, useState } from "react";
import { api } from "../api";

/** About DTAG: what it is, who made it (ZeD Lab, University of Kentucky), data sources, version. */
export function AboutDialog({ onClose }: { onClose: () => void }) {
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const version = health ? String(health.dtag_version ?? "") : "";
  const commit = health?.git_commit ? String(health.git_commit).slice(0, 10) : "";

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal about" role="dialog" aria-modal="true" aria-labelledby="about-title" onClick={(e) => e.stopPropagation()}>
        <div className="about-h">
          <span className="brand-mark about-mark" aria-hidden="true">
            <svg viewBox="0 0 64 64" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round">
              <circle cx="20" cy="20" r="7.5" />
              <path d="M6 50c0-8.3 6.3-14.5 14-14.5S34 41.7 34 50" />
              <g strokeDasharray="4 5" opacity="0.85">
                <circle cx="44" cy="20" r="7.5" />
                <path d="M30 50c0-8.3 6.3-14.5 14-14.5S58 41.7 58 50" />
              </g>
            </svg>
          </span>
          <div>
            <h2 id="about-title">DTAG</h2>
            <div className="note">Digital Twin Anchored Generation · native LSM workbench</div>
          </div>
          <button className="link about-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <p>
          DTAG builds a digital twin of a survey respondent from a persona and lets you question it. Every answer is
          anchored to the conditional response distributions of a native LSM model trained on real survey data, and the
          respondent's survey state carries forward from question to question, so you can follow how answers, the
          ideology index and the whole predicted-answer landscape evolve.
        </p>

        <div className="about-credit">
          <div className="section-title">Developed by</div>
          <div>
            <b>ZeD Lab</b>, University of Kentucky
          </div>
          <div>
            Contact: <a href="mailto:ishanu_ch@uky.edu">ishanu_ch@uky.edu</a>
          </div>
        </div>

        <div className="about-credit">
          <div className="section-title">Survey data</div>
          <div className="note">
            Models are trained on the General Social Survey (NORC at the University of Chicago), the World Values Survey,
            Afrobarometer and Eurobarometer (GESIS). The surveys' producers bear no responsibility for the models or their
            use here.
          </div>
        </div>

        <div className="about-foot note">
          {version && <span>version {version}</span>}
          {commit && <span className="mono">commit {commit}</span>}
          <a href="/docs" target="_blank" rel="noreferrer">
            API docs
          </a>
          <a href="https://github.com/zeroknowledgediscovery/dtag" target="_blank" rel="noreferrer">
            repository
          </a>
        </div>
      </div>
    </div>
  );
}
