"""Municode Meetings (Kronenwetter).

Listing: the hub's "Meetings Directory" table at /meetings3, filtered by date
(From = since, To = a year ahead, so upcoming meetings beyond the hub's default
30 days are included) and paged by following its "View Additional Meetings"
link until there is none. Each row is one meeting:

    Date      <span class="date-display-single" content="2026-10-26T18:00:00-05:00">
    Meeting   the title, as typed ("Revised Village Board Meeting")
    Agenda    MEET-Agenda-<guid>.pdf on the blob host, and the ADA HTML agenda
              meetings.municode.com/adaHtmlDocument/index?cc=KRNWTRWI&me=<guid>&ip=False
    Minutes   MEET-Minutes-<guid>.pdf on the blob host, once posted

The meeting id is that 32-hex guid (the `me=` parameter, also in every
MEET-*-<guid>.pdf file name on the row). A row with no files carries no guid
and is skipped: it has no notice to archive (15 of 296 rows since 2024, 12 of
them canceled), and it is listed once an agenda is posted. The hub has no
canceled flag of its own; a cancellation shows only in the title, which
bodies.match reads. Minutes revisions overwrite the same MEET-Minutes URL.

The notice is the ADA HTML agenda: its bytes are archived, and its text has
one line per header line, section header and agenda item, each starting with
its <num> label. Minutes are PDFs. The ADA page sends no Last-Modified, so
notices are always downloaded; minutes are HEAD-checked first.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

import documents
import polite
from adapters.base import DocFile, Documents, KnownFile, Meeting, Unchanged

HUB_PATH = "/meetings3"
UPCOMING_DAYS = 366
_GUID = re.compile(r"^[0-9a-f]{32}$")
_FILE_GUID = re.compile(r"MEET-(?:Agenda|Packet|Minutes)-([0-9a-f]{32})\.pdf$")
_START = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}):\d{2}[+-]\d{2}:\d{2}$")
_INVISIBLE = re.compile("[​‌‍﻿]")
_SPACE = re.compile(r"\s+")


# ---------------------------------------------------------------- listing

def list_meetings(jurisdiction: str, config: dict, since: date) -> list[Meeting]:
    base = config["base"]
    until = date.today() + timedelta(days=UPCOMING_DAYS)
    url: str | None = hub_url(base, since, until)
    meetings: list[Meeting] = []
    while url:
        soup = _soup(polite.get(url).content)
        meetings.extend(parse_rows(soup, jurisdiction, base, since, until))
        url = next_page_url(soup, base)
    return meetings


def hub_url(base: str, since: date, until: date) -> str:
    params = []
    for name, d in (("date_filter", since), ("date_filter_1", until)):
        params += [f"{name}%5Bvalue%5D%5Bmonth%5D={d.month}",
                   f"{name}%5Bvalue%5D%5Bday%5D={d.day}",
                   f"{name}%5Bvalue%5D%5Byear%5D={d.year}"]
    params.append("field_microsite_tid_selective=All")
    return f"{base}{HUB_PATH}?{'&'.join(params)}"


def next_page_url(soup: BeautifulSoup, base: str) -> str | None:
    link = soup.select_one("ul.pager a[href]")
    return urljoin(base, link["href"]) if link else None


def parse_rows(soup: BeautifulSoup, jurisdiction: str, base: str,
               since: date, until: date) -> list[Meeting]:
    table = soup.select_one("div.view-content table.views-table")
    if table is None:
        raise ValueError(f"{jurisdiction}: no meetings table on the hub page")
    meetings = []
    for row in table.select("tbody > tr"):
        meeting = parse_row(row, jurisdiction, base)
        if meeting is None:
            continue
        if not since.isoformat() <= meeting.meeting_date <= until.isoformat():
            raise ValueError(f"{jurisdiction}: hub ignored its date filter ({meeting.start} {meeting.title!r})")
        meetings.append(meeting)
    return meetings


def parse_row(row: Tag, jurisdiction: str, base: str) -> Meeting | None:
    """The row's meeting, or None for a row with no files (it carries no meeting guid)."""
    title = _clean(_cell(row, "Meeting").get_text(" "))
    guid = row_guid(row, title)
    if guid is None:
        return None
    agenda_pdf = _link(_cell(row, "Agenda"), "PDF Agenda for ")
    agenda_html = _link(_cell(row, "Agenda"), "HTML Agenda for ")
    minutes = _link(_cell(row, "Minutes"), "PDF Minutes for ")
    details = _link(_cell(row, "View"), "")
    return Meeting(
        jurisdiction=jurisdiction,
        meeting_id=guid,
        title=title,
        start=parse_start(_cell(row, "Date")),
        notice_url=agenda_html or "",
        minutes_url=minutes,
        source={
            "agenda_pdf_url": agenda_pdf,
            "details_url": urljoin(base, details) if details else None,
        },
    )


def row_guid(row: Tag, title: str) -> str | None:
    """The meeting guid, which every file link on the row must agree on; None with no files."""
    guids = set()
    for a in row.select("a[href]"):
        href = a["href"]
        if "adaHtmlDocument" in href:
            guids.add(parse_qs(urlsplit(href).query)["me"][0])
        found = _FILE_GUID.search(href)
        if found:
            guids.add(found.group(1))
    if not guids:
        return None
    if len(guids) != 1 or not _GUID.match(next(iter(guids))):
        raise ValueError(f"hub row {title!r}: expected one meeting guid, found {sorted(guids)}")
    return guids.pop()


def parse_start(cell: Tag) -> str:
    span = cell.select_one("span.date-display-single[content]")
    if span is None:
        raise ValueError(f"hub row has no date: {cell!s:.200}")
    found = _START.match(span["content"])
    if not found:
        raise ValueError(f"hub row date not understood: {span['content']!r}")
    return f"{found.group(1)}T{found.group(2)}"


def _cell(row: Tag, label: str) -> Tag:
    cell = row.select_one(f'td[data-th="{label}"]')
    if cell is None:
        raise ValueError(f"hub row has no {label!r} column")
    return cell


def _link(cell: Tag, title_prefix: str) -> str | None:
    """The cell's link whose title starts with title_prefix (the hub labels each file link)."""
    hits = [a["href"] for a in cell.select("a[href]") if a.get("title", "").startswith(title_prefix)]
    if len(hits) > 1:
        raise ValueError(f"hub cell has {len(hits)} links titled {title_prefix!r}")
    return hits[0] if hits else None


# ---------------------------------------------------------------- documents

def fetch_documents(meeting: Meeting, known: dict[str, KnownFile]) -> Documents:
    notice = fetch_notice(meeting.notice_url) if meeting.notice_url else None
    minutes = fetch_minutes(meeting.minutes_url, known.get("minutes")) if meeting.minutes_url else None
    return Documents(notice=notice, minutes=minutes)


def fetch_notice(url: str) -> DocFile:
    response = polite.get(url)
    content = response.content
    text = documents.require_text(agenda_text(content), url)
    return DocFile(
        kind="notice", url=url, content=content, extension="html",
        sha256=documents.sha256(content), text=text, text_source="html",
        size=len(content), last_modified=response.headers.get("Last-Modified"),
    )


def fetch_minutes(url: str, known: KnownFile | None) -> DocFile | Unchanged:
    if known is not None and known["url"] == url:
        head = polite.head(url).headers
        if int(head["Content-Length"]) == known["size"] and head.get("Last-Modified") == known["last_modified"]:
            return Unchanged(kind="minutes", sha256=known["sha256"])
    response = polite.get(url)
    content = response.content
    pdf = documents.pdf_text(content, url)
    return DocFile(
        kind="minutes", url=url, content=content, extension="pdf",
        sha256=documents.sha256(content), text=pdf.text, text_source=pdf.text_source,
        size=len(content), pages=pdf.pages, ocr_pages=pdf.ocr_pages,
        last_modified=response.headers.get("Last-Modified"),
    )


# ---------------------------------------------------------------- agenda text

def agenda_text(content: bytes) -> str:
    """One line per header line, section header and agenda item (see adapters/base.py)."""
    soup = _soup(content)
    agenda = soup.select_one("div.ap-agenda")
    if agenda is None:
        raise ValueError("ADA agenda has no div.ap-agenda")
    lines = [_clean(span.get_text("")) for span in soup.select("header span.header-content__h1")]
    for block in agenda.select("h2.section-header, li"):
        lines.append(_block_text(block))
    return "\n".join(line for line in lines if line)


def _block_text(block: Tag) -> str:
    """A section header or list item as one line: its label, then its own text (not nested items)."""
    block = _copy(block)
    for nested in block.find_all(["ol", "ul"]):
        nested.decompose()
    for br in block.find_all("br"):
        br.replace_with(" ")
    # Each span is one field (a title, a description line), so adjacent spans are
    # separate words: "<span>CLOSED SESSION</span><span>Consideration…</span>".
    for tag in block.find_all(["num", "span", "p", "div"]):
        tag.append(" ")
    return _clean(block.get_text(""))


def _copy(tag: Tag) -> Tag:
    return BeautifulSoup(str(tag), "html.parser").contents[0]


def _clean(text: str) -> str:
    return _SPACE.sub(" ", _INVISIBLE.sub("", text)).strip()


def _soup(content: bytes) -> BeautifulSoup:
    """Municode pages are UTF-8 (declared in a meta tag; the ADA host sends no charset header)."""
    return BeautifulSoup(content.decode("utf-8"), "html.parser")
