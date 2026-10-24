"""Build an unreviewed pilot instrument from actual map/model categories.

The generated file must be reviewed before staging/production. No category
labels or map text are guessed. Run after installing the verified native model.
"""
import argparse
import csv
import json
from pathlib import Path

import yaml

from . import ROOT
from .adapter import MISSING, NativeAdapter
from .study_config import StudyConfig

BASELINE = "confinan conbus coneduc conpress conmedic contv conjudge consci conlegis conarmy trust fair helpful".split()
OUTCOMES = "cappun courts tax".split()

# Audited against the checked-in GSS 2024 semantic map. These are excerpts,
# truncated labels or question fragments, NOT verified verbatim 2024 questions.
# Retain the source strings; the question generator must complete and validate
# a neutral respondent-facing question from the excerpt and native answer options.
INCOMPLETE_GSS_2024 = frozenset("""
confinan
nataid natchld natcity natcrime natcrimy natdrug nateduc natenrgy
natenviy natheal natrace natroad natsci natspac
eqwlth helppoor helpsick helpnot letin1a fehire fejobaff fefam
workhard helpoth
""".split())


def build(adapter, steps=20):
    from optimize_question_sets import askable
    ctx, g = adapter.world.ctx, adapter.world.g
    reserved = set(BASELINE + OUTCOMES) | set(g.left_map) | set(g.right_map)
    # A deliberately limited draft bank. Investigators must review ALL text and options.
    candidates = [v for v in sorted(ctx.idx_map) if v not in reserved and v.startswith("nat")
                  and askable(v, ctx.var_map.get(v, ""), ctx.feat)]
    candidates += [v for v in "eqwlth helppoor helpsick helpnot letin1a getahead goodlife fehire fejobaff fefam happy health workhard helpoth".split()
                   if v not in reserved and v in ctx.var_map and askable(v, ctx.var_map[v], ctx.feat)]
    items = []
    for phase, variables in [("baseline", BASELINE), ("outcome", OUTCOMES), ("intervention", candidates)]:
        for v in variables:
            labels = [a for a in adapter.support(v) if not MISSING.search(a)]
            if v not in ctx.var_map or not (2 <= len(labels) <= 20):
                if phase != "intervention":
                    raise ValueError(f"instrument requires reviewed replacement for {v}")
                continue
            items.append({"item_id": v, "original_wording": ctx.var_map[v],
                          "source_text_incomplete": v in INCOMPLETE_GSS_2024, "choices": [
                {"native_value": a, "display_label": a} for a in labels], "phase": phase,
                "required": False, "version": "draft-1"})
    config = StudyConfig(study_id="pilot-001", intervention_steps=steps, items=items)
    adapter.validate_config(config)
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    # Adapter initialization only needs the fixed model identifier and release.
    from types import SimpleNamespace
    adapter = NativeAdapter(SimpleNamespace(model_key="gss/gss_2024", model_release="v0.2.1"))
    config = build(adapter)
    out = Path(args.out)
    if out.exists():
        raise SystemExit("refusing to overwrite an existing instrument")
    out.write_text(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False))
    print(f"Wrote {out}: {len(config.items)} native-validated items; reviewed=false")


if __name__ == "__main__":
    main()
