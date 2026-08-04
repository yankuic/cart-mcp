"""Golden-value validation of the CART pipeline against embedded expected outputs."""
from __future__ import annotations

import re

from . import data as cart_data
from . import pipeline, sda

GOLDEN_RATING_KEY = re.compile(r"^(?P<attribute>.+):(?P<value>\d+)$")


def _golden_rows_by_key() -> list[dict]:
    """Expand each golden CSV row into a comparable expectation.

    Rows carry either a `rating_key` ({attributename}:{value}) or a plain
    `attributename` + `rating_value` pair (SOC golden format).
    """
    expectations = []
    for filename in cart_data.golden_csv_files():
        for row in cart_data.golden_csv_rows(filename):
            rating_key = (row.get("rating_key") or "").strip()
            match = GOLDEN_RATING_KEY.match(rating_key)
            if match:
                attribute = match.group("attribute")
                expected_value = int(match.group("value"))
            else:
                attribute = (row.get("attributename") or row.get("rating_name") or "").strip()
                expected_value = row.get("rating_value")
                if expected_value is not None:
                    try:
                        expected_value = int(expected_value)
                    except (TypeError, ValueError):
                        expected_value = None
            expected_class = (row.get("rating_class") or "").strip()
            if not attribute or not expected_class:
                continue
            expectations.append(
                {
                    "golden_file": filename,
                    "landunit": (row.get("landunit") or "").strip(),
                    "attribute": attribute,
                    "expected_value": expected_value,
                    "expected_class": expected_class,
                }
            )
    return expectations


def run_validation() -> dict:
    aois = cart_data.load_test_aois()
    landunits = [(a["landunit"], a["wkt"]) for a in aois]

    query = pipeline.build_query(landunits)
    result = sda.submit(query)
    live = sda.parse_ratings(result)

    live_by = {
        (row["landunit"], concern_key): row
        for row in live
        for concern_key in [(cart_data.find_concern(row["rating_name"]) or {}).get("key")]
        if concern_key
    }

    checks = []
    passed = 0
    failed = 0
    for expectation in _golden_rows_by_key():
        concern = cart_data.find_concern(expectation["attribute"])
        row = live_by.get((expectation["landunit"], concern["key"])) if concern else None
        if row is None:
            check = {
                **expectation,
                "status": "FAIL",
                "detail": "no live rating found for this concern/landunit",
            }
            failed += 1
        else:
            value_matches = (
                expectation["expected_value"] is None
                or row["rating_value"] == expectation["expected_value"]
            )
            match = row["rating_class"] == expectation["expected_class"] and value_matches
            check = {
                **expectation,
                "status": "PASS" if match else "FAIL",
                "actual_class": row["rating_class"],
                "actual_value": row["rating_value"],
                "detail": "" if match else "rating class or value differs from golden",
            }
            if match:
                passed += 1
            else:
                failed += 1
        checks.append(check)

    return {
        "test_aois": [a["landunit"] for a in aois],
        "checks": checks,
        "summary": {"passed": passed, "failed": failed},
        "caveat": (
            "Golden values were produced from the 2018 ND001/SD105 survey-area "
            "snapshots. If those areas have been republished since, legitimate "
            "differences are expected. Verify freshness via soils_metadata."
        ),
    }
