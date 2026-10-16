#!/usr/bin/env python3
"""How much does the native P(a | s, v) depend on the persona state s?

Total-variation distance between CM, WF and empty-state answer distributions for
every non-persona variable (reads one_step_enumeration outputs + one model pass).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from optimizer.dtag_bridge import DEFAULT_POLES, World, canonical_map, ensure_model  # noqa: E402

RES = HERE / "results" / "one_step_enumeration"
P = {n: pd.read_csv(RES / n / "response_level.csv") for n in ("CM", "WF")}
shared = sorted(set(P["CM"].variable) & set(P["WF"].variable))
w = World(str(ensure_model("gss/gss_2018", None, download=False)), str(canonical_map("gss/gss_2018")),
          str(DEFAULT_POLES), str(RES / "native_cache"))
empty = w.dists({}, shared)
tv = {}
for n in P:
    g = P[n].groupby("variable")
    tv[n] = {v: 0.5 * sum(abs(r.conditional_probability - empty[v].get(r.answer, 0.0))
                          for r in g.get_group(v).itertuples()) for v in shared}
cm = P["CM"].set_index(["variable", "answer"]).conditional_probability
wf = P["WF"].set_index(["variable", "answer"]).conditional_probability
tvcw = (cm - wf.reindex(cm.index)).abs().groupby(level=0).sum() / 2
df = pd.DataFrame({"tv_CM_empty": tv["CM"], "tv_WF_empty": tv["WF"], "tv_CM_WF": tvcw.reindex(shared)})
df.index.name = "variable"
df.to_csv(RES / "conditioning_strength.csv")
q = df.quantile([.5, .9, .99]).T
print(q.round(4).to_string())
for c in df:
    print(c, "share < 0.01:", round((df[c] < 0.01).mean(), 3), "share < 0.05:", round((df[c] < 0.05).mean(), 3))
print(df.sort_values("tv_CM_WF", ascending=False).head(12).round(3).to_string())
for v in ("ABHELP2", "homosex", "spkhomo", "abany", "PRES16", "god", "grass", "gunlaw"):
    if v in df.index: print(v, df.loc[v].round(3).to_dict())
