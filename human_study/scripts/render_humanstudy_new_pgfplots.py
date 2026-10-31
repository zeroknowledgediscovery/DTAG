#!/usr/bin/env python3
"""Rebuild NEW human-study PGFPlots aggregates from the private GCS-backed export.

From the DTAG root:
 python3 human_study/scripts/render_humanstudy_new_pgfplots.py \
   --analysis-dir ~/private/dtag-analysis-2026-10-30-restored

Uses only GCS-finalized six-baseline cohorts, only 20/20 completions:
Left 21, Right 38, Neutral 7, Random 5. Does not expose any individual rows.
Also creates humanstudy_new_trajectory_right_q4_unflagged.csv for an
additional PGFPlots figure: 19 Right-push participants remaining after
excluding the 19 initially-Left Right-push participants with no positive
baseline-relative displacement after question four (17 TP + 2 FP).
The Left/Neutral/Random trajectories remain unfiltered.
Preserves all old 49-session tex/Figures/humanstudy_* assets unchanged.
"""
from __future__ import annotations
import argparse
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np

ARMS = ("left", "right", "neutral", "random")
STUDIES = {"prolific-v3-human-opinions-2026-10",
           "prolific-v3-left-followup-2026-10",
           "prolific-v3-right-followup-2026-10"}
EXPECTED = {"left": (21,17,4,20), "right":(38,29,9,21),
            "neutral":(7,6,1,None), "random":(5,2,3,None)}
EPS = 1e-10

def read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def num(x):
    v=float(x)
    if not math.isfinite(v):
        raise ValueError("Nonfinite model index")
    return v

def save(path,columns,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.writer(f); w.writerow(columns); w.writerows(rows)

def load(root):
    sessions=[r for r in read(root/"sessions.csv")
              if r["dtag_study_id"] in STUDIES
              and r.get("complete_20_archive","").lower()=="true"]
    if len(sessions)!=71:
        raise ValueError(f"Expected 71 complete calibrated sessions, got {len(sessions)}")
    ids={r["session_uid"] for r in sessions}
    if len(ids)!=len(sessions): raise ValueError("Duplicate complete session UID")
    index=defaultdict(dict)
    for r in read(root/"steps.csv"):
        uid=r["session_uid"]
        if uid not in ids: continue
        t=int(r["step"])
        if t not in range(21) or t in index[uid] or r.get("source_class")=="no_archive":
            raise ValueError("Invalid, duplicate, or unarchived step")
        index[uid][t]=num(r["index"])
    arms={arm:[] for arm in ARMS}
    for r in sessions:
        uid=r["session_uid"]; arm=r["policy"].lower()
        if arm not in arms: raise ValueError("Unexpected arm")
        vals=index[uid]
        if set(vals)!=set(range(21)): raise ValueError("Missing archived I0..I20")
        i0=num(r["baseline_index"]); i20=num(r["final_archived_index"])
        if abs(vals[0]-i0)>1e-9 or abs(vals[20]-i20)>1e-9:
            raise ValueError("Archive index mismatch")
        arms[arm].append({"base":i0,"index":vals,
                          "delta":[vals[t]-i0 for t in range(21)]})
    return arms

def build(arms,out,boots,seed):
    summary=[]
    for arm in ARMS:
        ps=arms[arm]
        n=len(ps); neg=sum(p["base"]<-EPS for p in ps)
        pos=sum(p["base"]>EPS for p in ps)
        success=(sum(p["delta"][20]<-EPS if arm=="left"
                     else p["delta"][20]>EPS for p in ps)
                 if arm in ("left","right") else None)
        if (n,neg,pos,success)!=EXPECTED[arm]:
            raise ValueError(f"{arm}: cohort mismatch: {(n,neg,pos,success)}")
        arr=np.asarray([p["delta"] for p in ps],dtype=float)
        rng=np.random.default_rng(seed+ARMS.index(arm))
        sampled=arr[rng.integers(n,size=(boots,n))]
        m=arr.mean(axis=0)
        lo,hi=np.percentile(sampled.mean(axis=1),(2.5,97.5),axis=0)
        save(out/f"humanstudy_new_trajectory_{arm}.csv",
             ("step","n","mean","ci_low","ci_high"),
             ((t,n,m[t],lo[t],hi[t]) for t in range(21)))
        save(out/f"humanstudy_new_endpoint_{arm}.csv",
             ("x","n","mean","ci_low","ci_high","err_minus","err_plus"),
             [(ARMS.index(arm)+1,n,m[20],lo[20],hi[20],m[20]-lo[20],hi[20]-m[20])])
        summary.append({"arm":arm,"n":n,"neg":neg,"pos":pos,"success":success,
                        "mean":float(m[20]),"lo":float(lo[20]),"hi":float(hi[20])})
    # Independently verify primary Q4 result from archived indices.
    m=Counter()
    for p in arms["right"]:
        if p["base"]>=-EPS: continue
        predicted=(p["index"][4]-p["base"])/4<=EPS
        failed=p["delta"][20]<=EPS
        m["TP" if predicted and failed else "FP" if predicted else
          "FN" if failed else "TN"]+=1
    if tuple(m[k] for k in ("TP","FP","FN","TN"))!=(17,2,0,10):
        raise ValueError(f"Q4 results mismatch: {dict(m)}")
    # Same cohort and plotting statistic as Fig. 3(a), with only the
    # initially-Left Right-push sessions flagged at Q4 excluded.
    # In the calibrated archives: TP=17, FP=2 excluded; TN=10 plus
    # 9 initially-Right sessions retained. No filtering on Q20 outcome.
    right_q4_unflagged=[
        p for p in arms["right"]
        if p["base"] >= -EPS or (p["index"][4]-p["base"])/4 > EPS
    ]
    remaining_left=sum(p["base"] < -EPS for p in right_q4_unflagged)
    remaining_right=sum(p["base"] > EPS for p in right_q4_unflagged)
    if (len(right_q4_unflagged),remaining_left,remaining_right)!=(19,10,9):
        raise ValueError("Q4-filtered Right cohort mismatch")
    filtered=np.asarray([p["delta"] for p in right_q4_unflagged],dtype=float)
    rng=np.random.default_rng(seed+29)
    drawn=filtered[rng.integers(len(filtered),size=(boots,len(filtered)))]
    filtered_mean=filtered.mean(axis=0)
    filtered_lo,filtered_hi=np.percentile(drawn.mean(axis=1),(2.5,97.5),axis=0)
    save(out/"humanstudy_new_trajectory_right_q4_unflagged.csv",
         ("step","n","mean","ci_low","ci_high"),
         ((t,len(filtered),filtered_mean[t],filtered_lo[t],filtered_hi[t])
          for t in range(21)))
    print("Right after Q4 resistance exclusion: n=19 "
          "(10 initially Left unflagged + 9 initially Right); "
          f"mean endpoint delta={filtered_mean[20]:+.6f}")
    save(out/"humanstudy_new_arm_summary.csv",
         ("arm","n_completed","n_baseline_negative","n_baseline_positive",
          "n_directional_success","mean_endpoint_change","endpoint_ci95_low","endpoint_ci95_high"),
         ((s["arm"],s["n"],s["neg"],s["pos"],
           "" if s["success"] is None else s["success"],s["mean"],s["lo"],s["hi"])
          for s in summary))
    lines=[
      "% Auto-generated from restored private GCS final archives; 71 calibrated 20/20.",
      "\\begin{table*}[!t]","\\centering",
      "\\caption{Human-study results by assigned policy. Endpoint displacement is",
      "measured from each participant's six-question baseline; intervals are",
      "95\\% participant-bootstrap percentile intervals (5,000 replicates).}",
      "\\label{tab:humanstudy-participants}","\\footnotesize",
      "\\setlength{\\tabcolsep}{6pt}","\\begin{tabular}{lrrrrr}",
      "\\toprule",
      "Policy & $n$ & Baseline $I_\\Phi<0$ & Baseline $I_\\Phi>0$ & Mean $\\Delta I_\\Phi(20)$ (95\\% CI) & Directional success \\\\",
      "\\midrule"]
    for s in summary:
        hit=(f"{s['success']}/{s['n']} ({100*s['success']/s['n']:.1f}\\%)"
             if s["success"] is not None else "---")
        # Math mode markers separated from interpolation to avoid accidental escapes.
        ci="$"+f"{s['mean']:+.4f}\\;[{s['lo']:+.4f},{s['hi']:+.4f}]"+ "$"
        lines.append(f"{s['arm'].title()} & {s['n']} & {s['neg']} & {s['pos']} & {ci} & {hit} \\\\")
    lines+=["\\bottomrule","\\end{tabular}","\\end{table*}",""]
    (out/"humanstudy_new_table.tex").write_text("\n".join(lines),encoding="utf-8")
    print("New PGFPlots source tables generated; Q4 TP/FP/FN/TN=17/2/0/10 verified.")
    for s in summary:
        print(f"{s['arm']}: n={s['n']}, mean_delta={s['mean']:+.6f}, 95% CI [{s['lo']:+.6f},{s['hi']:+.6f}]")
    print("Files:",out)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--analysis-dir",required=True,type=Path)
    p.add_argument("--output-dir",type=Path,default=Path("tex/Figures"))
    p.add_argument("--bootstrap",type=int,default=5000)
    p.add_argument("--seed",type=int,default=20261030)
    a=p.parse_args()
    if a.bootstrap<100: p.error("--bootstrap must be at least 100")
    build(load(a.analysis_dir.expanduser()),a.output_dir,a.bootstrap,a.seed)

if __name__=="__main__":
    main()
