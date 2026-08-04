"""Opt-in tests requiring live access to the public Soil Data Access web service.

Run with: uv run pytest -m network
"""
import pytest

from cart_mcp import data as cart_data
from cart_mcp import pipeline, sda

pytestmark = pytest.mark.network


def test_sda_endpoint_public_no_auth():
    result = sda.submit("SELECT TOP 1 areasymbol FROM sacatalog")
    assert result.row_count >= 1
    assert "areasymbol" in result.columns


def test_minimal_kitchensink_query_runs():
    aoi = cart_data.load_test_aois()[0]
    query = pipeline.build_query([(aoi["landunit"], aoi["wkt"])])
    result = sda.submit(query)
    rows = sda.parse_ratings(result)
    assert rows, "pipeline returned no ratings"


def test_rate_aoi_returns_expected_concerns():
    from cart_mcp.server import _rate

    aoi = cart_data.load_test_aois()[0]
    out = _rate([(aoi["landunit"], aoi["wkt"])], None)
    names = {r["rating_name"] for r in out["ratings"]}
    assert "Agricultural Organic Soil Subsidence" in names
    assert "Soil Organic Carbon Stock" in names
    for r in out["ratings"]:
        assert r["landunit"] == aoi["landunit"]


def test_get_aoi_soil_map_returns_geojson():
    from cart_mcp.server import _soil_map

    aoi = cart_data.load_test_aois()[0]
    out = _soil_map(aoi["wkt"], aoi["landunit"])
    assert out["type"] == "FeatureCollection"
    assert out["feature_count"] >= 1
    for feature in out["features"]:
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert feature["properties"]["mukey"] is not None
        assert feature["properties"]["musym"]


def test_get_aoi_risk_map_returns_ratings():
    from cart_mcp.server import _risk_map

    aoi = cart_data.load_test_aois()[0]
    out = _risk_map(aoi["wkt"], "Soil Susceptibility to Compaction", aoi["landunit"])
    assert out["type"] == "FeatureCollection"
    assert out["feature_count"] >= 1
    for feature in out["features"]:
        props = feature["properties"]
        assert props["rating_class"], props
        assert props["landunit"] == aoi["landunit"]
