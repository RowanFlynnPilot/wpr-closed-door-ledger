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


def _doc(text: str) -> DocFile:
    content = text.encode("utf-8")
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


def test_backfilled_version_is_used_and_never_changed():
    late = [{"seen_at": "2026-10-23T12:00:00Z"}]
    assert build.items_version(late, "2024-03-05T18:00") is late[0]
    assert build.items_version([{"seen_at": "2026-03-05T12:00:00Z"}], "2026-03-05") is not None   # date-only start


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
