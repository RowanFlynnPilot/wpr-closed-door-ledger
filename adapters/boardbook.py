"""BoardBook (meetings.boardbook.org): Wausau School District and D.C. Everest.

Listing: /Public/Organization/{org} is one page holding every meeting the
organization has ever posted, newest first, each a `tr.row-for-board`. Its
first cell starts with the heading "September 16, 2026 at 6:30 PM - Regular
School Board Meeting" (or "October 28, 2026 Immediately following ... - Title"
when no clock time is given), wrapped in `span.meeting-is-cancelled` markers
when canceled. Its last cell links Agenda and, once posted, Minutes.

Notice: /Public/Agenda/{org}?meeting=N, an HTML page whose agenda is the table
in div#Tab-AgendaItem, one `tr.agenda-item-information` per item. The item's
own wording is its div.form-check, which starts with the numbering label
("XIV.A."), followed by its div.Description when it has one; presenters and
attachment lists are not text.

Minutes: /Public/Minutes/{org}?meeting=N is a viewer page; the PDF's id is in
the hidden input NewDocumentViewerDocumentID, and the PDF downloads from
/Documents/DownloadPDF/{id}?org={org}. BoardBook sends no Last-Modified, so
there is no HEAD shortcut: every call downloads both documents.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

import documents
import polite
from adapters.base import DocFile, Documents, KnownFile, Meeting

BASE = "https://meetings.boardbook.org"

_HEADING = re.compile(
    r"^(?P<date>[A-Z][a-z]+ \d{1,2}, \d{4})"
    r"(?: at (?P<time>\d{1,2}:\d{2} [AP]M))?"
    r"(?P<when>.*?) - (?P<title>.+)$"
)
# Every agenda page carries a per-request anti-forgery token. It is blanked
# before archiving so the same agenda always has the same sha256.
_TOKEN = re.compile(rb'(name="__RequestVerificationToken" type="hidden" value=")[^"]*(")')


class BoardBookPageError(Exception):
    pass


def listing_url(org: int) -> str:
    return f"{BASE}/Public/Organization/{org}"


def agenda_url(org: int, meeting_id: str) -> str:
    return f"{BASE}/Public/Agenda/{org}?meeting={meeting_id}"


def pdf_url(org: int, document_id: str) -> str:
    return f"{BASE}/Documents/DownloadPDF/{document_id}?org={org}"


def _collapse(text: str) -> str:
    return " ".join(text.split())


# ---- listing ----------------------------------------------------------------

def list_meetings(jurisdiction: str, config: dict, since: date) -> list[Meeting]:
    org = config["org"]
    html = polite.get(listing_url(org)).text
    meetings = [parse_row(jurisdiction, org, row) for row in listing_rows(html)]
    return [m for m in meetings if m.meeting_date >= since.isoformat()]


def listing_rows(html: str) -> list[Tag]:
    table = BeautifulSoup(html, "html.parser").find("table", id="PublicMeetingsTable")
    if table is None:
        raise BoardBookPageError("listing page has no PublicMeetingsTable")
    # Older meeting descriptions embed their own <tr>s; only board rows are meetings.
    return table.find_all("tr", class_="row-for-board")


def parse_row(jurisdiction: str, org: int, row: Tag) -> Meeting:
    meeting_cell, _location, links_cell = row.find_all("td", recursive=False)
    heading = meeting_cell.find("div")
    canceled = bool(heading.find_all("span", class_="meeting-is-cancelled"))
    start, title = parse_heading(heading_text(heading))
    links = {a.get_text(strip=True): urljoin(BASE, a["href"]) for a in links_cell.find_all("a")}
    meeting_id = _meeting_param(links["Agenda"])
    return Meeting(
        jurisdiction=jurisdiction,
        meeting_id=meeting_id,
        title=title,
        start=start,
        notice_url=agenda_url(org, meeting_id),
        minutes_url=links.get("Minutes"),
        canceled=canceled,
        source={"org": org},
    )


def heading_text(heading: Tag) -> str:
    """The heading without its "Cancelled" markers."""
    parts = [s for s in heading.find_all(string=True)
             if not s.find_parent("span", class_="meeting-is-cancelled")]
    return _collapse(" ".join(parts))


def parse_heading(text: str) -> tuple[str, str]:
    """("2026-09-16T18:30", "Regular School Board Meeting") from a listing heading."""
    m = _HEADING.match(text)
    if not m:
        raise BoardBookPageError(f"unrecognized meeting heading {text!r}")
    day = datetime.strptime(m["date"], "%B %d, %Y").date().isoformat()
    if m["time"] is None:
        return day, m["title"]
    clock = datetime.strptime(m["time"], "%I:%M %p").strftime("%H:%M")
    return f"{day}T{clock}", m["title"]


def _meeting_param(url: str) -> str:
    (meeting_id,) = parse_qs(urlsplit(url).query)["meeting"]
    return meeting_id


# ---- documents ----------------------------------------------------------------

def fetch_documents(meeting: Meeting, known: dict[str, KnownFile]) -> Documents:
    notice = fetch_notice(meeting) if meeting.notice_url else None
    minutes = fetch_minutes(meeting) if meeting.minutes_url else None
    return Documents(notice=notice, minutes=minutes)


def fetch_notice(meeting: Meeting) -> DocFile:
    response = polite.get(meeting.notice_url)
    content = stable_html(response.content)
    text = documents.require_text(agenda_text(response.text, meeting.notice_url), meeting.notice_url)
    return DocFile(
        kind="notice",
        url=meeting.notice_url,
        content=content,
        extension="html",
        sha256=documents.sha256(content),
        text=text,
        text_source="html",
        size=len(content),
        last_modified=response.headers.get("Last-Modified"),
    )


def stable_html(content: bytes) -> bytes:
    """The page as served, with the per-request anti-forgery token blanked."""
    return _TOKEN.sub(rb"\1\2", content)


def agenda_text(html: str, name: str) -> str:
    """One line per agenda item: its numbering label and wording, as shown."""
    pane = BeautifulSoup(html, "html.parser").find("div", id="Tab-AgendaItem")
    if pane is None:
        raise BoardBookPageError(f"{name}: no agenda table (not an agenda page)")
    lines = [item_line(row, name) for row in pane.find_all("tr", class_="agenda-item-information")]
    return "\n".join(line for line in lines if line)


def item_line(row: Tag, name: str) -> str:
    """An item's wording, then its description ("Description: ...") when it has one.

    BoardBook hides descriptions until a reader picks "Show Everything", but
    they are part of the posted agenda. Presenters and attachments are not.
    """
    wording = row.find("div", class_="form-check")
    if wording is None:
        raise BoardBookPageError(f"{name}: agenda row {row.get('data-agendaitemid')} has no wording")
    parts = [wording.get_text(" ")]
    description = row.find("div", class_="Description")
    if description is not None:
        parts.append(description.get_text(" "))
    return _collapse(" ".join(parts))


def fetch_minutes(meeting: Meeting) -> DocFile:
    org = meeting.source["org"]
    viewer = polite.get(meeting.minutes_url)
    url = pdf_url(org, minutes_document_id(viewer.text, meeting.minutes_url))
    response = polite.get(url)
    pdf = documents.pdf_text(response.content, url)
    return DocFile(
        kind="minutes",
        url=url,
        content=response.content,
        extension="pdf",
        sha256=documents.sha256(response.content),
        text=pdf.text,
        text_source=pdf.text_source,
        size=len(response.content),
        pages=pdf.pages,
        ocr_pages=pdf.ocr_pages,
        last_modified=response.headers.get("Last-Modified"),
    )


def minutes_document_id(html: str, name: str) -> str:
    """The minutes PDF's id from the viewer page. A meeting without minutes
    redirects to the organization page, which has no viewer input."""
    field = BeautifulSoup(html, "html.parser").find("input", id="NewDocumentViewerDocumentID")
    if field is None or not field.get("value", "").isdigit():
        raise BoardBookPageError(f"{name}: no NewDocumentViewerDocumentID (not a minutes viewer page)")
    return field["value"]
