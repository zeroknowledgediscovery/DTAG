#!/usr/bin/env python3
"""Ten-question fixed-set order test for DTAG's native GSS LSM.

For each of six pinned personas x 3 observed source-policy question sets,
hold the ten *variables* constant and replay original, reverse, and independent
fixed random permutations. At each position draw the answer from the native
conditional distribution given all previously drawn answers. The same
deterministic uniform variate for a given (persona, set, run, variable) is
reused across permutations (common-random-number coupling). This does NOT fix
answers; answer changes caused by conditioning are counted explicitly.

In a coherent static joint P(X | s0), ancestral draws of all ten variables
would have the same terminal joint distribution in every order. A difference
in expected I(s_final) across orders therefore diagnoses order dependence in
the fitted conditionals/sampling procedure; it does not establish that
human beliefs changed as a result of questioning.

Source item sets are fixed ex ante in fixed_10q_order_sets.json, from
rep 0 of the previously completed DTAG 10-question experiment. The original
sequence's sampled answers are used ONLY in a structural invariance control
(I with identical assignments in reversed insertion order is the same).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
DEFAULT_SETS = ROOT / "experiments/persona_push/fixed_10q_order_sets.json"
DEFAULT_PERSONAS = ROOT / "optimizer/personas/gss2024_spectrum.yaml"
ORDER_NAMES = ("original", "reverse", "shuffle1", "shuffle2")
# Keep figure order self-contained: launching this file directly is valid even
# when another installed package called 'scripts' shadows our script folder.
PAIRS = (
    ("cm_rural_alabama", "wf_new_york_city"),
    ("religious_conservative_woman_texas", "secular_liberal_man_seattle"),
    ("hispanic_catholic_man_arizona", "black_churchgoing_woman_atlanta"),
)


def seed_for(*parts):
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big")


def read_pinned(path):
    import yaml
    return {p["id"]: dict(p["state"]) for p in yaml.safe_load(
        Path(path).read_text(encoding="utf-8"))["participants"]}


def read_sets(path, policies=("right", "left", "neutral"), steps=10):
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    keep = [s for s in obj["sets"] if s["source_policy"] in policies]
    if not keep:
        raise ValueError("No sets matching policy selection")
    for s in keep:
        q = s["questions"]
        if len(q) != steps or len(set(q)) != steps:
            raise ValueError(f"Expected {steps} unique questions: {s}")
        if set(q) != set(s["source_answers"]):
            raise ValueError(f"Source answer keys mismatch question set: {s['persona']}")
    return keep


def order_permutations(questions, persona, policy, seed):
    """Four distinct precommitted orders of the same ten items."""
    q = tuple(questions)
    result = {"original": q, "reverse": q[::-1]}
    for j in (1, 2):
        rng = np.random.default_rng(seed_for(seed, persona, policy, "perm", j))
        for trial in range(100):
            z = tuple(rng.permutation(q))
            if z not in result.values():
                break
        else:
            raise RuntimeError("Failed to generate unique permutations")
        result[f"shuffle{j}"] = z
    assert len(result) == 4
    assert all(set(v) == set(q) for v in result.values())
    return result


_WORLD = None


def _init_worker(model_dir, map_path, poles, cache):
    global _WORLD
    from optimizer.dtag_bridge import World
    _WORLD = World(model_dir, map_path, poles, cache)


def _job(job):
    """One ten-question replay: return one terminal record and ten item draws."""
    persona, source_policy, pinned, source_answers, order_name, order, rep, seed = job
    state, dropped = _WORLD.valid(pinned)
    if dropped:
        raise ValueError(f"{persona}: invalid anchor assignments {dropped}")
    if set(order) & set(state):
        raise ValueError(f"{persona} has a question already pinned in initial state")

    i0 = _WORLD.I(state)
    u = {
        v: np.random.default_rng(
            seed_for(seed, persona, source_policy, rep, v)).random()
        for v in order
    }
    drawn = {}
    detail = []
    for step, v in enumerate(order, 1):
        dist = _WORLD.dists(state, [v]).get(v)
        if not dist:
            raise RuntimeError(f"No native response distribution: {persona}, {v}, {step}")
        labels = list(dist)
        prob = np.asarray([dist[x] for x in labels], dtype=float)
        if not np.isfinite(prob).all() or np.any(prob < 0) or prob.sum() <= 0:
            raise ValueError(f"Invalid distribution for {persona} {v}: {dist}")
        prob /= prob.sum()
        k = min(int(np.searchsorted(np.cumsum(prob), u[v], side="right")), len(labels)-1)
        answer = labels[k]
        state[v] = answer
        drawn[v] = answer
        detail.append({
            "persona": persona, "source_policy": source_policy,
            "rep": rep, "order": order_name, "step": step, "variable": v,
            "answer": answer, "conditional_probability": float(prob[k]),
            "uniform": float(u[v]),
        })
    if set(drawn) != set(order):
        raise AssertionError("A fixed-set replay lost one of its ten variables")
    final_i = _WORLD.I(state)

    # A structural control: the same final *assignments* in an alternate
    # insertion order must have the same I, up to native floating-point noise.
    same_answers = {**_WORLD.valid(pinned)[0], **source_answers}
    same_reverse = {**_WORLD.valid(pinned)[0],
                    **{v: source_answers[v] for v in reversed(order)}}
    same_i = _WORLD.I(same_answers)
    same_reverse_i = _WORLD.I(same_reverse)
    if not math.isclose(same_i, same_reverse_i, abs_tol=1e-10, rel_tol=0):
        raise AssertionError(
            f"Fixed-answer invariance failed: {persona}, {source_policy}, "
            f"{same_i}, {same_reverse_i}"
        )
    return {
        "persona": persona, "source_policy": source_policy,
        "order": order_name, "rep": rep, "initial_I": i0,
        "final_I": final_i, "net_delta": final_i-i0,
        "answer_map": json.dumps(drawn, sort_keys=True),
        "fixed_answer_control_I": same_i,
        "fixed_answer_control_error": same_reverse_i - same_i,
    }, detail


def bootstrap(x, n=2000, seed=0):
    x = np.asarray(x, dtype=float)
    m = float(x.mean())
    if len(x) < 2:
        return m, float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    samples = np.empty(n)
    for i in range(0, n, 250):
        k = min(n-i, 250)
        samples[i:i+k] = x[rng.integers(len(x), size=(k, len(x)))].mean(axis=1)
    return (m, *map(float, np.quantile(samples, [0.025, 0.975])))


def summarize(terminal, reps, bootstrap_count, seed):
    groups = defaultdict(dict)
    for r in terminal:
        k = (r["persona"], r["source_policy"], r["order"])
        if r["rep"] in groups[k]:
            raise RuntimeError(f"Duplicate replay: {k}, rep={r['rep']}")
        groups[k][r["rep"]] = r
    # Enforce full coverage, no dropouts/padding, exact 4*reps per set.
    keys = sorted(set((p, s) for p, s, o in groups))
    endpoint, contrast, omnibus = [], [], []
    for i, (p, source) in enumerate(keys):
        by_order = {}
        for j, o in enumerate(ORDER_NAMES):
            rr = groups.get((p, source, o), {})
            if set(rr) != set(range(reps)):
                raise RuntimeError(
                    f"Incomplete replay {p}/{source}/{o}: "
                    f"found reps {sorted(rr)}, expected 0..{reps-1}"
                )
            by_order[o] = [rr[r] for r in range(reps)]
            net = np.asarray([r["net_delta"] for r in by_order[o]])
            m, lo, hi = bootstrap(net, bootstrap_count, seed_for(seed, i, j))
            endpoint.append({
                "persona": p, "source_policy": source, "order": o,
                "reps": reps, "initial_I": by_order[o][0]["initial_I"],
                "mean_final_I": by_order[o][0]["initial_I"]+m,
                "mean_net_delta": m, "ci_low": lo, "ci_high": hi,
                "sd_net_delta": float(np.std(net, ddof=1)),
            })
        baseline = by_order["original"]
        omeans = [float(np.mean([x["final_I"] for x in by_order[o]])) for o in ORDER_NAMES]
        omnibus.append({
            "persona": p, "source_policy": source, "reps": reps,
            "max_minus_min_order_mean": max(omeans)-min(omeans),
            "mean_range": min(omeans), "max_range": max(omeans),
        })
        for j, o in enumerate(ORDER_NAMES[1:], 1):
            alt = by_order[o]
            paired = np.asarray([alt[r]["final_I"]-baseline[r]["final_I"]
                                 for r in range(reps)])
            num_different = np.array([
                sum(json.loads(alt[r]["answer_map"])[v] !=
                    json.loads(baseline[r]["answer_map"])[v]
                    for v in json.loads(baseline[r]["answer_map"]))
                for r in range(reps)
            ])
            m, lo, hi = bootstrap(paired, bootstrap_count, seed_for(seed, i, "contrast", j))
            contrast.append({
                "persona": p, "source_policy": source,
                "order": o, "reference_order": "original",
                "reps": reps, "mean_final_I_difference": m,
                "ci_low": lo, "ci_high": hi,
                "sd_paired_difference": float(np.std(paired, ddof=1)),
                "fraction_replays_with_answer_change": float(np.mean(num_different > 0)),
                "mean_num_changed_answers_out_of_10": float(np.mean(num_different)),
            })
    return endpoint, contrast, omnibus


def write_csv(path, rows):
    if not rows:
        raise ValueError(f"No output for {path}")
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def make_figure(contrast, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    all_p = [p for pair in PAIRS for p in pair]
    pols = ("right", "left", "neutral")
    alternatives = ("reverse", "shuffle1", "shuffle2")
    labels = {"reverse": "Reverse", "shuffle1": "Shuffle 1", "shuffle2": "Shuffle 2"}
    fig, axes = plt.subplots(6, 3, figsize=(10.4, 12.0), sharex=True)
    for ip, person in enumerate(all_p):
        for j, pol in enumerate(pols):
            ax = axes[ip,j]
            rr = {r["order"]: r for r in contrast if r["persona"]==person and r["source_policy"]==pol}
            for k, order in enumerate(alternatives):
                r=rr[order]
                mean=r["mean_final_I_difference"]
                left=mean-r["ci_low"]
                right=r["ci_high"]-mean
                ax.errorbar([mean], [2-k], xerr=[[max(left,0)],[max(right,0)]],
                            fmt="o", capsize=2, markersize=4, color=f"C{k}")
            ax.axvline(0, color="0.5", ls=":", lw=.8)
            ax.grid(axis="x", alpha=.2)
            ax.set_ylim(-.6, 2.6)
            ax.set_yticks([2,1,0])
            if j==0:
                ax.set_yticklabels([labels[x] for x in alternatives])
                ax.set_ylabel(person.replace("_"," "), fontsize=7)
            else:
                ax.set_yticklabels([])
            if ip==0: ax.set_title(f"{pol.title()}-derived set")
            if ip==5: ax.set_xlabel(r"$E[I_{\mathrm{order}}-I_{\mathrm{original}}]$")
    fig.suptitle("Fixed ten-question sets: native conditional-response order effects\n"
                 "Paired mean differences and pointwise 95% bootstrap CIs", y=.998)
    fig.tight_layout(rect=[0,0,1,.960])
    fig.savefig(out / "fixed_10q_order_effects.pdf", bbox_inches="tight")
    fig.savefig(out / "fixed_10q_order_effects.png", dpi=190, bbox_inches="tight")
    plt.close(fig)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="gss/gss_2024")
    ap.add_argument("--sets", type=Path, default=DEFAULT_SETS)
    ap.add_argument("--personas", type=Path, default=DEFAULT_PERSONAS)
    ap.add_argument("--out", type=Path, default=ROOT / "outputs/dtag_persona_push/order_replay_10q")
    ap.add_argument("--policies", nargs="+", choices=["right","left","neutral"],
                    default=["right","left","neutral"])
    ap.add_argument("--steps", type=int, default=10)
    ap.add_argument("--reps", type=int, default=40)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument("--quick", action="store_true",
                    help="2 reps per order; plumbing check, NOT inferential results")
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--finalize-only", action="store_true",
                    help="Regenerate order-effect PDF/PNG and summaries from saved "
                         "CSV results without any native simulation")

    args=ap.parse_args()
    if args.quick:
        args.reps=2
        print("SMOKE MODE: 2 reps per order, not suitable for conclusions",flush=True)
    if args.reps<2 or args.workers<1 or args.bootstrap<100:
        ap.error("reps>=2, workers>=1, bootstrap>=100 required")
    args.out.mkdir(parents=True,exist_ok=True)
    if args.finalize_only:
        # Crucial recovery path: all native replay results and summary CSVs
        # were already written before make_figure could raise an ImportError.
        # This mode never loads the native model or regenerates responses.
        endpoint_path = args.out / "run_endpoints.csv"
        draws_path = args.out / "question_draws.csv"
        for path in (endpoint_path, draws_path, args.out / "fixed_orders.json"):
            if not path.is_file():
                raise FileNotFoundError(f"Cannot finalize; missing saved data: {path}")
        with endpoint_path.open(newline="", encoding="utf-8") as fh:
            terminals = list(csv.DictReader(fh))
        with draws_path.open(newline="", encoding="utf-8") as fh:
            draws = list(csv.DictReader(fh))
        for row in terminals:
            row["rep"] = int(row["rep"])
            for name in ("initial_I", "final_I", "net_delta"):
                row[name] = float(row[name])
                if not math.isfinite(row[name]):
                    raise ValueError(f"Nonfinite saved {name}: {row}")
        expected_sets = {
            (s["persona"], s["source_policy"])
            for s in read_sets(args.sets, policies=args.policies, steps=args.steps)
        }
        expected_runs = len(expected_sets) * len(ORDER_NAMES) * args.reps
        if len(terminals) != expected_runs or len(draws) != expected_runs * args.steps:
            raise ValueError(
                f"Saved outputs incomplete: {len(terminals)} endpoints, "
                f"{len(draws)} question draws; expected {expected_runs} and "
                f"{expected_runs * args.steps} respectively")
        actual_sets = {(r["persona"], r["source_policy"]) for r in terminals}
        if actual_sets != expected_sets:
            raise ValueError(f"Saved persona/set groups differ: {actual_sets ^ expected_sets}")
        for row in draws:
            row["rep"] = int(row["rep"])
            row["step"] = int(row["step"])
        by_run = defaultdict(list)
        for row in draws:
            key = (row["persona"], row["source_policy"], row["order"], row["rep"])
            by_run[key].append(row["step"])
        if set(by_run) != {
            (r["persona"],r["source_policy"],r["order"],r["rep"]) for r in terminals
        } or any(sorted(v) != list(range(1,args.steps+1)) for v in by_run.values()):
            raise ValueError("Saved question draws do not contain every step of every run")
        endpoint, contrast, omnibus = summarize(
            terminals, args.reps, args.bootstrap, args.seed)
        write_csv(args.out / "endpoint_summary.csv", endpoint)
        write_csv(args.out / "paired_order_contrasts.csv", contrast)
        write_csv(args.out / "omnibus_order_spread.csv", omnibus)
        make_figure(contrast, args.out)
        recovery = {
            "recovered_from_saved_native_runs": True,
            "model_evaluation_performed": False,
            "steps": args.steps, "repetitions": args.reps,
            "completed_replays_verified": expected_runs,
            "saved_endpoints_sha256": hashlib.sha256(endpoint_path.read_bytes()).hexdigest(),
            "saved_draws_sha256": hashlib.sha256(draws_path.read_bytes()).hexdigest(),
            "note": "This restores figures and summaries after a post-run "
                    "plotting failure. It does not recover a missing native model hash.",
        }
        (args.out / "figure_recovery.json").write_text(
            json.dumps(recovery, indent=2) + "\n", encoding="utf-8")
        print(f"Recovered figures and summaries from {expected_runs} complete "
              f"{args.steps}-question native replay records; no simulations rerun.",
              flush=True)
        return
    pinned=read_pinned(args.personas)
    sources=read_sets(args.sets, policies=args.policies, steps=args.steps)
    jobs=[]; orders_file=[]
    for s in sources:
        persona=s["persona"]
        if persona not in pinned:
            raise ValueError(f"Persona not found: {persona}")
        orders=order_permutations(s["questions"],persona,s["source_policy"],args.seed)
        for name, items in orders.items():
            orders_file.append({"persona":persona,"source_policy":s["source_policy"],
                                "order":name,"questions":list(items)})
            for rep in range(args.reps):
                jobs.append((persona,s["source_policy"],pinned[persona],
                             s["source_answers"],name,items,rep,args.seed))
    print(f"Fixed sets={len(sources)}, orders per set=4, draws per order={args.reps}, "
          f"ten-item native replay runs={len(jobs)}",flush=True)
    from optimizer.dtag_bridge import (World, DEFAULT_POLES, canonical_map,
                                       ensure_model, sha256)
    model=ensure_model(args.model,None,download=not args.no_download)
    mp=canonical_map(args.model)
    cache=args.out/"native_cache"
    cache.mkdir(exist_ok=True)
    init=(str(model),str(mp),str(DEFAULT_POLES),str(cache))
    terminals=[]; draws=[]
    if args.workers==1:
        _init_worker(*init)
        for k,job in enumerate(jobs,1):
            t,d=_job(job);terminals.append(t);draws+=d
            if k%40==0: print(f"Completed {k}/{len(jobs)}",flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker,
                                 initargs=init) as pool:
            tasks=[pool.submit(_job,job) for job in jobs]
            for k,future in enumerate(as_completed(tasks),1):
                t,d=future.result();terminals.append(t);draws+=d
                if k%40==0: print(f"Completed {k}/{len(jobs)}",flush=True)
    terminals.sort(key=lambda x:(x["persona"],x["source_policy"],x["order"],x["rep"]))
    draws.sort(key=lambda x:(x["persona"],x["source_policy"],x["order"],x["rep"],x["step"]))
    if len(terminals)!=len(jobs) or len(draws)!=len(jobs)*args.steps:
        raise AssertionError(f"Incomplete output; {args.steps} steps required for every replay")
    endpoint, contrast, omnibus=summarize(terminals,args.reps,args.bootstrap,args.seed)
    write_csv(args.out/"run_endpoints.csv",terminals)
    write_csv(args.out/"question_draws.csv",draws)
    write_csv(args.out/"endpoint_summary.csv",endpoint)
    write_csv(args.out/"paired_order_contrasts.csv",contrast)
    write_csv(args.out/"omnibus_order_spread.csv",omnibus)
    (args.out/"fixed_orders.json").write_text(json.dumps(orders_file,indent=2)+"\n")
    make_figure(contrast,args.out)
    try:
        sha=subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD"],
                                    stderr=subprocess.DEVNULL,text=True).strip()
    except Exception:
        sha="unknown"
    manifest={
        "model":args.model,"model_path":str(model),"map_sha256":sha256(mp),
        "poles_sha256":sha256(Path(DEFAULT_POLES)),
        "persona_sha256":sha256(args.personas),"set_file_sha256":sha256(args.sets),
        "git_commit":sha,"fixed_sets":len(sources),"orders_per_set":4,
        "repetitions":args.reps,"questions_per_run":args.steps,
        "seed":args.seed,"bootstrap":args.bootstrap,"workers":args.workers,
        "runs":len(jobs),"quick":args.quick,
        "answer_sampling":"native sequential conditionals, matched uniform draws by question ID",
        "CIs":"pointwise percentile paired-run bootstrap; comparisons versus original",
        "interpretation":"synthetic-model order dependence; not causal persuasion in human respondents",
    }
    (args.out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(f"VERIFIED: {len(jobs)} full {args.steps}-item replays. "
          f"Results at {args.out}",flush=True)


if __name__=="__main__":
    main()
