"""Fetch listings and documents from each platform into the archive.

    python fetch.py --since 2024-01-01      # the one-time local backfill
    python fetch.py --recent                # nightly: the last 90 days and upcoming meetings

A meeting's documents are fetched when it starts within the re-check window
(the last 90 days, or later) or has never been fetched; so an interrupted
backfill resumes where it stopped, and older meetings are fetched once.
Jurisdictions run in parallel (one thread each); polite.py keeps each host
to one request a second. Titles a jurisdiction excludes (quorum notices) are
listed but not fetched. Every error is raised once all threads finish, and the
run fails.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import adapters
import bodies
import store

RECHECK_DAYS = 90
STALE_DAYS = 60
SKIP_PLATFORMS = {"marathon_county"}    # the residential machine runs this one (see CLAUDE.md)


def recheck_from(today: date) -> date:
    return today - timedelta(days=RECHECK_DAYS)


def needs_fetch(record: dict, start: str, today: date) -> bool:
    return record["last_fetched"] is None or start[:10] >= recheck_from(today).isoformat()


def check_not_stale(jurisdiction: str, meetings: list, today: date) -> None:
    """A listing with no meeting in the last 60 days means the adapter or the site broke."""
    floor = (today - timedelta(days=STALE_DAYS)).isoformat()
    if not any(floor <= m.meeting_date <= today.isoformat() for m in meetings):
        raise RuntimeError(f"{jurisdiction}: no meetings listed for the last {STALE_DAYS} days")


def mark_removed(root: Path, jurisdiction: str, listed: set[str], since: date, today: date) -> int:
    """Archived meetings inside the listed window that the platform no longer lists."""
    removed = 0
    for record in store.all_records(root, jurisdiction):
        start = record["listing"].get("start", "")[:10]
        if since.isoformat() <= start <= today.isoformat() and record["id"] not in listed \
                and record["source_status"] != "removed":
            record["source_status"] = "removed"
            store.save(root, record)
            removed += 1
    return removed


def run_jurisdiction(root: Path, config: dict, jurisdiction: str, since: date, today: date,
                     dry_run: bool) -> str:
    jur = config["jurisdictions"][jurisdiction]
    adapter = adapters.for_platform(jur["platform"])
    meetings = adapter.list_meetings(jurisdiction, jur, since)
    check_not_stale(jurisdiction, meetings, today)
    todo = []
    for meeting in meetings:
        record = store.load(root, jurisdiction, meeting.meeting_id)
        if record is None or needs_fetch(record, meeting.start, today):
            todo.append((meeting, record))
    if dry_run:
        return f"{jurisdiction}: {len(meetings)} listed, {len(todo)} would be fetched"
    new_versions = excluded = 0
    for i, (meeting, record) in enumerate(todo, 1):
        seen_at = store.now_utc()
        record = record or store.new_record(meeting, seen_at)
        store.update_listing(record, meeting, seen_at)
        if _excluded(config, meeting):
            # Not marked fetched: if bodies.yaml later keeps this meeting, the next run fetches it.
            excluded += 1
        else:
            docs = adapter.fetch_documents(meeting, store.known_files(record))
            new_versions += store.apply_document(root, record, "notice", docs.notice, seen_at)
            new_versions += store.apply_document(root, record, "minutes", docs.minutes, seen_at)
            record["last_fetched"] = seen_at
        store.save(root, record)
        if i % 25 == 0:
            print(f"  {jurisdiction}: {i}/{len(todo)}", flush=True)
    removed = mark_removed(root, jurisdiction, {m.id for m in meetings}, since, today)
    return (f"{jurisdiction}: {len(meetings)} listed, {len(todo)} fetched, {excluded} excluded, "
            f"{new_versions} new file versions, {removed} newly removed")


def _excluded(config: dict, meeting) -> bool:
    try:
        return bodies.match(config, meeting.jurisdiction, meeting.meeting_id, meeting.title,
                            meeting.category_id).excluded
    except (bodies.UnmatchedMeeting, bodies.AmbiguousMeeting):
        return False     # fetched anyway; build.py fails until bodies.yaml classifies it


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    window = parser.add_mutually_exclusive_group(required=True)
    window.add_argument("--since", type=date.fromisoformat, help="list meetings from this date (backfill)")
    window.add_argument("--recent", action="store_true", help=f"the last {RECHECK_DAYS} days and upcoming")
    parser.add_argument("--jurisdiction", action="append", help="limit to these jurisdictions")
    parser.add_argument("--archive", type=Path, default=store.ARCHIVE)
    parser.add_argument("--dry-run", action="store_true", help="list only; write nothing")
    args = parser.parse_args(argv)

    config = bodies.load()
    today = date.today()
    since = recheck_from(today) if args.recent else args.since
    names = args.jurisdiction or [k for k, j in config["jurisdictions"].items()
                                  if j["platform"] not in SKIP_PLATFORMS]
    if not args.archive.is_dir():
        raise SystemExit(f"{args.archive} is missing: check out wpr-closed-door-archive there")
    failures = []
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        futures = {n: pool.submit(run_jurisdiction, args.archive, config, n, since, today, args.dry_run)
                   for n in names}
        for name, future in futures.items():
            try:
                print(future.result(), flush=True)
            except Exception:
                failures.append(name)
                print(f"{name}: FAILED\n{traceback.format_exc()}", file=sys.stderr, flush=True)
    if failures:
        print(f"failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
