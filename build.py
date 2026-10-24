"""Build the ledger from the archive. Reads only archive/; makes no requests.

    python build.py                 # internal files to archive/data/, public projection to site/
    python build.py --dry-run       # build and check everything, write nothing

Fails (exit 1) on any meeting title bodies.yaml doesn't classify, and on any
review in reviews.json whose key matches no item.

Internal files (archive/data/, every field): meetings.json, closed_sessions.json, and
unnoticed_closed_sessions.json (minutes that record a closed session the notice never listed).
Public projection (site/data/, whitelisted fields only): closed_sessions.json
and .csv, meetings.json and .csv, bodies.json; plus the archived notice copies
that published items link to (site/archive/).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import bodies
import extract
import minutes as minutes_rules
import store

CENTRAL = ZoneInfo("America/Chicago")
ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"

PUBLIC_ITEM_FIELDS = ["id", "meeting_id", "bodies", "meeting_date", "item_text", "citation_raw", "exemptions",
                      "other_citations", "purpose_text", "notice_url", "archive_url", "minutes", "review_note"]
# The minutes rules (minutes.py) are published only once the Q3 2026 hand-check
# has validated them against what editors read in the minutes.
PUBLISH_MINUTES = False
PUBLIC_MEETING_FIELDS = ["id", "bodies", "jurisdiction", "meeting_date", "canceled", "notice_url", "notice_versions",
                         "source_status", "closed_item_count", "minutes_url"]


class BuildError(Exception):
    pass


# --- which notice version the items come from --------------------------------

def _local_date(seen_at: str) -> str:
    return datetime.strptime(seen_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(CENTRAL).date().isoformat()


def _seen_before_start(version: dict, start: str) -> bool:
    """Seen before the meeting started. A date-only start counts the whole meeting day."""
    if len(start) == 10:
        return _local_date(version["seen_at"]) <= start
    started = datetime.fromisoformat(start).replace(tzinfo=CENTRAL).astimezone(timezone.utc)
    seen = datetime.strptime(version["seen_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return seen < started


def items_version(notices: list[dict], start: str) -> dict | None:
    """The latest notice version seen before the meeting started; the earliest if none was (backfill)."""
    before = [v for v in notices if _seen_before_start(v, start)]
    return before[-1] if before else (notices[0] if notices else None)


def changed_after_meeting(root: Path, record: dict) -> bool:
    """A notice version whose text differs from the one before it, first seen after the meeting date.

    The first archived version never sets it, so backfilled history never does.
    """
    notices = store.versions(record, "notice")
    date = record["listing"]["start"][:10]
    folder = store.meeting_dir(root, record["jurisdiction"], record["meeting_id"])
    for previous, version in zip(notices, notices[1:]):
        if _local_date(version["seen_at"]) > date and \
                (folder / version["text_file"]).read_text(encoding="utf-8") != \
                (folder / previous["text_file"]).read_text(encoding="utf-8"):
            return True
    return False


# --- internal files ------------------------------------------------------------

def item_text_source(version: dict, page: int) -> str:
    if version["text_source"] == "html":
        return "html"
    return "ocr" if page in version["ocr_pages"] else "text_layer"


def build_meeting(root: Path, config: dict, record: dict) -> tuple[dict, list[dict]] | None:
    """The meetings.json row and closed_sessions.json rows for one archived meeting; None if excluded."""
    listing = record["listing"]
    match = bodies.match(config, record["jurisdiction"], record["meeting_id"], listing["title"],
                         listing["category_id"])
    if match.excluded:
        return None
    notices = store.versions(record, "notice")
    minutes = store.versions(record, "minutes")
    meeting = {
        "id": record["id"], "bodies": match.bodies, "jurisdiction": record["jurisdiction"],
        "title": listing["title"], "start": listing["start"], "meeting_date": listing["start"][:10],
        "canceled": listing["canceled"] or match.canceled, "notice_url": listing["notice_url"],
        "notice_versions": len(notices), "changed_after_meeting": changed_after_meeting(root, record),
        "source_status": record["source_status"], "notices_reconvene": False, "closed_item_count": 0,
        "minutes_url": listing["minutes_url"], "minutes_versions": len(minutes),
        "notice_file": None, "minutes": None, "minutes_convene_pages": [],
    }
    folder = store.meeting_dir(root, record["jurisdiction"], record["meeting_id"])
    if minutes:
        # The latest minutes version: minutes get amended (Kronenwetter, Jan 12, 2026).
        facts = minutes_rules.analyze((folder / minutes[-1]["text_file"]).read_text(encoding="utf-8"),
                                      len(minutes))
        meeting["minutes"] = minutes_rules.as_record(facts)
        meeting["minutes_convene_pages"] = list(facts.convene_pages)
    version = items_version(notices, listing["start"])
    items: list[dict] = []
    if version:
        text = (folder / version["text_file"]).read_text(encoding="utf-8")
        if version["file"]:      # None when the file was too large to archive (store.MAX_FILE)
            meeting["notice_file"] = f"meetings/{record['jurisdiction']}/{record['meeting_id']}/{version['file']}"
        meeting["notices_reconvene"] = extract.notices_reconvene(text)
        for found in extract.closed_items(text):
            row = extract.item_record(meeting, found, item_text_source(version, found.page))
            row["minutes"] = meeting["minutes"]
            if all(row["id"] != other["id"] for other in items):
                items.append(row)
        meeting["closed_item_count"] = len(items)
    return meeting, items


def build_internal(root: Path, config: dict) -> tuple[list[dict], list[dict]]:
    meetings: list[dict] = []
    items: list[dict] = []
    errors: list[str] = []
    window = str(config["window_start"])
    for record in store.all_records(root):
        if record["listing"]["start"][:10] < window:
            continue
        try:
            built = build_meeting(root, config, record)
        except (bodies.UnmatchedMeeting, bodies.AmbiguousMeeting) as e:
            errors.append(str(e))
            continue
        if built:
            meetings.append(built[0])
            items.extend(built[1])
    if errors:
        raise BuildError("bodies.yaml does not classify these meetings:\n  " + "\n  ".join(errors))
    meetings.sort(key=lambda m: (m["meeting_date"], m["id"]))
    items.sort(key=lambda i: (i["meeting_date"], i["id"]))
    return meetings, items


def unnoticed_sessions(meetings: list[dict]) -> list[dict]:
    """Meetings whose minutes record a motion to convene in closed session, but whose
    archived notice has no closed-session item. Leads for editors; never published."""
    return [{"meeting_id": m["id"], "bodies": m["bodies"], "meeting_date": m["meeting_date"],
             "notice_url": m["notice_url"], "notice_versions": m["notice_versions"],
             "minutes_url": m["minutes_url"], "minutes_pages": m["minutes_convene_pages"],
             "held": m["minutes"]["held"]}
            for m in meetings
            if m["minutes"] and m["minutes"]["motion_recorded"] and not m["closed_item_count"]]


def check_reviews(reviews: dict, items: list[dict]) -> None:
    ids = {i["id"] for i in items}
    orphans = sorted(k for k in reviews if not k.startswith("_") and k not in ids)
    if orphans:
        raise BuildError("reviews.json keys that match no item:\n  " + "\n  ".join(orphans))
    for key, review in reviews.items():
        if not key.startswith("_") and review["decision"] not in ("confirmed", "flagged", "withhold"):
            raise BuildError(f"reviews.json {key}: decision must be confirmed, flagged or withhold")


# --- public projection ---------------------------------------------------------

def unconfirmed_bodies(config: dict) -> set[str]:
    return {b["key"] for j in config["jurisdictions"].values() for b in j["bodies"] if "confirm" in b}


def public_projection(config: dict, meetings: list[dict], items: list[dict], reviews: dict) -> dict:
    hidden = unconfirmed_bodies(config)
    by_id = {m["id"]: m for m in meetings}
    withheld_meetings = {i["meeting_id"] for i in items if reviews.get(i["id"], {}).get("decision") == "withhold"}
    public_items = []
    for item in items:
        review = reviews.get(item["id"], {})
        published_bodies = [b for b in item["bodies"] if b not in hidden]
        if review.get("decision") == "withhold" or not published_bodies:
            continue
        meeting = by_id[item["meeting_id"]]
        row = {**item, "bodies": published_bodies,
               "minutes": item["minutes"] if PUBLISH_MINUTES else None,
               "notice_url": "" if item["meeting_id"] in withheld_meetings else meeting["notice_url"],
               "archive_url": "" if item["meeting_id"] in withheld_meetings or not meeting["notice_file"]
               else "archive/" + meeting["notice_file"].removeprefix("meetings/"),
               "review_note": review.get("note") if review.get("decision") in ("confirmed", "flagged") else None}
        public_items.append({k: row[k] for k in PUBLIC_ITEM_FIELDS})
    public_meetings = []
    for meeting in meetings:
        published_bodies = [b for b in meeting["bodies"] if b not in hidden]
        if not published_bodies:
            continue
        withheld = meeting["id"] in withheld_meetings
        row = {**meeting, "bodies": published_bodies, "notice_url": "" if withheld else meeting["notice_url"],
               "closed_item_count": sum(1 for i in public_items if i["meeting_id"] == meeting["id"])}
        public_meetings.append({k: row[k] for k in PUBLIC_MEETING_FIELDS})
    public_bodies = [{"key": b["key"], "name": b["name"], "jurisdiction": key, "jurisdiction_name": j["name"]}
                     for key, j in config["jurisdictions"].items() for b in j["bodies"] if b["key"] not in hidden]
    covered = sorted({m["jurisdiction"] for m in public_meetings})
    meta = {"built_at": store.now_utc(), "window_start": str(config["window_start"]),
            "jurisdictions": [config["jurisdictions"][j]["name"] for j in covered],
            "unpublished_bodies": len(hidden), "minutes_published": PUBLISH_MINUTES}
    return {"closed_sessions": public_items, "meetings": public_meetings, "bodies": public_bodies, "meta": meta}


def _csv(rows: list[dict], fields: list[str]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "; ".join(v) if isinstance(v, list) else
                         json.dumps(v) if isinstance(v, dict) else v for k, v in row.items()})
    return out.getvalue()


def _json(data) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def write_site(site: Path, root: Path, projection: dict) -> None:
    if site.exists():
        shutil.rmtree(site)
    web = ROOT / "web"
    if web.is_dir():
        shutil.copytree(web, site, ignore=shutil.ignore_patterns("dist", "node_modules", "*.md"))
    data = site / "data"
    data.mkdir(parents=True, exist_ok=True)
    for name in ("closed_sessions", "meetings"):
        (data / f"{name}.json").write_text(_json(projection[name]), encoding="utf-8")
    (data / "closed_sessions.csv").write_text(_csv(projection["closed_sessions"], PUBLIC_ITEM_FIELDS), encoding="utf-8")
    (data / "meetings.csv").write_text(_csv(projection["meetings"], PUBLIC_MEETING_FIELDS), encoding="utf-8")
    (data / "bodies.json").write_text(_json(projection["bodies"]), encoding="utf-8")
    (data / "meta.json").write_text(_json(projection["meta"]), encoding="utf-8")
    shutil.copyfile(ROOT / "bodies.yaml", site / "bodies.yaml")
    for path in sorted({i["archive_url"] for i in projection["closed_sessions"] if i["archive_url"]}):
        target = site / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / "meetings" / path.removeprefix("archive/"), target)


# --- summary -------------------------------------------------------------------

def summary(meetings: list[dict], items: list[dict]) -> str:
    lines = [f"{'jurisdiction':14} {'meetings':>8} {'w/ notice':>9} {'w/ closed':>9} {'items':>6} {'ok':>5} {'check':>6} {'19.86':>6}"]
    for jur in sorted({m["jurisdiction"] for m in meetings}):
        ms = [m for m in meetings if m["jurisdiction"] == jur]
        its = [i for i in items if i["meeting_id"].split(":")[0] == jur]
        t = Counter(i["triage"] for i in its)
        bargaining = sum(1 for i in its if not i["exemptions"] and not i["no_citation"])
        lines.append(f"{jur:14} {len(ms):8} {sum(1 for m in ms if m['notice_versions']):9} "
                     f"{sum(1 for m in ms if m['closed_item_count']):9} {len(its):6} {t['ok']:5} {t['check']:6} {bargaining:6}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, default=store.ARCHIVE)
    parser.add_argument("--site", type=Path, default=SITE)
    parser.add_argument("--dry-run", action="store_true", help="build and check; write nothing")
    args = parser.parse_args(argv)
    config = bodies.load()
    reviews_path = args.archive / "reviews.json"
    reviews = json.loads(reviews_path.read_text(encoding="utf-8")) if reviews_path.exists() else {}
    try:
        meetings, items = build_internal(args.archive, config)
        check_reviews(reviews, items)
    except BuildError as e:
        print(f"BUILD FAILED: {e}", file=sys.stderr)
        return 1
    projection = public_projection(config, meetings, items, reviews)
    print(summary(meetings, items))
    if args.dry_run:
        return 0
    data = args.archive / "data"
    data.mkdir(exist_ok=True)
    (data / "meetings.json").write_text(_json(meetings), encoding="utf-8")
    (data / "closed_sessions.json").write_text(_json(items), encoding="utf-8")
    (data / "unnoticed_closed_sessions.json").write_text(_json(unnoticed_sessions(meetings)), encoding="utf-8")
    write_site(args.site, args.archive, projection)
    print(f"wrote {data} and {args.site}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
