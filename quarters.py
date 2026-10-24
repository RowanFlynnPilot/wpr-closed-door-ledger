"""Quarters, body names and records custodians, shared by audit.py and handcheck.py."""
from __future__ import annotations

import re
from datetime import date


def quarter_range(quarter: str) -> tuple[date, date]:
    """("2026Q3") -> (2026-07-01, 2026-09-30)."""
    m = re.fullmatch(r"(\d{4})Q([1-4])", quarter)
    if not m:
        raise ValueError(f"quarter must look like 2026Q3, not {quarter!r}")
    year, q = int(m[1]), int(m[2])
    start = date(year, 3 * q - 2, 1)
    end = date(year + (q == 4), 1 if q == 4 else 3 * q + 1, 1)
    return start, date.fromordinal(end.toordinal() - 1)


def in_quarter(meeting_date: str, quarter: str) -> bool:
    start, end = quarter_range(quarter)
    return start.isoformat() <= meeting_date <= end.isoformat()


def body_index(config: dict) -> dict[str, dict]:
    """Body key -> {name, jurisdiction, custodian}. The custodian defaults to the jurisdiction."""
    return {b["key"]: {"name": b["name"], "jurisdiction": key,
                       "custodian": b.get("custodian", j["name"])}
            for key, j in config["jurisdictions"].items() for b in j["bodies"]}
