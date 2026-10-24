"""Closed-session items in a notice's text. Deterministic, no LLM.

1. segment(): split the text into agenda items by their numbering labels, never
   by line (PDF text wraps mid-citation). HTML text arrives one item per line
   (adapters/base.py). An unnumbered line in capitals ("CLOSED SESSION",
   "ACTION AFTER CLOSED SESSION") is a header above the numbered items.
2. Each item gets a depth from its label style, in the order the styles first
   appear (I. -> A. -> 1. -> a.), and a parent: the nearest earlier item that is
   shallower.
3. A closed-session section is an item that mentions convening in closed
   session (not reconvening or acting after it) plus everything under it. Each
   item in a section that cites s. 19.85(1) or s. 19.86 is a closed-session
   item. A section with no citation anywhere becomes one item with
   no_citation set. Header-only lines are not items.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import citations
from purpose import purpose_text

TRIAGE_TERMS = json.loads(Path(__file__).with_name("triage_terms.json").read_text(encoding="utf-8"))

_ROMAN = r"(?:X{0,3})(?:IX|IV|V?I{0,3})"
_PART = r"(?:[IVXLC]+|[A-Z]|\d{1,2}|[a-z])"
_LABEL = re.compile(
    r"^\s*(?P<label>"
    r"(?P<combined>" + _PART + r"(?:\." + _PART + r")+\.?)"          # BoardBook "V.A." "II.A.1."
    r"|(?P<simple>" + _PART + r")[.)]"                                # "IV." "A." "7." "a)"
    r"|\((?P<paren>\d{1,2}|[a-z]|[ivx]{1,4})\)"                       # "(1)" "(a)"
    r"|(?P<bare>\d{1,2})(?=\s+[A-Z])"                                 # Wausau's "5 Closed Session."
    r"|(?P<ocr>\d{1,2}),(?=\s+[A-Z])"                                 # OCR reads "8." as "8,"
    r")(?:\s+(?=\S)|(?<=\.)(?=[A-Z][a-z]))"                           # D.C. Everest PDFs: "III.The Board"
)
_CLOSED = re.compile(r"closed\s+session", re.I)
# Mentions of closed session that are not about convening one.
_NOT_CONVENE = re.compile(
    r"reconven|return\w*\s+(?:to|into)\s+open|"
    r"(?:after|following|from|out\s+of|upon\s+return\w*\s+from)\s+(?:the\s+)?closed\s+session|"
    r"(?:discussed|taken\s+up|considered)\s+in\s+(?:the\s+)?closed\s+session|"
    r"\bminutes\b|closed\s+session\s+(?:[IVX]+\s+)?(?:of|held|on)\s+(?:\w+\s+)?\d|"
    r"prior\s+to\s+(?:any\s+)?(?:potential\s+|possible\s+)?closed\s+session|"
    r"action\s+on\s+(?:the\s+)?closed\s+session|"
    r"closed\s+session\s+(?:was\s+|has\s+been\s+)?(?:removed|cancel+ed|deleted|struck|withdrawn)",  # amendment notes
    re.I,
)
# Wording that convenes a closed session even when the item also mentions reconvening.
_CONVENE_VERB = re.compile(
    r"\b(?:adjourn\w*|convene|convening|go|move|enter\w*|recess\w*|continue)\s+(?:\w+\s+){0,3}?"
    r"(?:in|into|to)\s+(?:a\s+)?closed\s+session|"
    r"^\W*closed\s+session\b|closed\s+session\s+(?:pursuant|under|per)\b|"
    r"request\s+for\s+(?:a\s+)?closed\s+session|announcement\s+of\s+(?:a\s+)?closed\s+session",
    re.I,
)
# An unnumbered line that starts one of these, in capitals, starts a new item
# (Wausau: "CLOSED SESSION pursuant to ...", "RECONVENE into Open Session";
# Weston: "MOTION TO MOVE TO CLOSED SESSION Pursuant to ...", "CONTINUE IN CLOSED SESSION").
_KEYWORD_LINE = re.compile(
    r"^(?:CLOSED\s+SESSION|RECONVENE|ADJOURN|CONVENE|CONTINUE\s+IN|ACTION\s+AFTER|ANNOUNCEMENT\s+OF|"
    r"OPEN\s+SESSION|RETURN\s+TO|MOTION\s+TO|MOVE\s+TO\s+CLOSED|REMAIN\s+IN\s+CLOSED|POSSIBLE\s+ACTION|"
    r"[A-Z][A-Z ,&'/-]{0,60}?CLOSED\s+SESSION)\b"   # "IF NECESSARY, MOTION TO MOVE TO CLOSED SESSION Pursuant ..."
)
# The agenda's closing item. Packets (Weston, some Wausau) carry other documents
# after the agenda, such as the previous meeting's minutes; pages after the one
# holding this line are not read. "Adjourn to closed session" is not it.
_ADJOURN = re.compile(r"^(?:\S{1,6}\s+)?adjourn(?:ment)?\b(?!\s+(?:to|into|in)\b)", re.I)
# Page headers and footers repeat at the top or bottom of each page.
_EDGE_LINES = 3
# "RECONVENE MEETING INTO OPEN SESSION" (Wausau), "RECONVEVE into Open Session" (a Weston
# misspelling) and "The Board will return to open session" (D.C. Everest) all state the intent.
_RECONVENE = re.compile(
    r"19\s*[./]?\s*85\s*\(\s*2\s*\)|(?:reconv\w*|return\w*)\s+(?:\w+\s+){0,2}?(?:in|into|to)\s+(?:the\s+)?open\s+session",
    re.I)


@dataclass
class Segment:
    label: str
    text: str           # the item's wording, label removed, whitespace collapsed
    page: int           # 1-based page the item starts on
    style: str          # label style; "header" for an unnumbered capitals line
    depth: int = 0
    parent: int | None = None
    children: list[int] = field(default_factory=list)


def _is_header(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return (len(letters) >= 6 and len(line) <= 90 and len(line.split()) >= 1
            and sum(c.isupper() for c in letters) / len(letters) >= 0.9)


def _style(m: re.Match, previous_upper: str | None) -> str:
    if m.group("combined"):
        return f"combined{m.group('combined').rstrip('.').count('.') + 1}"
    if m.group("paren"):
        return "paren-digit" if m.group("paren").isdigit() else "paren-lower"
    if m.group("bare") or m.group("ocr"):
        return "digit"
    part = m.group("simple")
    if part.isdigit():
        return "digit"
    if part.islower():
        return "lower"
    if len(part) > 1:
        return "roman"
    if re.fullmatch(_ROMAN, part) and part:
        # "I.", "V.", "X.", "C." after "H.", "U.", "W.", "B." are letters, not numerals.
        if len(part) == 1 and previous_upper and ord(part) - ord(previous_upper) == 1:
            return "upper"
        return "roman"
    return "upper"


def _edge_key(line: str) -> str:
    return re.sub(r"[\d\s]+", " ", line).strip().casefold()


def agenda_pages(text: str, stop_at_adjourn: bool = True) -> list[list[str]]:
    """Each page's non-empty lines, whitespace collapsed, without repeated page
    headers and footers, and (for notices) ending with the page that holds the
    closing Adjourn."""
    # U+F0B7 is the Symbol-font bullet Weston's PDFs use; it is a bullet.
    text = text.replace("", "•")
    pages = [[re.sub(r"\s+", " ", l).strip() for l in p.splitlines() if l.strip()] for p in text.split("\f")]
    if len(pages) > 1:
        seen: dict[str, set[int]] = {}
        for n, lines in enumerate(pages):
            for line in lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]:
                seen.setdefault(_edge_key(line), set()).add(n)
        repeated = {k for k, on in seen.items() if len(on) > 1}
        pages = [[l for i, l in enumerate(lines)
                  if not ((i < _EDGE_LINES or i >= len(lines) - _EDGE_LINES) and _edge_key(l) in repeated)]
                 for lines in pages]
    for n, lines in enumerate(pages):
        if stop_at_adjourn and any(_ADJOURN.match(l) and len(l) <= 40 for l in lines):
            return pages[: n + 1]
    return pages


def segment(text: str, stop_at_adjourn: bool = True) -> list[Segment]:
    """Agenda items. Minutes are segmented the same way, without stopping at Adjourn."""
    segments: list[Segment] = []
    previous_upper = None
    for page_no, lines in enumerate(agenda_pages(text, stop_at_adjourn), 1):
        for line in lines:
            m = _LABEL.match(line)
            if m:
                style = _style(m, previous_upper)
                if style == "upper":
                    previous_upper = m.group("simple")
                rest = line[m.end():]
                if rest.startswith(m.group("label") + " "):     # BoardBook sometimes doubles it: "II.A. II.A."
                    rest = rest[len(m.group("label")) + 1:]
                segments.append(Segment(m.group("label"), rest, page_no, style))
            elif _KEYWORD_LINE.match(line):
                segments.append(Segment("", line, page_no, "keyword"))
            elif _is_header(line) and not (segments and segments[-1].style == "header"
                                           and not segments[-1].text.rstrip().endswith((".", ":"))
                                           and len(segments[-1].text) < 60):
                segments.append(Segment("", line, page_no, "header"))
            elif segments:
                segments[-1].text += " " + line
            else:
                segments.append(Segment("", line, page_no, "preamble"))
    _assign_depths(segments)
    return segments


def _assign_depths(segments: list[Segment]) -> None:
    order: list[str] = []
    numbered_depth = 0
    for i, seg in enumerate(segments):
        if seg.style in ("header", "preamble"):
            seg.depth = -1
        elif seg.style == "keyword":
            seg.depth = numbered_depth          # a sibling of the numbered item before it
        elif seg.style.startswith("combined"):
            seg.depth = int(seg.style[len("combined"):]) - 1
        else:
            if seg.style not in order:
                order.append(seg.style)
            seg.depth = order.index(seg.style)
        if seg.style not in ("header", "preamble", "keyword"):
            numbered_depth = seg.depth
        for j in range(i - 1, -1, -1):
            if segments[j].depth < seg.depth:
                seg.parent = j
                segments[j].children.append(i)
                break


def _descendants(segments: list[Segment], i: int) -> list[int]:
    out = []
    for c in segments[i].children:
        out.append(c)
        out.extend(_descendants(segments, c))
    return out


def _ancestors(segments: list[Segment], i: int) -> list[int]:
    out = []
    p = segments[i].parent
    while p is not None:
        out.append(p)
        p = segments[p].parent
    return out


def convenes(text: str) -> bool:
    """The text is about convening a closed session, not reconvening or acting after one."""
    return bool(_CONVENE_VERB.search(text)) or (bool(_CLOSED.search(text)) and not _NOT_CONVENE.search(text))


def cites(text: str) -> bool:
    c = citations.parse(text)
    return bool(c.exemptions) or any(o.startswith("19.86") for o in c.other_citations)


def notices_reconvene(text: str) -> bool:
    """The agenda states the intent to reconvene in open session. Only the agenda's own
    pages count: a packet's bound-in earlier agendas and minutes don't."""
    return bool(_RECONVENE.search("\n".join(" ".join(page) for page in agenda_pages(text))))


@dataclass(frozen=True)
class Found:
    item_text: str
    page: int
    no_citation: bool
    subject_from: str | None = None     # another item that names this one's subject (s. 19.86 footnotes)


# A heading row carrying an asterisked footnote: "ADJOURNMENT* * The Parties may
# continue negotiations in closed session pursuant to ss. 19.86 ..." (Wausau SD).
_FOOTNOTE = re.compile(r"^[A-Z][A-Z ]{2,40}\*\s*\*\s*(?P<note>\S.*)$")


def _cited(segments: list[Segment], i: int, picked: list[int]) -> Found:
    """A cited closed-session item. A footnote is the item, not the heading it hangs from;
    a s. 19.86 footnote takes its subject from the item that cites s. 19.86 and names the talks."""
    text = segments[i].text
    footnote = _FOOTNOTE.match(text)
    if footnote and _CLOSED.search(footnote["note"]):
        text = footnote["note"]
    subject_from = None
    c = citations.parse(text)
    if not c.exemptions and any(o.startswith("19.86") for o in c.other_citations):
        earlier = [segments[j].text for j in range(i) if j not in picked
                   and any(o.startswith("19.86") for o in citations.parse(segments[j].text).other_citations)]
        subject_from = earlier[-1] if earlier else None
    return Found(text, segments[i].page, False, subject_from)


def closed_items(text: str) -> list[Found]:
    """The notice's closed-session items.

    A notice with any cited closed-session item yields only those: its uncited
    mentions ("ANNOUNCEMENT OF CLOSED SESSION", "Closed Session Information
    (Board Only)") belong to the same session. A notice whose closed-session
    sections cite nothing yields ONE no_citation item: their wording, " / "-joined.
    """
    segments = segment(text)
    picked = [i for i, seg in enumerate(segments)
              if cites(seg.text) and (convenes(seg.text)
                                      or any(convenes(segments[a].text) for a in _ancestors(segments, i)))]
    if picked:
        return [_cited(segments, i, picked) for i in picked]
    uncited: list[tuple[int, str]] = []
    taken: set[int] = set()
    for i, seg in enumerate(segments):
        if i not in taken and convenes(seg.text):
            under = _descendants(segments, i)
            uncited.append((seg.page, " ".join([seg.text] + [segments[d].text for d in under])))
            taken.update(under)
    if not uncited:
        return []
    return [Found(" / ".join(t for _, t in uncited), uncited[0][0], True)]


# --- item records -----------------------------------------------------------

def normalize(item_text: str) -> str:
    return re.sub(r"\s+", " ", item_text).strip().casefold()


def item_id(meeting_id: str, item_text: str) -> str:
    return f"{meeting_id}:{hashlib.sha256(normalize(item_text).encode('utf-8')).hexdigest()[:12]}"


def triage(no_citation: bool, cites_subsection_1: bool | None, purpose: str | None,
           text_source: str, exemptions: list[str]) -> str:
    if no_citation or not cites_subsection_1 or text_source == "ocr":
        return "check"
    if not purpose or len(purpose.split()) < 4:
        return "check"
    if not exemptions or any(not TRIAGE_TERMS.get(letter) for letter in exemptions):
        return "check"          # 19.86-only items, and letters with no terms (ee, eg, em)
    lowered = purpose.lower()
    terms = [t.lower() for letter in exemptions for t in TRIAGE_TERMS[letter]]
    return "ok" if any(t in lowered for t in terms) else "check"


def item_record(meeting: dict, found: Found, text_source: str) -> dict:
    """One closed_sessions.json row. `meeting` is the meetings.json row."""
    c = citations.parse(found.item_text)
    # None only when the item cites no statute at all; a wrong statute ("19.81(1)(c)") still names a subject.
    purpose = purpose_text(found.subject_from or found.item_text)
    return {
        "id": item_id(meeting["id"], found.item_text),
        "meeting_id": meeting["id"],
        "bodies": meeting["bodies"],
        "meeting_date": meeting["meeting_date"],
        "item_text": found.item_text,
        "citation_raw": c.citation_raw,
        "exemptions": c.exemptions,
        "cites_subsection_1": c.cites_subsection_1,
        "other_citations": c.other_citations,
        "no_citation": found.no_citation,
        "text_source": text_source,
        "purpose_text": purpose,
        "triage": triage(found.no_citation, c.cites_subsection_1, purpose, text_source, c.exemptions),
        "minutes": None,
    }
