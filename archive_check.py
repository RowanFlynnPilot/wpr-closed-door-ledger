"""Run before every archive push: no file over 50 MB, and the repo under 1 GB, or stop.

    python archive_check.py              # after committing in archive/, before pushing
    python archive_check.py --push       # check, then push if both limits hold

The repo's size is git's own count of its objects (loose and packed), which
is what GitHub stores.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import store

MAX_FILE = 50 * 1024 * 1024
MAX_REPO = 1024 * 1024 * 1024


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def largest_files(root: Path, n: int = 1) -> list[tuple[int, str]]:
    """The n largest files in HEAD, as (bytes, path)."""
    rows = []
    for line in git(root, "ls-tree", "-r", "-l", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        size = meta.split()[3]
        if size != "-":
            rows.append((int(size), path))
    return sorted(rows, reverse=True)[:n]


def repo_bytes(root: Path) -> int:
    counts = dict(line.split(": ") for line in git(root, "count-objects", "-v").splitlines())
    return (int(counts["size"]) + int(counts["size-pack"])) * 1024


def problems(root: Path) -> list[str]:
    found = []
    if git(root, "status", "--porcelain").strip():
        found.append("uncommitted changes in the archive: commit before checking")
    for size, path in largest_files(root, 20):
        if size > MAX_FILE:
            found.append(f"{path} is {size / 2**20:.1f} MB (limit 50 MB)")
    total = repo_bytes(root)
    if total >= MAX_REPO:
        found.append(f"repo is {total / 2**30:.2f} GB (limit 1 GB)")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, default=store.ARCHIVE)
    parser.add_argument("--push", action="store_true", help="push when the checks pass")
    parser.add_argument("--dry-run", action="store_true", help="check only, even with --push")
    args = parser.parse_args(argv)
    found = problems(args.archive)
    size, path = (largest_files(args.archive) or [(0, "-")])[0]
    print(f"archive: {repo_bytes(args.archive) / 2**20:.1f} MB; largest file {path} ({size / 2**20:.2f} MB)")
    if found:
        print("STOP, not pushing:\n  " + "\n  ".join(found), file=sys.stderr)
        return 1
    if args.push and not args.dry_run:
        git(args.archive, "push", "origin", "HEAD")
        print("pushed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
