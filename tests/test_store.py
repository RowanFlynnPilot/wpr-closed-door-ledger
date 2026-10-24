"""store.py, fetch.py's scheduling rules and archive_check.py, offline."""
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import archive_check  # noqa: E402
import fetch  # noqa: E402
import store  # noqa: E402
from adapters.base import DocFile, Meeting, Unchanged  # noqa: E402

MEETING = Meeting("wausau", "130", "Economic Development Committee Regular Meeting",
                  "2026-01-06T17:00", "https://example.test/agenda/130", None)


def _doc(content: bytes, kind: str = "notice") -> DocFile:
    import hashlib
    return DocFile(kind, "https://example.test/f", content, "pdf", hashlib.sha256(content).hexdigest(),
                   "text", "text_layer", len(content), 1)


def test_versions_are_appended_once(tmp_path):
    record = store.new_record(MEETING, "2026-01-01T00:00:00Z")
    store.update_listing(record, MEETING, "2026-01-01T00:00:00Z")
    assert store.apply_document(tmp_path, record, "notice", _doc(b"v1"), "2026-01-01T00:00:00Z")
    assert not store.apply_document(tmp_path, record, "notice", _doc(b"v1"), "2026-01-02T00:00:00Z")
    assert store.apply_document(tmp_path, record, "notice", _doc(b"v2"), "2026-01-03T00:00:00Z")
    sha = record["versions"][-1]["sha256"]
    assert not store.apply_document(tmp_path, record, "notice", Unchanged("notice", sha), "2026-01-04T00:00:00Z")
    assert [v["seen_at"][:10] for v in record["versions"]] == ["2026-01-01", "2026-01-03"]
    assert store.known_files(record)["notice"]["sha256"] == sha
    folder = store.meeting_dir(tmp_path, "wausau", "130")
    assert (folder / f"notice-{sha[:12]}.pdf").read_bytes() == b"v2"
    store.apply_document(tmp_path, record, "notice", None, "2026-01-05T00:00:00Z")
    assert record["file_status"]["notice"] == "removed" and len(record["versions"]) == 2
    store.save(tmp_path, record)
    assert store.load(tmp_path, "wausau", "130") == record


def test_fetch_schedule():
    today = date(2026, 10, 23)
    fetched = {"last_fetched": "2026-10-01T00:00:00Z"}
    assert fetch.needs_fetch({"last_fetched": None}, "2024-01-05", today)
    assert not fetch.needs_fetch(fetched, "2025-03-01T18:00", today)
    assert fetch.needs_fetch(fetched, "2026-07-25", today)            # inside 90 days
    assert fetch.needs_fetch(fetched, "2026-11-02T18:00", today)      # upcoming
    fetch.check_not_stale("wausau", [replace(MEETING, start="2026-09-01")], today)
    with pytest.raises(RuntimeError, match="no meetings"):
        fetch.check_not_stale("wausau", [MEETING], today)


def test_mark_removed(tmp_path):
    record = store.new_record(MEETING, "2026-01-01T00:00:00Z")
    store.update_listing(record, MEETING, "2026-01-01T00:00:00Z")
    store.save(tmp_path, record)
    assert fetch.mark_removed(tmp_path, "wausau", {"wausau:130"}, date(2026, 1, 1), date(2026, 2, 1)) == 0
    assert fetch.mark_removed(tmp_path, "wausau", set(), date(2026, 1, 7), date(2026, 2, 1)) == 0   # outside window
    assert fetch.mark_removed(tmp_path, "wausau", set(), date(2026, 1, 1), date(2026, 2, 1)) == 1
    assert store.load(tmp_path, "wausau", "130")["source_status"] == "removed"


def test_archive_check(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@example.test")
    git("config", "user.name", "t")
    (tmp_path / "small.txt").write_bytes(b"x" * 100)
    (tmp_path / "big.pdf").write_bytes(b"y" * 5000)
    git("add", "-A")
    git("commit", "-q", "-m", "t")
    assert archive_check.largest_files(tmp_path)[0] == (5000, "big.pdf")
    assert archive_check.problems(tmp_path) == []
    monkeypatch.setattr(archive_check, "MAX_FILE", 1000)
    assert any("big.pdf" in p for p in archive_check.problems(tmp_path))
    (tmp_path / "new.txt").write_text("uncommitted")
    assert any("uncommitted" in p for p in archive_check.problems(tmp_path))


def test_files_over_the_limit_keep_only_text(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MAX_FILE", 3)
    record = store.new_record(MEETING, "2026-01-01T00:00:00Z")
    assert store.apply_document(tmp_path, record, "minutes", _doc(b"big file", "minutes"), "2026-01-01T00:00:00Z")
    v = record["versions"][0]
    folder = store.meeting_dir(tmp_path, "wausau", "130")
    assert v["file"] is None and (folder / v["text_file"]).exists() and v["size"] == 8
    assert not list(folder.glob("*.pdf"))
