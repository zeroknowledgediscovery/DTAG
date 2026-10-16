"""Append one independently sampled neutral GSS sequence and descriptive audit per run.

The --type input is only an expected observational label; it NEVER conditions
candidate generation, acceptance, stopping or retry. The actual measured regime
is recorded separately. No search for directional political effects is performed.

Examples:
 python -m optimizer.sequence_library_runner --year 2018 --type '++' --workers 4
 python -m optimizer.sequence_library_runner --year 2024 --type=-+ --freezeinit --length 12
 python -m optimizer.sequence_library_runner --year 2016 --type=-- \
    --min-length 10 --max-length 20 --plateau-tolerance .0005
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import secrets
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import yaml

from . import population
from .__main__ import Ctx, DEFAULTS, merge
from .dtag_bridge import REPO
from .four_way_audit import analyze

YEARS = (2016, 2018, 2024)
TYPES = ("++", "+-", "-+", "--")
REGIME_TO_TYPE = {
    "positive_translation": "++", "divergence": "+-",
    "convergence": "-+", "negative_translation": "--"
}
CORE = ("polviews", "partyid")


@contextmanager
def exclusive_library(path):
    """Single-machine interprocess lock; not an MCC distributed lock."""
    import fcntl

    path.mkdir(parents=True, exist_ok=True)
    with (path / ".lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, path)


def candidate_hash(year, rows):
    ids = [row["id"] for row in rows]
    return hashlib.sha256(json.dumps([year, ids], separators=(",", ":")).encode()).hexdigest()


def sample_candidate(pool, year, length, seed, existing):
    """One random sample, retrying duplicates only; never uses the requested type."""
    if length < 1 or length > len(pool):
        raise ValueError("Invalid length for candidate bank")
    rng = random.Random(seed)
    for attempt in range(5000):
        chosen = rng.sample(pool, length)
        sig = candidate_hash(year, chosen)
        if sig not in existing:
            return chosen, sig
    raise RuntimeError("No novel sampled sequence found after 5000 duplicate-only retries")


def write_sequence(path, questions):
    with Path(path).open("w", newline="", encoding="utf-8") as file:
        w = csv.writer(file)
        w.writerow(["step", "question", "variables"])
        for index, row in enumerate(questions, 1):
            w.writerow([index, row["question"], row["id"]])


def plain_source_personas(output):
    """Remove 2024-only expected labels from text inputs for cross-wave decoding."""
    root = REPO / "optimizer/personas/gss2024_asset_cm_wf.yaml"
    original = yaml.safe_load(root.read_text(encoding="utf-8"))["participants"]
    entries = []
    for row in original:
        if "text_file" not in row and "text" not in row:
            raise ValueError("Input persona requires text")
        # The original reference holds explicitly stated polviews/partyid.
        # Only these two fields are copied into each wave's initial state;
        # all other mappings remain wave-specific and LLM-decoded.
        if not row.get("expected_state_ref"):
            raise ValueError(f"Persona {row['id']} has no explicit anchor reference")
        entries.append({"id": row["id"],
                        "core_state_ref": row["expected_state_ref"],
                        **{k: row[k] for k in ("text_file", "text") if k in row}})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump({"participants": entries}, sort_keys=False), encoding="utf-8")
    return output


def derive_spec(base_people, spec, seed):
    """Vary initial conditioning by omitting optional decoded facts; core retained."""
    rng = random.Random(seed + 997 * spec)
    result = []
    for person in base_people:
        state = dict(person["state"])
        if not set(CORE).issubset(state):
            raise ValueError("Persona decoding must include polviews and partyid for both personas")
        optional = sorted(set(state).difference(CORE))
        if spec:
            n = min(len(optional), max(1, round(.1 * spec * len(optional))))
            for var in rng.sample(optional, n):
                del state[var]
        result.append({"id": person["id"], "state": state})
    return result


def spec_config(year, output, persona_file, workers, freezeinit, seed, states, draws):
    return merge(DEFAULTS, {
        "model": f"gss/gss_{year}", "download": True, "out": str(output),
        "workers": workers,
        "llm": {"provider": "openai", "model": "gpt-4.1-mini", "api_key_env": "OPENAI_API_KEY"},
        "participants": {"file": str(persona_file), "decode": "auto",
                         "core_variables": list(CORE), "protect_mapped": bool(freezeinit),
                         "perturb": {"drop": .15, "resample": .15}},
        "bank": {"source": "map", "mapping": "source", "rewrite": False},
        "search": {"resp_mode": "draw"},
        "validate": {"seed": seed, "states_per_persona": states,
                     "reps_per_state": draws, "augment_count": 6,
                     "baselines": 0, "order_baselines": 0}
    })


def choose_length(trajs, starts, minimum=10, tolerance=.0005, window=3):
    """Neutral plateau stopping; no desired direction or target magnitude is consulted.

    trajs: simulated pathways for full max-length candidate, n_draws x (steps+1).
    Stop when both *absolute* mean per-question increments remain <= tolerance
    for window successive additions after the minimum.
    """
    paths = np.asarray(trajs, dtype=float)
    starts = np.asarray(starts, dtype=float)
    if paths.ndim != 2 or paths.shape[1] < minimum + 1:
        raise ValueError("Insufficient trajectory length")
    positive = starts > .005
    negative = starts < -.005
    if not positive.any() or not negative.any():
        raise ValueError("Both starting-index groups required")
    maxlen = paths.shape[1] - 1
    if window < 1:
        raise ValueError("window must be positive")
    stable_steps = 0
    for length in range(1, maxlen + 1):
        # Equal sign-agnostic tolerance for both observed starting-state groups.
        increment = paths[:, length] - paths[:, length - 1]
        stable = max(abs(float(increment[positive].mean())),
                     abs(float(increment[negative].mean()))) <= tolerance
        stable_steps = (stable_steps + 1) if stable else 0
        # Evaluate a window of increments ending at the current prefix.
        # The pilot starts earlier than minimum to allow stopping at minimum.
        if length >= minimum and stable_steps >= window:
            return length
    return maxlen


def group_state_z(state_csv, sign_code):
    """Signed standardized descriptive change over DISTINCT starting states."""
    rows = list(csv.DictReader(Path(state_csv).open(encoding="utf-8", newline="")))
    values = []
    for g, desired in ((1, sign_code[0]), (-1, sign_code[1])):
        samples = np.asarray([float(r["mean_change"]) for r in rows
                              if int(r["start_group"]) == g])
        if len(samples) < 5:
            return None
        stderr = float(samples.std(ddof=1) / math.sqrt(len(samples)))
        if not math.isfinite(stderr) or stderr < 1e-12:
            return None
        values.append(float((1 if desired == "+" else -1) * samples.mean() / stderr))
    return values


def score_from_z(z):
    """Rounded minimum z across group/specifications; not used for sequence selection."""
    if z is None or not math.isfinite(z):
        return 0
    return int(min(10, max(0, math.floor(z + .5))))


def save_state_rows(path, runs, paths, prefix, band=.005):
    groups = {}
    for run, traj in zip(runs, paths):
        sid = str(run[4])
        row = groups.setdefault(sid, {"i0": run[2], "participant": run[0], "values": []})
        row["values"].append(float(traj[prefix] - traj[0]))
    rows = []
    for sid, rec in groups.items():
        i0 = float(rec["i0"])
        group = 1 if i0 > band else -1 if i0 < -band else 0
        rows.append({"state_id": sid, "start_group": group, "I_start": i0,
                     "mean_change": float(np.mean(rec["values"])),
                     "draws": len(rec["values"])})
    with Path(path).open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["state_id", "start_group", "I_start",
                                                   "mean_change", "draws"])
        writer.writeheader()
        writer.writerows(rows)


def load_attempts(root):
    manifest = root / "library.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return data.get("attempts", [])
    return []


def write_library_index(root, records):
    """One human-readable row per attempt. Never counts specifications as sets."""
    columns = ["run_id", "year", "requested_label", "observed_label",
               "confirmed", "quality_score", "robust_z", "actual_length",
               "freezeinit", "status", "candidate_sha256", "sequence_file", "error"]
    file = root / "library.csv"
    temporary = file.with_name(file.name + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow({k: record.get(k, "") for k in columns})
    os.replace(temporary, file)


def run_once(args):
    if args.length is not None:
        if not 10 <= args.length <= 20:
            raise ValueError("length must be between 10 and 20")
        minlen = maxlen = args.length
    else:
        minlen, maxlen = args.min_length, args.max_length
        if not 10 <= minlen <= maxlen <= 20:
            raise ValueError("Require 10 <= min-length <= max-length <= 20")
    root = Path(args.library).expanduser().resolve()
    with exclusive_library(root):
        records = load_attempts(root)
        number = len(records) + 1
        run_id = f"{number:05d}"
        folder = root / "attempts" / run_id
        folder.mkdir(parents=True, exist_ok=False)
        seed = args.seed if args.seed is not None else secrets.randbits(32)
        record = {"run_id": run_id, "year": args.year, "requested_label": args.type,
                  "seed": seed, "freezeinit": args.freezeinit,
                  "min_length": minlen, "max_length": maxlen,
                  "status": "started", "folder": str(folder)}
        records.append(record)
        atomic_json(root / "library.json", {"schema": 1, "attempts": records})
        write_library_index(root, records)
        atomic_json(folder / "run_parameters.json", {**vars(args), "resolved_seed": seed})
        try:
            source = root / "cache" / "source_personas.yaml"
            plain_source_personas(source)
            base_file = root / "cache" / f"gss_{args.year}_base_personas.json"
            setup_dir = root / "cache" / f"gss_{args.year}_setup"
            config = spec_config(args.year, setup_dir, source, args.workers, args.freezeinit,
                                 seed, args.states, args.draws)
            config["cache"] = str(root / "cache" / f"gss_{args.year}_llm_cache.json")
            # Ctx invokes ensure_model; uses same manifest, SHA256, safe extract,
            # and per-user model cache as the DTAG web app.
            ctx = Ctx(config, need_llm=not base_file.is_file())
            try:
                if base_file.is_file():
                    base_people = json.loads(base_file.read_text(encoding="utf-8"))
                    # Fail closed if a cache predates the two-anchor invariant.
                    for p in base_people:
                        if not set(CORE).issubset(p.get("state", {})):
                            raise ValueError(
                                f"Cached {args.year} persona {p.get('id')} lacks "
                                f"{sorted(set(CORE) - set(p.get('state', {})))}. "
                                f"Remove {base_file} and rerun to rebuild.")
                else:
                    base_people = ctx.participants()
                    for p in base_people:
                        if not set(CORE).issubset(p["state"]):
                            raise ValueError(
                                f"Persona {p['id']} missing mandatory protected anchors")
                    atomic_json(base_file, base_people)
                # Recalculate anchor protection for THIS run: the frozen
                # decoded-state cache is shared across freezeinit settings.
                base_people = [dict(p) for p in base_people]
                for p in base_people:
                    if not set(CORE).issubset(p["state"]):
                        raise ValueError(f"Missing core variables in {p['id']} state")
                    fixed = sorted(p["state"]) if args.freezeinit else sorted(set(CORE))
                    p["protected"] = fixed
                    p["protected_values"] = {k: p["state"][k] for k in fixed}
                bank = ctx.bank(people=base_people)
            finally:
                ctx._logf.close()
            existing = {r.get("candidate_sha256") for r in records if r.get("candidate_sha256")}
            candidate, digest = sample_candidate(bank, args.year, maxlen, seed, existing)
            # Run exactly one outcome-independent candidate per invocation.
            write_sequence(folder / "candidate_full.csv", candidate)
            record["candidate_sha256"] = digest
            record["model"] = f"gss/gss_{args.year}"
            outputs = []
            chosen_length = None
            print(f"Candidate {run_id}: year={args.year}, requested label={args.type}, "
                  f"freezeinit={args.freezeinit}, length={minlen}..{maxlen}",
                  flush=True)
            for spec in range(args.specifications):
                subdir = folder / f"spec_{spec:02d}"
                subdir.mkdir()
                pin = derive_spec(base_people, spec, seed)
                persona_file = subdir / "personas.yaml"
                persona_file.write_text(yaml.safe_dump({"participants": pin}, sort_keys=False))
                conf = spec_config(args.year, subdir, persona_file, args.workers,
                                   args.freezeinit, seed + 100003 * spec,
                                   args.states, args.draws)
                conf["llm"] = None
                subctx = Ctx(conf, need_llm=False)
                try:
                    people = subctx.participants()
                    if chosen_length is None:
                        if args.length is not None:
                            chosen_length = args.length
                        else:
                            # Separate pilot: neither pilot starts nor responses are
                            # included in subsequent held-out validations or z-scores.
                            pilot = subctx.simulator(people, candidate)
                            try:
                                pilot_runs = pilot.make_runs(
                                    people, max(2, args.draws // 2), seed + 999999,
                                    only_directed=False,
                                    states_per_persona=max(5, args.states // 3),
                                    augment_count=6)
                                pilot_paths = pilot.simulate(
                                    pilot_runs, [[q["id"]] for q in candidate],
                                    "draw", trajectories=True)
                                pilot_starts = np.asarray([r[2] for r in pilot_runs], dtype=float)
                                chosen_length = choose_length(
                                    pilot_paths, pilot_starts, minlen,
                                    args.plateau_tolerance, args.plateau_window)
                                atomic_json(folder / "pilot_length.json", {
                                    "chosen_length": chosen_length,
                                    "min_length": minlen, "max_length": maxlen,
                                    "window": args.plateau_window,
                                    "tolerance": args.plateau_tolerance,
                                    "seed": seed + 999999,
                                    "n_pilot_draws": len(pilot_runs),
                                    "rule": "sign-neutral plateau of mean incremental index changes",
                                    "independent_of_validation": True})
                            finally:
                                pilot.close()
                    # Validate ONLY the chosen prefix, excluding future questions
                    # from the context-augmentation exclusions.
                    chosen_questions = candidate[:chosen_length]
                    simulation = subctx.simulator(people, chosen_questions)
                    try:
                        runs = simulation.make_runs(
                            people, args.draws, conf["validate"]["seed"], only_directed=False,
                            states_per_persona=args.states, augment_count=6)
                        trajectory = simulation.simulate(
                            runs, [[q["id"]] for q in chosen_questions],
                            "draw", trajectories=True)
                    finally:
                        simulation.close()
                    i0 = np.asarray([r[2] for r in runs], dtype=float)
                    used = np.asarray(trajectory)
                    np.savez_compressed(
                        subdir / "validation_trajectories.npz", trajectories=used,
                        initial_ideology=i0,
                        state_id=np.asarray([r[4] for r in runs]),
                        participant=np.asarray([r[0] for r in runs]))
                    save_state_rows(subdir / "per_state.csv", runs, trajectory, chosen_length)
                    atomic_json(subdir / "manifest.json", subctx.manifest(len(candidate)))
                    result = analyze(subdir, seed=seed + spec)
                    outputs.append({"specification": spec, "analysis": result})
                    atomic_json(subdir / "analysis.json", result)
                finally:
                    subctx._logf.close()
            saved = candidate[:chosen_length]
            write_sequence(folder / "question_set.csv", saved)
            observed = [REGIME_TO_TYPE.get(o["analysis"].get("observed_regime")) for o in outputs]
            unanimous = bool(observed and observed[0] and all(x == observed[0] for x in observed))
            all_supported = all(o["analysis"]["status"] == "supported_by_state_bootstrap" for o in outputs)
            true_type = observed[0] if unanimous else None
            zs = [group_state_z(folder / f"spec_{j:02d}" / "per_state.csv", true_type)
                  for j in range(len(outputs))] if true_type else []
            robust_z = min(v for pair in zs if pair for v in pair) if zs and all(zs) else None
            score = score_from_z(robust_z) if unanimous and all_supported else 0
            record.update({"status": "validated", "observed_label": true_type,
                           "confirmed": bool(unanimous and all_supported),
                           "quality_score": score, "robust_z": robust_z,
                           "actual_length": chosen_length,
                           "requested_label_matched": bool(true_type == args.type),
                           "specifications": outputs})
            # File identifier is observed classification, NOT requested type.
            # An unstable result never receives a directional filename.
            label = true_type if record["confirmed"] else "unclassified"
            sequence_number = 1 + sum(
                1 for previous in records[:-1]
                if previous.get("year") == args.year
                and (previous.get("observed_label")
                     if previous.get("confirmed") else "unclassified") == label
                and previous.get("sequence_file"))
            record["sequence_number"] = sequence_number
            name = f"{label}_{score}__{args.year}__{sequence_number:03d}.csv"
            (root / "sequences").mkdir(exist_ok=True)
            exported = root / "sequences" / name
            if exported.exists():
                raise FileExistsError(exported)
            # The sequence is preserved regardless of observed direction or strength.
            exported.write_bytes((folder / "question_set.csv").read_bytes())
            record["sequence_file"] = str(exported)
            atomic_json(folder / "result.json", record)
            print(f"Saved {exported}")
            print(f"Observed: {true_type or 'inconsistent'}; requested annotation: {args.type}; "
                  f"score: {score}/10; length: {chosen_length}")
            return record
        except BaseException as exc:
            record.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            atomic_json(folder / "error.json", record)
            raise
        finally:
            atomic_json(root / "library.json", {"schema": 1, "attempts": records})
            write_library_index(root, records)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, choices=YEARS, required=True)
    parser.add_argument("--type", choices=TYPES, required=True,
                        help="expected observational label only; never drives generation")
    parser.add_argument("--freezeinit", action="store_true",
                        help="protect all retained persona assignments (default: protect only polviews and partyid)")
    parser.add_argument("--length", type=int, help="fixed length, between 10 and 20")
    parser.add_argument("--min-length", type=int, default=10)
    parser.add_argument("--max-length", type=int, default=20)
    parser.add_argument("--plateau-tolerance", type=float, default=.0005,
                        help="sign-neutral threshold for additional mean per-question movement")
    parser.add_argument("--plateau-window", type=int, default=3)
    parser.add_argument("--states", type=int, default=30,
                        help="distinct starting state attempts for each persona/specification")
    parser.add_argument("--draws", type=int, default=10)
    parser.add_argument("--specifications", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--library", default="outputs/optimizer/sequence_library")
    args = parser.parse_args(argv)
    if args.states < 5 or args.draws < 1 or args.specifications < 2:
        parser.error("Require states >= 5, draws >= 1 and specifications >= 2")
    if args.plateau_tolerance < 0 or args.plateau_window < 1:
        parser.error("plateau tolerance must be nonnegative and plateau window positive")
    run_once(args)


if __name__ == "__main__":
    main()
