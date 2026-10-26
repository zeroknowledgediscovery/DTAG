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
    source="How proud are you of America in each of the following? Its history.",
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
                f"7 means almost all are {high}."
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



# 2024 RACDIF classical causal-attribution battery (pp. 201–203).
# Separate from the *X wording-experiment* items whose canonical label is
# truncated; those X variables are excluded in the full Prolific YAMLs.
_RACDIF_CAUSES = {
    "racdif1": ("racial discrimination", r"\bdiscriminat\w*\b"),
    "racdif2": ("an inborn difference in ability to learn",
                r"\b(?:innate|inborn|in-born|genetic\w*)\b.{0,100}\b(?:learn\w*|abilit\w*)\b"),
    "racdif3": ("unequal opportunities for education",
                r"\b(?:educat\w*|school\w*)\b.{0,140}\b(?:opportunit\w*|access|chance|equal)\b"),
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


def context_for(variable: str) -> WordingContract | None:
    return CONTRACTS.get(variable.lower())


def validates_wording(variable: str, generated: str) -> bool:
    """Require explicit referent and preserved construct/scale in output.

    This narrowly targeted deterministic guard is not a substitute for a
    full instrument-level audit of every other native GSS question.
    """
    contract = context_for(variable)
    return (contract is None or (
        bool(generated.strip())
        and all(re.search(pattern, generated, re.IGNORECASE | re.DOTALL)
                for pattern in contract.required_patterns)
    ))
