"""Coarse topic for a survey item from its question text (keyword rules; deterministic, offline).

Used to group items into arcs in the decision-landscape view. The first matching topic wins, so
the order of TOPICS matters (e.g. "confidence in churches" is Trust, "abortion" is checked before
"women"); roster and interviewer items go to "Background". Unmatched items fall into "Other".
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

# (topic, regex over the upper-cased question text + variable name)
TOPICS: List[Tuple[str, str]] = [
    # Roster / interviewer / background items (household or network members, ratings, schooling).
    ("Background", r"PERSON\s*\d|\d(ST|ND|RD|TH) PERSON|\(\d(ST|ND|RD|TH) MENTIONED|INTERVIEWER|RATING\b|COUNTRY OF ORIGIN|"
                   r"COLLEGE MAJOR|FIELD OF DEGREE|HIGHEST DEGREE|SCHOOL \w+ COURSE|HIGH SCHOOL|\bWEIGHS|HOW TALL|BELTCODE|CITIZEN\b(?! SAID)|"
                   r"PERCENTAGE OF|BASED ON ACS|PRESENCE OF OTHERS|CONSENT"),
    ("Trust & confidence", r"\bCONFID|\bTRUST|\bHELPFUL\b|\bFAIR\b|\bHONEST|TAKE ADVANTAGE"),
    ("Abortion & sexuality", r"ABORT|\bSEX|HOMOSEX|\bGAY|LESBIAN|PORN|BIRTH CONTROL|CONTRACEP|\bPILL"),
    ("Religion", r"RELIG|\bGOD\b|BIBLE|PRAY|CHURCH|CLERG|HEAVEN|\bHELL\b|POSTLIFE|AFTERLIFE|LIFE AFTER DEATH|CHRIS ?TIAN|MUSLIM|BUDDHI|HINDU|RELOBJ|MEANINGFUL|SPIRIT|SACRED|FAITH|\bSOUL|ASTROLOG|HOROSCOPE|MIRACLE"),
    ("Race & immigration", r"\bBLACK|\bWHITE|HISPANIC|\bRACE\b|RACIAL|RACIS|IMMIGR|ETHNIC|AFFIRM|PREFERENCE IN HIRING|\bASIAN|MINORIT|\bJEW|SEGREG|DISCRIMINAT"),
    ("Family & gender", r"FAMIL|CHILD|\bKID|PARENT|MARRI|MARRY|DIVORC|SPANK|\bWOMEN|\bWOMAN|\bWIFE|HUSBAND|MOTHER|FATHER|\bMEN\b|GENDER ROLE|OBEY|THINK FOR ONES SELF"),
    ("Government & spending", r"GOVT|GOVERNMENT|\bTAX|WELFARE|SPEND|INCOME DIFFER|REDUCE INCOME|MEDICAL CARE|FOREIGN AID|IMPROVING|HALTING|SUPPORTING|ASSISTANCE|SOCIAL SECURITY|MASS TRANSPORT|HIGHWAY|PARKS|SPACE EXPLOR|MILITARY|ARMAMENT|NATIONAL DEFENSE"),
    ("Politics & civil liberties", r"ALLOW|SPEAK|LIBRARY|\bBOOK|COMMUNIST|MILITARIST|ATHEIST|ANTIRELIG|\bVOTE|PARTY|POLIT|POLABUSE|VULGAR|LIBERAL|CONSERVATIVE|PRESIDENT|CONGRESS|COURT|POLICE|CRIME|\bLAW|DEATH PENALTY|EXECUT|\bGUN|MARIJUANA|LEGAL|CIVIL|PROTEST|DEMOCRA|FREEDOM|SUICIDE"),
    ("Science & environment", r"\bSCI|ENVIR|PESTICID|\bNUKE|NUCLEAR|CLIMATE|ENERGY|GENETIC|\bNANO|TECHNOLOG|RESEARCH|\bEARTH|ANTIBIOTIC|EVOLV|ASTRONOM|RADIOACT|LASER|ELECTRON|CONTINENT|NATURAL ENVIRON|ANIMAL"),
    ("Work & economy", r"\bWORK|\bJOB|EMPLOY|\bPAY|WAGE|INCOME|COWORK|UNION|BUSINESS|COMPANY|ECONOM|STANDARD OF LIVING|\bRICH|\bPOOR|PROFIT|SALARY|FINANC|MONEY|CLASS\b|OCCUP|PROMOT|HOURS|PENSION|FRINGE|BENEFIT PLAN|ESOP|SELF-MANAGED|SUPERVIS|DEVELOP MY ABILIT|SUBORDIN"),
    ("Health & wellbeing", r"HEALTH|MENTAL|DEPRESS|HAPP|LONELY|ISOLAT|SLEEP|\bSICK|DRUG|COCAINE|CRACK|HEROIN|ALCOHOL|DRINK|SMOK|\bFELT|STRESS|DANGEROUS|TREATMENT|DISEASE|DISAB|ACTIVITY LIMIT|USED UP|GOALS|SATISFIED WITH|FATALISM|COURSE OF THEIR LIVES|CONDOM|LIFTING|PHYSICAL EFFORT|HAND MOVEMENT"),
    ("Social life & media", r"FRIEND|NEWS|EMAIL|\bWWW|INTERNET|\bTV\b|TELEVIS|\bREAD|\bPET\b|PETS|\bZOO|KNOW SOMEONE|SEES OR TALKS|FACE TO FACE|NEIGHBOR|CLOSE R IS|SOCIAL|CLUB|ASSOCIATION|VOLUNTEER|MUSEUM|LIBRAR|TRAILS|COMMUNITY|WELL LIKED|POPULAR|HELP OTHERS|GOSSIP|FORGIVE|DOG\b|\bCAT\b|HORSE|BIRD|FISH|GOAT"),
]
OTHER = "Other"
# Display order: opinion topics first, then the leftovers.
ORDER: List[str] = [t for t, _ in TOPICS if t != "Background"] + [OTHER, "Background"]
_RX = [(t, re.compile(p)) for t, p in TOPICS]


# GSS abortion battery: the item texts ("NOT MARRIED", "POOR") do not mention abortion.
_VAR_RULES = [("Abortion & sexuality", re.compile(r"^ab(any|nomore|single|poor|rape|hlth|defect|mother|moral|pro|inf|felegl|melegl|help\d|elegl|choose|sex)", re.I))]


def topic_of(text: str, variable: str = "") -> str:
    for t, rx in _VAR_RULES:
        if rx.search(variable or ""):
            return t
    s = f"{text or ''} {variable or ''}".upper()
    for t, rx in _RX:
        if rx.search(s):
            return t
    return OTHER


def topics_for(items: Iterable[str], var_map: Dict[str, str]) -> Dict[str, str]:
    return {v: topic_of(var_map.get(v, ""), v) for v in items}
