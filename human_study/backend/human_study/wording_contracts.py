"""Source-grounded, fail-closed wording contracts for context-dependent GSS 2024 items.

Only listed items receive replacement LLM INPUT context. The original native
map labels, selected variable IDs, answer support, and optimizer remain intact.
The original map wording is still archived by StudyService.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


GSS_2024_SOURCE = (
    "https://gss.norc.org/content/dam/gss/get-documentation/pdf/"
    "codebook/GSS%202024%20Codebook%20R2.pdf"
)

AMERICA = r"\b(?:america(?:'s)?|american|united states|u\.?\s?s\.?)\b"
PROUD = r"\bproud\b"


@dataclass(frozen=True)
class WordingContract:
    source: str
    required_patterns: tuple[str, ...]
    source_reference: str = GSS_2024_SOURCE


# In GSS 2024 these are follow-on items under the shared question:
# "How proud are you of America in each of the following?"
# The semantic map retains just the dependent fragment ("its history", etc.).
_PRIDE_TOPICS = {
    "prouddem": ("the way democracy works", r"\bdemocrac\w*\b"),
    "proudpol": ("its political influence in the world", r"\bpolitical\b.*\binfluence\b"),
    "proudeco": ("its economic achievements", r"\beconomic\b.*\bachievement\w*\b"),
    "proudspt": ("its achievements in sports", r"\bsport\w*\b"),
    "proudart": ("its achievements in the arts and literature", r"\barts?\b|\bliterature\b"),
    "proudhis": ("its history", r"\bhistor(?:y|ical)\b"),
}

CONTRACTS: dict[str, WordingContract] = {
    name: WordingContract(
        source=f"How proud are you of America for {topic}?",
        required_patterns=(PROUD, AMERICA, pattern),
    )
    for name, (topic, pattern) in _PRIDE_TOPICS.items()
}
# Prefer the simplest standalone construction for the observed defect.
CONTRACTS["proudhis"] = WordingContract(
    source="How proud are you of America's history?",
    required_patterns=(PROUD, AMERICA, r"\bhistor(?:y|ical)\b"),
)

# These 2024 questionnaire variables share a contextual seven-point scale.
# The semantic map often contains a truncated introduction and omits the group.
# Do not let the LLM substitute a different group or reverse the endpoints.
_GROUPS = {
    "whts": ("White people", r"\b(?:white people|whites|white americans?)\b"),
    "blks": ("Black people", r"\b(?:black people|blacks|african americans?)\b"),
    "hsps": ("Hispanic Americans", r"\b(?:hispanic(?: americans?| people)?|latino(?: americans?| people|s)?)\b"),
}
_SCALE = {
    "work": (
        "hard-working", "lazy",
        r"\b(?:1|one)\b.{0,200}\bhard[\s-]*work(?:ing)?\b.{0,200}\b(?:7|seven)\b.{0,200}\blazy\b",
    ),
    "wlth": (
        "rich", "poor",
        r"\b(?:1|one)\b.{0,200}\brich\b.{0,200}\b(?:7|seven)\b.{0,200}\bpoor\b",
    ),
}
for kind, (low, high, scale_rule) in _SCALE.items():
    for suffix, (group, group_rule) in _GROUPS.items():
        variable = kind + suffix
        CONTRACTS[variable] = WordingContract(
            source=(
                f"Rate {group} in general on a seven-point scale: "
                f"1 means almost all {group} are {low}; "
                f"7 means almost all are {high}. Where would you place them?"
            ),
            required_patterns=(group_rule, scale_rule),
        )



# AUDITED CIVIL LIBERTIES BATTERY (2024 R2, codebook pp. 114–120)
# The original survey asks a sequence about the same person. DTAG asks
# each variable independently, so carry the person and action into EVERY
# stand-alone LLM source. Preserve the experimental "y" wording distinctions.
_CIVIL_SUBJECTS = {
    "ath": ("a person opposed to all churches and religion",
            r"\b(?:against|oppos\w*)\b.{0,100}\b(?:church\w*|religion)\b"),
    "athy": ("a person opposed to all churches and religion",
             r"\b(?:against|oppos\w*)\b.{0,100}\b(?:church\w*|religion)\b"),
    "rac": ("a person who believes Black people are genetically inferior",
            r"\bblack\b.{0,100}\b(?:genetic\w*|inferior)\b"),
    "racy": ("a person who believes Black people are genetically inferior",
             r"\bblack\b.{0,100}\b(?:genetic\w*|inferior)\b"),
    "com": ("a man who admits he is a Communist", r"\bcommunis\w*\b"),
    "comy": ("a self-identified Communist", r"\bcommunis\w*\b"),
    "mslm": ("a Muslim clergyman who preaches hatred of the United States",
             r"\bmuslim\b.{0,100}\b(?:clerg\w*|religious leader|cleric)\b.{0,140}\b(?:hatred|hate)\b.{0,100}\b(?:united states|america|u\.?s\.?)\b"),
    "mslmy": ("an Islamic religious leader who preaches hatred of the United States",
              r"\b(?:islamic|muslim)\b.{0,100}\b(?:religious leader|clerg\w*|cleric)\b.{0,140}\b(?:hatred|hate)\b.{0,100}\b(?:united states|america|u\.?s\.?)\b"),
}
# Only actual 2024 map keys; no nonexistent COL*Y cases are synthesized.
_CIVIL_VARIABLES = {
    "ath": ("spk", "col", "lib"),
    "athy": ("spk", "lib"),
    "rac": ("spk", "col", "lib"),
    "racy": ("spk", "lib"),
    "com": ("spk", "col", "lib"),
    "comy": ("spk", "col", "lib"),
    "mslm": ("spk", "col", "lib"),
    "mslmy": ("spk", "lib"),
}
for suffix, kinds in _CIVIL_VARIABLES.items():
    subject, subject_rule = _CIVIL_SUBJECTS[suffix]
    for kind in kinds:
        if kind == "spk":
            source = (f"Consider {subject}. If this person wanted to give a speech "
                      "in the community expressing those views, should the speech "
                      "be allowed?")
            patterns = (subject_rule, r"\b(?:speak|speech)\b",
                        r"\b(?:allow\w*|permi\w*|free)\b")
        elif kind == "col" and suffix in ("com", "comy"):
            source = (f"Consider {subject}, currently teaching at a college. "
                      "Should this person be fired from that teaching position?")
            patterns = (subject_rule, r"\b(?:teach\w*|professor|college|university)\b",
                        r"\b(?:fir\w*|dismiss\w*|lose.{0,20}job)\b")
        elif kind == "col":
            source = (f"Consider {subject}. Should this person be allowed "
                      "to teach in a college or university?")
            patterns = (subject_rule, r"\b(?:teach\w*|college|university)\b",
                        r"\b(?:allow\w*|permi\w*)\b")
        else:
            source = (f"Consider {subject}, who has written a book in the public "
                      "library. If people in your community proposed removing "
                      "this book from the public library, would you favor removing it?")
            patterns = (subject_rule, r"\bbook\b", r"\b(?:librar\w*)\b",
                        r"\b(?:remov\w*|tak\w*.{0,15}out|ban\w*)\b")
        CONTRACTS[kind + suffix] = WordingContract(source, patterns)


# AUDITED ABORTION GRID (2024 R2, pp. 171–174). The source labels for
# follow-on questions omit the common "legal abortion" stem entirely.
_ABORTION_SCENARIOS = {
    "abdefect": ("there is a strong chance of a serious defect in the baby",
                 r"\b(?:defect|abnormal\w*|disabilit\w*)\b"),
    "abnomore": ("she is married and does not want any more children",
                 r"\bmarri\w*\b.{0,140}\b(?:more|another)\b.{0,50}\bchild\w*\b"),
    "abhlth": ("her own health is seriously endangered by the pregnancy",
               r"\b(?:health|life)\b.{0,110}\b(?:risk|danger|threat|pregnan\w*)\b"),
    "abpoor": ("her family has a very low income and cannot afford another child",
               r"\b(?:poor|low income|afford|financial\w*)\b"),
    "abrape": ("she became pregnant as a result of rape", r"\brap\w*\b"),
    "absingle": ("she is unmarried and does not want to marry the man",
                 r"\b(?:unmarried|not married|single)\b"),
    "abany": ("she wants an abortion for any reason", r"\b(?:any reason|whatever reason)\b"),
}
for name, (condition, condition_pattern) in _ABORTION_SCENARIOS.items():
    for suffix in ("", "g"):
        CONTRACTS[name + suffix] = WordingContract(
            "Do you think a pregnant woman should be legally allowed to obtain "
            f"an abortion if {condition}?",
            (r"\babort\w*\b", r"\b(?:legal\w*|law|permi\w*|allow\w*)\b",
             condition_pattern),
        )


# SUICIDE GRID (2024 R2, pp. 182–184): all labels require the shared
# "right to end one's own life" stem to be intelligible independently.
_SUICIDE_CONDITIONS = {
    "suicide1": ("the person has an incurable disease", r"\b(?:incurab\w*|terminal\w*)\b"),
    "suicide2": ("the person has gone bankrupt", r"\b(?:bankrupt\w*|insolven\w*)\b"),
    "suicide4": ("the person is tired of living and ready to die",
                 r"\b(?:tired of living|ready to die|no longer wish\w* to live)\b"),
}
for name, (condition, condition_pattern) in _SUICIDE_CONDITIONS.items():
    for suffix in ("", "g"):
        CONTRACTS[name + suffix] = WordingContract(
            "Do you think a person has the right to end their own life if "
            f"{condition}?",
            (r"\b(?:right|allow\w*|permi\w*)\b",
             r"\b(?:end.{0,20}(?:own|their|his|her).{0,10}life|suicid\w*|take.{0,20}(?:own|their|his|her).{0,10}life)\b",
             condition_pattern),
        )


# EQWLTH 2024 map/codebook source ends MID-SENTENCE. Preserve both ends
# of the seven-point scale rather than prompting from the truncated label.
CONTRACTS["eqwlth"] = WordingContract(
    "Some people think the government in Washington should reduce income "
    "differences between rich and poor people, for instance by taxation or "
    "income assistance. Others think the government should not concern "
    "itself with reducing those differences. Where do you stand on a "
    "seven-point scale from 1 (government should reduce income differences) "
    "to 7 (government should not concern itself with reducing differences)?",
    (r"\bgovernment\b", r"\bincome\b.{0,100}\b(?:differen\w*|inequal\w*|gap)\b",
     r"\b(?:reduc\w*|lessen\w*)\b", r"\b(?:not|no)\b.{0,100}\b(?:concern\w*|reduc\w*|interven\w*)\b"),
)


# GSS spending grid: the map has the topic but embeds a parenthetical
# shared stem. Ensure every stand-alone question explicitly asks about
# government/national spending and gives the too-much/too-little scale.
_NAT_TOPICS = {
    "natspac": "the space program", "natenvir": "improving and protecting the environment",
    "natheal": "improving the nation's health", "natcity": "problems of big cities",
    "natcrime": "halting the rising crime rate", "natdrug": "drug addiction",
    "nateduc": "improving the education system", "natrace": "conditions of Black people",
    "natarms": "the military, armaments, and defense", "nataid": "foreign aid",
    "natfare": "welfare", "natroad": "highways and bridges",
    "natsoc": "Social Security", "natchld": "assistance for childcare",
    "natsci": "supporting scientific research", "natenrgy": "alternative energy sources",
    "natspacy": "space exploration", "nathealy": "health",
    "natcityy": "assistance to big cities", "natcrimy": "law enforcement",
    "natdrugy": "drug rehabilitation", "nateducy": "education",
    "natracey": "assistance to Black people", "natarmsy": "national defense",
    "nataidy": "assistance to other countries", "natfarey": "assistance to the poor",
}
for name, topic in _NAT_TOPICS.items():
    CONTRACTS[name] = WordingContract(
        f"Do you think we are spending too much, too little, or about the "
        f"right amount on {topic}?",
        (r"\b(?:spend\w*|expenditure\w*|fund\w*)\b",
         r"\btoo much\b", r"\btoo little\b",
         r"\b(?:right amount|about right|appropriate amount)\b",
         re.escape(topic).replace(r"\ ", r"\s+")),
    )



# GSS INSTITUTIONAL CONFIDENCE GRID (2024 R2, pp. 157–165).
# The original shared stem asks about confidence in people RUNNING institutions.
_CONFIDENCE_TARGETS = {
    "conbus": ("major companies", r"\b(?:major companies|business(?:es)?|corporat\w*)\b"),
    "conclerg": ("organized religion", r"\b(?:organized religion|religious institution\w*|church\w*|clergy)\b"),
    "coneduc": ("education", r"\b(?:education|schools?|educational institution\w*)\b"),
    "conlabor": ("organized labor", r"\b(?:organized labor|trade union\w*|labor union\w*)\b"),
    "conpress": ("the press", r"\b(?:press|news media|journalis\w*)\b"),
    "conmedic": ("medicine", r"\b(?:medicine|medical (?:profession|institution\w*)|healthcare)\b"),
    "contv": ("television", r"\b(?:television|tv)\b"),
    "conjudge": ("the United States Supreme Court", r"\b(?:supreme court)\b"),
    "consci": ("the scientific community", r"\b(?:scientific community|scientists?|science)\b"),
    "conlegis": ("the United States Congress", r"\b(?:congress|legislat\w*)\b"),
    "conarmy": ("the military", r"\b(?:military|armed forces|army)\b"),
}
for name, (institution, target_pattern) in _CONFIDENCE_TARGETS.items():
    CONTRACTS[name] = WordingContract(
        f"How much confidence do you have in the people running {institution}: "
        "a great deal, only some, or hardly any at all?",
        (r"\bconfiden\w*\b", target_pattern,
         r"\b(?:great deal|a lot)\b", r"\b(?:hardly any|very little)\b"),
    )


# Police-force vignettes (2024 R2, policing battery). A conditional fragment
# alone cannot be answered as a moral/political opinion.
_POLICE_SCENARIOS = {
    "polabuse": ("a citizen said vulgar and obscene things to the officer",
                 r"\b(?:vulgar|obscene|swear\w*|insult\w*)\b"),
    "polabusey": ("a citizen said vulgar and obscene things to the officer",
                  r"\b(?:vulgar|obscene|swear\w*|insult\w*)\b"),
    "polmurdr": ("the citizen was being questioned as a murder suspect",
                 r"\b(?:murder|homicide)\b.{0,100}\b(?:suspect|question\w*)\b"),
}
for name, (condition, condition_pattern) in _POLICE_SCENARIOS.items():
    CONTRACTS[name] = WordingContract(
        f"Would you approve of a police officer physically striking a citizen "
        f"if {condition}?",
        (r"\b(?:police|policeman|officer)\b", r"\b(?:strik\w*|hitt\w*|hit|physically)\b",
         condition_pattern),
    )



def validates_standalone(text: str) -> bool:
    """Last-resort generic guard for visible orphan references and source markup.

    The source-specific contracts above provide the important *semantic* checks.
    This lightweight extra check catches outright broken unanchored subjects,
    placeholders, and copied codebook ellipses even for future map variables.
    """
    question = text.strip()
    if not question or not question.endswith("?"):
        return False
    if re.search(r"\{\s*#|(?:\.{3,}|…)|\[[A-Z_ ]{4,}\]", question):
        return False
    # Only inspect the START: a later "such a person" is legitimate if
    # explicitly introduced in an earlier sentence of the same question.
    if re.search(
        r"^(?:do you (?:think|believe) (?:that )?|should |would |could |"
        r"if |suppose )(?:such|this|that) (?:a )?person\b",
        question, re.I,
    ):
        return False
    if re.search(
        r"^(?:should|would|could|do you think|suppose) "
        r"(?:he|she|they|it|the book|this book)\b", question, re.I,
    ):
        return False
    if re.search(r"^if (?:she|he|they|this person)\b", question, re.I):
        return False
    if re.search(
        r"^(?:would you (?:favor|support|oppose) (?:remov\w*|bann\w*)|"
        r"do you favor removing) (?:this|the) book\b",
        question, re.I,
    ):
        return False
    return True



# 2024 RACDIF causal-attribution battery and its experimental -X form.
# The NORC 2024 R2 codebook identifies the -X version as differing in its
# extended historical-comparison introduction, NOT the causal explanations.
# The 2024 English ballot provides the full causal questions, whereas the
# 2024 R2 codebook labels for -X items truncate those explanatory endings.
_RACDIF_CAUSES = {
    "racdif1": ("racial discrimination", r"\bdiscriminat\w*\b"),
    "racdif2": ("an inborn difference in ability to learn",
                r"\b(?:innate|inborn|in-born|genetic\w*)\b.{0,100}\b(?:learn\w*|abilit\w*)\b"),
    "racdif3": ("unequal opportunities for education",
                r"\b(?:unequal opportunit\w*.{0,60}educat\w*|educat\w*.{0,140}(?:opportunit\w*|access|chance|equal))\b"),
    "racdif4": ("differences in motivation or willpower",
                r"\b(?:motivat\w*|willpower|will power)\b"),
    "racdif5": ("differences in upbringing", r"\bupbring\w*\b"),
}
for name, (cause, cause_pattern) in _RACDIF_CAUSES.items():
    CONTRACTS[name] = WordingContract(
        "On average Black people have worse jobs, income and housing than "
        "White people. Do you think those differences are mainly due to "
        f"{cause}?",
        (r"\bblack\b.{0,110}\b(?:white)\b",
         r"\b(?:jobs?|income|housing)\b",
         r"\b(?:differen\w*|inequal\w*|gap\w*)\b",
         cause_pattern),
    )

# The alternative -X wording explicitly includes a historical-comparison
# introduction. For a standalone question say the *series* has been asked
# for almost 50 years: RACDIF5 itself was first added in 2024.
# Keep the same causal concept and YES/NO response coding as the base item.
RACDIF_2024_BALLOT_SOURCE = (
    "https://gss.norc.org/content/dam/gss/get-documentation/pdf/"
    "quex/GSS2024_Ballot1_English.pdf"
)
for name in _RACDIF_CAUSES:
    base = CONTRACTS[name]
    CONTRACTS[name + "x"] = WordingContract(
        source=(
            "The GSS has asked questions about racial inequality for almost "
            "50 years. For historical comparison, we ask the following "
            "question. " + base.source
        ),
        required_patterns=(
            *base.required_patterns,
            r"\b(?:50|fifty)\b.{0,30}\byears?\b",
            r"\bhistorical\b.{0,45}\bcomparison\b",
        ),
        source_reference=RACDIF_2024_BALLOT_SOURCE,
    )


# Gender-role agreement grid (2024 R2 pp. 138–139); restore the common
# response stem, and complete FEFAM's truncated "takes care of the..." label
# from the historically documented wording "home and family".
_GENDER_AGREEMENT = {
    "fechld": (
        "a working mother can establish as warm and secure a relationship "
        "with her children as a mother who does not work",
        r"\bworking mother\b.{0,160}\b(?:warm|secure)\b",
    ),
    "fepresch": (
        "a preschool child is likely to suffer if the child's mother works",
        r"\bpreschool\b.{0,130}\bsuffer\b",
    ),
    "fefam": (
        "it is better for everyone if the man achieves outside the home "
        "and the woman takes care of the home and family",
        r"\bman\b.{0,120}\b(?:achiev\w*|work\w*)\b.{0,120}\bwoman\b.{0,130}\bhome\b",
    ),
}
for name, (statement, subject_pattern) in _GENDER_AGREEMENT.items():
    CONTRACTS[name] = WordingContract(
        f"To what extent do you agree or disagree with the statement that "
        f"{statement}: strongly agree, agree, disagree, or strongly disagree?",
        (subject_pattern, r"\bstrongly agree\b",
         r"\bstrongly disagree\b"),
    )



# STANDALONE 2024 RACE, HIRING AND PUBLIC-SURVEILLANCE ITEMS.
# The source map is especially abbreviated for RACERANK2/3, RACECEN2/3,
# AFFRMACT, DISCAFFW, FEJOBAFF, and CCTV. A respondent does not see the
# immediately preceding NORC ballot screen in an adaptive DTAG session.
# Rebuild the ENTIRE question rather than offering "these races", "these
# options", "this law", or an unexplained "it".
RACE_OPTIONS = (
    "White; Black or African American; American Indian or Alaska Native; "
    "Asian Indian; Chinese; Filipino; Japanese; Korean; Vietnamese; "
    "Other Asian; Native Hawaiian; Guamanian or Chamorro; Samoan; "
    "Other Pacific Islander; Some other race; Hispanic"
)
# Every native choice must be visible; including only common categories
# while referring to "these options" is not an acceptable standalone item.
RACE_REQUIRED_LABELS = tuple(
    re.escape(label.strip()).replace(r"\ ", r"\s+")
    for label in RACE_OPTIONS.split(";")
)

for rank in (1, 2, 3):
    if rank == 1:
        stem = "Which racial identity do you identify with most strongly?"
        ordinal = r"\b(?:most strongly|most closely|first|primary)\b"
    elif rank == 2:
        stem = ("If you identify with more than one racial identity, which "
                "one do you identify with second most strongly?")
        ordinal = r"\b(?:second|2nd)\b"
    else:
        stem = ("If you identify with three or more racial identities, "
                "which one do you identify with third most strongly?")
        ordinal = r"\b(?:third|3rd)\b"
    CONTRACTS[f"racerank{rank}"] = WordingContract(
        stem + " Options include: " + RACE_OPTIONS + "?",
        (r"\b(?:race|racial)\b", ordinal,
         r"\bwhite\b", r"\bblack\b", r"\basian\b",
         r"\b(?:indian|native)\b", *RACE_REQUIRED_LABELS),
    )
    desc = (
        "Which race or races do you consider yourself to be? You may "
        "identify with more than one. "
        if rank == 1 else
        "If you identify with two or more races, which additional race "
        "would you name second? " if rank == 2 else
        "If you identify with three or more races, which additional race "
        "would you name third? "
    )
    CONTRACTS[f"racecen{rank}"] = WordingContract(
        desc + "Options include: " + RACE_OPTIONS + "?",
        (r"\b(?:race|racial)\b", r"\bwhite\b", r"\bblack\b",
         r"\basian\b", r"\b(?:indian|native)\b",
         r"\b(?:more than one|second|third|additional)\b",
         *RACE_REQUIRED_LABELS),
    )

# Forced-choice race-based housing discrimination law: complete BOTH laws
# (2024 codebook RACOPEN / RACOPENV / RACOPENNV).
for variable in ("racopen", "racopenv", "racopennv"):
    CONTRACTS[variable] = WordingContract(
        "Imagine two proposed laws about selling a house. One law allows "
        "a homeowner to refuse to sell to a buyer because of the buyer's "
        "race. The other law prohibits a homeowner from refusing to sell "
        "because of the buyer's race. Which law would you favor?",
        (r"\b(?:homeowner|home owner)\b", r"\brace\b",
         r"\b(?:refus\w*|discriminat\w*)\b",
         r"\b(?:allow\w*|permi\w*)\b",
         r"\b(?:prohibit\w*|prevent\w*|forbid\w*|not allow)\b",
         r"\b(?:which law|favor)\b"),
    )

CONTRACTS["cctv"] = WordingContract(
    "Do you think the United States government should have the right to "
    "keep people under video surveillance in public areas? Would you say "
    "it definitely should, probably should, probably should not, or "
    "definitely should not have that right?",
    (r"\b(?:government|state)\b", r"\b(?:video surveillance|cctv)\b",
     r"\bpublic\b", r"\b(?:right|allowed|authority)\b",
     r"\b(?:definitely should|probably should)\b",
     r"\b(?:should not|shouldn't)\b"),
)

CONTRACTS["affrmact"] = WordingContract(
    "Do you favor or oppose giving Black people preference in hiring and "
    "promotion to address past racial discrimination?",
    (r"\bblack\b", r"\b(?:hiring|hire\w*)\b",
     r"\b(?:preferen\w*|priority)\b",
     r"\b(?:favor|support|oppose)\b"),
)

CONTRACTS["fejobaff"] = WordingContract(
    "Some people say that because of past discrimination, women should be "
    "given preference in hiring and promotion. Others say that giving women "
    "that preference is wrong because it discriminates against men. "
    "Are you for or against preferential hiring and promotion of women?",
    (r"\bwomen\b", r"\bmen\b", r"\b(?:hiring|hire\w*)\b",
     r"\bpreferen\w*\b", r"\b(?:for or against|favor|oppose)\b"),
)

CONTRACTS["fehire"] = WordingContract(
    "Because of past discrimination against women, should employers make "
    "special efforts to hire and promote qualified women? Do you strongly "
    "agree, agree, neither agree nor disagree, disagree, or strongly disagree?",
    (r"\bwomen\b", r"\b(?:hire|hiring)\b", r"\bpromot\w*\b",
     r"\b(?:qualified|special efforts)\b",
     r"\b(?:agree|disagree)\b"),
)

# Hiring disadvantage *chance* is different from a preference policy.
_HIRING_CHANCES = {
    "discaff": ("a White person", "an equally or less qualified Black person",
                r"\bwhite\b", r"\bblack\b"),
    "discaffm": ("a man", "an equally or less qualified woman",
                 r"\bman\b", r"\bwoman\b"),
    "discaffw": ("a woman", "an equally or less qualified man",
                 r"\bwoman\b", r"\bman\b"),
    "discaffwv": ("a woman", "an equally or less qualified man",
                  r"\bwoman\b", r"\bman\b"),
    "discaffwnv": ("a woman", "an equally or less qualified man",
                   r"\bwoman\b", r"\bman\b"),
}
for variable, (affected, beneficiary, grp1, grp2) in _HIRING_CHANCES.items():
    CONTRACTS[variable] = WordingContract(
        f"How likely do you think it is nowadays that {affected} will not "
        f"get a job or promotion while {beneficiary} gets one instead? "
        "Would you say very likely, somewhat likely, somewhat unlikely, "
        "or very unlikely?",
        (grp1, grp2, r"\b(?:job|hiring|hire)\b", r"\bqualif\w*\b",
         r"\b(?:likel\w*|chance)\b", r"\b(?:promotion|promot\w*)\b"),
    )

# The native map contains fragmentary citizenship labels; distinguish
# *personal status* from *the importance of citizenship* and *preferences*.
CONTRACTS["amcit"] = WordingContract(
    "How important do you think having American citizenship is for being "
    "truly American: very important, fairly important, not very important, "
    "or not important at all?",
    (r"\b(?:american|united states)\b", r"\bcitizenship\b",
     r"\bimportant\b"),
)
CONTRACTS["amcitizn"] = WordingContract(
    "To what extent do you agree or disagree with the statement: "
    "'I would rather be a citizen of the United States than a citizen "
    "of any other country'?",
    (r"\b(?:citizen|citizenship)\b", r"\b(?:united states|america)\b",
     r"\b(?:rather|prefer)\b", r"\b(?:agree|disagree)\b"),
)
for variable in ("citizen", "uscitzn"):
    CONTRACTS[variable] = WordingContract(
        "Are you currently a citizen of the United States?",
        (r"\bcitizen\b", r"\b(?:united states|america)\b"),
    )

# The violence vignettes inherit the action under discussion in the original
# sequence; make each askable item complete.
for variable in ("polattak", "polattaky"):
    CONTRACTS[variable] = WordingContract(
        "Would you approve of a police officer physically striking a "
        "citizen who was attacking that officer with their fists?",
        (r"\bpolice\b", r"\b(?:strik\w*|hit|physically)\b",
         r"\battack\w*\b", r"\bfists?\b"),
    )


# GSS 2024 ACPTTG and CHNGDOCS (Ballot 1, pp. 261-262; codebook R2,
# p. 517). The native semantic map reduces ACPTTG to "accepting people"
# and CHNGDOCS to a short label without the subject of the change. The
# complete GSS question defines *who* and what the government would allow.
# Never infer the omitted referent from the response options or ideology.
_2024_BALLOT_1 = (
    "https://gss.norc.org/content/dam/gss/get-documentation/pdf/"
    "quex/GSS2024_Ballot1_English.pdf"
)
CONTRACTS["acpttg"] = WordingContract(
    source=(
        "Do you think American society has gone too far, about far enough, "
        "or not far enough in accepting people whose sex differs from the "
        "one they were assigned at birth?"
    ),
    required_patterns=(
        r"\b(?:american society|society in (?:the )?(?:united states|america))\b",
        r"\baccept\w*\b",
        r"\b(?:transgender\b|(?:sex|gender).{0,110}assigned at birth)\b",
        r"\btoo far\b",
        r"\b(?:about far enough|about right|roughly enough)\b",
        r"\bnot far enough\b",
    ),
    source_reference=_2024_BALLOT_1,
)
CONTRACTS["chngdocs"] = WordingContract(
    source=(
        "Do you think the law should allow people to change the sex listed "
        "on official documents, such as a driver's license, to reflect a "
        "sex different from the one they were assigned at birth?"
    ),
    required_patterns=(
        r"\b(?:law|legally|government)\b",
        r"\b(?:allow|permit)\b",
        r"\bchang\w*\b",
        r"\b(?:sex|gender)\b",
        r"\b(?:official documents?|driver'?s licen[sc]e)\b",
        r"\bassigned at birth\b",
    ),
    source_reference=_2024_BALLOT_1,
)


# RINCOM16: 2024 GSS R2 codebook, pp. 93-94, Showcard A20.
# The live participant test revealed "the following ranges" with NO ranges.
# These are the 26 non-reserved survey categories and MUST be presented.
INCOME16_RANGES = (
    "Under $1,000", "$1,000 to $2,999", "$3,000 to $3,999",
    "$4,000 to $4,999", "$5,000 to $5,999", "$6,000 to $6,999",
    "$7,000 to $7,999", "$8,000 to $9,999",
    "$10,000 to $12,499", "$12,500 to $14,999",
    "$15,000 to $17,499", "$17,500 to $19,999",
    "$20,000 to $22,499", "$22,500 to $24,999",
    "$25,000 to $29,999", "$30,000 to $34,999",
    "$35,000 to $39,999", "$40,000 to $49,999",
    "$50,000 to $59,999", "$60,000 to $74,999",
    "$75,000 to $89,999", "$90,000 to $109,999",
    "$110,000 to $129,999", "$130,000 to $149,999",
    "$150,000 to $169,999", "$170,000 or over",
)
_INCOME16_PATTERNS = tuple(
    re.escape(label).replace(r"\ ", r"\s+")
    for label in INCOME16_RANGES
)
CONTRACTS["rincom16"] = WordingContract(
    "Thinking about your earnings from work during the last year, before "
    "taxes or other deductions, which of the following income ranges best "
    "describes your total earnings? Available ranges: "
    + "; ".join(INCOME16_RANGES) + "?",
    (r"\bearnings?\b", r"\b(?:work|occupation|job)\b",
     r"\b(?:last year|previous year)\b", r"\bbefore taxes\b",
     *_INCOME16_PATTERNS),
)

# The source treats 2nd and 3rd race as follow-up mentions, not assertions
# that every participant has three race identities. Display explicit
# applicability and a truthful route for those to whom it does not apply.
for prefix in ("racecen", "racerank"):
    for ordinal, threshold in ((2, "two"), (3, "three")):
        variable = f"{prefix}{ordinal}"
        original = CONTRACTS[variable]
        CONTRACTS[variable] = WordingContract(
            "Only if you identify with at least " + threshold +
            " racial identities: " + original.source.rstrip("?") +
            " If you identify with fewer than " + threshold +
            ", please answer 'not applicable'?",
            original.required_patterns +
            (r"\b(?:only if|if you identify with at least)\b",
             r"\bat least\b.{0,30}\b" + threshold + r"\b",
             r"\bnot applicable\b"),
            original.source_reference,
        )

# At runtime do not expose a mismatched 16-choice generic list if the
# native LSM holds recoded 13-category RACECEN values for the 2024 wave.
_NATIVE_RACE_IDS = {
    "racecen1", "racecen2", "racecen3",
    "racerank1", "racerank2", "racerank3",
}


def context_for_native_item(variable: str, answer_labels) -> WordingContract | None:
    """Use the native source-map answer alphabet, not guessed survey options."""
    base = CONTRACTS.get(variable.casefold())
    if base is None or variable.casefold() not in _NATIVE_RACE_IDS:
        return base
    values = list(dict.fromkeys(str(v).strip() for v in answer_labels if str(v).strip()))
    if not values:
        return base
    labels = "; ".join(values)
    text = base.source.replace(RACE_OPTIONS, labels)
    # Replace fixed catalogue checks with checks of the *actual* model
    # alphabet; race identity, order, applicability checks are unchanged.
    patterns = tuple(p for p in base.required_patterns
                     if p not in RACE_REQUIRED_LABELS) + tuple(
        re.escape(v).replace(r"\ ", r"\s+")
        for v in values
    )
    return WordingContract(text, patterns, base.source_reference)


def context_for(variable: str) -> WordingContract | None:
    return CONTRACTS.get(variable.lower())


def validates_wording(variable: str, generated: str, contract_override=None) -> bool:
    """Require explicit referent and preserved construct/scale in output.

    This narrowly targeted deterministic guard is not a substitute for a
    full instrument-level audit of every other native GSS question.
    """
    contract = contract_override or context_for(variable)
    return (contract is None or (
        bool(generated.strip())
        and all(re.search(pattern, generated, re.IGNORECASE | re.DOTALL)
                for pattern in contract.required_patterns)
    ))
