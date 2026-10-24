"""Platform adapters, keyed by the `platform:` value in bodies.yaml."""
from __future__ import annotations

import importlib


def for_platform(platform: str):
    return importlib.import_module(f"adapters.{platform}")
