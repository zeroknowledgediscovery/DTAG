#!/usr/bin/env python3
"""Find question sequences that robustly polarize two GSS personas, and validate them.

Goal: a 10-12 question sequence that, with state updates on and sampled (``draw``)
answers, moves the conservative persona (CM) toward the R pole (ideology up) and the
progressive persona (WF) toward the L pole (ideology down) at the same time, robustly
across answer sampling and across perturbations of the initial persona.

Method (all native, no LLM; one GSS survey item per question):

1. Persona perturbation. Each persona is a distribution over initial states: the facts
   in its description with plausible variation (age, children, place size, news habit,
   veteran years, strength of political views), optional inferences an LLM might add
   (party, religion, attendance, marital status, education) and random omission of
   stated facts. Optimization and validation use disjoint seeds.
2. Greedy search under ``draw``. A population of perturbed initial states per persona is
   advanced question by question. A candidate item is scored at each state by its exact
   distribution of ideology change over its answers. The item is added that maximizes, for the
   worse of the two personas, mean/sd of the signed net change (so far + this question) over
   the mixture of population states and sampled answers, i.e. the share of runs expected to
   move the right way; every state then draws its answer. The search stops when no item
   raises that score by --min-gain.
   Candidates are the survey's opinion items (no respondent facts, identity or
   self-placement), re-screened in full every few steps.
3. Validation. The chosen sequence is replayed end-to-end in ``draw`` mode on held-out
   perturbed personas with fresh seeds; means, 95% bootstrap CIs and the share of runs
   moving in the intended direction are reported, against random opinion-item sequences
   of the same length and any comparison sets given.

Usage:
  python scripts/optimize_question_sets.py --wave 2024 --out outputs/polarization_gss2024
  (native GSS model under $DTAG_MODEL_ROOT or ~/.cache/dtag/models; ~1-2 h on 4 cores)
"""
from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline as core  # noqa: E402
from dtag_session import ModelContext, build_polar_geometry  # noqa: E402
from model_backend import load_model  # noqa: E402

# ----------------------------------------------------------------------------- personas

def _pick(rng: random.Random, weighted: List[Tuple[str, float]]) -> str:
    r, acc = rng.random() * sum(w for _, w in weighted), 0.0
    for v, w in weighted:
        acc += w
        if r <= acc:
            return v
    return weighted[-1][0]


RURAL = ["open country within larger civil divisions (division, township, etc.)",
         "a town or village (2,500 to 9,999)",
         "an incorporated area less than 2,500 or an unincorporated area of 1,000 to 2,499",
         "not within an smsa, (within a county) and a small city (10,000 to 49,999)"]
URBAN = ["a large central city (over 250,000)", "a medium size central city (50,000 to 250,000)",
         "a suburb of a large central city"]


RICH_BASE = {"CM": {"partyid": "strong republican", "relig": "protestant", "attend": "every week",
                    "marital": "married", "degree": "high school"},
             "WF": {"partyid": "strong democrat", "relig": "none", "attend": "never",
                    "marital": "never married", "degree": "bachelor's"}}


def sample_persona(side: str, seed: int, perturb: bool = True, rich: bool = False) -> Dict[str, str]:
    """Initial survey state for gss2024_cm ('CM') or gss2024_wf ('WF').

    perturb=False gives the base persona (stated facts only, or with ``rich`` also the usual
    inferences: party, religion, attendance, marital status, education). With perturb=True the
    facts vary, stated facts are sometimes omitted, and inferences are added with probability
    0.4 (0.8 when ``rich``) with varied values."""
    rng = random.Random(f"{side}-{seed}")
    if side == "CM":  # 45 year old white male with children in rural Alabama, regular news consumer,
        # working in farming, veteran, conservative
        if not perturb:
            return {"sex": "male", "age": "45.0", "race": "white", "region": "south", "childs": "2.0",
                    "xnorcsiz": RURAL[0], "news": "every day", "wrkstat": "working full time",
                    "vetyears": "yes, 2-4 years", "polviews": "conservative", **(RICH_BASE["CM"] if rich else {})}
        st = {"sex": "male", "age": f"{rng.randint(38, 55)}.0", "race": "white", "region": "south",
              "childs": f"{rng.choice([1, 2, 2, 3, 4])}.0", "xnorcsiz": rng.choice(RURAL),
              "news": _pick(rng, [("every day", .7), ("a few times a week", .3)]),
              "wrkstat": _pick(rng, [("working full time", .85), ("working part time", .15)]),
              "vetyears": rng.choice(["yes, less than 2 years", "yes, 2-4 years", "yes, more than 4 years"]),
              "polviews": _pick(rng, [("conservative", .6), ("extremely conservative", .2), ("slightly conservative", .2)])}
        extras = {"partyid": _pick(rng, [("strong republican", .5), ("not very strong republican", .3),
                                         ("independent, close to republican", .2)]),
                  "relig": _pick(rng, [("protestant", .7), ("christian", .2), ("catholic", .1)]),
                  "attend": _pick(rng, [("every week", .4), ("nearly every week", .3), ("about once a month", .3)]),
                  "marital": _pick(rng, [("married", .85), ("divorced", .15)]),
                  "degree": _pick(rng, [("high school", .6), ("associate/junior college", .2), ("less than high school", .2)])}
    else:  # 22 year old white female without children in urban New York, regular news consumer,
        # working in retail, highly progressive
        if not perturb:
            return {"sex": "female", "age": "22.0", "race": "white", "region": "northeast", "childs": "0.0",
                    "xnorcsiz": URBAN[0], "news": "every day", "wrkstat": "working full time",
                    "vetyears": "no active duty", "polviews": "extremely liberal", **(RICH_BASE["WF"] if rich else {})}
        st = {"sex": "female", "age": f"{rng.randint(19, 27)}.0", "race": "white", "region": "northeast",
              "childs": _pick(rng, [("0.0", .9), ("1.0", .1)]), "xnorcsiz": rng.choice(URBAN),
              "news": _pick(rng, [("every day", .7), ("a few times a week", .3)]),
              "wrkstat": _pick(rng, [("working full time", .6), ("working part time", .4)]),
              "vetyears": "no active duty",
              "polviews": _pick(rng, [("extremely liberal", .6), ("liberal", .3), ("slightly liberal", .1)])}
        extras = {"partyid": _pick(rng, [("strong democrat", .6), ("not very strong democrat", .25),
                                         ("independent, close to democrat", .15)]),
                  "relig": _pick(rng, [("none", .7), ("catholic", .1), ("jewish", .1), ("other", .1)]),
                  "attend": _pick(rng, [("never", .6), ("less than once a year", .25), ("about once or twice a year", .15)]),
                  "marital": "never married",
                  "degree": _pick(rng, [("bachelor's", .4), ("high school", .4), ("associate/junior college", .2)])}
    for k in list(st):  # the LLM may not assign every stated fact
        if k not in ("sex", "polviews") and rng.random() < 0.15:
            del st[k]
    for k, v in extras.items():  # ...and may infer more
        if rng.random() < (0.8 if rich else 0.4):
            st[k] = v
    return st

# ------------------------------------------------------------------- candidate questions

ADMIN = re.compile(r"^(year|id|wt.*|ballot|vpsu|vstrat|samp.*|form.*|oversamp|phase|mode|int.*|spanint|dateintv|"
                   r"isco.*|occ.*|indus.*|prestg.*|sei.*|cohort|hompop|hhtype.*|hhrace|respnum|adults|babies|preteen|"
                   r"teens|.*code|.*wt|feeused|lngthinv|cointerview|.*seq|coop|comprend|version|issp|gssfile)$")
FACTUAL_TEXT = re.compile(
    r"\br's\b|respondent|ancestors|\bborn\b|household|in hh|partner|spouse|mother|father|denomination|"
    r"religious preference|religious tradition|religion in which raised|\bvote\b|voted|voting|who you would|"
    r"in home|hunt|race, first|sex assigned|sex now|orientation|sex partner|own or rent|hiv|internet|"
    r"number of hours|hours usually|diploma|highest year|family income|income in|earners|industry|occupation|"
    r"condition of health|\bx\b|x's|situation caused|childhood|region of residence|mobility|visitor|supervisor|"
    r"speak other language|familiarity|x-rated|sex with person|fundamentalist|atheist|grid on web|version y|"
    r"ver y|\by$|volunteered response|time series|reason not|reason r |percent of|ever work|"
    r"find equally good job|is life exciting|afraid to walk|spend evening|threatened|not smart|ups and downs|"
    r"born again|interested in campaigns")
# Reviewed against GSS 2024: respondent facts, behaviour logs, survey meta-data, vignettes and
# political self-identification (asking these relabels the persona instead of probing an opinion).
FACTUAL_VARS = set("""
dwelown partners hunt owngun rifle shotgun pistol relig reltrad denom fund norelgsp pres16 pres20 if20who
whovote24 whovote24a whovotets reborn raceacs1 raceacs2 raceacs3 raceacs4 raceacs5 raceacs6
wrkstat wrkslf marital martype divorce widowed sibs childs major1 major2 res16 family16 earnrs region xnorcsiz
partyid polviews leftrght leftrght1 raclive weekswrk joblose satjob richwork class satfin finalter wksups wksups1
unemp rowngun news tvhours phone racwork yousup refpromo refmorwk workless noathome nonurse vigversn dofirst
knwmhosp knwpatnt diagnosd mhtreatd othlang othlang1 othlang2 compuse disrspct poorserv afraidof chldvig chldprob
chembal imprvdis imprveat imprvmed nextdoor chldfrnd adcoumed mntlill violpeop violself numemps wrkslffam mhtrtot2
marcohab sexfreq ethnic eth1 hispanic vetyears worda wordb wordc wordd worde wordf wordg wordh wordi wordj wordk
wordl wordn wordsum pasei10educ masei10educ spsei10educ cosei10educ spanself spaneng kish wrkgovt1 wrkgovt2
raceacs7 raceacs8 raceacs9 raceacs10 raceacs14 raceacs15 raceacs16 fileversion whatslf2 racerank1 racerank2
racerank3 svyenjoy svyid1 svyid2 subsamprate norelgsp16 polnewsfrom modepet modeprot modelobby modeorgprot modeorg
sexpaid nocondom nodocidu femself1 mascself1 femsee1 mascsee1 devtype family16sex citizen polnews hapmar
age sex race degree attend
""".split())
OPINION_OK = {"god", "letin1a", "relpersn", "pray", "relactiv"}


def askable(v: str, text: str, feat: set) -> bool:
    """Opinion/attitude item that can be put to a persona as a question."""
    if v in OPINION_OK:
        return True
    if ADMIN.match(v) or v in FACTUAL_VARS or FACTUAL_TEXT.search((text or "").lower()):
        return False
    return not any(v.endswith(s) and v[: -len(s)] in feat for s in ("y", "g", "v", "nv", "a"))

# ------------------------------------------------------------------------ native model

class World:
    def __init__(self, wave: str, model_root: str, assets_dir: str):
        mp_ = os.path.join(model_root, "gss", f"gss_{wave}")
        self.m = load_model(mp_)
        map_csv = ROOT / "maps" / "gss" / f"gss_{wave}_map.csv"
        self.ctx = ModelContext(self.m, mp_, str(map_csv), assets_dir=assets_dir)
        self.g = build_polar_geometry(self.ctx, str(ROOT / "assets" / "polar_vectors" / "polar_vectors.csv"))
        self.text = {r["variable"]: r["question_text_filled"] or r["question_text"]
                     for r in csv.DictReader(open(map_csv, encoding="utf-8"))}

    def valid(self, st: Dict[str, str]) -> Dict[str, str]:
        return {k: v for k, v in st.items() if k in self.ctx.idx_map and v in self.ctx.possible.get(k, [])}

    def I(self, st: Dict[str, str]) -> float:
        X = core.build_full_vector_from_state(self.m, st, self.ctx.idx_map)
        return float(core.ideology_index_from_vectors(X, self.g.sL, self.g.sR, self.m, dLR=self.g.dLR))

    def dists(self, st: Dict[str, str], vars_: List[str]) -> Dict[str, Dict[str, float]]:
        N = core.build_NULL_with_assignments(self.m, dict(st), self.ctx.idx_map)
        out = {}
        for v, d in core.qnet_conditional_distributions(self.m, N, target_vars=list(vars_)).items():
            d = {a: p for a, p in d.items() if a in self.ctx.possible.get(v, []) and p > 0}
            s = sum(d.values())
            if s > 0:
                out[v] = {a: p / s for a, p in d.items()}
        return out


W: Optional[World] = None


def _init(wave: str, model_root: str, assets_dir: str) -> None:
    global W
    W = World(wave, model_root, assets_dir)


def _expected(args) -> Dict[str, List[Tuple[float, float]]]:
    """Exact outcome distribution of dI for each candidate at one state: [(dI, p)] over its answers
    (answers with p >= 2%, at most the 8 likeliest, renormalized)."""
    st, I0, vars_ = args
    out = {}
    for v, d in W.dists(st, [v for v in vars_ if v not in st]).items():
        opts = sorted(d.items(), key=lambda x: -x[1])[:8]
        opts = [(a, p) for a, p in opts if p >= 0.02] or opts[:1]
        z = sum(p for _, p in opts)
        out[v] = [(W.I({**st, v: a}) - I0, p / z) for a, p in opts]
    return out


def _draw(args) -> Tuple[Dict[str, str], float]:
    st, v, seed = args
    d = W.dists(st, [v]).get(v)
    if not d:
        return st, W.I(st)
    a = random.Random(seed).choices(list(d), weights=list(d.values()))[0]
    st = {**st, v: a}
    return st, W.I(st)


def _simulate(args) -> List[float]:
    """Full draw-mode run of a sequence from one initial state; returns the ideology trajectory."""
    st, seq, seed = args
    rng = random.Random(seed)
    traj = [W.I(st)]
    for v in seq:
        d = W.dists(st, [v]).get(v)
        if d:
            st = {**st, v: rng.choices(list(d), weights=list(d.values()))[0]}
        traj.append(W.I(st))
    return traj

# ------------------------------------------------------------------------------ search

SIGN = {"CM": +1, "WF": -1}  # polarization: CM toward R (+), WF toward L (-)


RICH = False  # persona definition: stated facts only, or with the usual inferences (--rich)
SD_FLOOR = 0.01  # index units; below this, differences are not practically detectable


def score(stats: Dict[str, List[List[Tuple[float, float]]]], offset: Dict[str, List[float]]) -> Tuple[float, Dict]:
    """Robustness of the signed net change after this question, per persona, over the mixture of
    population states x sampled answers (net = change so far + this question's change).
    Score = worse persona's mean/sd (z), which tracks the share of runs moving the right way."""
    per = {}
    for side, per_state in stats.items():
        vals, wts = [], []
        for off, dist in zip(offset[side], per_state):
            for dI, p in dist:
                vals.append(off + SIGN[side] * dI)
                wts.append(p / len(per_state))
        x, wt = np.array(vals), np.array(wts)
        m = float(np.sum(wt * x))
        sd = float(np.sqrt(np.sum(wt * (x - m) ** 2)))
        step = float(np.sum(wt * (x - np.repeat(offset[side], [len(d) for d in per_state]))))
        per[side] = {"z": m / max(sd, SD_FLOOR), "mean_net": m, "sd_net": sd, "mean_step": step,
                     "share_right": float(np.sum(wt * (x > 0)))}
    return min(p["z"] for p in per.values()), per


def _score_items(pool: mp.Pool, pop: Dict, vars_: List[str], n: int) -> List[Tuple[float, str, Dict]]:
    jobs = [(st, I, vars_) for s in SIGN for st, I, _ in pop[s][:n]]
    res = pool.map(_expected, jobs, chunksize=1)
    per_side = {s: res[i * n:(i + 1) * n] for i, s in enumerate(SIGN)}
    offset = {s: [SIGN[s] * (I - I_start) for _, I, I_start in pop[s][:n]] for s in SIGN}
    scored = []
    for v in vars_:
        stats = {s: [r.get(v, [(0.0, 1.0)]) for r in per_side[s]] for s in SIGN}  # item already fixed: no change
        sc, per = score(stats, offset)
        scored.append((sc, v, per))
    return sorted(scored, key=lambda x: -x[0])


def optimize(pool: mp.Pool, w: World, cands: List[str], n_pop: int, length: int, prescreen: int,
             rescreen_every: int, screen_pop: int, min_gain: float, log) -> List[Dict]:
    pop = {s: [] for s in SIGN}
    for s in SIGN:
        for i in range(n_pop):
            st = w.valid(sample_persona(s, i, perturb=i > 0, rich=RICH))
            I = w.I(st)
            pop[s].append((st, I, I))
    chosen: List[Dict] = []
    shortlist: List[str] = []
    current = 0.0  # z of the empty sequence
    for step in range(length):
        used = {c["variable"] for c in chosen}
        full = step % rescreen_every == 0
        if full:  # cheap screen of every opinion item on a sub-population
            rough = _score_items(pool, pop, [v for v in cands if v not in used], screen_pop)
            shortlist = [v for _, v, _ in rough[:prescreen]]
        scored = _score_items(pool, pop, [v for v in shortlist if v not in used], n_pop)
        if not scored or scored[0][0] < current + min_gain:
            log(f"step {step + 1}: no item raises the robust score (z) by {min_gain}; stopping at {len(chosen)} questions")
            break
        current = scored[0][0]
        sc, v, per = scored[0]
        chosen.append({"variable": v, "text": w.text.get(v, ""), "score": sc, **{f"{s}_{k}": per[s][k] for s in SIGN for k in per[s]}})
        log(f"step {step + 1}: {v:12s} z={sc:+.2f}  CM net={per['CM']['mean_net']:+.4f}±{per['CM']['sd_net']:.4f} right={per['CM']['share_right']:.2f}"
            f"  WF net={per['WF']['mean_net']:+.4f}±{per['WF']['sd_net']:.4f} right={per['WF']['share_right']:.2f} (signed) | {w.text.get(v, '')[:50]}"
            + ("  [after full screen]" if full else ""))
        adv = pool.map(_draw, [(st, v, 1_000_003 * step + 2 * i + (s == 'WF')) for s in SIGN for i, (st, _, _) in enumerate(pop[s])])
        starts = {s: [x[2] for x in pop[s]] for s in SIGN}
        pop = {s: [(st, I, starts[s][i]) for i, (st, I) in enumerate(adv[j * n_pop:(j + 1) * n_pop])] for j, s in enumerate(SIGN)}
    return chosen

# -------------------------------------------------------------------------- validation

def validate(pool: mp.Pool, w: World, seq: List[str], n: int, seed0: int) -> Dict[str, np.ndarray]:
    """Trajectories (n x len+1) per side on held-out perturbed personas, fresh draw seeds."""
    out = {}
    for s in SIGN:
        jobs = [(w.valid(sample_persona(s, seed0 + i, rich=RICH)), seq, seed0 * 7919 + i) for i in range(n)]
        out[s] = np.array(pool.map(_simulate, jobs, chunksize=4))
    return out


def ci(x: np.ndarray, rng: np.random.Generator, B: int = 2000) -> Tuple[float, float, float]:
    boots = rng.choice(x, size=(B, len(x)), replace=True).mean(axis=1)
    return float(x.mean()), float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))


def summarize(traj: Dict[str, np.ndarray], rng: np.random.Generator) -> Dict:
    dC = traj["CM"][:, -1] - traj["CM"][:, 0]
    dW = traj["WF"][:, -1] - traj["WF"][:, 0]
    m = min(len(dC), len(dW))
    gap = dC[:m] - dW[:m]
    return {"n": int(len(dC)),
            "CM_change": ci(dC, rng), "CM_share_up": float(np.mean(dC > 0)),
            "WF_change": ci(dW, rng), "WF_share_down": float(np.mean(dW < 0)),
            "gap_change": ci(gap, rng),
            "share_both": float(np.mean((dC[:m] > 0) & (dW[:m] < 0)))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wave", default="2024")
    ap.add_argument("--model-root", default=os.environ.get("DTAG_MODEL_ROOT", str(Path.home() / ".cache/dtag/models")))
    ap.add_argument("--out", default="outputs/polarization_gss2024")
    ap.add_argument("--length", type=int, default=12)
    ap.add_argument("--pop", type=int, default=16, help="perturbed initial states per persona during search")
    ap.add_argument("--prescreen", type=int, default=30, help="shortlist size from each full screen")
    ap.add_argument("--screen-pop", type=int, default=4, help="states per persona for the full screen")
    ap.add_argument("--rescreen-every", type=int, default=4)
    ap.add_argument("--min-gain", type=float, default=0.02, help="stop when no item raises the robust score (z) this much")
    ap.add_argument("--sd-floor", type=float, default=0.01, help="minimum spread (index units) in the robustness score")
    ap.add_argument("--rich", action="store_true", help="personas include party, religion, attendance, marital status, education")
    ap.add_argument("--n-val", type=int, default=300, help="held-out validation runs per persona")
    ap.add_argument("--baselines", type=int, default=20, help="random opinion-item sequences for comparison")
    ap.add_argument("--n-base", type=int, default=30)
    ap.add_argument("--compare", nargs="*", default=[], help="name=var1,var2,... sequences to validate alongside")
    ap.add_argument("--sequence", default="", help="skip search; validate this comma-separated variable sequence")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    args = ap.parse_args()

    global SD_FLOOR, RICH
    SD_FLOOR = args.sd_floor
    RICH = args.rich
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "log.txt", "a", encoding="utf-8")

    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True); logf.write(line + "\n"); logf.flush()

    assets = str(out / "assets_cache")
    w = World(args.wave, args.model_root, assets)
    feat = set(w.ctx.feat)
    cands = [v for v in w.ctx.feat if askable(v, w.text.get(v, ""), feat)]
    log(f"GSS {args.wave}: {len(cands)} opinion items; poles {Path(w.g.path).name} ({len(w.g.left_map)} items)")
    rng = np.random.default_rng(12345)
    with mp.get_context("fork").Pool(args.workers, initializer=_init, initargs=(args.wave, args.model_root, assets)) as pool:
        if args.sequence:
            seq = args.sequence.split(",")
        else:
            chosen = optimize(pool, w, cands, args.pop, args.length, args.prescreen, args.rescreen_every, args.screen_pop, args.min_gain, log)
            json.dump(chosen, open(out / "search.json", "w"), indent=1)
            seq = [c["variable"] for c in chosen]
        log("sequence: " + ",".join(seq))
        results = {}
        traj = validate(pool, w, seq, args.n_val, seed0=100000)
        np.savez(out / "validation_trajectories.npz", CM=traj["CM"], WF=traj["WF"])
        results["optimized"] = summarize(traj, rng)
        results["optimized"]["per_step"] = {s: [ci(traj[s][:, k] - traj[s][:, 0], rng) for k in range(traj[s].shape[1])] for s in SIGN}
        log(f"optimized: {json.dumps({k: v for k, v in results['optimized'].items() if k != 'per_step'})}")
        for spec in args.compare:
            name, vs = spec.split("=", 1)
            t = validate(pool, w, [v for v in vs.split(",") if v in feat], args.n_val, seed0=100000)
            results[f"compare:{name}"] = summarize(t, rng)
            log(f"compare {name}: {json.dumps(results[f'compare:{name}'])}")
        base = []
        brng = random.Random(7)
        for b in range(args.baselines):
            bseq = brng.sample(cands, len(seq))
            t = validate(pool, w, bseq, args.n_base, seed0=200000 + 1000 * b)
            sm = summarize(t, rng)
            base.append({"sequence": bseq, "CM_mean": sm["CM_change"][0], "WF_mean": sm["WF_change"][0],
                         "gap_mean": sm["gap_change"][0], "share_both": sm["share_both"]})
        results["random_baseline"] = {
            "sets": len(base),
            "CM_mean_range": [min(b["CM_mean"] for b in base), max(b["CM_mean"] for b in base)] if base else None,
            "WF_mean_range": [min(b["WF_mean"] for b in base), max(b["WF_mean"] for b in base)] if base else None,
            "gap_mean_median": float(np.median([b["gap_mean"] for b in base])) if base else None,
            "gap_mean_max": max(b["gap_mean"] for b in base) if base else None,
            "share_both_median": float(np.median([b["share_both"] for b in base])) if base else None,
            "sets_detail": base}
        log(f"random baseline: {json.dumps({k: v for k, v in results['random_baseline'].items() if k != 'sets_detail'})}")
    results["sequence"] = [{"variable": v, "text": w.text.get(v, "")} for v in seq]
    results["config"] = vars(args)
    json.dump(results, open(out / "results.json", "w"), indent=1)
    log(f"wrote {out / 'results.json'}")


if __name__ == "__main__":
    main()
