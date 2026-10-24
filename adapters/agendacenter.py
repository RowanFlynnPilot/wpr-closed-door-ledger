"""CivicPlus AgendaCenter (Weston): meetings from the category listings, packets and minutes as PDFs.

The /AgendaCenter page lists every category (a `div.listing` with id "cat<N>")
and the years each one offers (`changeYear(<year>, <N>, ...)` links). Each
category-year listing comes from POST /AgendaCenter/UpdateCategoryList with
`year` and `catID`; every row (`tr.catAgendaRow`) is one meeting:

  - h3 anchor name "_MMDDYYYY-<id>": the meeting date and the AgendaCenter id.
    No start time is listed, so `start` is the date alone.
  - h3 text "Posted <stamp>" or "Amended <stamp>": when the current file went up.
  - the agenda link in the row's <p>: the title, and /AgendaCenter/ViewFile/Agenda/_MMDDYYYY-<id>
  - td.minutes link, when minutes are posted: /AgendaCenter/ViewFile/Minutes/_MMDDYYYY-<id>
  - a.previous link, when earlier versions exist: /AgendaCenter/PreviousVersions/_MMDDYYYY-<id>

Every category is listed, including ones bodies.yaml does not name, so a new
category fails bodies.match instead of being missed. The platform has no
canceled flag; clerks write it into the title ("**CANCELED**", "[CANCELLED]",
"Notice of Meeting Cancellation").

The file served as the Agenda is the whole meeting packet (up to hundreds of
pages). Its text is read from the first NOTICE_PAGES pages and only those pages
are archived; sha256, size and pages describe the full file. AgendaCenter sends
no Last-Modified header, so a notice's `last_modified` is the listing's
Posted/Amended stamp, and a packet is re-downloaded only when that stamp or the
HEAD Content-Length differs from the archived version.

Earlier versions of an agenda are listed on its PreviousVersions page
(fetch_previous_versions). They carry no date; the listing's stamp dates the
current version, and every earlier version predates it.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

import documents
import polite
from adapters.base import DocFile, Documents, KnownFile, Meeting, Unchanged

NOTICE_PAGES = 5
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_YEAR_LINK = re.compile(r"changeYear\((\d{4}),\s*(\d+)\s*,")
_ROW_ANCHOR = re.compile(r"_(\d{2})(\d{2})(\d{4})-(\d+)")
_STAMP = re.compile(r"\b(Posted|Amended)\s+([A-Z][a-z]{2}) (\d{1,2}), (\d{4}) (\d{1,2}):(\d{2}) ([AP]M)\b")
_CANCELED = re.compile(r"\bcancel+(?:ed|ation)\b", re.I)


def list_meetings(jurisdiction: str, config: dict, since: date) -> list[Meeting]:
    base = config["base"]
    meetings: list[Meeting] = []
    for category_id, years in categories(polite.get(f"{base}/AgendaCenter").text).items():
        for year in years:
            if year >= since.year:
                html = category_listing(base, category_id, year)
                meetings += [m for m in parse_listing(html, jurisdiction, base, category_id, year)
                             if m.meeting_date >= since.isoformat()]
    return meetings


def categories(page: str) -> dict[int, list[int]]:
    """Category id -> the years its listing offers, from the /AgendaCenter page."""
    found: dict[int, list[int]] = {}
    for div in BeautifulSoup(page, "html.parser").select('div.listing[id^="cat"]'):
        category_id = int(div["id"].removeprefix("cat"))
        years = set()
        for link in div.select('a[href^="javascript:changeYear("]'):
            year, linked_category = _YEAR_LINK.match(link["href"].removeprefix("javascript:")).groups()
            if int(linked_category) != category_id:
                raise ValueError(f"AgendaCenter category {category_id} links a year of category {linked_category}")
            years.add(int(year))
        found[category_id] = sorted(years)
    if not found:
        raise ValueError("AgendaCenter page lists no categories")
    return found


def category_listing(base: str, category_id: int, year: int) -> str:
    return polite.post(f"{base}/AgendaCenter/UpdateCategoryList",
                       data={"year": year, "catID": category_id}).text


def parse_listing(html: str, jurisdiction: str, base: str, category_id: int, year: int) -> list[Meeting]:
    """Meetings in one category-year listing. A year the page offers must list at least one meeting."""
    soup = BeautifulSoup(html, "html.parser")
    current = soup.select_one(f"span#section{category_id} li.current")
    if current is None or current.get_text(strip=True) != str(year):
        raise ValueError(f"AgendaCenter listing for category {category_id} is not the {year} listing")
    rows = soup.select("tr.catAgendaRow")
    if not rows:
        raise ValueError(f"AgendaCenter category {category_id} offers {year} but lists no meetings")
    return [parse_row(row, jurisdiction, base, category_id) for row in rows]


def parse_row(row: Tag, jurisdiction: str, base: str, category_id: int) -> Meeting:
    heading = row.find("h3")
    month, day, year, meeting_id = _ROW_ANCHOR.fullmatch(heading.find("a", attrs={"name": True})["name"]).groups()
    agenda = row.find("p").find("a", href=True)
    title = " ".join(agenda.get_text().split())
    minutes = row.select_one("td.minutes a[href]")
    previous = row.select_one("a.previous[href]")
    stamp_kind, stamp = listing_stamp(heading.get_text(" "))
    return Meeting(
        jurisdiction=jurisdiction,
        meeting_id=meeting_id,
        title=title,
        start=f"{year}-{month}-{day}",
        notice_url=base + agenda["href"],
        minutes_url=base + minutes["href"] if minutes else None,
        canceled=bool(_CANCELED.search(title)),
        category_id=category_id,
        source={
            "listed": stamp_kind,                 # "Posted" or "Amended"
            "listed_at": stamp,                   # local ISO time of that stamp
            "previous_versions_url": base + previous["href"] if previous else None,
        },
    )


def listing_stamp(heading: str) -> tuple[str, str]:
    """("Posted"|"Amended", local ISO minute) from a row heading's "Posted Oct 15, 2026 1:11 PM"."""
    found = _STAMP.search(" ".join(heading.split()))
    if found is None:
        raise ValueError(f"AgendaCenter row has no Posted/Amended stamp: {heading!r}")
    kind, month, day, year, hour, minute, half = found.groups()
    stamp = datetime.strptime(f"{month} {day} {year} {hour}:{minute} {half}", "%b %d %Y %I:%M %p")
    return kind, stamp.strftime("%Y-%m-%dT%H:%M")


def fetch_documents(meeting: Meeting, known: dict[str, KnownFile]) -> Documents:
    return Documents(
        notice=fetch_notice(meeting, known.get("notice")),
        minutes=fetch_minutes(meeting.minutes_url) if meeting.minutes_url else None,
    )


def fetch_notice(meeting: Meeting, known: KnownFile | None) -> DocFile | Unchanged:
    """The packet's first NOTICE_PAGES pages and their text; Unchanged if HEAD and the listing match the archive."""
    url = meeting.notice_url
    stamp = meeting.source["listed_at"]
    if known is not None and packet_unchanged(url, stamp, known):
        return Unchanged("notice", known["sha256"])
    content = pdf_content(polite.get(url))
    text = documents.pdf_text(content, url, max_pages=NOTICE_PAGES)
    return DocFile(
        kind="notice", url=url, content=documents.first_pages(content, NOTICE_PAGES), extension="pdf",
        sha256=documents.sha256(content), text=text.text, text_source=text.text_source,
        size=len(content), pages=text.pages, ocr_pages=text.ocr_pages, last_modified=stamp,
    )


_ARCHIVED = re.compile(r"/AgendaCenter/ViewFile/ArchivedAgenda/_\d{8}-(\d+)$")


def archived_versions(html: str, base: str) -> list[tuple[int, str]]:
    """(archive id, URL) of each earlier version on a PreviousVersions page, oldest first.

    The page dates none of them: every row repeats the meeting's Posted stamp. Archive
    ids rise as versions are archived, so they order the versions."""
    found = {}
    for link in BeautifulSoup(html, "html.parser").find_all("a", href=_ARCHIVED):
        found[int(_ARCHIVED.search(link["href"]).group(1))] = base + link["href"]
    return sorted(found.items())


def fetch_previous_versions(meeting: Meeting, known_urls: set[str]) -> list[tuple[int, DocFile]]:
    """The meeting's earlier agenda versions not yet archived, as (archive id, DocFile),
    each read like a notice: the packet's first pages, with the full file's sha256."""
    page = meeting.source.get("previous_versions_url")
    if not page:
        return []
    base = re.match(r"https?://[^/]+", page).group(0)
    found = []
    for archive_id, url in archived_versions(polite.get(page).text, base):
        if url in known_urls:
            continue
        content = pdf_content(polite.get(url))
        text = documents.pdf_text(content, url, max_pages=NOTICE_PAGES)
        found.append((archive_id, DocFile(
            kind="notice", url=url, content=documents.first_pages(content, NOTICE_PAGES), extension="pdf",
            sha256=documents.sha256(content), text=text.text, text_source=text.text_source,
            size=len(content), pages=text.pages, ocr_pages=text.ocr_pages, last_modified=None,
        )))
    return found


def packet_unchanged(url: str, stamp: str, known: KnownFile) -> bool:
    if known["url"] != url or known["last_modified"] != stamp:
        return False
    head = polite.head(url)
    pdf_content_type(head)
    return int(head.headers["Content-Length"]) == known["size"]


def fetch_minutes(url: str) -> DocFile:
    """Minutes are small and get revised, so they are always downloaded; sha256 tells versions apart.

    Weston posts most minutes as PDF and a few as Word files (June 8, 2026)."""
    response = polite.get(url)
    content = response.content
    if response.headers.get("Content-Type", "").startswith(DOCX):
        return DocFile(
            kind="minutes", url=url, content=content, extension="docx",
            sha256=documents.sha256(content), text=documents.docx_text(content, url), text_source="text_layer",
            size=len(content), last_modified=response.headers.get("Last-Modified"),
        )
    pdf_content_type(response)
    text = documents.pdf_text(content, url)
    return DocFile(
        kind="minutes", url=url, content=content, extension="pdf",
        sha256=documents.sha256(content), text=text.text, text_source=text.text_source,
        size=len(content), pages=text.pages, ocr_pages=text.ocr_pages,
        last_modified=response.headers.get("Last-Modified"),
    )


def pdf_content(response) -> bytes:
    pdf_content_type(response)
    return response.content


def pdf_content_type(response) -> None:
    content_type = response.headers.get("Content-Type", "")
    if not content_type.startswith("application/pdf"):
        raise ValueError(f"{response.url} is {content_type!r}, not a PDF")
