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
    r"19\s*[./]?\s*8[56]\s*(?:(?:,|and|or|&)?\s*\(\s*\w{1,2}\s*\)?\s*,?\s*)*"
    r"(?:\s*,?\s*(?:of\s+the\s+)?(?:Wis(?:consin)?\.?\s*Stat(?:ute)?s?\.?|Wisconsin\s+Statutes))?",
    re.I,
)
# Phrases after which a notice names its actual subject.
_MARKER = re.compile(
    r"(?:\b(?:for\s+the\s+purposes?\s+of|regarding|in\s+regards?\s+to|t\s?o\s+wit|specifically|to\s+discuss|re:|"
    r"including|discussing|related\s+to|relating\s+to|to\s+hold)|•|[–—](?=\s*[A-Z]))\s*[:\-–—•]?\s*",
    re.I,
)
# The start of another motion: a subject clause ends there (Kronenwetter puts
# two motions in one item).
_MOTION_START = re.compile(
    r"\b(?:consideration\s+of\s+(?:a\s+)?motion|motion\s+to\s+(?:convene|adjourn|move|go))\b", re.I)
# Procedural words. Text before the citation made only of these (and item labels)
# names no subject: "MOTION TO MOVE TO", "The Board will adjourn to", "CONTINUE".
_PROCEDURAL = set("""
    the a an board council committee commission education village city will may shall likely entertain
    consider consideration contemplate of motion motions move moving to into in continue continuing convene
    convening adjourn adjournment adjourning directly enter entering go recess closed session pursuant under
    per wis wisconsin stat stats statute statutes state sec section sections s ss meeting meetings regular special
    following after before open prior remain remaining executive if necessary needed trustees for
    announcement possible discussion action approve approving going and
""".split())
# A sentence's end, but not an initial ("T. Winters") or an abbreviation ("vs. City", "No. 24CV40").
_SENTENCE_END = re.compile(r"(?<!\b[A-Z])(?<!\bvs)(?<!\bv)(?<!\bNo)(?<!\bSt)(?<!\bInc)(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<!\bWis)(?<!\bStat)(?<!\bStats)\.\s+[A-Z]")
# Statute letters in parentheses inside a clause ("(1)(c)") are dropped; longer
# parentheses ("(Riverlife South)", "applicant(s)") are part of the subject.
_SHORT_PAREN = re.compile(r"\(\s*(?:\d{1,2}|[a-h]{1,2}|cm)\s*\)", re.I)
_NOT_A_SUBJECT = re.compile(r"^(?:board only|if necessary|if needed|same|the same|said)$", re.I)
# The statute's own wording, restated in the notice. A subject candidate is cut
# where it begins: "To consider the employment, promotion, compensation or
# performance evaluation data of an employee" names no subject.
_STATUTE_WORDING = re.compile(
    r"(?:which,?\s*if\s+discussed\s+in\s+(?:open\s+session|public),?\s*)?(?:would\s+)?(?:be\s+)?likely\s+"
    r"(?:to\s+)?have\s+a\s+substantial\s+adverse\s+effect|"
    r"employment,\s*promotion,\s*compensation|performance\s+evaluation\s+data|financial,\s*medical,\s*social|"
    r"deliberating\s+or\s+negotiating\s+the\s+purchas|conferring\s+with\s+legal\s+counsel|"
    r"dismissal,\s*demotion,\s*licensing|crime\s+detection\s+or\s+prevention|(?:judicial\s+or\s+)?quasi-judicial\s+trial|"
    r"(?:deliberating\s+(?:concerning\s+|on\s+)?)?a\s+case\s+which\s+was\s+the\s+subject|purchasing\s+of\s+public\s+propert|investing\s+of\s+public\s+funds|"
    r"competitive\s+(?:or|and)\s+bargaining\s+reasons|personal\s+histories|preliminary\s+consideration\s+of\s+specific|"
    r"requests?\s+for\s+confidential\s+(?:written\s+)?advice|probation,?\s+extended\s+supervision",
    re.I,
)
_FILLER = {"to", "consider", "considering", "the", "of", "a", "an", "and", "or", "for", "data", "any", "on"}


def _subject(candidate: str) -> str:
    """The candidate cut where the statute's wording begins; "" if no subject is left."""
    found = _STATUTE_WORDING.search(candidate)
    if found:
        candidate = _clean(candidate[: found.start()])
    candidate = _clean(re.sub(r"(?i)\s+(?:and|or|when|whenever|which|where)$", "", candidate))
    meaningful = [w for w in re.findall(r"[\w'’/-]+", candidate.lower()) if w not in _FILLER]
    return candidate if len(meaningful) >= 2 or (meaningful and not found) else ""


def _names_something(text: str) -> bool:
    words = re.findall(r"[A-Za-z']+", text)
    return any(w.lower() not in _PROCEDURAL and not w.lower().startswith("purs")     # "PURSUSANT" (Kronenwetter)
               and not re.fullmatch(r"[IVXLC]+|[A-Za-z]", w) for w in words)


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
        if _names_something(before):
            lead = _subject(re.sub(r"(?i)\s*(?:in\s+)?closed\s+session$", "", before).strip())
    if lead:
        parts.append(lead)
    # 2. Subject named after a marker. A clause runs to the next citation, bullet or
    #    motion, so multi-exemption items keep every subject, and a second "regarding"
    #    inside one subject doesn't split it. Markers inside a kept lead are covered.
    covered = first.start() if lead else 0
    for marker in _MARKER.finditer(item_text):
        if marker.start() < covered:
            continue
        rest = item_text[marker.end():]
        stops = [m.start() for m in (_CITATION.search(rest), re.search("•", rest), _MOTION_START.search(rest),
                                     _SENTENCE_END.search(rest), re.search(r";\s*t\s?o\s+wit", rest, re.I),
                                     re.search(r"^[^(]*?\)", rest)) if m]           # the parenthesis it sits in
        end = min(stops) if stops else len(rest)
        clause = _clean(_SHORT_PAREN.sub(" ", rest[:end]))
        while (opening := _MARKER.match(clause)) and opening.end():
            clause = _clean(clause[opening.end():])        # "specifically, to discuss the ..."
        clause = re.sub(r"(?i)^and\s+(?:(?:consider|discuss)\s+)?", "", clause)   # "to discuss and consider the ..."
        clause = "" if _NOT_A_SUBJECT.match(clause) else _subject(clause)
        if clause:
            parts.append(clause)
            # A clause that was only statute wording ("for the purpose of conferring with legal
            # counsel ...") hides nothing: a later "to wit" in it still names the subject.
            covered = marker.end() + end
    # 3. Subjects given in parentheses (D.C. Everest's layout).
    for paren in re.findall(r"\(([^()]{3,})\)", item_text):
        paren = _clean(paren)
        if not re.match(r"^\s*(?:\d|[a-h]{1,2}|cm)\s*$", paren, re.I) and not _NOT_A_SUBJECT.match(paren):
            if _subject(paren):
                parts.append(paren)
    # 4. Otherwise, the words right after the last citation, to the end of the sentence
    #    ("CONTINUE IN CLOSED SESSION PURSUANT TO §19.85(1)(c) Reclassification Review ...").
    if not parts:
        last = None
        for last in _CITATION.finditer(item_text):
            pass
        if last:
            rest = item_text[last.end():]
            stops = [m.start() for m in (re.search(r"\.\s", rest), _MOTION_START.search(rest)) if m]
            tail = _subject(_clean(rest[: min(stops)] if stops else rest))
            if tail and _names_something(tail):
                parts.append(tail)
    # A part already contained in another ("loss of personal property" inside
    # "Inquiry regarding loss of personal property") is not a second subject.
    seen: list[str] = []
    for part in parts:
        if part and part not in seen and not any(part != other and part in other for other in parts):
            seen.append(part)
    return "; ".join(seen)
