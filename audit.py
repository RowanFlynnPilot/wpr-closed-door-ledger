"""The quarterly records audit: one request per records custodian, from audit/request_template.md.

    python audit.py --quarter 2026Q3          # writes archive/audit/2026-Q3/
    python audit.py --quarter 2026Q3 --dry-run

Reads archive/data/closed_sessions.json (run build.py first). Each request
lists every closed session noticed in the quarter for a body whose records
that custodian keeps (bodies.yaml `custodian:`, defaulting to the
jurisdiction). Sessions under s. 19.86 alone are left out: the open meetings
law does not apply to bargaining negotiations, so s. 19.88(3) records don't
exist for them. The bracketed fields the template leaves for the requester
([RECORDS CUSTODIAN], [EMAIL], [AMOUNT], [NAME], [PHONE]) stay as they are.

Nothing is filed: the requests are written for an editor to send and log in
the Records Ledger.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import bodies
import quarters
import store

TEMPLATE = Path(__file__).with_name("audit") / "request_template.md"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def requests(config: dict, items: list[dict], quarter: str) -> dict[str, list[dict]]:
    """Custodian -> the quarter's noticed closed sessions for bodies it keeps records for."""
    index = quarters.body_index(config)
    grouped: dict[str, list[dict]] = {}
    for item in items:
        bargaining_only = not item["exemptions"] and not item["no_citation"]
        if not quarters.in_quarter(item["meeting_date"], quarter) or bargaining_only:
            continue
        for custodian in dict.fromkeys(index[b]["custodian"] for b in item["bodies"]):
            grouped.setdefault(custodian, []).append(item)
    return dict(sorted(grouped.items()))


def list_line(item: dict, index: dict, notice_url: str) -> str:
    names = " and ".join(index[b]["name"] for b in item["bodies"])
    cited = item["citation_raw"] or "no statute cited"
    wording = " ".join(item["item_text"].split())
    return f"- {item['meeting_date']} | {names} | {wording} | {cited} | {notice_url}"


def fill(template: str, custodian: str, quarter: str, lines: list[str]) -> str:
    start, end = quarters.quarter_range(quarter)
    year, q = quarter.split("Q")
    body = template.split("-->", 2)[-1].lstrip() if template.startswith("<!--") else template
    filled = (body.replace("[CUSTODIAN]", custodian)
                  .replace("[QUARTER]", f"Q{q} {year}")
                  .replace("[START DATE]", f"{start:%B} {start.day}, {start.year}")
                  .replace("[END DATE]", f"{end:%B} {end.day}, {end.year}"))
    marker = re.search(r"\[GENERATED LIST[^\]]*\]", filled)
    return filled[: marker.start()] + "\n".join(lines) + filled[marker.end():]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quarter", required=True, help="e.g. 2026Q3")
    parser.add_argument("--archive", type=Path, default=store.ARCHIVE)
    parser.add_argument("--dry-run", action="store_true", help="print the request counts; write nothing")
    args = parser.parse_args(argv)
    config = bodies.load()
    index = quarters.body_index(config)
    items = json.loads((args.archive / "data" / "closed_sessions.json").read_text(encoding="utf-8"))
    meetings = {m["id"]: m for m in json.loads((args.archive / "data" / "meetings.json").read_text(encoding="utf-8"))}
    template = TEMPLATE.read_text(encoding="utf-8")
    grouped = requests(config, items, args.quarter)
    out = args.archive / "audit" / args.quarter.replace("Q", "-Q")
    summary = [f"# Records audit requests, {args.quarter}", "",
               "Not filed. Each file is one request; fill the bracketed requester fields, send it, "
               "and log it in the Records Ledger.", "",
               "| Custodian | Closed sessions | File |", "|---|---|---|"]
    for custodian, rows in grouped.items():
        lines = [list_line(i, index, meetings[i["meeting_id"]]["notice_url"]) for i in rows]
        name = f"{slug(custodian)}.md"
        summary.append(f"| {custodian} | {len(rows)} | {name} |")
        print(f"{custodian}: {len(rows)} closed sessions")
        if not args.dry_run:
            out.mkdir(parents=True, exist_ok=True)
            (out / name).write_text(fill(template, custodian, args.quarter, lines), encoding="utf-8")
    if "unknown" in grouped:
        summary += ["", "**Custodian unknown:** the bodies under \"unknown\" have an open `confirm:` "
                    "question in bodies.yaml about who keeps their records. Settle it before sending."]
    if not args.dry_run:
        out.mkdir(parents=True, exist_ok=True)
        (out / "README.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
