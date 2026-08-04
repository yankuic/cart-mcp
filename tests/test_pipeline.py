from cart_mcp import pipeline

VALID_MULTI = "MULTIPOLYGON (((-102.13 45.94, -102.12 45.94, -102.12 45.95, -102.13 45.95, -102.13 45.94)))"


def test_template_keeps_declare_macros_for_sda():
    sql = pipeline.build_query([("T9981 Fld3", VALID_MULTI)])
    assert "~DeclareGeometry(@aoiGeom)~" in sql
    assert "DECLARE @aoiGeom" not in sql


def test_validate_wkt_accepts_polygon():
    assert pipeline.validate_wkt(VALID_MULTI)


def test_validate_wkt_rejects_non_4326():
    import pytest

    with pytest.raises(ValueError, match="outside EPSG:4326"):
        pipeline.validate_wkt(
            "POLYGON ((500000 4000000, 500001 4000000, 500001 4000001, 500000 4000001, 500000 4000000))"
        )


def test_validate_wkt_rejects_non_polygon():
    import pytest

    with pytest.raises(ValueError, match="Polygon or MultiPolygon"):
        pipeline.validate_wkt("POINT (-102.13 45.94)")


def test_validate_wkt_rejects_garbage():
    import pytest

    with pytest.raises(ValueError):
        pipeline.validate_wkt("MULTIPOLYGON (((not numbers)))")


def test_validate_wkt_rejects_oversized():
    import pytest

    with pytest.raises(ValueError, match="unreasonably large"):
        pipeline.validate_wkt(
            "POLYGON ((-130 20, -60 20, -60 50, -130 50, -130 20))"
        )


def test_build_aoi_section_escapes_names():
    section = pipeline.build_aoi_section([("O'Brien", VALID_MULTI)])
    assert "O''Brien" in section
    assert "STGeomFromText" in section


def test_build_aoi_section_limits():
    import pytest

    with pytest.raises(ValueError, match="too many landunits"):
        pipeline.build_aoi_section([(f"F{i}", VALID_MULTI) for i in range(51)])


def test_build_query_kitchen_template_integrity():
    sql = pipeline.build_query([("T9981 Fld3", VALID_MULTI)])
    assert pipeline.AOI_MARKER not in sql
    assert "INSERT INTO #AoiTable" in sql
    assert "STGeomFromText" in sql
    assert "LandunitRatingsCART2" in sql
    assert "LandunitRatingsAirQualityData" not in sql
    assert "STIntersects" in sql


def test_build_soil_summary_query():
    sql = pipeline.build_soil_summary_query([("T9981 Fld3", VALID_MULTI)])
    assert "soil_summary" in sql or "#M2" in sql
    assert "LandunitRatingsCART2" not in sql


def test_build_soil_map_query():
    sql = pipeline.build_soil_map_query([("T9981 Fld3", VALID_MULTI)])
    assert "~DeclareGeometry" in sql
    assert pipeline.AOI_MARKER not in sql
    assert "STAsText" in sql
    assert "soilgeog" in sql
    assert "LandunitRatingsCART2" not in sql


def test_build_risk_map_query():
    sql = pipeline.build_risk_map_query(
        [("T9981 Fld3", VALID_MULTI)], "Soil Susceptibility to Compaction"
    )
    assert "{ATTRIBUTE_NAME}" not in sql
    assert "SELECT @attributeName = 'Soil Susceptibility to Compaction';" in sql
    assert "cointerp" in sql
    assert "ROW_NUMBER()" in sql
    assert pipeline.AOI_MARKER not in sql


def test_build_risk_map_query_rejects_non_cointerp():
    import pytest

    for concern in ("Soil Organic Carbon Stock", "Aggregate Stability", "Farmland Classification"):
        with pytest.raises(ValueError, match="cointerp"):
            pipeline.build_risk_map_query([("F1", VALID_MULTI)], concern)


def test_build_risk_map_query_rejects_unknown():
    import pytest

    with pytest.raises(ValueError, match="unknown concern"):
        pipeline.build_risk_map_query([("F1", VALID_MULTI)], "not a concern")
