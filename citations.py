"""Statute citations in a closed-session agenda item.

Deterministic, no LLM. Tested against tests/fixtures/citations.json, which
holds real notices from all five reachable jurisdictions plus a few
synthetic edge cases.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Paragraph letters that exist in s. 19.85(1). The closing parenthesis is
# optional because real notices drop it ("19.85(1)(g for ...").
_LETTER = r"\(\s*(ee|eg|em|[a-h])\b\s*\)?"
_SEP = r"(?:\s*(?:,|and|or|&)\s*)*"
# "(1)" may be typed "(l)"; a comma may follow it (Weston: "19.85(1), (c) and (f)").
_SUB1 = r"\(\s*[1l]\s*\)"
# The dot is optional: one Kronenwetter notice reads "Wis. Stat. 1985(1)(f)".
# Letters are read when chained directly after "19.85", so "except where
# par. (b) applies" inside the (f) paraphrase is never counted.
# A slash may stand in for the dot: one Wausau notice reads "19/85 (1)(f)".
_CITE_1985 = re.compile(r"19\s*[./]?\s*85\s*(?:" + _SUB1 + r"\s*,?\s*)?((?:" + _LETTER + _SEP + r")+)", re.I)
_HAS_SUB1 = re.compile(r"19\s*[./]?\s*85\s*" + _SUB1, re.I)
# D.C. Everest lists further letters after the first exemption's paraphrase:
# "... (Administrator Retirement Agreements) and (e) for Deliberating ...".
# Only read when the item already cites 19.85, and only when the letter
# introduces another exemption's wording.
_CONTINUATION = re.compile(
    r"(?<!par\.\s)(?<!paragraph\s)(?<!\w)\(\s*(ee|eg|em|[a-h])\s*\)\s*"
    r"(?:Wis\.\s*Stats?\.?\s*|W\.?S\.?S\.?\s*)?[-–—]?\s*"
    r"(?=for\b|to\b|consider|deliberat|confer)",
    re.I,
)

# Any other statute: a section number after a statute marker, plus numbers
# chained to it with "and" or commas. Municipal code numbers ("12.56.130",
# "Section 2.04 of the Village Code") are not statutes.
_SECTION = r"\d{1,3}\.\d{2,4}(?![\d.]\d)(?:\s*\(\s*[0-9a-z]{1,4}\s*\))*"
_MARKER = r"(?:\bss?\.|§§?|\bSections?\b|\bWis\.\s*Stats?\.?|\bW\.?S\.?S\.?)"
_OTHER = re.compile(
    _MARKER + r"\s*(" + _SECTION + r"(?:\s*(?:,|and|&)\s*" + _SECTION + r")*)"
    r"(?!\s*,?\s+of\s+the\s+(?:[\w.]+\s+){0,4}code)",
    re.I,
)


@dataclass(frozen=True)
class Citations:
    exemptions: list[str]               # s. 19.85(1) letters, in order of appearance
    cites_subsection_1: bool | None     # None when the item cites no 19.85 exemption
    other_citations: list[str]          # every other statute, normalized ("111.70(4)(cm)")
    citation_raw: str                   # the 19.85 citation text as written, "; "-joined (else any other statute's)


def parse(text: str) -> Citations:
    found: list[tuple[int, str]] = []
    raw: list[tuple[int, str]] = []
    has_sub1: list[bool] = []
    spans: list[tuple[int, int]] = []
    for match in _CITE_1985.finditer(text):
        raw.append((match.start(), re.sub(r"\s+", " ", match.group(0)).strip(" ,")))
        spans.append(match.span())
        has_sub1.append(bool(_HAS_SUB1.match(match.group(0))))
        for letter in re.finditer(_LETTER, match.group(1), re.I):
            found.append((match.start(1) + letter.start(), letter.group(1).lower()))
    if found:
        for match in _CONTINUATION.finditer(text):
            found.append((match.start(), match.group(1).lower()))
            # D.C. Everest's chained "(e) for ...": its own piece of the citation as written.
            if not any(start <= match.start() < end for start, end in spans):
                raw.append((match.start(), f"({match.group(1)})"))
    letters: list[str] = []
    for _, letter in sorted(found):
        if letter not in letters:
            letters.append(letter)
    others: list[str] = []
    other_raw: list[tuple[int, str]] = []
    for match in _OTHER.finditer(text):
        other_raw.append((match.start(), re.sub(r"\s+", " ", match.group(0)).strip(" ,")))
        for section in re.findall(_SECTION, match.group(1), re.I):
            section = re.sub(r"\s+", "", section).lower()
            if not section.startswith("19.85") and section not in others:
                others.append(section)
    return Citations(
        exemptions=letters,
        cites_subsection_1=all(has_sub1) if has_sub1 else None,
        other_citations=others,
        # The s. 19.85 citation as written; with none, whatever statute the item cites
        # instead (SAFER's "§ 19.81(1)(c)"), so a wrong citation is visible as written.
        citation_raw="; ".join(r for _, r in sorted(raw or other_raw)),
    )
