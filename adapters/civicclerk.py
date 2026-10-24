"""CivicClerk (Wausau): meetings from the public API, agendas and minutes as PDFs.

Listing: GET {api}/Events filtered on startDateTime, following @odata.nextLink
(15 events a page). Each event's `publishedFiles` names its files by `type`:

  "Agenda"         the notice (1-3 pages, "OFFICIAL NOTICE & AGENDA")
  "Agenda Packet"  the agenda plus every attachment; the notice only for an
                   event that posts no "Agenda" (three 2024 events do)
  "Minutes"        the minutes
  "Notice"         a "Notice of Possible Quorum" of some other body; never this
                   event's notice, so it is ignored

Any other type raises, so a new kind of file is looked at before it is skipped.

startDateTime carries a "Z" but is Central wall-clock time: Board of Public
Works events read "10:30:00Z" and their agendas say 10:30 AM. It is used as is.

Files download from {api}/Meetings/GetMeetingFileStream(fileId=N,plainText=false);
that is the URL the portal's own "Agenda (PDF)" link points to. plainText=true
returns empty text for files that have a text layer, so it is never used. The
endpoint answers HEAD with 405, so there is no cheap Unchanged check.

notice_url and minutes_url are portal pages ({portal}/event/{id}/files/agenda/{fileId});
the portal uses the "agenda" path segment for every file type, minutes included.

CivicClerk has no canceled flag: a cancellation shows only in the title
("CANCELED - ..."), which bodies.match reads.
"""
from __future__ import annotations

import re
from datetime import date

import documents
import polite
from adapters.base import DocFile, Documents, KnownFile, Meeting

NOTICE = "Agenda"
PACKET = "Agenda Packet"
MINUTES = "Minutes"
IGNORED = {"Notice"}
KNOWN_TYPES = {NOTICE, PACKET, MINUTES} | IGNORED
# A packet used as the notice is read and archived to this many pages, as Weston's are.
PACKET_PAGES = 5

_START = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d):00Z")


def list_meetings(jurisdiction: str, config: dict, since: date) -> list[Meeting]:
    """Every event starting on or after `since`, upcoming ones included."""
    api = config["api"]
    return [_meeting(jurisdiction, api, e) for e in _events(api, since)]


def fetch_documents(meeting: Meeting, known: dict[str, KnownFile]) -> Documents:
    """Download the notice and minutes PDFs listed for the meeting."""
    src = meeting.source
    notice = None
    if src["notice_file_id"] is not None:
        pages = PACKET_PAGES if src["notice_type"] == PACKET else None
        notice = _doc_file("notice", src["api"], src["notice_file_id"], meeting.id, pages)
    minutes = None
    if src["minutes_file_id"] is not None:
        minutes = _doc_file("minutes", src["api"], src["minutes_file_id"], meeting.id, None)
    return Documents(notice=notice, minutes=minutes)


def _events(api: str, since: date) -> list[dict]:
    url = f"{api}/Events"
    params = {"$filter": f"startDateTime ge {since.isoformat()}T00:00:00Z",
              "$orderby": "startDateTime"}
    events: list[dict] = []
    while url:
        page = polite.get(url, params=params).json()
        events += page["value"]
        url = page.get("@odata.nextLink")
        params = None   # the next link carries the filter and a skip token
    return events


def _meeting(jurisdiction: str, api: str, event: dict) -> Meeting:
    files = _files_by_type(event)
    notice_type = NOTICE if NOTICE in files else PACKET if PACKET in files else None
    notice_id = files[notice_type]["fileId"] if notice_type else None
    minutes_id = files[MINUTES]["fileId"] if MINUTES in files else None
    portal = portal_base(api)
    return Meeting(
        jurisdiction=jurisdiction,
        meeting_id=str(event["id"]),
        title=event["eventName"],
        start=_start(event),
        notice_url=_portal_url(portal, event["id"], notice_id) if notice_id else "",
        minutes_url=_portal_url(portal, event["id"], minutes_id) if minutes_id else None,
        source={"api": api, "notice_type": notice_type,
                "notice_file_id": notice_id, "minutes_file_id": minutes_id},
    )


def _files_by_type(event: dict) -> dict[str, dict]:
    """The event's published files keyed by type; raises on an unknown or repeated type."""
    files: dict[str, dict] = {}
    for f in event["publishedFiles"]:
        kind = f["type"]
        if kind not in KNOWN_TYPES:
            raise ValueError(f"CivicClerk event {event['id']}: unknown file type {kind!r}")
        if kind in files:
            raise ValueError(f"CivicClerk event {event['id']}: more than one {kind!r} file")
        files[kind] = f
    return files


def _start(event: dict) -> str:
    m = _START.fullmatch(event["startDateTime"])
    if not m:
        raise ValueError(f"CivicClerk event {event['id']}: unexpected startDateTime "
                         f"{event['startDateTime']!r}")
    return m.group(1)


def portal_base(api: str) -> str:
    """https://wausauwi.api.civicclerk.com/v1 -> https://wausauwi.portal.civicclerk.com"""
    m = re.fullmatch(r"https://([a-z0-9-]+)\.api\.civicclerk\.com/v1", api)
    if not m:
        raise ValueError(f"not a CivicClerk API base: {api!r}")
    return f"https://{m.group(1)}.portal.civicclerk.com"


def _portal_url(portal: str, event_id: int, file_id: int) -> str:
    return f"{portal}/event/{event_id}/files/agenda/{file_id}"


def file_url(api: str, file_id: int) -> str:
    return f"{api}/Meetings/GetMeetingFileStream(fileId={file_id},plainText=false)"


def _doc_file(kind: str, api: str, file_id: int, meeting_id: str,
              max_pages: int | None) -> DocFile:
    url = file_url(api, file_id)
    response = polite.get(url)
    full = response.content
    if not full.startswith(b"%PDF"):
        raise ValueError(f"{meeting_id} {kind}: {url} did not return a PDF")
    text = documents.pdf_text(full, f"{meeting_id} {kind} ({url})", max_pages)
    archived = documents.first_pages(full, max_pages) if max_pages else full
    return DocFile(
        kind=kind,
        url=url,
        content=archived,
        extension="pdf",
        sha256=documents.sha256(full),
        text=text.text,
        text_source=text.text_source,
        size=len(full),
        pages=text.pages,
        ocr_pages=text.ocr_pages,
        last_modified=response.headers.get("Last-Modified"),
    )
