"""build.py on a small archive written with store.py."""
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bodies  # noqa: E402
import build  # noqa: E402
import store  # noqa: E402
from adapters.base import DocFile, Meeting  # noqa: E402

CONFIG = bodies.load()
CLAIMS = ("6. CLOSED SESSION pursuant to Section 19.85(1)(g), Wis. Stats., for the purpose of deliberating on claims.\n"
          "7. RECONVENE MEETING INTO OPEN SESSION for the purpose of acting upon closed session item, if necessary.")
SALE = ("4. Adjourn to Closed Session pursuant to Wisconsin State Statute § 19.85(1)(e) for deliberating or negotiating "
        "the purchasing of public properties, whenever competitive or bargaining reasons require a closed session in "
        "regard to the sale of 424 Burns Street, Wausau.") + " filler" * 40


def _pdf(pages: int) -> bytes:
    import io
    import pypdf
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(612, 792)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _doc(text: str) -> DocFile:
    # A real PDF with one page per text page, made unique by a trailing comment.
    content = _pdf(text.count("\f") + 1) + b"%" + hashlib.sha256(text.encode("utf-8")).hexdigest().encode()
    return DocFile("notice", "https://example.test/f", content, "pdf", hashlib.sha256(content).hexdigest(),
                   text, "text_layer", len(content), 1)


def _add(root, meeting_id, title, start, versions):
    meeting = Meeting("wausau", meeting_id, title, start, f"https://example.test/{meeting_id}", None)
    record = store.new_record(meeting, versions[0][0])
    store.update_listing(record, meeting, versions[0][0])
    for seen_at, text in versions:
        store.apply_document(root, record, "notice", _doc(text), seen_at)
    record["last_fetched"] = versions[-1][0]
    store.save(root, record)


@pytest.fixture
def archive(tmp_path):
    _add(tmp_path, "927", "Board Of Public Works Regular Meeting", "2026-06-02T10:30",
         [("2026-05-29T12:00:00Z", CLAIMS)])
    # Seen twice before the meeting (the later one counts), then changed after it.
    _add(tmp_path, "130", "Economic Development Committee Regular Meeting", "2026-07-07T17:00",
         [("2026-07-01T12:00:00Z", SALE.replace("424", "999")), ("2026-07-06T12:00:00Z", SALE),
          ("2026-07-09T12:00:00Z", SALE + " amended")])
    _add(tmp_path, "5", "Possible Quorum of the Common Council", "2026-07-07T17:00",
         [("2026-07-01T12:00:00Z", CLAIMS)])
    _add(tmp_path, "6", "Affordable Housing Regional Task Force", "2026-07-08T09:00",
         [("2026-07-01T12:00:00Z", CLAIMS)])
    return tmp_path


def test_internal_files(archive):
    meetings, items = build.build_internal(archive, CONFIG)
    assert [m["id"] for m in meetings] == ["wausau:927", "wausau:130", "wausau:6"]   # quorum notice excluded
    m130 = next(m for m in meetings if m["id"] == "wausau:130")
    assert m130["notice_versions"] == 3 and m130["changed_after_meeting"] and m130["closed_item_count"] == 1
    sale = next(i for i in items if i["meeting_id"] == "wausau:130")
    assert "424 Burns Street" in sale["purpose_text"]                 # the version seen last before the meeting
    claims = next(i for i in items if i["meeting_id"] == "wausau:927")
    assert claims["exemptions"] == ["g"] and claims["triage"] == "check"
    assert not next(m for m in meetings if m["id"] == "wausau:927")["changed_after_meeting"]


def _record(start, versions, source=None):
    return {"listing": {"start": start, "source": source or {}}, "versions": versions}


def test_backfilled_version_is_used_and_never_changed():
    late = {"kind": "notice", "seen_at": "2026-10-23T12:00:00Z"}
    assert build.items_version(_record("2024-03-05T18:00", [late])) is late
    same_day = {"kind": "notice", "seen_at": "2026-03-05T12:00:00Z"}
    assert build.items_version(_record("2026-03-05", [same_day])) is same_day        # date-only start


def _weston(root, start, stamp, current, earlier):
    """A Weston meeting backfilled today: the current version stamped `stamp`, plus earlier
    versions from the platform's PreviousVersions page as (archive id, text)."""
    meeting = Meeting("weston", "1716", "Board of Trustees Regular Meeting", start,
                      "https://example.test/1716", None, category_id=3, source={"listed_at": stamp})
    seen_at = "2026-10-23T12:00:00Z"
    record = store.new_record(meeting, seen_at)
    store.update_listing(record, meeting, seen_at)
    doc = _doc(current)
    store.apply_document(root, record, "notice", DocFile(**{**doc.__dict__, "last_modified": stamp}), seen_at)
    for archive_id, text in earlier:
        doc = _doc(text)
        store.apply_previous_version(root, record, archive_id,
                                     DocFile(**{**doc.__dict__, "url": f"https://example.test/a/{archive_id}"}), seen_at)
    record["last_fetched"] = seen_at
    store.save(root, record)


def test_version_amended_after_the_meeting_yields_to_the_newest_earlier_one(tmp_path):
    # Re-posted two days after the meeting with the closed session dropped.
    _weston(tmp_path, "2024-12-16", "2024-12-18T09:00", "1. Call to order." + " x" * 120,
            [(1790, SALE.replace("424", "999")), (1824, SALE)])
    meetings, items = build.build_internal(tmp_path, CONFIG)
    assert meetings[0]["notice_versions"] == 3 and meetings[0]["changed_after_meeting"]
    assert len(items) == 1 and "424 Burns Street" in items[0]["purpose_text"]     # 1824, not 1790
    assert meetings[0]["notice_file"].endswith(".pdf")


def test_version_posted_before_the_meeting_is_used(tmp_path):
    _weston(tmp_path, "2024-12-16", "2024-12-11T16:33", SALE, [(1824, "1. Call to order." + " x" * 120)])
    meetings, items = build.build_internal(tmp_path, CONFIG)
    assert len(items) == 1 and not meetings[0]["changed_after_meeting"]


def test_unclassified_title_fails(archive):
    _add(archive, "77", "Mystery Committee", "2026-07-08T09:00", [("2026-07-01T12:00:00Z", CLAIMS)])
    with pytest.raises(build.BuildError, match="Mystery Committee"):
        build.build_internal(archive, CONFIG)


def test_reviews_and_projection(archive):
    meetings, items = build.build_internal(archive, CONFIG)
    with pytest.raises(build.BuildError, match="match no item"):
        build.check_reviews({"wausau:1:000000000000": {"decision": "flagged"}}, items)
    claims = next(i for i in items if i["meeting_id"] == "wausau:927")
    sale = next(i for i in items if i["meeting_id"] == "wausau:130")
    reviews = {claims["id"]: {"decision": "withhold", "note": "named a person"},
               sale["id"]: {"decision": "flagged", "note": "editor note", "editor": "SS", "date": "2026-11-02"}}
    build.check_reviews(reviews, items)
    p = build.public_projection(CONFIG, meetings, items, reviews)
    assert [i["id"] for i in p["closed_sessions"]] == [sale["id"]]            # withheld and confirm: bodies dropped
    assert p["closed_sessions"][0]["review_note"] == "editor note"
    assert set(p["closed_sessions"][0]) == set(build.PUBLIC_ITEM_FIELDS)
    assert "triage" not in p["closed_sessions"][0]
    m927 = next(m for m in p["meetings"] if m["id"] == "wausau:927")
    assert m927["notice_url"] == "" and m927["closed_item_count"] == 0
    assert "wausau:6" not in {m["id"] for m in p["meetings"]}
    assert "wausau-affordable-housing-task-force" not in {b["key"] for b in p["bodies"]}


def test_write_site(archive, tmp_path):
    meetings, items = build.build_internal(archive, CONFIG)
    p = build.public_projection(CONFIG, meetings, items, {})
    site = tmp_path / "site"
    build.write_site(site, archive, p)
    assert (site / "data" / "closed_sessions.csv").read_text(encoding="utf-8").startswith("id,meeting_id,bodies")
    for item in p["closed_sessions"]:
        assert (site / item["archive_url"]).is_file()


def test_minutes_facts_and_unnoticed_sessions(archive):
    meeting = Meeting("wausau", "925", "Board Of Public Works Regular Meeting", "2026-06-09T09:30",
                      "https://example.test/925", "https://example.test/925/minutes")
    record = store.new_record(meeting, "2026-06-05T12:00:00Z")
    store.update_listing(record, meeting, "2026-06-05T12:00:00Z")
    store.apply_document(archive, record, "notice", _doc("1. Make recommendation for lighting materials." + " x" * 120),
                         "2026-06-05T12:00:00Z")
    text = ("CLOSED SESSION pursuant to Section 19.85(1)(g), Wis. Stats., for the purpose of deliberating on claims\n"
            "Motion by Doe, second by Roe to convene in closed session. Motion passed.")
    content = text.encode("utf-8")
    store.apply_document(archive, record, "minutes",
                         DocFile("minutes", "https://example.test/m", content, "pdf",
                                 hashlib.sha256(content).hexdigest(), text, "text_layer", len(content), 1),
                         "2026-06-20T12:00:00Z")
    store.save(archive, record)
    meetings, items = build.build_internal(archive, CONFIG)
    leads = build.unnoticed_sessions(meetings)
    assert [l["meeting_id"] for l in leads] == ["wausau:925"] and leads[0]["minutes_pages"] == [1]
    m = next(m for m in meetings if m["id"] == "wausau:925")
    assert m["minutes"]["vote_record"] == "result_only" and m["minutes"]["exemption_in_minutes"]
    p = build.public_projection(CONFIG, meetings, items, {})
    assert all(i["minutes"] is None for i in p["closed_sessions"])      # not published until validated


def test_public_copy_is_the_agenda_only(tmp_path):
    import io
    import pypdf
    packet = CLAIMS + "\n8. Adjourn" + "\f" + "MINUTES OF THE PREVIOUS MEETING\nPublic comment: a resident of 123 Main St."
    _add(tmp_path, "930", "Board Of Public Works Regular Meeting", "2026-06-09T10:30", [("2026-06-05T12:00:00Z", packet)])
    meetings, items = build.build_internal(tmp_path, CONFIG)
    p = build.public_projection(CONFIG, meetings, items, {})
    url = next(i["archive_url"] for i in p["closed_sessions"] if i["meeting_id"] == "wausau:930")
    assert len(pypdf.PdfReader(io.BytesIO(build.public_copy(tmp_path, url))).pages) == 1
    assert build.public_copy_path("meetings/wausau_sd/1/notice-abc.html") == "archive/wausau_sd/1/notice-abc.txt"


def test_redact_review(archive):
    meetings, items = build.build_internal(archive, CONFIG)
    sale = next(i for i in items if i["meeting_id"] == "wausau:130")
    with pytest.raises(build.BuildError, match="not in the item's wording"):
        build.check_reviews({sale["id"]: {"decision": "redact", "redact": ["Jane Roe"]}}, items)
    with pytest.raises(build.BuildError, match="lists the text"):
        build.check_reviews({sale["id"]: {"decision": "redact"}}, items)
    with pytest.raises(build.BuildError, match="only to a redact review"):
        build.check_reviews({sale["id"]: {"decision": "flagged", "redact": ["424 Burns Street"]}}, items)
    reviews = {sale["id"]: {"decision": "redact", "redact": ["424 Burns Street"], "note": "private address"}}
    build.check_reviews(reviews, items)
    p = build.public_projection(CONFIG, meetings, items, reviews)
    row = next(i for i in p["closed_sessions"] if i["id"] == sale["id"])
    assert "424 Burns" not in row["item_text"] and "[name withheld]" in row["item_text"]
    assert "424 Burns" not in row["purpose_text"] and "[name withheld]" in row["purpose_text"]
    assert row["archive_url"] == "" and row["notice_url"] and row["review_note"] is None
    assert "424 Burns" in sale["item_text"]                    # internal data keeps the wording
