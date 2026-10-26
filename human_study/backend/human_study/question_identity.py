"""Participant-level protection against asking the same GSS construct repeatedly.

The native model still scores every remaining candidate with its unmodified
conditional state. These groups only prevent re-asking *near-equivalent* survey
items in one human session; they do not remove variables from the experiment
or alter the survey/LSM maps. Based on the 2024 GSS ballot and map IDs.

Do not collapse different substantive constructs solely because both mention
race, hiring, or citizenship. The explicit groups below correspond to a shared
survey stem/response task or a known wording-form variant.
"""
from __future__ import annotations



# Wording variants and dependent follow-on race identification questions.
RACE_IDENTITY = {
    "race", "raceself", "racerank1", "racerank2", "racerank3",
    "racecen1", "racecen2", "racecen3", "racesee",
}
# Exactly one causal explanation can be probed per participant from this
# five-item family; other explanations remain available to other participants.
RACIAL_CAUSES = {f"racdif{i}{suffix}" for i in range(1, 6) for suffix in ("", "x")}
# 2024 wording splits, alternate pronouns, and strongly overlapping policies.
HIRING_PREFERENCE = {
    "affrmact", "fejobaff", "fehire", "jobaff", "fejob1",
    "fejob2", "fejob3",
}
HIRING_DISCRIMINATION = {
    "discaff", "discaffm", "discaffw", "discaffwv", "discaffwnv",
}
CITIZENSHIP = {"citizen", "uscitzn", "amcit", "amcitizn"}
RACIAL_HOME_SALES = {"racopen", "racopenv", "racopennv"}
SOCIAL_SURVEILLANCE = {"cctv", "cctvy"}
# GSS alternate wording variants for the SAME action and referent.
CIVIL_LIBERTIES_VARIANTS = (
    ("spkath", "spkathy"), ("libath", "libathy"),
    ("spkrac", "spkracy"), ("librac", "libracy"),
    ("spkcom", "spkcomy"), ("colcom", "colcomy"), ("libcom", "libcomy"),
    ("spkmslm", "spkmslmy"), ("libmslm", "libmslmy"),
    ("polhitok", "polhitoky"), ("polabuse", "polabusey"),
    ("polattak", "polattaky"), ("letdie1", "letdie1y"),
    ("divlaw", "divlawv", "divlawnv"),
    ("racopen", "racopenv", "racopennv"),
)

_GROUPS = {
    "race-identity": RACE_IDENTITY,
    "racial-inequality-causes": RACIAL_CAUSES,
    "hiring-preference": HIRING_PREFERENCE,
    "hiring-discrimination": HIRING_DISCRIMINATION,
    "citizenship": CITIZENSHIP,
    "home-sale-discrimination": RACIAL_HOME_SALES,
    "public-video-surveillance": SOCIAL_SURVEILLANCE,
}
_GROUPS.update({
    "wording-variant-" + group[0]: set(group)
    for group in CIVIL_LIBERTIES_VARIANTS
})
_LOOKUP = {item: name for name, group in _GROUPS.items() for item in group}


def question_family(variable: str) -> str:
    """Canonical participant-facing question family (not a model coordinate)."""
    v = str(variable).casefold()
    if v in _LOOKUP:
        return _LOOKUP[v]
    # GSS historical survey-form suffixes: distinguish genuine 'y' concept
    # IDs from parallel question formulations only when explicitly enumerated.
    return "variable:" + v


def already_covered_ids(candidate_ids, asked_ids):
    """Only suppress covered variants *within a session*, never globally."""
    seen = {question_family(v) for v in asked_ids}
    return {v for v in candidate_ids if question_family(v) in seen}
