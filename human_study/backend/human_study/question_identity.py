"""Per-session duplicate suppression for *the same* GSS question.

Do not collapse subjects or question batteries: causes of racial inequality,
hiring policies, citizenship status/attitudes and ordered race mentions are
different model coordinates measuring different constructs.
"""
from __future__ import annotations

# Only source-documented variant forms of exactly the same measured task.
# The native optimizer still dynamically scores every other model coordinate.
VERIFIED_ALTERNATE_FORMS = (
    ("spkath", "spkathy"),
    ("libath", "libathy"),
    ("spkrac", "spkracy"),
    ("librac", "libracy"),
    ("spkcom", "spkcomy"),
    ("colcom", "colcomy"),
    ("libcom", "libcomy"),
    ("spkmslm", "spkmslmy"),
    ("libmslm", "libmslmy"),
    ("polhitok", "polhitoky"),
    ("polattak", "polattaky"),
    ("divlaw", "divlawv", "divlawnv"),
    ("racopen", "racopenv", "racopennv"),
)
_ALIASES = {
    variable: forms[0]
    for forms in VERIFIED_ALTERNATE_FORMS for variable in forms
}


def question_family(variable: str) -> str:
    """Exact identity, except evidence-backed alternate wording of one task."""
    v = str(variable).casefold()
    return _ALIASES.get(v, v)


def already_covered_ids(candidate_ids, asked_ids):
    seen = {question_family(v) for v in asked_ids}
    return {v for v in candidate_ids if question_family(v) in seen}
