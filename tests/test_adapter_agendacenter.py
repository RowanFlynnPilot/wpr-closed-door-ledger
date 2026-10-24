"""adapters/agendacenter.py, offline. polite.get/post/head are monkeypatched.

Fixtures under tests/fixtures/adapters/agendacenter/ are trimmed from Weston's
live AgendaCenter (Oct 23, 2026): the /AgendaCenter page with three categories
(rows removed) and the 2026 Village Board listing with three rows.
"""
import io
import sys
from datetime import date
from pathlib import Path

import pypdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bodies  # noqa: E402
import documents  # noqa: E402
from adapters import agendacenter  # noqa: E402
from adapters.base import Unchanged  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "adapters" / "agendacenter"
PAGE = (FIXTURES / "agendacenter_page.html").read_text(encoding="utf-8")
LISTING = (FIXTURES / "listing_3_2026.html").read_text(encoding="utf-8")
CONFIG = bodies.load()["jurisdictions"]["weston"]
BASE = "https://www.westonwi.gov"


class FakeResponse:
    def __init__(self, url, content=b"", headers=None):
        self.url = url
        self.content = content
        self.text = content.decode("utf-8") if isinstance(content, bytes) else content
        self.headers = headers or {}


def _text_pdf(pages: int) -> bytes:
    """A small PDF with a text layer on every page."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None,
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for n in range(1, pages + 1):
        lines = [f"Page {n} of the meeting packet.", f"{n}. VILLAGE BOARD AGENDA ITEM NUMBER {n}",
                 "Motion to convene in closed session per 19.85(1)(c) and (f)."]
        stream = ("BT /F1 12 Tf 14 TL 72 720 Td " + " ".join(f"({line}) Tj T*" for line in lines) + " ET").encode()
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        content_id = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {pages} >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _rows():
    return agendacenter.parse_listing(LISTING, "weston", BASE, 3, 2026)


def test_categories_lists_every_category_and_its_years():
    got = agendacenter.categories(PAGE)
    assert got[3][:2] == [2013, 2014] and got[3][-1] == 2026
    assert got[26] == [2020, 2021]          # Building Committee: not in bodies.yaml, still listed
    assert got[31] == [2024, 2025, 2026]


def test_parse_listing_rows():
    amended, budget, canceled = _rows()
    assert amended.meeting_id == "1982" and amended.start == "2026-10-19"
    assert amended.title == "Board of Trustees Meeting Agenda and Packet"
    assert amended.notice_url == f"{BASE}/AgendaCenter/ViewFile/Agenda/_10192026-1982"
    assert amended.minutes_url is None and not amended.canceled and amended.category_id == 3
    assert amended.source == {
        "listed": "Amended", "listed_at": "2026-10-16T15:19",
        "previous_versions_url": f"{BASE}/AgendaCenter/PreviousVersions/_10192026-1982",
    }
    assert budget.id == "weston:1963" and budget.meeting_date == "2026-09-08"
    assert budget.minutes_url == f"{BASE}/AgendaCenter/ViewFile/Minutes/_09082026-1963"
    assert budget.source["listed"] == "Posted" and budget.source["listed_at"] == "2026-09-03T12:40"
    assert canceled.title.startswith("**CANCELED**") and canceled.canceled
    for m in _rows():
        assert bodies.match(bodies.load(), "weston", m.meeting_id, m.title, m.category_id).bodies == ["weston-village-board"]


def test_canceled_markers_anywhere_in_title():
    for title in ["Plan Commission Meeting - Cancelled", "03/11/2024 @ 6PM Plan Commission Meeting [CANCELLED]",
                  "Cancelled: Tourism Commission Agenda & Packet",
                  "12/01/2025 Meeting of the CLPS Committee - Notice of Meeting Cancellation"]:
        assert agendacenter._CANCELED.search(title)
    assert not agendacenter._CANCELED.search("Board of Trustees Meeting Agenda and Packet AMENDED (1-15-2024)")


def test_listing_for_wrong_year_raises():
    with pytest.raises(ValueError, match="not the 2025 listing"):
        agendacenter.parse_listing(LISTING, "weston", BASE, 3, 2025)


def test_offered_year_with_no_rows_raises():
    empty = LISTING.split("<tbody>")[0] + "<tbody></tbody></table>"
    with pytest.raises(ValueError, match="lists no meetings"):
        agendacenter.parse_listing(empty, "weston", BASE, 3, 2026)


def test_list_meetings_posts_each_year_since(monkeypatch):
    posts = []

    def post(url, data):
        posts.append((url, data))
        return FakeResponse(url, LISTING.encode())

    monkeypatch.setattr(agendacenter.polite, "get", lambda url, **kw: FakeResponse(url, PAGE.encode()))
    monkeypatch.setattr(agendacenter.polite, "post", post)
    rows = _rows()
    monkeypatch.setattr(agendacenter, "parse_listing", lambda html, j, b, c, y: rows)
    got = agendacenter.list_meetings("weston", CONFIG, date(2026, 3, 17))
    url = f"{BASE}/AgendaCenter/UpdateCategoryList"
    # category 26 offers nothing since 2024, so it is not requested
    assert posts == [(url, {"year": 2026, "catID": 3}), (url, {"year": 2026, "catID": 31})]
    assert [m.meeting_id for m in got] == ["1982", "1963"] * 2     # the Mar 16 row is before `since`


def test_fetch_notice_keeps_first_five_pages(monkeypatch):
    packet = _text_pdf(7)
    meeting = _rows()[0]
    monkeypatch.setattr(agendacenter.polite, "get",
                        lambda url, **kw: FakeResponse(url, packet, {"Content-Type": "application/pdf"}))
    docs = agendacenter.fetch_documents(meeting, {})
    notice = docs.notice
    assert docs.minutes is None
    assert notice.sha256 == documents.sha256(packet) and notice.size == len(packet) and notice.pages == 7
    assert notice.text.count("\f") == 4 and "Page 5 of" in notice.text and "Page 6 of" not in notice.text
    assert notice.text_source == "text_layer" and notice.ocr_pages == []
    assert notice.last_modified == "2026-10-16T15:19"
    assert len(pypdf.PdfReader(io.BytesIO(notice.content)).pages) == 5


def test_unchanged_when_head_and_listing_stamp_match(monkeypatch):
    meeting = _rows()[0]
    known = {"url": meeting.notice_url, "sha256": "ab" * 32, "size": 12100428, "last_modified": "2026-10-16T15:19"}
    heads = []

    def head(url, **kw):
        heads.append(url)
        return FakeResponse(url, headers={"Content-Type": "application/pdf", "Content-Length": "12100428"})

    monkeypatch.setattr(agendacenter.polite, "head", head)
    monkeypatch.setattr(agendacenter.polite, "get", lambda url, **kw: pytest.fail("downloaded an unchanged packet"))
    assert agendacenter.fetch_notice(meeting, known) == Unchanged("notice", "ab" * 32)
    assert heads == [meeting.notice_url]


def test_new_stamp_or_size_downloads_again(monkeypatch):
    meeting = _rows()[0]
    packet = _text_pdf(2)
    monkeypatch.setattr(agendacenter.polite, "head", lambda url, **kw: FakeResponse(
        url, headers={"Content-Type": "application/pdf", "Content-Length": "999"}))
    monkeypatch.setattr(agendacenter.polite, "get",
                        lambda url, **kw: FakeResponse(url, packet, {"Content-Type": "application/pdf"}))
    old_stamp = {"url": meeting.notice_url, "sha256": "ab" * 32, "size": 999, "last_modified": "2026-10-15T13:11"}
    other_size = {**old_stamp, "last_modified": "2026-10-16T15:19", "size": 1000}
    for known in (old_stamp, other_size):
        assert agendacenter.fetch_notice(meeting, known).sha256 == documents.sha256(packet)


def test_minutes_downloaded_whole(monkeypatch):
    meeting = _rows()[1]
    pdf = _text_pdf(3)
    seen = []

    def get(url, **kw):
        seen.append(url)
        return FakeResponse(url, pdf, {"Content-Type": "application/pdf"})

    monkeypatch.setattr(agendacenter.polite, "get", get)
    docs = agendacenter.fetch_documents(meeting, {})
    assert seen == [meeting.notice_url, meeting.minutes_url]
    assert docs.minutes.kind == "minutes" and docs.minutes.content == pdf and docs.minutes.pages == 3
    assert docs.minutes.text.count("\f") == 2 and docs.minutes.last_modified is None


def test_non_pdf_raises(monkeypatch):
    monkeypatch.setattr(agendacenter.polite, "get", lambda url, **kw: FakeResponse(
        url, b"<html>error</html>", {"Content-Type": "text/html; charset=utf-8"}))
    with pytest.raises(ValueError, match="not a PDF"):
        agendacenter.fetch_notice(_rows()[0], None)
