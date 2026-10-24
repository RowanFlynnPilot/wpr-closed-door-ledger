"""The interface every platform adapter implements.

An adapter module exposes:

    list_meetings(jurisdiction: str, config: dict, since: date) -> list[Meeting]
        Every meeting the platform lists for that jurisdiction starting on or
        after `since`, including upcoming ones. `config` is the jurisdiction's
        block from bodies.yaml. Any HTTP error raises (polite.py does this).

    fetch_documents(meeting: Meeting, known: dict[str, KnownFile]) -> Documents
        The meeting's current notice (agenda) and minutes. `known` holds the
        latest archived version of each kind ("notice", "minutes"); an adapter
        may answer Unchanged when a HEAD request shows the file has not changed,
        instead of downloading it again.

An adapter whose platform lists earlier versions of an agenda (AgendaCenter)
also exposes:

    fetch_previous_versions(meeting: Meeting, known_urls: set[str]) -> list[tuple[int, DocFile]]
        Each earlier version not in `known_urls`, with the platform's archive id,
        which orders the versions. fetch.py calls it once per listing stamp.

All HTTP goes through polite.py. Text comes from documents.py (PDF text
layer, OCR for scans). No adapter decides what counts as a closed session;
that is extract.py's job.

Text conventions, so extract.py can segment by agenda item:
  - PDF text is pdfplumber's, pages joined with "\\f" (documents.pdf_text).
  - HTML text puts each agenda item (a BoardBook table row, a Municode list
    item) on exactly ONE line, starting with its numbering label as shown
    ("IV.", "A.", "7.", "a)"), with internal whitespace collapsed and HTML
    entities unescaped. Nested items are separate lines.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


@dataclass(frozen=True)
class Meeting:
    jurisdiction: str           # bodies.yaml key: wausau, wausau_sd, dc_everest, weston, kronenwetter
    meeting_id: str             # platform id, unique within the jurisdiction
    title: str                  # as listed (bodies.match normalizes it)
    start: str                  # local (Central) ISO start: "2026-09-01T17:15", or "2026-09-01" if no time is listed
    notice_url: str             # public URL a reader can open for the agenda ("" if none posted yet)
    minutes_url: str | None     # public URL for the minutes, when listed
    canceled: bool = False      # the platform's own canceled flag
    category_id: int | None = None   # AgendaCenter category; None elsewhere
    source: dict = field(default_factory=dict)  # JSON-serializable values fetch_documents needs

    @property
    def id(self) -> str:
        return f"{self.jurisdiction}:{self.meeting_id}"

    @property
    def meeting_date(self) -> str:
        return self.start[:10]


@dataclass(frozen=True)
class DocFile:
    kind: str                   # "notice" or "minutes"
    url: str                    # public URL of the file as downloaded
    content: bytes              # bytes to archive (Weston notices: the first 5 pages only)
    extension: str              # "pdf" or "html"
    sha256: str                 # of the full file as served (Weston: the whole packet)
    text: str                   # see "Text conventions" above
    text_source: str            # "text_layer", "html" or "ocr"
    size: int                   # bytes of the full file as served
    pages: int | None = None    # pages in the full file (PDF)
    ocr_pages: list[int] = field(default_factory=list)   # 1-based pages read by OCR
    last_modified: str | None = None                     # HTTP Last-Modified, if sent


@dataclass(frozen=True)
class Unchanged:
    """A HEAD request showed the file matches the latest archived version."""
    kind: str
    sha256: str


@dataclass(frozen=True)
class Documents:
    notice: DocFile | Unchanged | None      # None: no agenda posted
    minutes: DocFile | Unchanged | None     # None: no minutes posted


class KnownFile(TypedDict):
    url: str
    sha256: str
    size: int
    last_modified: str | None
