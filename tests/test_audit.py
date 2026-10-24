"""quarters.py, audit.py and handcheck.py on small built data."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import audit  # noqa: E402
import bodies  # noqa: E402
import handcheck  # noqa: E402
import quarters  # noqa: E402

CONFIG = bodies.load()


def _item(meeting_id, day, body, exemptions, no_citation=False, raw="19.85(1)(g)"):
    return {"id": f"{meeting_id}:abc", "meeting_id": meeting_id, "bodies": [body], "meeting_date": day,
            "item_text": "CLOSED SESSION pursuant to Section 19.85(1)(g), Wis. Stats., for claims.",
            "citation_raw": raw, "exemptions": exemptions, "no_citation": no_citation}


ITEMS = [
    _item("wausau:1", "2026-07-07", "wausau-board-of-public-works", ["g"]),
    _item("wausau:2", "2026-10-02", "wausau-board-of-public-works", ["g"]),                    # Q4
    _item("weston:3", "2026-08-10", "mountain-bay-police-commission", ["c"]),
    _item("wausau_sd:4", "2026-07-01", "wausau-sd-board", [], raw=""),                          # 19.86 only
    _item("wausau:5", "2026-09-01", "wausau-affordable-housing-task-force", [], no_citation=True, raw=""),
]


def test_quarters():
    assert quarters.quarter_range("2026Q3") == (date(2026, 7, 1), date(2026, 9, 30))
    assert quarters.quarter_range("2026Q4") == (date(2026, 10, 1), date(2026, 12, 31))
    assert quarters.body_index(CONFIG)["mountain-bay-police-commission"]["custodian"] == \
        "Mountain Bay Metropolitan Police Department"
    assert quarters.body_index(CONFIG)["wausau-finance"]["custodian"] == "City of Wausau"


def test_requests_grouped_by_custodian():
    grouped = audit.requests(CONFIG, ITEMS, "2026Q3")
    assert {k: [i["meeting_id"] for i in v] for k, v in grouped.items()} == {
        "City of Wausau": ["wausau:1"],
        "Mountain Bay Metropolitan Police Department": ["weston:3"],
        "unknown": ["wausau:5"],
    }


def test_fill_template():
    template = audit.TEMPLATE.read_text(encoding="utf-8")
    index = quarters.body_index(CONFIG)
    text = audit.fill(template, "City of Wausau", "2026Q3",
                      [audit.list_line(ITEMS[0], index, "https://example.test/agenda")])
    assert "Q3 2026" in text and "July 1, 2026" in text and "September 30, 2026" in text
    assert "2026-07-07 | Board of Public Works | CLOSED SESSION pursuant" in text
    assert "[GENERATED LIST" not in text and "DRAFT" not in text
    assert "[RECORDS CUSTODIAN]" in text and "[EMAIL]" in text          # left for the requester


def test_handcheck_is_blind():
    meetings = [
        {"id": "wausau:1", "meeting_date": "2026-07-07", "jurisdiction": "wausau", "canceled": False,
         "bodies": ["wausau-board-of-public-works"], "notice_url": "n1", "minutes_url": "m1", "closed_item_count": 1,
         "minutes": {"held": True, "motion_recorded": True, "vote_record": "result_only",
                     "exemption_in_minutes": True, "reconvened": True, "minutes_version": 1},
         "minutes_convene_pages": [1]},
        {"id": "wausau:9", "meeting_date": "2026-07-14", "jurisdiction": "wausau", "canceled": False,
         "bodies": ["wausau-board-of-public-works"], "notice_url": "n9", "minutes_url": "m9", "closed_item_count": 0,
         "minutes": {"held": True, "motion_recorded": True, "vote_record": "result_only",
                     "exemption_in_minutes": True, "reconvened": True, "minutes_version": 1},
         "minutes_convene_pages": [2]},
    ]
    noticed, unnoticed, automated = handcheck.rows(CONFIG, meetings, ITEMS, "2026Q3")
    assert [r["meeting_id"] for r in noticed] == ["wausau:1"] and noticed[0]["noticed_exemptions"] == "g"
    assert all(noticed[0][f] == "" for f in handcheck.FIELDS)
    assert unnoticed[0]["closed_session_in_minutes"] == ""
    assert automated["wausau:1"]["vote_record"] == "result_only"
    assert automated["wausau:9"] == {"closed_session_in_minutes": True, "pages": [2]}
