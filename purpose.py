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
    r"(?:(?:Wisconsin\s+State\s+Statutes?|Wis\.\s*Stats?\.?|W\.?S\.?S\.?|Sections?|ss?\.)\s*)?§*\s*"
    r"19\s*[./]?\s*8[56]\s*(?:\(\s*\w{1,2}\s*\)?\s*(?:,|and|or|&)?\s*)*"
    r"(?:\s*,?\s*(?:of\s+the\s+)?(?:Wis(?:consin)?\.?\s*Stat(?:ute)?s?\.?|Wisconsin\s+Statutes))?",
    re.I,
)
# Phrases after which a notice names its actual subject.
_MARKER = re.compile(
    r"(?:\b(?:for\s+the\s+purposes?\s+of|regarding|in\s+regards?\s+to|to\s+wit|specifically|to\s+discuss|re:)|•)\s*[:\-–—•]?\s*",
    re.I,
)
# Words that carry no subject. If nothing else precedes the citation, the
# notice named no subject there.
_BOILERPLATE = re.compile(
    r"(?:^|\s)(?:[IVXL]+\.|\d+[.)]?|[A-Z]\.)(?=\s)|"
    r"the\s+board\s+will\s+(?:consider|contemplate)\s+adjournment\s+to|the\s+board\s+will\s+convene\s+into|"
    r"consideration\s+of\s+motion\s+to\s+convene\s+into|adjourn(?:ment)?\s+to|convene\s+(?:meeting\s+)?into|"
    r"closed\s+session|pursuant\s+to|\bunder\b|[.:,;\-–—]",
    re.I,
)
_NOT_A_SUBJECT = re.compile(r"^(?:board only|if necessary|if needed)$", re.I)


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
    # 1. Subject named after a marker. Take each marker's clause up to the next
    #    citation, the next marker, or the end, so multi-exemption items keep every subject.
    for marker in _MARKER.finditer(item_text):
        rest = item_text[marker.end():]
        stops = [m.start() for m in (_CITATION.search(rest), _MARKER.search(rest)) if m]
        clause = _clean(re.sub(r"\([^)]*\)", " ", rest[: min(stops)] if stops else rest))
        if clause:
            parts.append(clause)
    # 2. Subjects given in parentheses (D.C. Everest's layout).
    for paren in re.findall(r"\(([^()]{3,})\)", item_text):
        paren = _clean(paren)
        if not re.match(r"^\s*(?:\d|[a-h]{1,2}|cm)\s*$", paren, re.I) and not _NOT_A_SUBJECT.match(paren):
            parts.append(paren)
    # 3. Subject written before the citation (Wausau School District's layout).
    first = _CITATION.search(item_text)
    if first and not parts:
        before = _clean(item_text[: first.start()])
        if before and _BOILERPLATE.sub(" ", before).strip():
            parts.append(re.sub(r"(?i)\s*(?:in\s+)?closed\s+session$", "", before).strip())
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return "; ".join(seen)
