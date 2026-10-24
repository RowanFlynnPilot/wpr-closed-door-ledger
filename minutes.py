"""What a meeting's minutes show about its closed session. Deterministic, no LLM.

The minutes are segmented like an agenda (extract.segment, without stopping
at Adjourn), so each motion sits with the agenda heading it was made under.

    held                  the minutes show the body convened in closed session
    motion_recorded       a motion to convene in closed session is recorded
    vote_record           how the minutes show the vote on that motion:
                          per_member | tally | unanimous | result_only | not_shown
    exemption_in_minutes  the closed-session item cites an s. 19.85(1) letter
    reconvened            the body reconvened in open session

Every value describes the document. None of them is a legal judgment: whether
a tally satisfies s. 19.85(1) is an editor's call. Nothing here copies text
out of the minutes, which name private people.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import citations
import extract

_MOTION = re.compile(
    r"\b(?:motion|motioned|moved|move)\b[^.;]{0,240}?"
    r"\b(?:(?:enter|convene|go|move|adjourn|recess)\w*\s+(?:\w+\s+){0,3}?)?(?:in|into|to)\s+(?:a\s+)?closed\s+session",
    re.I,
)                                   # "Motion by Lewitzke and seconded by Felch to Closed Session"
_CONVENED = re.compile(
    r"\bconvened\s+(?:in|into|to)\s+(?:a\s+)?closed\s+session|time\s+into\s+closed\s+session|"
    r"present\s+in\s+closed\s+session|adjourned\s+(?:directly\s+)?from\s+closed\s+session|"
    r"\b(?:entered|went|moved|adjourned)\s+(?:in|into|to)\s+closed\s+session\s+at\b|"
    r"\bentered\s+(?:in|into\s+)?(?:a\s+)?closed\s+session|"                 # "The committee entered closed session."
    r"\bthe\s+\w+\s+moved\s+(?:in|into|to)\s+closed\s+session|closed\s+session\s+convened\b",
    re.I,
)
_PASSED = re.compile(r"\b(?:passed|carried|approved|adopted)\b|\bmotion\s+(?:passes|carries)\b", re.I)
_PER_MEMBER = re.compile(      # "James Bouche – Yes", "Ben Bliven: Yea", "Jeff Micholic – Aye"
    r"[A-Z][\w.'’-]+(?:\s+[A-Z][\w.'’-]+){0,3}\s*[:–—-]\s*(?:[Yy]es|YES|[Aa]ye|AYE|[Yy]ea|YEA|[Nn]o|NO|[Nn]ay|NAY)\b")
# "Yes: Martens, Henke, ..." and "With a roll call vote, Xiong, Grabko, Dickerson, ... all yes"
_YES_LIST = re.compile(r"\b(?i:yes|ayes?|yeas?)\s*:\s*[A-Z][a-z]|"
                       r"(?i:roll\s*call\s+vote),?\s+(?:[A-Z][\w'’-]+,\s*){2,}[^.]{0,80}?\b(?i:all\s+(?:yes|ayes?|yeas?))\b")
_TALLY = re.compile(
    r"\b\d{1,2}\s*[-:–]\s*\d{1,2}\b(?!\s*(?:a\.?m|p\.?m))|\b(?:yes|ayes?|yeas?)\s*:?\s*\d{1,2}\b", re.I)
_UNANIMOUS = re.compile(r"\bunanimous(?:ly)?\b", re.I)
_RECONVENED = re.compile(
    r"\b(?:motion|motioned|moved)\b[^.;]{0,200}?\breconven\w*\s+(?:in|into|to)\s+(?:the\s+)?open\s+session|"
    r"\breconvened\s+(?:in|into|to)\s+(?:the\s+)?open\s+session|time\s+into\s+open\s+session|"
    r"\b(?:returned|came\s+back)\s+(?:in|into|to)\s+open\s+session|\bback\s+in(?:to)?\s+open\s+session",
    re.I,
)
_NOT_RECONVENED = re.compile(r"\bd(?:id|oes)\s+not\s+reconvene|\bno\s+reconven", re.I)
# How far after the motion its vote is looked for: up to the next motion. Motions
# often restate the statute's paraphrase first (D.C. Everest: 1,000+ characters).
_VOTE_WINDOW = 2500


@dataclass(frozen=True)
class MinutesFacts:
    held: bool
    motion_recorded: bool
    vote_record: str | None         # None when no motion is recorded
    exemption_in_minutes: bool
    reconvened: bool
    minutes_version: int
    convene_pages: tuple[int, ...]  # pages with a motion to convene (for the hand-check; no text)


def _vote_text(text: str, start: int) -> str:
    window = text[start:start + _VOTE_WINDOW]
    following = re.search(r"\bmotion(?:ed)?\s+by\b|\bmoved\s+to\b", window[20:], re.I)
    return window[: following.start() + 20] if following else window


def vote_record(vote: str) -> str:
    if len(_PER_MEMBER.findall(vote)) >= 2 or _YES_LIST.search(vote):
        return "per_member"
    if _TALLY.search(vote):
        return "tally"
    if _UNANIMOUS.search(vote):
        return "unanimous"
    if _PASSED.search(vote):
        return "result_only"
    return "not_shown"


def analyze(text: str, minutes_version: int) -> MinutesFacts:
    segments = extract.segment(text, stop_at_adjourn=False)
    motions: list[tuple[extract.Segment, re.Match]] = []
    for seg in segments:
        motions += [(seg, m) for m in _MOTION.finditer(seg.text)]
    held = bool(_CONVENED.search(text)) or any(
        _PASSED.search(_vote_text(seg.text, m.end())) for seg, m in motions)
    # The first motion whose vote the minutes show; a heading ("MOTION TO MOVE TO
    # CLOSED SESSION") or a request for a motion comes before the motion itself.
    shown = [r for r in (vote_record(_vote_text(seg.text, m.end())) for seg, m in motions) if r != "not_shown"]
    record = (shown[0] if shown else "not_shown") if motions else None
    exemption = any(citations.parse(seg.text).exemptions for seg, _ in motions) or any(
        seg.parent is not None and citations.parse(segments[seg.parent].text).exemptions
        for seg, _ in motions)
    reconvened = bool(_RECONVENED.search(text)) and not _NOT_RECONVENED.search(text)
    return MinutesFacts(held, bool(motions), record, exemption, reconvened, minutes_version,
                        tuple(sorted({seg.page for seg, _ in motions})))


def as_record(facts: MinutesFacts) -> dict:
    """The closed_sessions.json `minutes` value."""
    row = asdict(facts)
    del row["convene_pages"]
    return row
