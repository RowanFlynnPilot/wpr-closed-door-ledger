"""Build the ledger from the archive. Reads only archive/; makes no requests.

    python build.py                 # internal files to archive/data/, public projection to site/
    python build.py --dry-run       # build and check everything, write nothing

Fails (exit 1) on any meeting title bodies.yaml doesn't classify, and on any
review in reviews.json whose key matches no item or whose redact text isn't in the item.

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
import documents
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


def _stamped_after_start(record: dict) -> bool:
    """The platform stamps the current version (Weston's "Posted/Amended") after the meeting began."""
    stamp = record["listing"].get("source", {}).get("listed_at")
    start = record["listing"]["start"]
    if not stamp:
        return False
    return stamp[:10] > start if len(start) == 10 else stamp > start[:16]


def readable_previous(record: dict) -> list[dict]:
    """The platform's earlier notice versions, oldest first, less any blank page it lists."""
    return [v for v in store.previous_versions(record, "notice") if v["text_source"] != "blank"]


def items_version(record: dict) -> dict | None:
    """The notice version the items come from: the latest seen before the meeting started.

    When none was (the backfill), the version the platform served then, unless the platform
    stamps it after the meeting and lists earlier versions: then the newest earlier one."""
    served = store.served_versions(record, "notice")
    start = record["listing"]["start"]
    before = [v for v in served if _seen_before_start(v, start)]
    if before:
        return before[-1]
    previous = readable_previous(record)
    if previous and _stamped_after_start(record):
        return previous[-1]
    return served[0] if served else None


def changed_after_meeting(root: Path, record: dict) -> bool:
    """A notice version whose text differs from the one before it, first seen after the meeting
    date; or a current version the platform stamps after the meeting whose text differs from
    the newest earlier version the platform lists.

    The first version the ledger saw is never compared with nothing, so backfilled history
    sets it only on the platform's own stamp.
    """
    served = store.served_versions(record, "notice")
    date = record["listing"]["start"][:10]
    folder = store.meeting_dir(root, record["jurisdiction"], record["meeting_id"])

    def text(version: dict) -> str:
        return (folder / version["text_file"]).read_text(encoding="utf-8")

    for previous, version in zip(served, served[1:]):
        if _local_date(version["seen_at"]) > date and text(version) != text(previous):
            return True
    previous = readable_previous(record)
    stamp = record["listing"].get("source", {}).get("listed_at")
    current = [v for v in served if stamp and v["last_modified"] == stamp]
    return bool(previous and current and _stamped_after_start(record) and text(current[-1]) != text(previous[-1]))


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
    version = items_version(record)
    items: list[dict] = []
    if version:
        text = (folder / version["text_file"]).read_text(encoding="utf-8")
        if extract.quorum_notice(text):     # a quorum notice under a committee's title: not a meeting
            return None
        if version["file"]:      # None when the file was too large to archive (store.MAX_FILE)
            meeting["notice_file"] = f"meetings/{record['jurisdiction']}/{record['meeting_id']}/{version['file']}"
        meeting["notices_reconvene"] = extract.notices_reconvene(text)
        for found in extract.closed_items(text):
            row = extract.item_record(meeting, found, item_text_source(version, found.page))
            row["minutes"] = meeting["minutes"]
            if len(match.bodies) > 1:
                names = {k: b["name"] for j in config["jurisdictions"].values() for b in j["bodies"]
                         if (k := b["key"]) in match.bodies}
                row["bodies"] = extract.section_bodies(text, found.item_text, names)
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


DECISIONS = ("confirmed", "flagged", "withhold", "redact")
REDACTED = "[name withheld]"
REDACTED_FIELDS = ("item_text", "purpose_text", "citation_raw")


def check_reviews(reviews: dict, items: list[dict]) -> None:
    by_id = {i["id"]: i for i in items}
    orphans = sorted(k for k in reviews if not k.startswith("_") and k not in by_id)
    if orphans:
        raise BuildError("reviews.json keys that match no item:\n  " + "\n  ".join(orphans))
    for key, review in reviews.items():
        if key.startswith("_"):
            continue
        if review["decision"] not in DECISIONS:
            raise BuildError(f"reviews.json {key}: decision must be one of {', '.join(DECISIONS)}")
        spans = review.get("redact")
        if review["decision"] == "redact":
            if not spans or not all(isinstance(s, str) and s.strip() for s in spans):
                raise BuildError(f'reviews.json {key}: a redact review lists the text to withhold in "redact"')
            missing = [s for s in spans if s not in by_id[key]["item_text"]]
            if missing:
                raise BuildError(f"reviews.json {key}: redact text not in the item's wording: {missing}")
        elif spans is not None:
            raise BuildError(f'reviews.json {key}: "redact" belongs only to a redact review')


def redacted(item: dict, review: dict) -> dict:
    """The item with each of a redact review's spans replaced in its wording, wherever it appears."""
    if review.get("decision") != "redact":
        return item
    row = dict(item)
    for field in REDACTED_FIELDS:
        if row[field]:
            for span in review["redact"]:
                row[field] = row[field].replace(span, REDACTED)
    return row


# --- public projection ---------------------------------------------------------

def unconfirmed_bodies(config: dict) -> set[str]:
    return {b["key"] for j in config["jurisdictions"].values() for b in j["bodies"] if "confirm" in b}


def public_projection(config: dict, meetings: list[dict], items: list[dict], reviews: dict) -> dict:
    hidden = unconfirmed_bodies(config)
    by_id = {m["id"]: m for m in meetings}
    def decided(decision: str) -> set[str]:
        return {i["meeting_id"] for i in items if reviews.get(i["id"], {}).get("decision") == decision}

    withheld_meetings = decided("withhold")
    # The archived copy holds the wording a redact review withholds, so the meeting's copy isn't
    # published; the link to the body's own posting stays.
    uncopied_meetings = withheld_meetings | decided("redact")
    public_items = []
    for item in items:
        review = reviews.get(item["id"], {})
        published_bodies = [b for b in item["bodies"] if b not in hidden]
        if review.get("decision") == "withhold" or not published_bodies:
            continue
        meeting = by_id[item["meeting_id"]]
        row = {**redacted(item, review), "bodies": published_bodies,
               "minutes": item["minutes"] if PUBLISH_MINUTES else None,
               "notice_url": "" if item["meeting_id"] in withheld_meetings else meeting["notice_url"],
               "archive_url": "" if item["meeting_id"] in uncopied_meetings or not meeting["notice_file"]
               else public_copy_path(meeting["notice_file"]),
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
        target.write_bytes(public_copy(root, path))


# --- the public archived copy -----------------------------------------------------
# What a reader gets from "Archived copy" is the agenda and nothing else. A PDF is
# cut after the page holding the agenda's closing Adjourn: Weston packets bind the
# previous meeting's minutes, with residents' names, right behind it. An HTML page
# (BoardBook, Municode) is published as its extracted text, so the platform's own
# scripts never run on the ledger's site.

def public_copy_path(notice_file: str) -> str:
    path = "archive/" + notice_file.removeprefix("meetings/")
    return path.rsplit(".", 1)[0] + ".txt" if path.endswith(".html") else path


def public_copy(root: Path, path: str) -> bytes:
    archived = root / "meetings" / path.removeprefix("archive/")
    text_file = archived.with_suffix(".txt")
    if path.endswith(".txt"):
        return text_file.read_bytes()
    agenda = extract.agenda_pages(text_file.read_text(encoding="utf-8"))
    return documents.first_pages(archived.read_bytes(), len(agenda))


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
