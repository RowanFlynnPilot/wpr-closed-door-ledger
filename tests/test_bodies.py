"""Run: python -m pytest tests

tests/fixtures/titles.json holds every 2024–Oct 2026 meeting title listed by
Wausau (CivicClerk), both school districts (BoardBook) and Kronenwetter
(Municode), pulled Oct 23, 2026. Weston matches on category ids instead.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bodies  # noqa: E402

CONFIG = bodies.load()
TITLES = json.loads((ROOT / "tests" / "fixtures" / "titles.json").read_text(encoding="utf-8"))


def test_every_real_title_maps():
    for t in TITLES:
        bodies.match(CONFIG, t["jurisdiction"], t["meeting_id"], t["title"])


def test_rules():
    m = bodies.match(CONFIG, "wausau", "1", "CANCELED - Plan Commission Meeting")
    assert m.bodies == ["wausau-plan-commission"] and m.canceled
    assert bodies.match(CONFIG, "wausau", "1", "Possible Quorum of the Common Council").excluded
    assert bodies.match(CONFIG, "wausau", "1", "*TEST MEETING").excluded          # normalized before exclude
    joint = bodies.match(CONFIG, "wausau", "1", "Joint Meeting of the Finance Committee and the Economic Development Committee")
    assert sorted(joint.bodies) == ["wausau-economic-development", "wausau-finance"]
    assert bodies.match(CONFIG, "wausau", "2291", "One Time Event").bodies == ["wausau-zoning-appeals"]
    assert bodies.match(CONFIG, "wausau_sd", "1", "Special Meeting").bodies == ["wausau-sd-board"]
    # generic "Public Meeting" titles: mapped one by one; graduations are excluded,
    # but bargaining sessions and task force meetings are not
    assert bodies.match(CONFIG, "wausau_sd", "748411", "Public Meeting").excluded
    assert bodies.match(CONFIG, "wausau_sd", "639532", "Public Meeting").bodies == ["wausau-sd-board"]
    assert bodies.match(CONFIG, "wausau_sd", "668230", "Public Meeting").bodies == ["wausau-sd-elementary-task-force"]
    assert bodies.match(CONFIG, "weston", "1", "anything", category_id=3).bodies == ["weston-village-board"]
    assert bodies.match(CONFIG, "weston", "1", "anything", category_id=17).excluded


def test_unmatched_and_ambiguous_fail():
    with pytest.raises(bodies.UnmatchedMeeting):
        bodies.match(CONFIG, "wausau", "1", "Mystery Committee")
    with pytest.raises(bodies.UnmatchedMeeting):
        bodies.match(CONFIG, "wausau_sd", "999999", "Public Meeting")             # new generic title: classify it
    with pytest.raises(bodies.AmbiguousMeeting):
        bodies.match(CONFIG, "kronenwetter", "1", "Plan Commission and Utility Committee Workshop")
