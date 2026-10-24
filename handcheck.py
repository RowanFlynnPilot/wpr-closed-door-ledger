"""The phase 2 minutes hand-check, kept blind: the sheet has no automated answers.

    python handcheck.py --quarter 2026Q3      # writes archive/handcheck/2026-Q3/
    python handcheck.py --quarter 2026Q3 --dry-run

Reads archive/data/ (run build.py first) and writes:
    sheet_noticed.csv      every meeting in the quarter that noticed a closed session:
                           editors read the minutes and fill held, motion_recorded,
                           vote_record, exemption_in_minutes, reconvened.
    sheet_unnoticed.csv    every other meeting in the quarter with minutes: editors
                           mark whether the minutes record a closed session anyway.
    automated.json         minutes.py's answers for the same rows. Open it only after
                           both sheets are filled in.
    README.md              how to fill the sheets.

The sheets carry links, never text from the minutes, which name private people.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import bodies
import quarters
import store

FIELDS = ["held", "motion_recorded", "vote_record", "exemption_in_minutes", "reconvened"]
NOTICED_COLUMNS = ["meeting_id", "meeting_date", "jurisdiction", "bodies", "noticed_exemptions", "notice_url",
                   "minutes_url", *FIELDS, "checked_by", "note"]
UNNOTICED_COLUMNS = ["meeting_id", "meeting_date", "jurisdiction", "bodies", "notice_url", "minutes_url",
                     "closed_session_in_minutes", "checked_by", "note"]

README = """# Minutes hand-check, {quarter}

Two sheets, one row per meeting. Open each `minutes_url`, read the minutes, and fill the blank columns.
Don't open `automated.json` until both sheets are done: it holds the machine's answers, and the point
is to see where they differ from yours.

## sheet_noticed.csv ({noticed} meetings that noticed a closed session)
| Column | Fill with |
|---|---|
| held | yes / no: the minutes show the body convened in closed session |
| motion_recorded | yes / no: a motion to convene in closed session is recorded |
| vote_record | per_member (each member's vote), tally ("5-0"), unanimous, result_only ("Motion passed."), not_shown, or none (no motion) |
| exemption_in_minutes | yes / no: the minutes cite an s. 19.85(1) letter for the closed session |
| reconvened | yes / no: the minutes show the body reconvened in open session |

A row with no `minutes_url` had no minutes posted when the sheet was made: write "no minutes" in the note.

## sheet_unnoticed.csv ({unnoticed} other meetings with minutes)
`closed_session_in_minutes`: yes / no. These meetings' posted agendas noticed no closed session.
A yes is a lead for NOTES.md (unvetted), not a finding.

Never copy names or wording from the minutes into either sheet.
"""


def rows(config: dict, meetings: list[dict], items: list[dict], quarter: str) -> tuple[list[dict], list[dict], dict]:
    index = quarters.body_index(config)
    exemptions: dict[str, list[str]] = {}
    for item in items:
        letters = item["exemptions"] or (["19.86"] if not item["no_citation"] else ["none cited"])
        exemptions.setdefault(item["meeting_id"], [])
        exemptions[item["meeting_id"]] += [x for x in letters if x not in exemptions[item["meeting_id"]]]
    noticed, unnoticed, automated = [], [], {}
    for m in meetings:
        if not quarters.in_quarter(m["meeting_date"], quarter) or m["canceled"]:
            continue
        base = {"meeting_id": m["id"], "meeting_date": m["meeting_date"], "jurisdiction": m["jurisdiction"],
                "bodies": "; ".join(index[b]["name"] for b in m["bodies"]), "notice_url": m["notice_url"],
                "minutes_url": m["minutes_url"] or ""}
        if m["closed_item_count"]:
            noticed.append({**base, "noticed_exemptions": ", ".join(exemptions[m["id"]]),
                            **{f: "" for f in FIELDS}, "checked_by": "", "note": ""})
            automated[m["id"]] = m["minutes"]
        elif m["minutes"]:
            unnoticed.append({**base, "closed_session_in_minutes": "", "checked_by": "", "note": ""})
            automated[m["id"]] = {"closed_session_in_minutes": m["minutes"]["motion_recorded"],
                                  "pages": m["minutes_convene_pages"]}
    return noticed, unnoticed, automated


def _write_csv(path: Path, columns: list[str], data: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quarter", required=True, help="e.g. 2026Q3")
    parser.add_argument("--archive", type=Path, default=store.ARCHIVE)
    parser.add_argument("--dry-run", action="store_true", help="print the row counts; write nothing")
    args = parser.parse_args(argv)
    data = args.archive / "data"
    meetings = json.loads((data / "meetings.json").read_text(encoding="utf-8"))
    items = json.loads((data / "closed_sessions.json").read_text(encoding="utf-8"))
    noticed, unnoticed, automated = rows(bodies.load(), meetings, items, args.quarter)
    print(f"{args.quarter}: {len(noticed)} meetings noticed a closed session; {len(unnoticed)} others have minutes")
    if args.dry_run:
        return 0
    out = args.archive / "handcheck" / args.quarter.replace("Q", "-Q")
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "sheet_noticed.csv", NOTICED_COLUMNS, noticed)
    _write_csv(out / "sheet_unnoticed.csv", UNNOTICED_COLUMNS, unnoticed)
    (out / "automated.json").write_text(json.dumps(automated, indent=1) + "\n", encoding="utf-8")
    (out / "README.md").write_text(README.format(quarter=args.quarter, noticed=len(noticed),
                                                 unnoticed=len(unnoticed)), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
