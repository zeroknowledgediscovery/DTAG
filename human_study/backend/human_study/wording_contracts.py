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
    "codebook/GSS%202024%20Codebook.pdf"
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
