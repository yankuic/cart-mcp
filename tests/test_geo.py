import json

from cart_mcp.geo import build_feature_collection, wkt_to_geojson

POLYGON_WKT = (
    "POLYGON ((-102.1334674808154 45.94464605628315, -102.1305452386178 45.94466255078163, "
    "-102.1250676378794 45.94469346863593, -102.12327175652177 45.9447036058142, "
    "-102.12327765248887 45.9457721832989, -102.1334674808154 45.94464605628315))"
)


def test_wkt_to_geojson_basic():
    geom = wkt_to_geojson(POLYGON_WKT)
    assert geom["type"] == "Polygon"
    first = geom["coordinates"][0][0]
    assert len(str(first[0]).split(".")[1]) <= 6  # rounded to 6 decimals


def test_wkt_to_geojson_rounds_coords():
    geom = wkt_to_geojson("POLYGON ((0.123456789 0.987654321, 1.000000001 0.0, 1.0 1.0, 0.0 1.0, 0.123456789 0.987654321))")
    coords = [c for ring in geom["coordinates"] for c in ring]
    assert all(len(str(c).split(".")[1]) <= 6 for pair in coords for c in pair)


def test_wkt_to_geojson_skips_invalid():
    assert wkt_to_geojson("POINT (1 2)") is not None  # non-polygon still converts
    assert wkt_to_geojson("garbage") is None
    assert wkt_to_geojson("") is None
    assert wkt_to_geojson(None) is None


def test_wkt_to_geojson_skips_invalid_geometry():
    bowtie = "POLYGON ((0 0, 2 2, 0 2, 2 0, 0 0))"  # self-intersecting -> invalid
    assert wkt_to_geojson(bowtie) is None


def test_build_feature_collection():
    rows = [
        {"landunit": "F1", "mukey": 1, "musym": "A", "poly_acres": 10.0, "geom_wkt": POLYGON_WKT},
        {"landunit": "F1", "mukey": 2, "musym": "B", "poly_acres": 5.0, "geom_wkt": "bad wkt"},
    ]
    fc = build_feature_collection(rows, ["landunit", "mukey", "musym", "poly_acres"])
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    feature = fc["features"][0]
    assert feature["type"] == "Feature"
    assert feature["properties"]["musym"] == "A"
    assert "geom_wkt" not in feature["properties"]
    json.dumps(fc)  # serializable


def test_build_feature_collection_empty():
    fc = build_feature_collection([], ["mukey"])
    assert fc == {"type": "FeatureCollection", "features": []}
