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
    r"|(?P<doubled>(?P<letter>[A-Z])(?P=letter))\."                   # Kronenwetter's letters run on past Z: "AA."
    r"|\((?P<paren>\d{1,2}|[a-z]|[ivx]{1,4})\)"                       # "(1)" "(a)"
    r"|(?P<bare>\d{1,2})(?=\s+[A-Z])"                                 # Wausau's "5 Closed Session."
    r"|(?P<bareroman>[IVX]{1,4})(?=\s+[A-Z])"                         # Wausau's "IV Closed Session."
    r"|(?P<ocr>\d{1,2}),(?=\s+[A-Z])"                                 # OCR reads "8." as "8,"
    # OCR misreads a number ("7." as "fe", "13." as "us.") before a motion line.
    r"|(?P<junk>(?!(?:of|to|a|an|by|in|on|or|and|the|for)\b)[a-z]{1,3}\.?)(?=\s+(?:Consideration\s+of\s+Motion|Motion\s+to)\b)"
    r")(?:\s+(?=\S)|(?<=\.)(?=[A-Z][a-z])|\s*$)"                      # "III.The Board"; a label alone on its line ("a.")
)
_CLOSED = re.compile(r"closed\s+session", re.I)
_ANNOUNCEMENT = re.compile(r"\bannouncement\s+of\s+(?:a\s+)?(?:possible\s+)?closed\s+session", re.I)
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
# A closed-session motion set on its own line, in any capitals, after a sentence ends
# ("4 Closed Session." then two paragraphs "Closed Session pursuant to ..."): its own item.
_MOTION_LINE = re.compile(r"closed\s+session\s+(?:pursuant|under)\b", re.I)
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
    if m.group("bareroman"):
        return "roman"
    if m.group("doubled"):
        return "upper"
    if m.group("bare") or m.group("ocr") or m.group("junk"):
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
            elif _KEYWORD_LINE.match(line) or (_MOTION_LINE.match(line) and segments
                                              and re.search(r"[.:]$", segments[-1].text)):
                segments.append(Segment("", line, page_no, "keyword"))
            elif _is_header(line) and not (segments and segments[-1].style == "header"
                                           and not segments[-1].text.rstrip().endswith((".", ":"))
                                           and len(segments[-1].text) < 60):
                segments.append(Segment("", line, page_no, "header"))
            elif segments:
                # A word or number broken at a hyphen ("Project ID 6999-" / "18-11") rejoins without a space.
                joiner = "" if re.search(r"\w-$", segments[-1].text) else " "
                segments[-1].text = (segments[-1].text + joiner + line).strip()
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


_QUORUM_HEADER = re.compile(r"\bmeeting(?:\s+of\s+the)?\s*:?\s*possible\s+quorum\b", re.I)


def quorum_notice(text: str) -> bool:
    """The agenda's own header says it is a possible-quorum notice ("Meeting of the: POSSIBLE
    QUORUM of the COMMON COUNCIL and/or ..."), whatever the listing title says."""
    first = agenda_pages(text)[0] if text else []
    return bool(_QUORUM_HEADER.search(" ".join(first[:15])))


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
    context: str | None = None          # the agenda item an unnumbered closed-session line sits under


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
    # An unnumbered "CLOSED SESSION pursuant to ..." line under a numbered item ("4. HEARING:
    # Appeal of Declaration of Chronic Nuisance Premises - 1013 N. Third Avenue") is that item's
    # closed session: when the line names nothing itself, the item above names the subject.
    context = None
    if segments[i].style == "keyword" and i > 0 and i - 1 not in picked:
        above = segments[i - 1]
        if above.style not in ("header", "preamble", "keyword") and not _CLOSED.search(above.text):
            context = above.text
    return Found(text, segments[i].page, False, subject_from, context)


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
    # An announcement ("ANNOUNCEMENT OF CLOSED SESSION", "Announcement of possible closed
    # session pursuant to ...") forecasts a session the agenda notices again where it is
    # held; it is counted only when nothing else is (Kronenwetter, Nov 14, 2024).
    held = [i for i in picked if not any(_ANNOUNCEMENT.search(segments[j].text)
                                         for j in [i] + _ancestors(segments, i))]
    picked = held or picked
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


# --- which bodies of a joint meeting an item belongs to -----------------------

_SECTION_FILLER = {"joint", "and", "the", "of", "agenda", "items", "item", "meeting", "session", "regular", "special"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("&", " and ")).strip().casefold()


def _name_forms(name: str) -> list[str]:
    """A body's name as headers write it: whole, without "Village "/"City of ", and without
    its trailing "Committee" ("JOINT FINANCE AND HUMAN RESOURCES COMMITTEE" names two)."""
    short = re.sub(r"^(?:village|city\s+of)\s+", "", name, flags=re.I)
    core = re.sub(r"\s+(?:committee|commission)$", "", short, flags=re.I)
    return [_norm(f) for f in dict.fromkeys([name, short, core])]


def _names_in(line: str, names: dict[str, str]) -> list[str]:
    """Body keys the line names."""
    low = _norm(line)
    return [key for key, name in names.items() if any(re.search(rf"\b{re.escape(f)}\b", low) for f in _name_forms(name))]


def _is_section_header(line: str, names: dict[str, str]) -> bool:
    keys = _names_in(line, names)
    if not keys or len(line) > 100 or re.search(r"adjourn", line, re.I):
        return False
    rest = _norm(line)
    for key in keys:
        for form in _name_forms(names[key]):
            rest = rest.replace(form, " ")
    return len([w for w in re.findall(r"[a-z0-9]+", rest) if w not in _SECTION_FILLER | {"committee", "committees"}]) <= 1


def _item_line(lines: list[str], item_text: str) -> int | None:
    """The line an item starts on, found by its whole text in the joined lines, spaces
    ignored (items often open with the same long statute wording)."""
    flat, starts = "", []
    for line in lines:
        starts.append(len(flat))
        flat += re.sub(r"\s+", "", line.casefold())
    pos = flat.find(re.sub(r"\s+", "", item_text.casefold()))
    if pos < 0:
        return None
    return max(i for i, s in enumerate(starts) if s <= pos)


def section_bodies(text: str, item_text: str, names: dict[str, str]) -> list[str]:
    """In a joint meeting's agenda, the bodies an item belongs to: those named by the
    section header it sits under ("Finance Committee" / "Joint Finance Committee and
    Economic Development Committee"), less any body adjourned before it ("Adjournment of
    Utility Committee"). All of the meeting's bodies when the agenda has no such structure."""
    lines = [line for page in agenda_pages(text) for line in page]
    at = _item_line(lines, item_text)
    first = next((i for i, line in enumerate(lines) if _LABEL.match(line)), None)
    if at is None or first is None:
        return list(names)
    section = list(names)
    for i in range(at - 1, first - 2, -1):     # the agenda's own lines, and the one just above its first item
        if i >= 0 and not _LABEL.match(lines[i]) and _is_section_header(lines[i], names):
            section = _names_in(lines[i], names)
            break
    adjourned = {key for line in lines[first:at] if re.search(r"adjourn", line, re.I) for key in _names_in(line, names)}
    kept = [key for key in section if key not in adjourned]
    return kept or list(names)


# --- item records -----------------------------------------------------------

def normalize(item_text: str) -> str:
    return re.sub(r"\s+", " ", item_text).strip().casefold()


def item_id(meeting_id: str, item_text: str) -> str:
    return f"{meeting_id}:{hashlib.sha256(normalize(item_text).encode('utf-8')).hexdigest()[:12]}"


# Each exemption's own wording. An item that uses one of these but doesn't cite its
# letter names a purpose with no exemption cited for it (a (c) item that goes on to
# "conferring with legal counsel ... with respect to litigation"), so it goes to review.
_LETTER_WORDING = {
    "a": r"quasi-judicial|a\s+case\s+which\s+was\s+the\s+subject",
    "b": r"dismissal,\s*demotion,\s*licensing",
    "c": r"employment,\s*promotion,\s*compensation",
    "d": r"crime\s+detection\s+or\s+prevention|probation,?\s+extended\s+supervision",
    "e": r"purchas\w*\s+of\s+public\s+propert|investing\s+of\s+public\s+funds|competitive\s+(?:or|and)\s+bargaining\s+reasons",
    "f": r"financial,\s*medical,\s*social|substantial\s+adverse\s+effect",
    "g": r"conferring\s+with\s+legal\s+counsel",
    "h": r"requests?\s+for\s+confidential\s+(?:written\s+)?advice",
}


def uncited_wording(item_text: str, exemptions: list[str]) -> list[str]:
    """Letters whose statute wording the item uses without citing them."""
    return [letter for letter, wording in _LETTER_WORDING.items()
            if letter not in exemptions and re.search(wording, item_text, re.I)]


def triage(no_citation: bool, cites_subsection_1: bool | None, purpose: str | None,
           text_source: str, exemptions: list[str], item_text: str = "") -> str:
    if no_citation or not cites_subsection_1 or text_source == "ocr":
        return "check"
    if exemptions and uncited_wording(item_text, exemptions):
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
    if purpose == "" and found.context:
        purpose = re.sub(r"\s+", " ", found.context).strip(" .;:")
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
        "triage": triage(found.no_citation, c.cites_subsection_1, purpose, text_source, c.exemptions, found.item_text),
        "minutes": None,
    }
