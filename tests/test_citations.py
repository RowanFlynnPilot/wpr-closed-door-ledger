"""Run: python -m pytest tests  (or: python tests/test_citations.py)"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from citations import parse  # noqa: E402
from purpose import purpose_text  # noqa: E402

CASES = json.loads((ROOT / "tests" / "fixtures" / "citations.json").read_text(encoding="utf-8"))["cases"]


def test_citations():
    failures = []
    for case in CASES:
        got = parse(case["text"])
        want = case["expected"]
        if (got.exemptions, got.cites_subsection_1, got.other_citations) != (
                want["exemptions"], want["cites_subsection_1"], want["other_citations"]):
            failures.append((case["id"], got, want))
    assert not failures, failures


def test_purpose():
    failures = []
    for case in CASES:
        got = purpose_text(case["text"])
        want = case["expected"]["purpose_contains"]
        ok = got in (None, "") if want is None else (got is not None and want.lower() in got.lower())
        if not ok:
            failures.append((case["id"], got, want))
    assert not failures, failures


if __name__ == "__main__":
    test_citations()
    test_purpose()
    print(f"ok: {len(CASES)} fixtures")
