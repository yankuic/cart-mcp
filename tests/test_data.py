from cart_mcp import data as cart_data
from cart_mcp import pipeline


def test_concerns_integrity():
    concerns = cart_data.load_concerns()
    assert len(concerns) >= 13
    for key, profile in concerns.items():
        assert profile["key"] == key
        assert profile["type"] in ("A", "B")
        assert "source" in profile
        assert "computable" in profile
        if profile["computable"]:
            assert profile["attribute_name"], key


def test_known_concerns_present():
    concerns = cart_data.load_concerns()
    for expected in (
        "Agricultural Organic Soil Subsidence",
        "Soil Organic Carbon Stock",
        "Surface Salt Concentration",
    ):
        assert expected in concerns


def test_find_concern_by_alias():
    profile = cart_data.find_concern("Limitations for Aerobic Soil Organisms")
    assert profile is not None
    assert profile["key"] == "Suitability for Aerobic Soil Organisms"


def test_find_unknown_concern_returns_none():
    assert cart_data.find_concern("not a concern") is None


def test_find_concern_case_insensitive():
    assert cart_data.find_concern("soil organic carbon stock")["key"] == "Soil Organic Carbon Stock"


def test_domains_cover_computable_concerns():
    domains = cart_data.load_rating_domains()
    for key, profile in cart_data.load_concerns().items():
        if profile["computable"]:
            assert key in domains, key


def test_practice_links_cover_mapped_concerns():
    links = cart_data.load_practice_links()
    assert "Agricultural Organic Soil Subsidence" in links
    for entry in links.values():
        assert entry["practices"]
        for practice in entry["practices"]:
            assert practice["code"].isdigit()
            assert practice["name"]
            assert practice["points"] > 0


def test_regulatory_map_covers_core_water_concerns():
    reg = cart_data.load_regulatory_map()
    assert "Soil Organic Carbon Stock" in reg
    assert any(
        "303(d)" in ref
        for entry in reg["Soil Organic Carbon Stock"]
        for ref in entry["regulatory_references"]
    )


def test_test_aois_valid_wkt():
    aois = cart_data.load_test_aois()
    assert {a["landunit"] for a in aois} == {"T9981 Fld3", "T9981 Fld4"}
    for a in aois:
        pipeline.validate_wkt(a["wkt"])


def test_golden_files_parse():
    files = cart_data.golden_csv_files()
    assert files
    for name in files:
        rows = cart_data.golden_csv_rows(name)
        assert rows, name
        assert "landunit" in rows[0]
