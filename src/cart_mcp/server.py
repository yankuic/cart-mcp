"""CART MCP server: exposes USDA NRCS CART soil resource concern ratings as MCP tools,
resources, and prompts. All runtime data comes from the public Soil Data Access web
service or embedded public-domain assets - no credentials, no private endpoints.
"""
from __future__ import annotations

import json
from typing import Literal

from fastmcp import FastMCP

from . import data as cart_data
from . import pipeline, sda
from .geo import build_feature_collection
from .prompts import register_prompts

DISCLAIMER = (
    "Ratings are an educational estimate of current soil conditions computed from "
    "published SSURGO data via the USDA Soil Data Access service. They are NOT an "
    "official NRCS/CART program score: official eligibility and ranking determinations "
    "come from your local NRCS field office. Ratings are only as fresh as each survey "
    "area's last publication date (included per landunit)."
)

mcp = FastMCP("cart")


# ---------------------------------------------------------------- tools


def _rate(landunits: list[tuple[str, str]], concerns: list[str] | None) -> dict:
    query = pipeline.build_query(landunits)
    result = sda.submit(query)
    ratings = sda.parse_ratings(result)

    if concerns:
        wanted = set()
        for name in concerns:
            concern = cart_data.find_concern(name)
            if concern is None:
                raise ValueError(f"unknown concern: {name!r}")
            wanted.add(concern["key"])
        ratings = [
            r
            for r in ratings
            if (cart_data.find_concern(r["rating_name"]) or {}).get("key") in wanted
        ]

    return {
        "landunits": [name for name, _ in landunits],
        "ratings": ratings,
        "ratable_concerns": [
            c["key"] for c in cart_data.load_concerns().values() if c["computable"]
        ],
        "disclaimer": DISCLAIMER,
    }


@mcp.tool()
def rate_aoi(
    wkt: str,
    landunit: str = "AOI 1",
    concerns: list[str] | None = None,
) -> dict:
    """Rate an area of interest (WKT, EPSG:4326) for CART soil resource concerns.

    Submits the CART pipeline to the public Soil Data Access web service and returns
    the landunit rating for every ratable concern (or the subset given in `concerns`).
    Each rating includes rating_name, rating_value, rating_class and the survey-area
    publication date (soils_metadata). Results are advisory - not official NRCS scores.
    """
    return _rate([(landunit, wkt)], concerns)


@mcp.tool()
def rate_aois(
    aois: list[dict],
    concerns: list[str] | None = None,
) -> dict:
    """Rate multiple landunits in one pipeline run.

    `aois` is a list of {"landunit": str (<=20 chars), "wkt": str (EPSG:4326)}.
    Ideal for comparing fields/parcels (e.g., EQIP/CSP portal parcel exploration).
    """
    landunits = [(a["landunit"], a["wkt"]) for a in aois]
    return _rate(landunits, concerns)


@mcp.tool()
def get_aoi_soil_summary(wkt: str, landunit: str = "AOI 1") -> dict:
    """Map units and major components intersecting an AOI (no ratings).

    Returns per map unit: mukey, symbol/name, survey order (invesintens), farmland
    class, acres, and its major components (compname, comppct_r, drainage class).
    Useful for transparency (E4) and leaching/water-table screening (W4).
    """
    query = pipeline.build_soil_summary_query([(landunit, wkt)])
    result = sda.submit(query)
    rows = [{k: (v if v is not None else None) for k, v in row.items()} for row in result.rows]
    return {"landunit": landunit, "map_units": rows, "columns": result.columns}


def _soil_map(wkt: str, landunit: str) -> dict:
    query = pipeline.build_soil_map_query([(landunit, wkt)])
    result = sda.submit(query)
    feature_collection = build_feature_collection(
        result.rows,
        property_keys=[
            "landunit",
            "mukey",
            "musym",
            "muname",
            "invesintens",
            "farmlndcl",
            "poly_acres",
        ],
    )
    return {
        "landunit": landunit,
        "type": feature_collection["type"],
        "features": feature_collection["features"],
        "feature_count": len(feature_collection["features"]),
    }


def _risk_map(wkt: str, concern: str, landunit: str) -> dict:
    query = pipeline.build_risk_map_query([(landunit, wkt)], concern)
    result = sda.submit(query)
    feature_collection = build_feature_collection(
        result.rows,
        property_keys=[
            "landunit",
            "mukey",
            "musym",
            "muname",
            "invesintens",
            "poly_acres",
            "rating_value",
            "rating_class",
        ],
    )
    profile = cart_data.find_concern(concern)
    return {
        "landunit": landunit,
        "concern": profile["key"] if profile else concern,
        "type": feature_collection["type"],
        "features": feature_collection["features"],
        "feature_count": len(feature_collection["features"]),
    }


@mcp.tool()
def get_aoi_soil_map(wkt: str, landunit: str = "AOI 1") -> dict:
    """Soil map for an AOI as GeoJSON (FeatureCollection).

    Each feature is a soil polygon clipped to the AOI with properties
    {landunit, mukey, musym, muname, invesintens, farmlndcl, poly_acres}.
    Render directly with Leaflet/ArcGIS; no ratings are computed.
    """
    return _soil_map(wkt, landunit)


@mcp.tool()
def get_aoi_risk_map(wkt: str, concern: str, landunit: str = "AOI 1") -> dict:
    """Risk map for one cointerp-backed concern as GeoJSON (FeatureCollection).

    Each feature is a soil polygon clipped to the AOI carrying the rating
    (rating_value, rating_class) of the dominant major soil component in its map
    unit. Order 5 survey map units are rated 'Not rated'. Supports cointerp-backed
    concerns only (e.g. the five SOH concerns, Hydric, Ponding/Flooding, AWS,
    Depth to Water Table, Drainage Class); SOC and other custom concerns raise
    an error.
    """
    return _risk_map(wkt, concern, landunit)


def _concerns_index() -> dict:
    return {
        "concerns": [
            {
                "key": c["key"],
                "type": c["type"],
                "computable": c["computable"],
                "source": c["source"],
                "pipeline_doc": c.get("pipeline_doc"),
            }
            for c in cart_data.load_concerns().values()
        ]
    }


def _resolve_concern(name: str) -> dict:
    profile = cart_data.find_concern(name)
    if profile is None:
        raise ValueError(
            f"unknown concern: {name!r}; see list_concerns for valid names"
        )
    return profile


def _concern_details(name: str) -> dict:
    key = _resolve_concern(name)["key"]
    return {
        "concern": _resolve_concern(name),
        "rating_domain": cart_data.load_rating_domains().get(key),
        "practices": cart_data.load_practice_links().get(key),
        "regulatory": cart_data.load_regulatory_map().get(key, []),
        "interpretation": cart_data.load_interpretations().get(key),
    }


def _rating_domain(name: str) -> dict:
    key = _resolve_concern(name)["key"]
    return {"concern": key, "rating_domain": cart_data.load_rating_domains().get(key)}


@mcp.tool()
def list_concerns() -> dict:
    """All CART resource concerns with pipeline type, data source, computability, and docs."""
    return _concerns_index()


@mcp.tool()
def get_concern_details(concern: str) -> dict:
    """Full profile for one concern: domain, practices, regulatory references."""
    return _concern_details(concern)


@mcp.tool()
def get_rating_domain(concern: str) -> dict:
    """Ordered rating classes (worst to best) for a concern."""
    return _rating_domain(concern)


@mcp.tool()
def list_practices_for_concern(concern: str) -> dict:
    """NRCS conservation practices that address a concern (advisory).

    Sourced from the public NRCS CART Practice Points spreadsheet
    ('Assoc Ag Land' points). Practices are listed by NRCS practice code, name, and
    points - they are suggestions for discussion, not a formal practice plan.
    """
    profile = cart_data.find_concern(concern)
    if profile is None:
        raise ValueError(
            f"unknown concern: {concern!r}; see list_concerns for valid names"
        )
    entry = cart_data.load_practice_links().get(profile["key"])
    if entry is None or not entry.get("practices"):
        return {
            "concern": profile["key"],
            "note": "no practice mapping available for this concern in the embedded data",
            "practices": [],
        }
    return {"concern": profile["key"], **entry}


@mcp.tool()
def validate_pipeline() -> dict:
    """Re-run the pipeline on the T9981 Fld3/Fld4 test fields and diff against golden values.

    Network required. Golden values are tied to the 2018 ND001/SD105 survey-area
    snapshots; a mismatch may be legitimate if those areas were republished since.
    """
    from .validation import run_validation

    return run_validation()


# ---------------------------------------------------------------- resources


@mcp.resource("cart://concerns")
def resource_concerns_index() -> str:
    """Index of all CART resource concerns."""
    return json.dumps(_concerns_index(), indent=2, default=str)


@mcp.resource("cart://concerns/{key}")
def resource_concern(key: str) -> str:
    """Full profile for one concern."""
    return json.dumps(_concern_details(key), indent=2, default=str)


@mcp.resource("cart://domains/{concern}")
def resource_domain(concern: str) -> str:
    """Rating domain for a concern."""
    return json.dumps(_rating_domain(concern), indent=2, default=str)


@mcp.resource("cart://interpretations")
def resource_interpretations() -> str:
    """Soil interpretation name mappings (attributename <-> mrulename <-> rulekey source)."""
    return json.dumps(cart_data.load_interpretations(), indent=2, default=str)


register_prompts(mcp)


def main() -> None:
    mcp.run(transport="stdio")


def serve(transport: Literal["stdio", "sse", "streamable-http"] = "stdio", port: int = 8000) -> None:
    if transport == "sse":
        mcp.run(transport="sse", host="127.0.0.1", port=port)
    elif transport == "streamable-http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=port)
    else:
        mcp.run(transport="stdio")
