"""extract.py on the layouts each jurisdiction uses.

The fixtures in tests/fixtures/notices.json are short excerpts of real posted
agendas (public notices; never minutes), with what a reader finds in them.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import extract  # noqa: E402

CASES = json.loads((ROOT / "tests" / "fixtures" / "notices.json").read_text(encoding="utf-8"))["cases"]


def test_notices():
    failures = []
    for case in CASES:
        found = extract.closed_items(case["text"])
        meeting = {"id": case["id"], "bodies": [], "meeting_date": ""}
        rows = [extract.item_record(meeting, f, "text_layer") for f in found]
        got = [{"exemptions": r["exemptions"], "no_citation": r["no_citation"], "starts": r["item_text"][:40],
                "purpose": r["purpose_text"]} for r in rows]
        want = case["items"]
        ok = len(got) == len(want) and all(
            g["exemptions"] == w["exemptions"] and g["no_citation"] == w.get("no_citation", False)
            and g["starts"].startswith(w["starts"][:40])
            and ("purpose" not in w or g["purpose"] == w["purpose"])
            and ("purpose_starts" not in w or (g["purpose"] or "").startswith(w["purpose_starts"]))
            for g, w in zip(got, want))
        ok = ok and extract.notices_reconvene(case["text"]) == case["notices_reconvene"]
        if not ok:
            failures.append((case["id"], got, want))
    assert not failures, failures


def test_item_id_survives_renumbering():
    a = "6. CLOSED SESSION pursuant to Section 19.85(1)(g), Wis. Stats., for the purpose of deliberating on claims."
    b = "9. CLOSED  SESSION pursuant to Section 19.85(1)(g), Wis. Stats., for the purpose of\ndeliberating on claims."
    ia, ib = (extract.closed_items(t)[0].item_text for t in (a, b))
    assert extract.item_id("wausau:927", ia) == extract.item_id("wausau:927", ib)
    assert extract.item_id("wausau:927", ia).startswith("wausau:927:") and len(extract.item_id("wausau:927", ia)) == 23


def test_triage():
    t = extract.triage
    assert t(False, True, "the sale of 424 Burns Street, Wausau", "text_layer", ["e"]) == "ok"
    assert t(False, True, "the sale of 424 Burns Street, Wausau", "ocr", ["e"]) == "check"
    assert t(False, True, "deliberating on claims", "text_layer", ["g"]) == "check"        # under 4 words
    assert t(False, False, "pre-qualification statements for 2025 projects", "text_layer", ["d"]) == "check"
    assert t(False, True, "pre-qualification statements for 2025 projects", "text_layer", ["e"]) == "check"  # no term
    assert t(False, True, "review of the deliberations of the council", "text_layer", ["ee"]) == "check"
    assert t(True, None, None, "html", []) == "check"
    assert t(False, None, "continue negotiations with the union", "html", []) == "check"   # 19.86 only


def test_item_record():
    meeting = {"id": "wausau:130", "bodies": ["wausau-economic-development"], "meeting_date": "2026-01-06"}
    text = ("4. Adjourn to Closed Session pursuant to Wisconsin State Statute § 19.85(1)(e) for deliberating or "
            "negotiating the purchasing of public properties, the investing of public funds, or conducting other "
            "specified public business, whenever competitive or bargaining reasons require a closed session in "
            "regard to the sale of 424 Burns Street, Wausau.")
    row = extract.item_record(meeting, extract.closed_items(text)[0], "text_layer")
    assert row["exemptions"] == ["e"] and row["cites_subsection_1"] is True and row["triage"] == "ok"
    assert row["purpose_text"] == "the sale of 424 Burns Street, Wausau" and row["minutes"] is None
    assert row["item_text"].startswith("Adjourn to Closed Session")
