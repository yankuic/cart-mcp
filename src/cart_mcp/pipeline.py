"""Build the CART rating pipeline SQL for the Soil Data Access web service."""
from __future__ import annotations

import re
from pathlib import Path

from shapely import wkt as shapely_wkt
from shapely.errors import GEOSException

SQL_DIR = Path(__file__).resolve().parent / "sql"

AOI_MARKER = "{AOI_SECTION}"
MAX_LANDUNITS = 50
MAX_AOI_AREA_DEG2 = 25.0


def validate_wkt(text: str) -> str:
    """Validate and normalize an AOI geometry. Must be EPSG:4326 (WGS84)."""
    if not text or not isinstance(text, str):
        raise ValueError("AOI geometry must be a WKT string")
    try:
        geom = shapely_wkt.loads(text)
    except (GEOSException, ValueError, AttributeError) as exc:
        raise ValueError(f"invalid WKT: {exc}") from exc
    if geom.is_empty or not geom.is_valid:
        raise ValueError("AOI geometry is empty or invalid (not valid)")
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"AOI geometry must be a Polygon or MultiPolygon, got {geom.geom_type}")
    minx, miny, maxx, maxy = geom.bounds
    if not (-180.0 <= minx <= maxx <= 180.0 and -90.0 <= miny <= maxy <= 90.0):
        raise ValueError("AOI geometry is outside EPSG:4326 (WGS84) bounds")
    if (maxx - minx) * (maxy - miny) > MAX_AOI_AREA_DEG2:
        raise ValueError("AOI geometry is unreasonably large; limit your area of interest")
    return geom.wkt


def build_aoi_section(landunits: list[tuple[str, str]]) -> str:
    """Build the AOI insert block for the pipeline template.

    landunits: sequence of (landunit_name, wkt_epsg4326).
    """
    if not landunits:
        raise ValueError("at least one landunit is required")
    if len(landunits) > MAX_LANDUNITS:
        raise ValueError(f"too many landunits ({len(landunits)}); max is {MAX_LANDUNITS}")
    blocks = []
    for name, wkt in landunits:
        if not name or len(str(name)) > 20:
            raise ValueError("landunit names must be non-empty and at most 20 characters")
        safe_name = str(name).replace("'", "''")
        blocks.append(
            "\n".join(
                [
                    f"SELECT @aoiGeom = GEOMETRY::STGeomFromText('{validate_wkt(wkt)}', 4326); ",
                    "SELECT @aoiGeomFixed = @aoiGeom.MakeValid().STUnion(@aoiGeom.STStartPoint()); ",
                    f"INSERT INTO #AoiTable ( landunit, aoigeom ) VALUES ('{safe_name}', @aoiGeomFixed); ",
                ]
            )
        )
    return "\n".join(blocks)


def load_template(name: str = "kitchen_template.sql") -> str:
    path = SQL_DIR / name
    return path.read_text(encoding="utf-8")


def build_query(landunits: list[tuple[str, str]], template_name: str = "kitchen_template.sql") -> str:
    """Assemble the full SDA query for the given AOIs.

    The template keeps its ~Declare~ macros verbatim: the SDA web service expands them
    server-side and rejects plain DECLARE statements ("Keyword declare not allowed").
    Only the exact marker line is substituted - comments mentioning the marker are safe.
    """
    template = load_template(template_name)
    if AOI_MARKER not in template:
        raise ValueError(f"template {template_name} has no {AOI_MARKER} marker")
    section = build_aoi_section(landunits)
    return re.sub(rf"^{re.escape(AOI_MARKER)}$", lambda _: section, template, flags=re.MULTILINE)


def build_soil_summary_query(landunits: list[tuple[str, str]]) -> str:
    """Lightweight query: map units + major components intersecting the AOI (no ratings)."""
    return build_query(landunits, template_name="soil_summary.sql")


def build_soil_map_query(landunits: list[tuple[str, str]]) -> str:
    """Query: per-polygon soil map (AOI-clipped geometry WKT) without ratings."""
    return build_query(landunits, template_name="soil_map.sql")


def build_risk_map_query(landunits: list[tuple[str, str]], concern: str) -> str:
    """Query: per-polygon risk map for one cointerp-backed concern.

    The concern's attributename is injected from validated embedded data only -
    user input never reaches the SQL template directly.
    """
    from . import data as cart_data

    profile = cart_data.find_concern(concern)
    if profile is None:
        raise ValueError(f"unknown concern: {concern!r}; see list_concerns for valid names")
    mrulename = (cart_data.load_interpretations().get(profile["key"]) or {}).get("mrulename")
    attribute_name = profile.get("attribute_name") or profile["key"]
    if not mrulename:
        raise ValueError(
            f"concern {profile['key']!r} has no cointerp interpretation "
            "(no rulekey/mrulename); risk maps support cointerp-backed concerns only"
        )
    if len(attribute_name) > 60:
        raise ValueError("internal error: attribute name too long for template")
    template = load_template("risk_map.sql")
    if AOI_MARKER not in template:
        raise ValueError("risk_map.sql has no {AOI_SECTION} marker")
    if "{ATTRIBUTE_NAME}" not in template:
        raise ValueError("risk_map.sql has no {ATTRIBUTE_NAME} marker")
    section = build_aoi_section(landunits)
    sql = re.sub(rf"^{re.escape(AOI_MARKER)}$", lambda _: section, template, flags=re.MULTILINE)
    return sql.replace("{ATTRIBUTE_NAME}", attribute_name.replace("'", "''"))
