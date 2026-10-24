"""Map a meeting to the governmental bodies that held it, per bodies.yaml.

The rules are written at the top of bodies.yaml; this module is their one
implementation. Unmatched and ambiguous titles raise, so the list of covered
bodies is always explicit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_MARKERS = re.compile(r"^\s*(?:[\*\s]*(?:revised|cancel+ed)\b[\s\-:*]*|\*+\s*)+", re.I)
# Canceled may lead or trail: "CANCELED - Plan Commission", "*Cancelled* ...",
# "Police and Fire Commission Meeting--CANCELLED" (Kronenwetter).
_CANCELED = re.compile(r"^[\s\*]*(?:revised\b[\s\-:*]*)?\**\s*cancel+ed\b|[\s\-*]cancel+ed[\s*]*$", re.I)


class UnmatchedMeeting(Exception):
    pass


class AmbiguousMeeting(Exception):
    pass


@dataclass(frozen=True)
class Match:
    bodies: list[str]       # body keys; empty when the title is excluded
    canceled: bool
    excluded: bool


def load(path: str | Path = Path(__file__).with_name("bodies.yaml")) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def normalize(title: str) -> str:
    return _MARKERS.sub("", title).strip()


def match(config: dict, jurisdiction: str, meeting_id: str, title: str,
          category_id: int | None = None) -> Match:
    jur = config["jurisdictions"][jurisdiction]
    canceled = bool(_CANCELED.search(title))
    clean = normalize(title)
    if any(re.search(p, clean, re.I) for p in jur.get("exclude", [])):
        return Match([], canceled, True)
    if category_id is not None and category_id in jur.get("exclude_category_ids", []):
        return Match([], canceled, True)
    override = jur.get("overrides", {}).get(f"{jurisdiction}:{meeting_id}")
    if override == "exclude":
        return Match([], canceled, True)
    if override:
        return Match(override if isinstance(override, list) else [override], canceled, False)
    if category_id is not None:
        hits = [b["key"] for b in jur["bodies"] if b.get("category_id") == category_id]
    else:
        hits = [b["key"] for b in jur["bodies"] if "match" in b and re.search(b["match"], clean, re.I)]
    if not hits:
        raise UnmatchedMeeting(f"{jurisdiction}:{meeting_id} {title!r} matches no body in bodies.yaml")
    if len(hits) > 1 and not re.search(r"\bjoint\b", clean, re.I):
        raise AmbiguousMeeting(f"{jurisdiction}:{meeting_id} {title!r} matches {hits}; add an override")
    return Match(hits, canceled, False)
