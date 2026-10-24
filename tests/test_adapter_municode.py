"""Offline tests for adapters/municode.py (no network: polite.get and polite.head are monkeypatched).

Fixtures in tests/fixtures/adapters/municode/ are Kronenwetter pages pulled
Oct 23, 2026 and trimmed: two hub pages (the first with five rows of Sep–Oct
2026, one of them file-less, and its "View Additional Meetings" link; the last
with the Jan 8, 2024 row and an empty pager), and the ADA HTML agenda of the
May 11, 2026 Village Board meeting cut to its closed-session sections. No
minutes content is stored here.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import documents  # noqa: E402
import polite  # noqa: E402
from adapters import municode  # noqa: E402
from adapters.base import DocFile, KnownFile, Meeting, Unchanged  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "adapters" / "municode"
BASE = "https://kronenwetter-wi.municodemeetings.com"
CONFIG = {"base": BASE}
ADA = "https://meetings.municode.com/adaHtmlDocument/index?cc=KRNWTRWI&me={}&ip=False"
BLOB = "https://mccmeetings.blob.core.usgovcloudapi.net/krnwtrwi-pubu/MEET-{}-{}.pdf"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeResponse:
    def __init__(self, content: bytes = b"", headers: dict | None = None):
        self.content = content
        self.headers = headers or {}


@pytest.fixture
def served(monkeypatch):
    """Map URL -> FakeResponse for GET and HEAD; records each (method, URL) asked for."""
    gets: dict[str, FakeResponse] = {}
    heads: dict[str, FakeResponse] = {}
    asked: list[tuple[str, str]] = []

    def get(url, **kwargs):
        asked.append(("GET", url))
        return gets[url]

    def head(url, **kwargs):
        asked.append(("HEAD", url))
        return heads[url]

    monkeypatch.setattr(polite, "get", get)
    monkeypatch.setattr(polite, "head", head)
    return gets, heads, asked


def meeting(guid: str = "c19b4fca8707467fa4d6a2fa1e4a4407", minutes: bool = True) -> Meeting:
    return Meeting("kronenwetter", guid, "Village Board Meeting", "2026-05-11T18:00",
                   ADA.format(guid), BLOB.format("Minutes", guid) if minutes else None)


# ---- listing ----------------------------------------------------------------

def test_list_meetings_follows_the_pager_and_skips_file_less_rows(served):
    gets, _, asked = served
    since = date(2024, 1, 1)
    first = municode.hub_url(BASE, since, date.today() + timedelta(days=municode.UPCOMING_DAYS))
    second = (f"{BASE}/meetings3?page=1&date_filter%5Bvalue%5D%5Bmonth%5D=1&date_filter%5Bvalue%5D%5Bday%5D=1"
              "&date_filter%5Bvalue%5D%5Byear%5D=2024&date_filter_1%5Bvalue%5D%5Bmonth%5D=10"
              "&date_filter_1%5Bvalue%5D%5Bday%5D=24&date_filter_1%5Bvalue%5D%5Byear%5D=2027"
              "&field_microsite_tid_selective=All")
    gets[first] = FakeResponse(fixture("hub_page0.html"))
    gets[second] = FakeResponse(fixture("hub_page1.html"))

    meetings = municode.list_meetings("kronenwetter", CONFIG, since)

    assert asked == [("GET", first), ("GET", second)]
    # The Sep 10, 2026 5:30pm Village Board row has no files, so no guid: it is skipped.
    assert [(m.start, m.title) for m in meetings] == [
        ("2026-10-26T18:00", "Revised Village Board Meeting"),
        ("2026-09-28T18:00", "Village Board Meeting"),
        ("2026-09-28T17:00", "Police and Fire Commission Meeting"),
        ("2026-09-10T18:00", "Plan Commission Meeting"),
        ("2024-01-08T18:00", "REVISED Village Board Meeting"),
    ]


def test_row_fields():
    soup = municode._soup(fixture("hub_page1.html"))
    [m] = municode.parse_rows(soup, "kronenwetter", BASE, date(2024, 1, 1), date(2027, 12, 31))
    guid = "c16f24e3bdaa422c8037770b22f9ecd9"
    assert m == Meeting(
        jurisdiction="kronenwetter", meeting_id=guid, title="REVISED Village Board Meeting",
        start="2024-01-08T18:00", notice_url=ADA.format(guid), minutes_url=BLOB.format("Minutes", guid),
        canceled=False, category_id=None,
        source={"agenda_pdf_url": BLOB.format("Agenda", guid),
                "details_url": f"{BASE}/bc-vb/page/revised-village-board-meeting-0"},
    )
    assert m.id == f"kronenwetter:{guid}" and m.meeting_date == "2024-01-08"
    assert municode.next_page_url(soup, BASE) is None      # the last page's pager is empty


def test_row_without_minutes():
    soup = municode._soup(fixture("hub_page0.html"))
    meetings = municode.parse_rows(soup, "kronenwetter", BASE, date(2024, 1, 1), date(2027, 12, 31))
    assert meetings[0].meeting_id == "bc64bc1cee794958999a4d624864a28e"
    assert meetings[0].minutes_url is None


def test_hub_url_filters_from_since_to_until():
    assert municode.hub_url(BASE, date(2024, 1, 1), date(2027, 10, 24)) == (
        f"{BASE}/meetings3?date_filter%5Bvalue%5D%5Bmonth%5D=1&date_filter%5Bvalue%5D%5Bday%5D=1"
        "&date_filter%5Bvalue%5D%5Byear%5D=2024&date_filter_1%5Bvalue%5D%5Bmonth%5D=10"
        "&date_filter_1%5Bvalue%5D%5Bday%5D=24&date_filter_1%5Bvalue%5D%5Byear%5D=2027"
        "&field_microsite_tid_selective=All")


def test_a_row_outside_the_date_filter_raises():
    soup = municode._soup(fixture("hub_page1.html"))
    with pytest.raises(ValueError, match="ignored its date filter"):
        municode.parse_rows(soup, "kronenwetter", BASE, date(2025, 1, 1), date(2027, 12, 31))


def test_a_row_whose_links_disagree_on_the_guid_raises():
    html = fixture("hub_page1.html").decode("utf-8").replace(
        "MEET-Agenda-c16f24e3bdaa422c8037770b22f9ecd9", "MEET-Agenda-" + "0" * 32)
    soup = municode._soup(html.encode("utf-8"))
    with pytest.raises(ValueError, match="expected one meeting guid"):
        municode.parse_rows(soup, "kronenwetter", BASE, date(2024, 1, 1), date(2027, 12, 31))


def test_a_page_without_the_table_raises():
    with pytest.raises(ValueError, match="no meetings table"):
        municode.parse_rows(municode._soup(b"<html><body></body></html>"), "kronenwetter", BASE,
                            date(2024, 1, 1), date(2027, 12, 31))


# ---- agenda text ------------------------------------------------------------

def test_agenda_text_one_line_per_item_with_its_label():
    lines = municode.agenda_text(fixture("ada_agenda_closed_session.html")).split("\n")
    assert lines[:7] == [
        "Village Board Meeting",
        "Monday, May 11, 2026 06:00 PM",
        "Kronenwetter Municipal Center - 1582 Kronenwetter Drive Board Room (Lower Level)",
        "1. CALL MEETING TO ORDER",
        "A. Pledge of Allegiance",
        "B. Roll Call",
        "4. ANNOUNCEMENT OF CLOSED SESSION",
    ]
    # Adjacent spans (title, then description) are separate words, not "SESSIONConsideration".
    assert lines[8] == (
        "9. CLOSED SESSION Consideration of motion to convene into closed session pursuant to "
        "Wis. Stat. 19.85 (1)( c ) for consideration of employment, promotion, compensation or "
        "performance evaluation data of any public employee over which the governmental body has "
        "jurisdiction or exercises responsibility – to wit staff's annual evaluation and/or pay increases")
    assert lines[9:11] == ["10. RECONVENE OPEN SESSION Consideration of motion to reconvene into open session.",
                           "11. ACTION AFTER CLOSED SESSION"]
    assert lines[11].startswith("NOTE: Upon reasonable notice") and "Posted: 05/06/2026" in lines[11]
    assert len(lines) == 12


def test_agenda_text_unescapes_entities_and_drops_invisible_characters():
    text = municode.agenda_text(fixture("ada_agenda_closed_session.html"))
    public_comment = text.split("\n")[7]
    assert public_comment.startswith("5. PUBLIC COMMENT Please be advised per State Statute Section 19.84(2), "
                                     "information will be received from the public. It is the policy")
    assert "Officer’s discretion" in public_comment
    for bad in ("&nbsp;", "&amp;", "\xa0", "​", "  "):
        assert bad not in text


def test_nested_items_are_separate_lines():
    html = b"""<html><body><header><div class="header-content"><h1>
      <span class="header-content__h1 h1-line-one">Plan Commission Meeting</span></h1></div></header>
      <div class="ap-agenda"><section class="agenda-section">
      <h2 class="section-header"><div class="Section0"><p><num>3.</num><span>NEW BUSINESS</span></p></div></h2>
      <ol class="agenda-items"><li><div class="Section0"><p><num>A.</num><span>Rezoning</span><br><span>Parcel 12</span></p></div>
        <ol><li><div class="Section0"><p><num>a)</num><span>Public&nbsp;hearing &amp; action</span></p></div></li></ol>
      </li></ol></section></div></body></html>"""
    assert municode.agenda_text(html).split("\n") == [
        "Plan Commission Meeting", "3. NEW BUSINESS", "A. Rezoning Parcel 12", "a) Public hearing & action"]


def test_an_agenda_without_the_agenda_div_raises():
    with pytest.raises(ValueError, match="ap-agenda"):
        municode.agenda_text(b"<html><body><p>Service unavailable</p></body></html>")


# ---- documents ----------------------------------------------------------------

def test_fetch_documents_notice_is_the_ada_html(served):
    gets, _, _ = served
    m = meeting(minutes=False)
    gets[m.notice_url] = FakeResponse(fixture("ada_agenda_closed_session.html"))
    docs = municode.fetch_documents(m, {})
    notice = docs.notice
    assert isinstance(notice, DocFile) and docs.minutes is None
    content = fixture("ada_agenda_closed_session.html")
    assert (notice.kind, notice.url, notice.extension, notice.text_source) == ("notice", m.notice_url, "html", "html")
    assert notice.content == content and notice.size == len(content)
    assert notice.sha256 == documents.sha256(content)
    assert notice.text == municode.agenda_text(content)
    assert notice.pages is None and notice.last_modified is None


def test_an_empty_agenda_page_raises(served):
    gets, _, _ = served
    m = meeting(minutes=False)
    gets[m.notice_url] = FakeResponse(b'<html><body><div class="ap-agenda"></div></body></html>')
    with pytest.raises(documents.UnreadableDocument):
        municode.fetch_documents(m, {})


def test_no_agenda_and_no_minutes(served):
    _, _, asked = served
    m = Meeting("kronenwetter", "c19b4fca8707467fa4d6a2fa1e4a4407", "Village Board Meeting",
                "2026-05-11T18:00", "", None)
    assert municode.fetch_documents(m, {}).notice is None
    assert municode.fetch_documents(m, {}).minutes is None
    assert asked == []


def _stub_pdf_text(monkeypatch):
    calls = []

    def pdf_text(content, name, max_pages=None):
        calls.append(name)
        return documents.PdfText("minutes text", "text_layer", [], 2)

    monkeypatch.setattr(documents, "pdf_text", pdf_text)
    return calls


def test_minutes_are_downloaded_when_nothing_is_known(served, monkeypatch):
    gets, _, asked = served
    calls = _stub_pdf_text(monkeypatch)
    m = meeting()
    gets[m.notice_url] = FakeResponse(fixture("ada_agenda_closed_session.html"))
    gets[m.minutes_url] = FakeResponse(b"%PDF-1.7 stand-in", {"Last-Modified": "Tue, 27 Jan 2026 14:24:29 GMT"})
    minutes = municode.fetch_documents(m, {}).minutes
    assert asked == [("GET", m.notice_url), ("GET", m.minutes_url)]
    assert calls == [m.minutes_url]
    assert (minutes.kind, minutes.url, minutes.extension, minutes.text_source, minutes.pages) == (
        "minutes", m.minutes_url, "pdf", "text_layer", 2)
    assert minutes.sha256 == documents.sha256(b"%PDF-1.7 stand-in")
    assert minutes.last_modified == "Tue, 27 Jan 2026 14:24:29 GMT"


def test_minutes_unchanged_by_head(served, monkeypatch):
    gets, heads, asked = served
    _stub_pdf_text(monkeypatch)
    m = meeting()
    gets[m.notice_url] = FakeResponse(fixture("ada_agenda_closed_session.html"))
    heads[m.minutes_url] = FakeResponse(headers={"Content-Length": "4096",
                                                 "Last-Modified": "Tue, 27 Jan 2026 14:24:29 GMT"})
    known = {"minutes": KnownFile(url=m.minutes_url, sha256="ab" * 32, size=4096,
                                  last_modified="Tue, 27 Jan 2026 14:24:29 GMT")}
    assert municode.fetch_documents(m, known).minutes == Unchanged("minutes", "ab" * 32)
    assert ("GET", m.minutes_url) not in asked


def test_revised_minutes_at_the_same_url_are_downloaded(served, monkeypatch):
    """Kronenwetter overwrites MEET-Minutes-<guid>.pdf in place when minutes are amended."""
    gets, heads, asked = served
    _stub_pdf_text(monkeypatch)
    m = meeting()
    gets[m.notice_url] = FakeResponse(fixture("ada_agenda_closed_session.html"))
    heads[m.minutes_url] = FakeResponse(headers={"Content-Length": "4096",
                                                 "Last-Modified": "Tue, 27 Jan 2026 14:24:29 GMT"})
    gets[m.minutes_url] = FakeResponse(b"%PDF-1.7 amended", {"Last-Modified": "Tue, 27 Jan 2026 14:24:29 GMT"})
    known = {"minutes": KnownFile(url=m.minutes_url, sha256="ab" * 32, size=4096,
                                  last_modified="Mon, 19 Jan 2026 10:00:00 GMT")}
    minutes = municode.fetch_documents(m, known).minutes
    assert isinstance(minutes, DocFile) and minutes.sha256 == documents.sha256(b"%PDF-1.7 amended")
    assert asked[-2:] == [("HEAD", m.minutes_url), ("GET", m.minutes_url)]
