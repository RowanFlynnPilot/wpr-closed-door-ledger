"""The archive's on-disk layout. Append-only: file versions are never removed.

    archive/meetings/<jurisdiction>/<meeting_id>/meeting.json
    archive/meetings/<jurisdiction>/<meeting_id>/<kind>-<sha12>.<pdf|html>
    archive/meetings/<jurisdiction>/<meeting_id>/<kind>-<sha12>.txt

meeting.json holds the latest listing, when the meeting was first and last
listed, and every distinct file version (by sha256) with the time it was first
seen. Weston notices are archived as their first 5 pages; the version's sha256,
size and pages describe the full packet.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from adapters.base import DocFile, KnownFile, Meeting, Unchanged

ARCHIVE = Path(__file__).with_name("archive")
MAX_FILE = 45 * 1024 * 1024


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def meeting_dir(root: Path, jurisdiction: str, meeting_id: str) -> Path:
    return root / "meetings" / jurisdiction / meeting_id


def load(root: Path, jurisdiction: str, meeting_id: str) -> dict | None:
    path = meeting_dir(root, jurisdiction, meeting_id) / "meeting.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save(root: Path, record: dict) -> None:
    folder = meeting_dir(root, record["jurisdiction"], record["meeting_id"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meeting.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def all_records(root: Path, jurisdiction: str | None = None) -> list[dict]:
    pattern = f"meetings/{jurisdiction or '*'}/*/meeting.json"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob(pattern))]


def new_record(meeting: Meeting, seen_at: str) -> dict:
    return {
        "id": meeting.id, "jurisdiction": meeting.jurisdiction, "meeting_id": meeting.meeting_id,
        "listing": {}, "first_listed": seen_at, "last_listed": seen_at, "last_fetched": None,
        "source_status": "live", "file_status": {}, "versions": [],
    }


def update_listing(record: dict, meeting: Meeting, seen_at: str) -> None:
    listing = asdict(meeting)
    del listing["jurisdiction"], listing["meeting_id"]
    record["listing"] = listing
    record["last_listed"] = seen_at
    record["source_status"] = "live"


def versions(record: dict, kind: str) -> list[dict]:
    return [v for v in record["versions"] if v["kind"] == kind]


def known_files(record: dict) -> dict[str, KnownFile]:
    known: dict[str, KnownFile] = {}
    for kind in ("notice", "minutes"):
        latest = versions(record, kind)[-1:]
        if latest:
            v = latest[0]
            known[kind] = KnownFile(url=v["url"], sha256=v["sha256"], size=v["size"], last_modified=v["last_modified"])
    return known


def apply_document(root: Path, record: dict, kind: str, doc: DocFile | Unchanged | None, seen_at: str) -> bool:
    """Record what the platform serves now for one kind. True when a new version was archived."""
    if doc is None:
        if versions(record, kind):
            record["file_status"][kind] = "removed"
        return False
    record["file_status"][kind] = "live"
    if isinstance(doc, Unchanged) or any(v["sha256"] == doc.sha256 for v in versions(record, kind)):
        return False
    folder = meeting_dir(root, record["jurisdiction"], record["meeting_id"])
    # An HTML page's chrome changes on its own (BoardBook's copyright years and asset
    # versions such as "All.27.css"); its document is the agenda text. Same text, same version.
    if doc.extension == "html" and any((folder / v["text_file"]).read_text(encoding="utf-8") == doc.text
                                       for v in versions(record, kind)):
        return False
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{kind}-{doc.sha256[:12]}"
    # The archive may hold no file over 50 MB; above MAX_FILE the version keeps
    # its text, sha256, size and URL, but not the file itself.
    stored = len(doc.content) <= MAX_FILE
    if stored:
        (folder / f"{stem}.{doc.extension}").write_bytes(doc.content)
    (folder / f"{stem}.txt").write_text(doc.text, encoding="utf-8")
    record["versions"].append({
        "kind": kind, "sha256": doc.sha256, "seen_at": seen_at, "url": doc.url,
        "file": f"{stem}.{doc.extension}" if stored else None, "text_file": f"{stem}.txt",
        "text_source": doc.text_source, "ocr_pages": doc.ocr_pages,
        "size": doc.size, "pages": doc.pages, "last_modified": doc.last_modified,
    })
    return True
