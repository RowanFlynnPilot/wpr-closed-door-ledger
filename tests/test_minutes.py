"""minutes.py on synthetic minutes modeled on each jurisdiction's layout.

Real minutes name private people, so these are written fresh, with invented names.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import minutes  # noqa: E402

PER_MEMBER = """II. Request for Closed Session Pursuant to State Statutes
Pat Doe moved to enter into Closed Session, seconded by Lee Roe. The
motion carried 6-0 via a roll call vote at 5:02 pm.
Pat Doe – Yes
Lee Roe – Yes
Kim Poe – Yes
III. Reconvene in Open Session
Lee Roe moved to reconvene in open session, seconded by Pat Doe. The motion carried 6-0 at 5:43 pm."""

YES_LIST = """CLOSED SESSION pursuant to Section 19.85(1)(e) of the Wisconsin Statutes regarding Parcel 1.
Motion by Doe, seconded by Roe, to move into closed session.
Roll Call Vote - Yes: Doe, Roe, Poe, Moe, Zoe; No: None. Motion carried 5-0.
CONVENED into Closed Session.
Adjourn"""

TALLY = """9 Closed Session.
Adjourn to Closed Session pursuant to Wisconsin State Statute § 19.85(1)(f) to discuss an investigation.
Motion by Alderperson Doe, seconded by Alderperson Roe, to adjourn to Closed Session pursuant to
Wisconsin State Statute § 19.85(1)(f).
Yes 11, No 0, Abstained 0
MOTION PASSED.
The Common Council convened into Closed Session.
The Common Council did not reconvene into Open Session.
10 Reconvene into Open Session, if necessary, to take action on Closed Session items."""

RESULT_ONLY = """CLOSED SESSION pursuant to Section 19.85(1)(g), Wis. Stats., for the purpose of deliberating on claims
Motion by Doe, second by Roe to convene in closed session. Motion passed.
RECONVENE MEETING INTO OPEN SESSION for the purpose of acting upon closed session items, if
necessary
Motion by Roe, second by Doe to reconvene in open session. Motion passed."""

UNANIMOUS = """6. CLOSED SESSION pursuant to Section 19.85(1)(g), Wis. Stats., for the purpose of deliberating on claims.
Motion by Doe, second by Roe to convene in closed session. Motion passed unanimously."""

NOT_SHOWN = """Closed Session pursuant to 19.85 (1)(f) for the purpose of considering leave requests.
Motion by Doe to go into closed session pursuant to 19.85 (1)(f). Second by Roe. Poe took rollcall of
members present. The committee entered closed session.
Reconvene into Open Session.
Poe indicated that the committee was back in open session."""

UNCITED = """2. ANNOUNCEMENT OF CLOSED SESSION
3. CLOSED SESSION
Motion by Doe/Roe to convene into closed session. Motion carried by roll call vote. 6:0.
TIME INTO CLOSED SESSION: 5:02 p.m.
4. RECONVENE OPEN SESSION
Motion by Roe/Doe to reconvene into open session. Motion carried by roll call vote. 6:0."""

NO_CLOSED = """1. Call to order at 5:00 p.m.
2. Approve minutes of the closed session of September 21, 2026. Motion by Doe, second by Roe. Motion carried 5-0.
3. Adjourn. Motion carried."""


@pytest.mark.parametrize("text, want", [
    (PER_MEMBER, dict(held=True, motion_recorded=True, vote_record="per_member", exemption_in_minutes=False, reconvened=True)),
    (YES_LIST, dict(held=True, motion_recorded=True, vote_record="per_member", exemption_in_minutes=True, reconvened=False)),
    (TALLY, dict(held=True, motion_recorded=True, vote_record="tally", exemption_in_minutes=True, reconvened=False)),
    (RESULT_ONLY, dict(held=True, motion_recorded=True, vote_record="result_only", exemption_in_minutes=True, reconvened=True)),
    (UNANIMOUS, dict(held=True, motion_recorded=True, vote_record="unanimous", exemption_in_minutes=True, reconvened=False)),
    (NOT_SHOWN, dict(held=True, motion_recorded=True, vote_record="not_shown", exemption_in_minutes=True, reconvened=True)),
    (UNCITED, dict(held=True, motion_recorded=True, vote_record="tally", exemption_in_minutes=False, reconvened=True)),
    (NO_CLOSED, dict(held=False, motion_recorded=False, vote_record=None, exemption_in_minutes=False, reconvened=False)),
])
def test_minutes_rules(text, want):
    got = minutes.as_record(minutes.analyze(text, 2))
    assert got == {**want, "minutes_version": 2}


def test_times_are_not_tallies():
    assert minutes.vote_record("Motion passed at 5:02 p.m.") == "result_only"
    assert minutes.vote_record("convened at 3:57 pm") == "not_shown"


def test_mentions_that_are_not_motions():
    for text in ["Motion by Doe/Roe to discuss the matter at the meeting scheduled on Monday, July 22, 2024, in closed session. Motion carried 5:0.",
                 "Motion by Doe, second by Roe, as follows: That the information received in closed session regarding a Village employee be accepted. Motion carried."]:
        assert not minutes.analyze(text, 1).motion_recorded
