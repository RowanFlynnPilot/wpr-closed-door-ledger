"""What a closed-session notice says the session is actually about.

Notices mostly restate the statute, then name the real subject after a marker
("for the purpose of", "regarding", "to wit", a bullet, ...), in parentheses, or, in the
Wausau School District's layout, before the citation. purpose_text() returns
that subject, or "" when the notice only restates the statute.

Deterministic, no LLM. Tested against every fixture's purpose_contains.
"""
from __future__ import annotations

import re

from citations import parse

# A citation, from its statute marker through the last paragraph letter.
_CITATION = re.compile(
    r"(?:\b(?:pursuant\s+to|under)\s+)?"
    r"(?:(?:Wisconsin\s+State\s+Statutes?|Wis\.\s*Stats?\.?(?:\s*(?:sec\.|ss?\.))?|W\.?S\.?S\.?|Sections?|sec\.|ss?\.)\s*)?§*\s*"
    r"19\s*[./]?\s*8[56]\s*(?:\(\s*\w{1,2}\s*\)?\s*(?:,|and|or|&)?\s*)*"
    r"(?:\s*,?\s*(?:of\s+the\s+)?(?:Wis(?:consin)?\.?\s*Stat(?:ute)?s?\.?|Wisconsin\s+Statutes))?",
    re.I,
)
# Phrases after which a notice names its actual subject.
_MARKER = re.compile(
    r"(?:\b(?:for\s+the\s+purposes?\s+of|regarding|in\s+regards?\s+to|to\s+wit|specifically|to\s+discuss|re:|"
    r"including|discussing|related\s+to|relating\s+to)|•)\s*[:\-–—•]?\s*",
    re.I,
)
_WEAK = re.compile(r"related\s+to|relating\s+to|including", re.I)
# The start of another motion: a subject clause ends there (Kronenwetter puts
# two motions in one item).
_MOTION_START = re.compile(
    r"\b(?:consideration\s+of\s+(?:a\s+)?motion|motion\s+to\s+(?:convene|adjourn|move|go))\b", re.I)
# Words that carry no subject. If nothing else precedes the citation, the
# notice named no subject there.
_BOILERPLATE = re.compile(
    r"(?:^|\s)(?:[IVXL]+\.|\d+[.)]?|[A-Z]\.)(?=\s)|"
    r"the\s+board\s+will\s+(?:consider|contemplate)\s+adjournment\s+to|the\s+board\s+will\s+convene\s+into|"
    r"consideration\s+of\s+(?:a\s+)?motion\s+to\s+(?:convene|adjourn|move|go)\s+(?:in|into|to)|"
    r"adjourn(?:ment)?\s+to|convene\s+(?:meeting\s+)?into|"
    r"closed\s+session|pursuant\s+to|\bunder\b|\bwis(?:consin)?\.?\s*stat(?:ute)?s?\.?|[.:,;\-–—]",
    re.I,
)
_NOT_A_SUBJECT = re.compile(r"^(?:board only|if necessary|if needed)$", re.I)
# The statute's own wording, restated in the notice. A subject candidate is cut
# where it begins: "To consider the employment, promotion, compensation or
# performance evaluation data of an employee" names no subject.
_STATUTE_WORDING = re.compile(
    r"(?:which,?\s*if\s+discussed\s+in\s+(?:open\s+session|public),?\s*)?(?:would\s+)?(?:be\s+)?likely\s+"
    r"(?:to\s+)?have\s+a\s+substantial\s+adverse\s+effect|"
    r"employment,\s*promotion,\s*compensation|performance\s+evaluation\s+data|financial,\s*medical,\s*social|"
    r"deliberating\s+or\s+negotiating\s+the\s+purchas|conferring\s+with\s+legal\s+counsel|"
    r"dismissal,\s*demotion,\s*licensing|crime\s+detection\s+or\s+prevention|quasi-judicial\s+trial",
    re.I,
)
_FILLER = {"to", "consider", "considering", "the", "of", "a", "an", "and", "or", "for", "data", "any", "on"}


def _subject(candidate: str) -> str:
    """The candidate cut where the statute's wording begins; "" if no subject is left."""
    found = _STATUTE_WORDING.search(candidate)
    if found:
        candidate = _clean(candidate[: found.start()])
    candidate = re.sub(r"(?i)\s+(?:and|or)$", "", candidate)
    meaningful = [w for w in re.findall(r"[\w'’/-]+", candidate.lower()) if w not in _FILLER]
    return candidate if len(meaningful) >= 2 or (meaningful and not found) else ""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" .;,:-–—")


def purpose_text(item_text: str) -> str | None:
    """The notice's own subject for a closed-session item.

    None when the item cites no statute (it goes to review as no_citation).
    "" when the notice only restates the statute.
    """
    cites = parse(item_text)
    if not cites.exemptions and not cites.other_citations:
        return None
    parts: list[str] = []
    # 1. Subject written before the citation (Wausau School District's layout:
    #    "Meet with Attorney to Discuss Sale of Property ss. 19.85(1)(e)"). Kept whole.
    first = _CITATION.search(item_text)
    lead = ""
    if first:
        before = _clean(item_text[: first.start()])
        if before and _subject(_BOILERPLATE.sub(" ", before)):
            lead =_subject(re.sub(r"(?i)\s*(?:in\s+)?closed\s+session$", "", before).strip())
    if lead:
        parts.append(lead)
    # 2. Subject named after a marker. Take each marker's clause up to the next
    #    citation, the next marker, the next motion, or the end, so multi-exemption
    #    items keep every subject. Markers inside a kept lead are already covered.
    covered = 0
    for marker in _MARKER.finditer(item_text):
        if lead and marker.start() < first.start() or marker.start() < covered:
            continue
        rest = item_text[marker.end():]
        # "related to", "relating to" and "including" sit inside subjects ("three Citizen
        # Complaints related to the Police Department"), so they don't end a clause.
        strong = next((m for m in _MARKER.finditer(rest) if not _WEAK.match(m.group())), None)
        stops = [m.start() for m in (_CITATION.search(rest), strong, _MOTION_START.search(rest)) if m]
        end = min(stops) if stops else len(rest)
        covered = marker.end() + end
        clause = _subject(_clean(re.sub(r"\([^)]*\)", " ", rest[:end])))
        if clause:
            parts.append(clause)
    # 3. Subjects given in parentheses (D.C. Everest's layout).
    for paren in re.findall(r"\(([^()]{3,})\)", item_text):
        paren = _clean(paren)
        if not re.match(r"^\s*(?:\d|[a-h]{1,2}|cm)\s*$", paren, re.I) and not _NOT_A_SUBJECT.match(paren):
            if _subject(paren):
                parts.append(paren)
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return "; ".join(seen)
