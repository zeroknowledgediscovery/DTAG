#!/usr/bin/env python3
"""Read-only interim report for live fixed-arm, zero-calibration DTAG studies.

Read Firestore via active gcloud CLI credentials. No respondent text, Prolific
participant IDs, or session identifiers are printed. No writes are performed.

Example:
  python human_study/scripts/report_nocal_live.py --arm right
  python human_study/scripts/report_nocal_live.py --arm right --campaign-id YOUR_PROLIFIC_STUDY_ID
  python human_study/scripts/report_nocal_live.py --arm right --campaign-id YOUR_PROLIFIC_STUDY_ID --trajectories
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from urllib.parse import quote
from report_left_live import token, list_docs, fields, numeric, describe


def get_rows(root, credential, arm):
    mask = ("consent_accepted", "phase", "policy", "next_step", "attention_completed",
            "state.baseline_index", "state.current_index", "prolific.prolific_study_id",
            "updated_at", "pending_exports")
    rows = []
    for doc in list_docs(root, credential, mask):
        s = fields(doc)
        state = s.get("state") or {}
        base = numeric(state.get("baseline_index"))
        current = numeric(state.get("current_index"))
        consent = s.get("consent_accepted") is True
        if consent and s.get("policy") not in (None, arm):
            raise SystemExit("Unexpected policy in this fixed-" + arm + " study")
        total = int(s.get("next_step") or 0)
        checks = int(s.get("attention_completed") or 0)
        step = total - checks   # no six-question baseline in this experiment
        if not 0 <= step <= 20:
            raise SystemExit("Invalid saved progress: check instrument/study ID")
        rows.append({
            "sid": doc["name"].rsplit("/", 1)[-1],
            "campaign": (s.get("prolific") or {}).get("prolific_study_id") or "(missing STUDY_ID)",
            "consent": consent, "phase": s.get("phase") or "unknown",
            "step": step, "checks": checks,
            "baseline": base, "current": current,
            "delta": current - base if current is not None and base is not None else None,
            "pending": len(s.get("pending_exports") or []),
            "updated": s.get("updated_at") or "",
        })
    return rows


def summary(rows, arm):
    consenting = [r for r in rows if r["consent"]]
    started = [r for r in consenting if r["baseline"] is not None]
    answered = [r for r in started if r["step"] > 0 and r["delta"] is not None]
    full = [r for r in started if r["step"] == 20]
    finalized = [r for r in started if r["phase"] == "complete"]
    print("\nFixed", arm.upper(), "push | zero baseline | LIVE Firestore snapshot")
    print("Enrolled:", len(rows), "consented:", len(consenting),
          "started:", len(started), ">=1 adaptive:", len(answered),
          "20/20:", len(full), "finalized:", len(finalized))
    print("Phases:", dict(sorted(Counter(r["phase"] for r in rows).items())))
    print("Outstanding archive exports:", sum(r["pending"] for r in rows))
    print("Last updated:", max((r["updated"] for r in rows), default="none"))
    print("Initial empty-state index:", describe([r["baseline"] for r in started]))
    print("\nLatest index displacement (+ = rightward, - = leftward):")
    for label, subset in (
        ("At least 1 adaptive", answered),
        ("1-19 adaptive", [r for r in answered if r["step"] < 20]),
        ("20 adaptive", full),
        ("Finalized", finalized),
    ):
        vals = [r["delta"] for r in subset if r["delta"] is not None]
        print(f"  {label:22s} {describe(vals)}")
        if vals:
            good = sum(d > 1e-10 if arm == "right" else d < -1e-10 for d in vals)
            print(f"    Directional success: {good}/{len(vals)} ({100*good/len(vals):.1f}%)")
    print("\nLatest saved progress bins (not matched horizons):")
    for lo, hi in [(1, 4), (5, 9), (10, 14), (15, 19), (20, 20)]:
        vals = [r["delta"] for r in answered if lo <= r["step"] <= hi]
        print(f"  {lo:02d}-{hi:02d}: {describe(vals)}")


def trajectory_report(root, credential, rows):
    buckets = defaultdict(list)
    attention_pass = Counter()
    for r in rows:
        if not r["consent"] or r["baseline"] is None or r["step"] < 1:
            continue
        url = root + "/" + quote(r["sid"], safe="") + "/questions"
        qdocs = list_docs(url, credential,
                          ("phase", "status", "step", "index_result.index_after",
                           "attention_passed"))
        counted = set()
        for doc in qdocs:
            q = fields(doc)
            if q.get("status") != "answered":
                continue
            if q.get("phase") == "attention":
                attention_pass[str(q.get("attention_passed"))] += 1
            if q.get("phase") != "intervention":
                continue
            idx = numeric((q.get("index_result") or {}).get("index_after"))
            step = q.get("step")
            if idx is not None and isinstance(step, int) and 0 <= step < 20:
                if step in counted:
                    raise SystemExit("Duplicate adaptive step found")
                counted.add(step)
                buckets[step + 1].append(idx - r["baseline"])
        if len(counted) != r["step"]:
            print("WARNING: trajectory/progress count mismatch for one session")
    print("\nMatched adaptive horizons (only participants reaching that step):")
    for step in (1, 3, 5, 10, 15, 20):
        print(f"  step {step:2d}: {describe(buckets[step])}")
    print("Attention-check answers:", dict(attention_pass))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", choices=("left", "right"), default="right")
    p.add_argument("--project", default="pkcsaas-01")
    p.add_argument("--database", default="dtag-human-pilot")
    p.add_argument("--study", default=None)
    p.add_argument("--campaign-id", default=None,
                   help="Prolific STUDY_ID of Democrat recruitment; omit to see all campaigns")
    p.add_argument("--trajectories", action="store_true",
                   help="Also load per-question model-index changes and attention-check pass counts")
    a = p.parse_args()
    study = a.study or f"dtag-v3-nocal-{a.arm}-2026-10"
    root = ("https://firestore.googleapis.com/v1/projects/" + quote(a.project, safe="")
            + "/databases/" + quote(a.database, safe="()")
            + "/documents/studies/" + quote(study, safe="") + "/sessions")
    credential = token()
    rows = get_rows(root, credential, a.arm)
    print("Study:", study, "| Firestore database:", a.database)
    print("Prolific campaign STUDY_ID counts:")
    for key, count in sorted(Counter(r["campaign"] for r in rows).items()):
        print(" ", key, count)
    if a.campaign_id:
        rows = [r for r in rows if r["campaign"] == a.campaign_id]
        print("Selected Prolific campaign:", a.campaign_id)
    else:
        print("WARNING: Unfiltered: may mix Democrat and Republican campaigns.")
    if not rows:
        print("No matching sessions; check study ID, database, and campaign ID.")
        return
    summary(rows, a.arm)
    if a.trajectories:
        trajectory_report(root, credential, rows)
    print("\nCAUTION: Change in model-inferred index is NOT observed opinion change.")
    print("Partial sessions have unequal exposure. Campaign membership is from Prolific STUDY_ID.")
    print("Only aggregate measures displayed; no participant IDs or answers exposed.")


if __name__ == "__main__":
    main()
