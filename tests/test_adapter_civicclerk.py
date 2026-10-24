"""Offline tests for adapters/civicclerk.py (Wausau).

Fixtures in tests/fixtures/adapters/civicclerk/, pulled Oct 23, 2026:
  events_page1.json, events_page2.json  real /Events pages, trimmed to six events
                                        and the fields the adapter reads
  agenda_500.pdf                        the Feb 11, 2025 Board of Public Works agenda
No minutes content is stored; minutes downloads are served the agenda's bytes.
"""
import io
import json
import sys
from datetime import date
from pathlib import Path

import pypdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import documents  # noqa: E402
import polite  # noqa: E402
from adapters import civicclerk  # noqa: E402
from adapters.base import Documents, Meeting  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "adapters" / "civicclerk"
API = "https://wausauwi.api.civicclerk.com/v1"
PORTAL = "https://wausauwi.portal.civicclerk.com"
CONFIG = {"api": API, "platform": "civicclerk"}
AGENDA = (FIX / "agenda_500.pdf").read_bytes()


class FakeResponse:
    def __init__(self, body=None, content=b"", headers=None):
        self._body = body
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._body


def _page(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture
def listing(monkeypatch):
    """Serve the two fixture pages; record every call."""
    calls = []
    page1 = _page("events_page1.json")

    def fake_get(url, params=None):
        calls.append((url, params))
        return FakeResponse(page1 if url == f"{API}/Events" else _page("events_page2.json"))

    monkeypatch.setattr(polite, "get", fake_get)
    return calls


@pytest.fixture
def files(monkeypatch):
    """Serve a PDF for any file stream URL; record every URL."""
    calls = []
    served = {"content": AGENDA}

    def fake_get(url, params=None):
        calls.append(url)
        return FakeResponse(content=served["content"])

    monkeypatch.setattr(polite, "get", fake_get)
    return calls, served


def _by_id(meetings):
    return {m.meeting_id: m for m in meetings}


def test_list_meetings_follows_next_link_with_since_filter(listing):
    meetings = civicclerk.list_meetings("wausau", CONFIG, date(2024, 1, 1))
    assert [m.meeting_id for m in meetings] == ["1463", "726", "4", "2242", "3585", "2460"]
    assert listing[0] == (f"{API}/Events", {"$filter": "startDateTime ge 2024-01-01T00:00:00Z",
                                            "$orderby": "startDateTime"})
    # the next link already carries the filter and skip token
    assert listing[1][0].startswith(f"{API}/Events?$filter=") and listing[1][1] is None
    assert len(listing) == 2


def test_meeting_fields(listing):
    m = _by_id(civicclerk.list_meetings("wausau", CONFIG, date(2024, 1, 1)))["726"]
    assert m.id == "wausau:726"
    assert m.title == "Board Of Public Works Regular Meeting"
    assert m.start == "2025-02-11T10:30"          # the "Z" is Central wall-clock time
    assert m.meeting_date == "2025-02-11"
    assert m.notice_url == f"{PORTAL}/event/726/files/agenda/500"
    assert m.minutes_url == f"{PORTAL}/event/726/files/agenda/501"
    assert m.canceled is False and m.category_id is None
    assert m.source == {"api": API, "notice_type": "Agenda",
                        "notice_file_id": 500, "minutes_file_id": 501}
    json.dumps(m.source)


def test_notice_choice(listing):
    ms = _by_id(civicclerk.list_meetings("wausau", CONFIG, date(2024, 1, 1)))
    # only a packet posted: the packet is the notice
    assert ms["1463"].source["notice_type"] == "Agenda Packet"
    assert ms["1463"].notice_url == f"{PORTAL}/event/1463/files/agenda/2171"
    # a "Notice of Possible Quorum" file is not the event's notice
    assert ms["4"].source["notice_file_id"] == 101
    # nothing posted, canceled or upcoming
    for mid in ("2242", "2460"):
        assert ms[mid].notice_url == "" and ms[mid].minutes_url is None
        assert ms[mid].source["notice_file_id"] is None and ms[mid].source["notice_type"] is None
    # CivicClerk has no canceled flag; the title carries it
    assert ms["3585"].title.startswith("CANCELED") and ms["3585"].canceled is False
    assert ms["3585"].minutes_url is None


def _event(**over):
    event = {"id": 9, "eventName": "Finance Committee Meeting", "startDateTime": "2026-01-06T17:15:00Z",
             "publishedFiles": [{"fileId": 1, "type": "Agenda"}]}
    event.update(over)
    return event


def test_unknown_or_repeated_file_type_raises():
    with pytest.raises(ValueError, match="unknown file type"):
        civicclerk._meeting("wausau", API, _event(publishedFiles=[{"fileId": 1, "type": "Amended Agenda"}]))
    with pytest.raises(ValueError, match="more than one"):
        civicclerk._meeting("wausau", API, _event(publishedFiles=[{"fileId": 1, "type": "Agenda"},
                                                                  {"fileId": 2, "type": "Agenda"}]))


def test_unexpected_start_raises():
    with pytest.raises(ValueError, match="startDateTime"):
        civicclerk._meeting("wausau", API, _event(startDateTime="2026-01-06T17:15:00-06:00"))


def test_portal_base():
    assert civicclerk.portal_base(API) == PORTAL
    with pytest.raises(ValueError):
        civicclerk.portal_base("https://example.com/v1")


def _meeting(notice_type="Agenda", notice=500, minutes=501):
    return Meeting("wausau", "726", "Board Of Public Works Regular Meeting", "2025-02-11T10:30",
                   f"{PORTAL}/event/726/files/agenda/{notice}", None,
                   source={"api": API, "notice_type": notice_type,
                           "notice_file_id": notice, "minutes_file_id": minutes})


def test_fetch_documents(files):
    calls, _ = files
    docs = civicclerk.fetch_documents(_meeting(), {})
    assert calls == [civicclerk.file_url(API, 500), civicclerk.file_url(API, 501)]
    assert all("plainText=false" in u for u in calls)
    n = docs.notice
    assert n.kind == "notice" and n.extension == "pdf"
    assert n.url == f"{API}/Meetings/GetMeetingFileStream(fileId=500,plainText=false)"
    assert n.content == AGENDA and n.size == len(AGENDA)
    assert n.sha256 == documents.sha256(AGENDA)
    assert n.text_source == "text_layer" and n.pages == 1 and n.ocr_pages == []
    assert "CLOSED SESSION pursuant to Section 19.85(d), Wis. Stats." in n.text
    assert docs.minutes.kind == "minutes"


def test_fetch_documents_nothing_posted(files):
    calls, _ = files
    assert civicclerk.fetch_documents(_meeting(notice=None, minutes=None), {}) == Documents(None, None)
    assert calls == []


def _seven_pages() -> bytes:
    page = pypdf.PdfReader(io.BytesIO(AGENDA)).pages[0]
    writer = pypdf.PdfWriter()
    for _ in range(7):
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_packet_notice_keeps_first_pages(files):
    _, served = files
    packet = _seven_pages()
    served["content"] = packet
    n = civicclerk.fetch_documents(_meeting(notice_type="Agenda Packet", minutes=None), {}).notice
    assert n.pages == 7 and n.size == len(packet) and n.sha256 == documents.sha256(packet)
    assert len(pypdf.PdfReader(io.BytesIO(n.content)).pages) == civicclerk.PACKET_PAGES
    assert n.text.count("\f") == civicclerk.PACKET_PAGES - 1


def test_non_pdf_raises(files):
    _, served = files
    served["content"] = b"<html>error</html>"
    with pytest.raises(ValueError, match="did not return a PDF"):
        civicclerk.fetch_documents(_meeting(minutes=None), {})
