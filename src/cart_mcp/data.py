"""Loaders for the embedded CART data assets (public-domain, committed to the package)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
EXPECTED_OUTPUTS_DIR = DATA_DIR / "expected_outputs"


def _load_json(name: str) -> dict:
    with (DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def load_concerns() -> dict[str, dict]:
    """Return {canonical_key: concern_profile} for all CART resource concerns."""
    data = _load_json("concerns.json")
    return {c["key"]: c for c in data["concerns"]}


def load_concern_index() -> dict[str, str]:
    """Case-insensitive lookup from any name/alias to the canonical concern key."""
    index: dict[str, str] = {}
    for key, profile in load_concerns().items():
        for name in (key, profile.get("name"), profile.get("attribute_name"), profile.get("attribute_alias")):
            if name:
                index[name.lower()] = key
    return index


def find_concern(name: str) -> dict | None:
    """Resolve a concern by canonical key, display name, or SQL attribute name/alias."""
    if not name:
        return None
    index = load_concern_index()
    key = index.get(name.strip().lower())
    if key is None:
        for candidate, mapped in index.items():
            if name.strip().lower() in candidate:
                key = mapped
                break
    return load_concerns().get(key) if key else None


def load_rating_domains() -> dict:
    return _load_json("rating_domains.json")["domains"]


def load_interpretations() -> dict:
    return _load_json("interpretations.json")["interpretations"]


def load_practice_links() -> dict:
    return _load_json("practice_links.json")


def load_regulatory_map() -> dict:
    return _load_json("concern_regulatory_map.json")["concern_regulatory_map"]


def load_test_aois() -> list[dict]:
    """Known validation AOIs: [{'landunit': str, 'wkt': str}]."""
    return _load_json("test_aois.json")["aois"]


def golden_csv_rows(name: str) -> list[dict]:
    """Rows of an embedded expected-outputs CSV, values as strings."""
    path = EXPECTED_OUTPUTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"no golden file: {name}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def golden_csv_files() -> list[str]:
    return sorted(p.name for p in EXPECTED_OUTPUTS_DIR.glob("*.csv"))
