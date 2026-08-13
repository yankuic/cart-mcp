"""Offline tests for the server tool/resource surface (no live SDA access)."""
import httpx
import pytest

from cart_mcp import cache as cache_mod
from cart_mcp import sda
from cart_mcp.server import (
    DISCLAIMER,
    _apply_geojson_caps,
    _concern_details,
    _concern_summary,
    _concerns_index,
    _rate,
    _rate_aois,
)

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<NewDataSet>
  <Table>
    <landunit>F1</landunit>
    <rating_name>Soil Susceptibility to Compaction</rating_name>
    <rating_value>1</rating_value>
    <rating_class>High</rating_class>
    <soils_metadata>ND001 2018-09-12</soils_metadata>
  </Table>
</NewDataSet>
"""


def _response(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, request=httpx.Request("POST", sda.SDA_ENDPOINT))


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_mod.clear_cache()
    yield
    cache_mod.clear_cache()


@pytest.fixture
def fake_sda(monkeypatch):
    def fake_post(*args, **kwargs):
        return _response(SAMPLE_XML)

    monkeypatch.setattr(httpx, "post", fake_post)


def test_summary_mode_is_compact():
    summary = _concern_summary("Soil Susceptibility to Compaction")
    assert set(summary) == {"concern", "name", "rating_domain", "top_practices"}
    assert summary["concern"] == "Soil Susceptibility to Compaction"
    assert len(summary["top_practices"]) <= 3


def test_summary_mode_normalizes_soc_domain():
    summary = _concern_summary("Soil Organic Carbon Stock")
    assert isinstance(summary["rating_domain"], list)


def test_full_details_retain_regulatory():
    full = _concern_details("Soil Susceptibility to Compaction", summary=False)
    assert "regulatory" in full
    assert "interpretation" in full


def test_disclaimer_present():
    assert "NOT" in DISCLAIMER
    assert "official NRCS" in DISCLAIMER


def test_concerns_index_lists_concerns():
    index = _concerns_index()
    assert index["concerns"]
    assert all("computable" in c for c in index["concerns"])


def test_rate_output_drops_boilerplate(fake_sda):
    out = _rate([("F1", "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))")], None)
    assert set(out) == {"landunits", "ratings"}
    assert "disclaimer" not in out
    assert "ratable_concerns" not in out


def test_rate_aois_invalid_wkt_reported_not_sinking(fake_sda):
    valid_wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
    out = _rate_aois(
        [
            {"landunit": "OK", "wkt": valid_wkt},
            {"landunit": "BAD", "wkt": "not a polygon"},
        ]
    )
    assert out["landunits"] == ["OK"]
    assert len(out["errors"]) == 1
    assert out["errors"][0]["landunit"] == "BAD"
    assert out["ratings"][0]["landunit"] == "F1"


def _feature(geom):
    return {"type": "Feature", "geometry": geom, "properties": {"musym": "A"}}


POLY = {
    "type": "Polygon",
    "coordinates": [[(0, 0), (0.0001, 0.0001), (0.0002, 0), (1, 0), (1, 1), (0, 1), (0, 0)]],
}


def test_apply_geojson_caps_no_truncation_within_limits():
    features = [_feature(POLY) for _ in range(10)]
    kept, truncated, dropped = _apply_geojson_caps(features, feature_cap=100, byte_cap=10**6)
    assert len(kept) == 10
    assert truncated is False
    assert dropped == 0


def test_apply_geojson_caps_feature_cap_drops_extras():
    features = [_feature(POLY) for _ in range(10)]
    kept, truncated, dropped = _apply_geojson_caps(features, feature_cap=3, byte_cap=10**6)
    assert len(kept) == 3
    assert truncated is True
    assert dropped == 7


def test_apply_geojson_caps_byte_cap_drops_later():
    features = [_feature(POLY) for _ in range(10)]
    kept, truncated, dropped = _apply_geojson_caps(features, feature_cap=100, byte_cap=1)
    # single feature exceeds a 1-byte cap; tolerance escalation still can't fit -> dropped
    assert len(kept) == 0
    assert truncated is True
    assert dropped == 10
