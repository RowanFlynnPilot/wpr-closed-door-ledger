"""Offline tests for adapters/boardbook.py (no network: polite.get is monkeypatched).

Fixtures in tests/fixtures/adapters/boardbook/ are BoardBook pages pulled
Oct 23, 2026 and trimmed: listing rows for both orgs, and the agenda tables of Wausau SD
meetings 674363 (Feb 4, 2025), 744112 (May 11, 2026) and 639532 (Jun 10,
2024) and D.C. Everest meeting 762740 (Sep 16, 2026). No minutes content is
stored here.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import documents  # noqa: E402
import polite  # noqa: E402
from adapters import boardbook  # noqa: E402
from adapters.base import Meeting  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "adapters" / "boardbook"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeResponse:
    def __init__(self, content: bytes, headers: dict | None = None):
        self.content = content
        self.text = content.decode("utf-8")
        self.headers = headers or {}


@pytest.fixture
def served(monkeypatch):
    """Map URL -> bytes; polite.get serves them and records each URL asked for."""
    pages: dict[str, bytes] = {}
    asked: list[str] = []

    def get(url, **kwargs):
        asked.append(url)
        return FakeResponse(pages[url])

    monkeypatch.setattr(polite, "get", get)
    return pages, asked


def listed(name: str, org: int) -> list[Meeting]:
    html = fixture(name).decode("utf-8")
    return [boardbook.parse_row("test", org, row) for row in boardbook.listing_rows(html)]


# ---- listing ----------------------------------------------------------------

def test_listing_rows_wausau_sd():
    meetings = listed("listing_1360.html", 1360)
    # The 2020 row's description embeds its own <tr>; it is not a meeting.
    assert [m.meeting_id for m in meetings] == ["769562", "674363", "583794", "395685"]
    upcoming, special, canceled, _ = meetings
    assert (upcoming.title, upcoming.start, upcoming.minutes_url) == ("Regular Meeting", "2026-10-12T17:00", None)
    assert special.title == "Special Meeting" and special.start == "2025-02-04T17:00"
    assert special.notice_url == "https://meetings.boardbook.org/Public/Agenda/1360?meeting=674363"
    assert special.minutes_url == "https://meetings.boardbook.org/Public/Minutes/1360?meeting=674363"
    assert special.source == {"org": 1360} and not special.canceled
    # "Cancelled" markers set the flag and are not part of the title.
    assert canceled.canceled and canceled.title == "Special Meeting" and canceled.start == "2023-05-15T17:00"


def test_listing_rows_dc_everest():
    meetings = listed("listing_1315.html", 1315)
    assert [m.meeting_id for m in meetings] == ["768009", "762740", "627827"]
    # "October 28, 2026 Immediately following the Annual Meeting/Budget Hearing - ..." has no clock time.
    assert meetings[0].start == "2026-10-28" and meetings[0].title == "Regular School Board Meeting"
    assert meetings[2].start == "2024-04-17T18:30"
    assert meetings[2].minutes_url == "https://meetings.boardbook.org/Public/Minutes/1315?meeting=627827"


def test_list_meetings_filters_by_date(served):
    pages, asked = served
    pages["https://meetings.boardbook.org/Public/Organization/1360"] = fixture("listing_1360.html")
    meetings = boardbook.list_meetings("wausau_sd", {"org": 1360}, date(2024, 1, 1))
    assert asked == ["https://meetings.boardbook.org/Public/Organization/1360"]
    assert [m.id for m in meetings] == ["wausau_sd:769562", "wausau_sd:674363"]


def test_heading_forms():
    assert boardbook.parse_heading("September 16, 2026 at 6:30 PM - Regular School Board Meeting") == \
        ("2026-09-16T18:30", "Regular School Board Meeting")
    assert boardbook.parse_heading("June 10, 2024 at 9:05 AM - Public Meeting - Negotiations") == \
        ("2024-06-10T09:05", "Public Meeting - Negotiations")
    with pytest.raises(boardbook.BoardBookPageError):
        boardbook.parse_heading("Sometime soon - Regular Meeting")


def test_listing_without_table_raises():
    with pytest.raises(boardbook.BoardBookPageError):
        boardbook.listing_rows("<html><body>Nightly Maintenance</body></html>")


# ---- agenda text -------------------------------------------------------------

def test_wausau_sd_closed_session_header_and_sub_items():
    text = boardbook.agenda_text(fixture("agenda_1360_674363.html").decode("utf-8"), "t")
    assert text.splitlines() == [
        "I. CALL TO ORDER",
        "II. Request for Closed Session Pursuant to State Statutes",
        "II.A. Administrator Contract Review s. 19.85 (1)(c)",
        "II.B. Pursuant to Section 19.85(1)(c), Wis. Stats., to consider employment, promotion, compensation, "
        "or performance evaluation data of any public employee over which the governmental body has "
        "jurisdiction or exercises responsibility, specifically, to discuss the employment of a member of "
        "the teaching staff.",
        "II.C. Preliminary Discussion Regarding Potential Litigation 19.85 (g)",
        "II.D. Reconvene in Open Session, to take further action if necessary and appropriate",
        "III. ADJOURN",
    ]


def test_presenters_and_attachments_are_not_item_text():
    lines = boardbook.agenda_text(fixture("agenda_1315_762740.html").decode("utf-8"), "t").splitlines()
    assert "VII.A. Approval of Minutes" in lines
    assert "IX.A. WASB Legislative Network Member" in lines
    assert not any("Attachments" in line or "Presenter" in line for line in lines)
    closed = lines[-1]
    assert closed.startswith("XIV. The Board will contemplate adjournment to Closed Session pursuant to W.S.S. 19.85(1)(f)")
    assert closed.endswith("(Seclusion and Restraint). The Board will adjourn from Closed Session.")


def test_description_follows_wording_on_the_same_line():
    lines = boardbook.agenda_text(fixture("agenda_1360_744112.html").decode("utf-8"), "t").splitlines()
    assert lines[1].startswith("VIII.B. Legal Expense Summary for 3rd Quarter Description: Estimated Time to Present: 2 Minutes")
    assert lines[2:] == [
        "XI. REQUEST FOR CLOSED SESSION PURSUANT TO STATE STATUTES",
        "XI.A. Final Notice of Non-renewal ss. 19.85(1)(c)",
        "XI.B. Contract Evaluation S. 19.85 (1)(e)(g)",
        "XI.C. Reconvene in Open Session, to take further action if necessary and appropriate",
    ]


def test_bargaining_footnote_stays_in_its_row():
    # Wausau SD's bargaining notices put the s. 19.86 closed-session note under ADJOURNMENT.
    lines = boardbook.agenda_text(fixture("agenda_1360_639532.html").decode("utf-8"), "t").splitlines()
    assert len(lines) == 3
    assert lines[2] == ("III. ADJOURNMENT* * The Parties may continue negotiations in closed session "
                        "pursuant to ss. 19.86 and 111.70 (4)(cm).")


def test_entities_unescaped_and_whitespace_collapsed():
    html = """<div id="Tab-AgendaItem"><table>
      <tr class="agenda-item-information"><td><div class="form-check"><i class="fa"></i>
        IV.&nbsp;Closed   Session
        pursuant to &sect;&nbsp;19.85(1)(e) <strong>(Sale of R&amp;D Building)</strong><br/>
      </div></td></tr></table></div>"""
    assert boardbook.agenda_text(html, "t") == "IV. Closed Session pursuant to § 19.85(1)(e) (Sale of R&D Building)"


def test_page_without_agenda_table_raises():
    with pytest.raises(boardbook.BoardBookPageError):
        boardbook.agenda_text("<html><body><table id='PublicMeetingsTable'></table></body></html>", "t")


def test_token_blanked_so_sha256_is_stable():
    page = fixture("agenda_1360_674363.html")
    assert b'name="__RequestVerificationToken" type="hidden" value=""' in boardbook.stable_html(page)
    other = page.replace(b'value="CfDJ8', b'value="XyZ9', 1)
    assert other != page
    assert documents.sha256(boardbook.stable_html(other)) == documents.sha256(boardbook.stable_html(page))


# ---- documents ----------------------------------------------------------------

def meeting(minutes_url: str | None) -> Meeting:
    return Meeting("wausau_sd", "674363", "Special Meeting", "2025-02-04T17:00",
                   boardbook.agenda_url(1360, "674363"), minutes_url, source={"org": 1360})


def test_fetch_documents(served, monkeypatch):
    pages, asked = served
    agenda = boardbook.agenda_url(1360, "674363")
    viewer = "https://meetings.boardbook.org/Public/Minutes/1360?meeting=674363"
    pdf = "https://meetings.boardbook.org/Documents/DownloadPDF/7000001?org=1360"
    pages[agenda] = fixture("agenda_1360_674363.html")
    pages[viewer] = b'<html><body><input type="hidden" id="NewDocumentViewerDocumentID" value="7000001" /></body></html>'
    pages[pdf] = b"%PDF-1.7 placeholder"
    monkeypatch.setattr(documents, "pdf_text",
                        lambda content, name: documents.PdfText("page one\fpage two", "ocr", [2], 2))

    docs = boardbook.fetch_documents(meeting(viewer), {})
    assert asked == [agenda, viewer, pdf]

    n = docs.notice
    assert (n.kind, n.url, n.extension, n.text_source) == ("notice", agenda, "html", "html")
    assert n.content == boardbook.stable_html(pages[agenda])
    assert n.sha256 == documents.sha256(n.content) and n.size == len(n.content)
    assert n.text.splitlines()[2] == "II.A. Administrator Contract Review s. 19.85 (1)(c)"

    m = docs.minutes
    assert (m.kind, m.url, m.extension, m.content) == ("minutes", pdf, "pdf", pages[pdf])
    assert (m.text_source, m.pages, m.ocr_pages) == ("ocr", 2, [2])
    assert m.sha256 == documents.sha256(pages[pdf]) and m.size == len(pages[pdf])


def test_no_minutes_listed(served):
    pages, asked = served
    pages[boardbook.agenda_url(1360, "674363")] = fixture("agenda_1360_674363.html")
    docs = boardbook.fetch_documents(meeting(None), {})
    assert docs.minutes is None and asked == [boardbook.agenda_url(1360, "674363")]


def test_minutes_link_landing_on_listing_raises(served):
    # BoardBook redirects a minutes link with no minutes to the organization page.
    pages, _ = served
    viewer = "https://meetings.boardbook.org/Public/Minutes/1360?meeting=674363"
    pages[boardbook.agenda_url(1360, "674363")] = fixture("agenda_1360_674363.html")
    pages[viewer] = fixture("listing_1360.html")
    with pytest.raises(boardbook.BoardBookPageError):
        boardbook.fetch_documents(meeting(viewer), {})


def test_empty_agenda_raises(served):
    pages, _ = served
    pages[boardbook.agenda_url(1360, "674363")] = (
        b'<div id="Tab-AgendaItem"><table><tr class="agenda-item-information"><td>'
        b'<div class="form-check">I. CALL TO ORDER</div></td></tr></table></div>')
    with pytest.raises(documents.UnreadableDocument):
        boardbook.fetch_documents(meeting(None), {})
