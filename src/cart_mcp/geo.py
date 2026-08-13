"""WKT -> GeoJSON conversion helpers for the map tools."""
from __future__ import annotations

from shapely import wkt as shapely_wkt
from shapely.errors import GEOSException
from shapely.geometry import shape

MAX_COORD_DECIMALS = 6


def _round_coords(value) -> object:
    if isinstance(value, dict):
        return {k: _round_coords(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round_coords(v) for v in value]
    if isinstance(value, float):
        return round(value, MAX_COORD_DECIMALS)
    return value


def wkt_to_geojson(wkt: str | None) -> dict | None:
    """Convert a WKT geometry string to a GeoJSON geometry dict.

    Invalid, empty, or unparseable geometries return None (clients skip them).
    Coordinates are rounded to 6 decimal places (~0.1 m) to keep payloads small.
    """
    if not wkt:
        return None
    try:
        geom = shapely_wkt.loads(wkt)
    except (GEOSException, ValueError, AttributeError):
        return None
    if geom.is_empty or not geom.is_valid:
        return None
    return _round_coords(geom.__geo_interface__)


def simplify_geojson(geometry: dict, tolerance: float) -> dict:
    """Simplify a GeoJSON geometry dict using shapely's Douglas-Peucker.

    Invalid, empty, or non-polygonal geometries are returned unchanged. The
    result is rounded to MAX_COORD_DECIMALS so payloads stay small.
    """
    try:
        geom = shape(geometry)
    except (GEOSException, ValueError, AttributeError):
        return geometry
    if geom.is_empty or not geom.is_valid or geom.geom_type not in ("Polygon", "MultiPolygon"):
        return geometry
    simplified = geom.simplify(tolerance, preserve_topology=True)
    return _round_coords(simplified.__geo_interface__)


def build_feature_collection(
    rows: list[dict],
    property_keys: list[str],
    geometry_key: str = "geom_wkt",
) -> dict:
    """Assemble a GeoJSON FeatureCollection from SDA result rows.

    Args:
        rows: SDA rows (values coerced by sda._coerce; None for NULLs).
        property_keys: row keys to carry into feature properties.
        geometry_key: row key holding the WKT geometry string.

    Returns:
        GeoJSON FeatureCollection dict; empty feature list for empty/no-geometry input.
    """
    features = []
    for row in rows:
        geometry = wkt_to_geojson(row.get(geometry_key))
        if geometry is None:
            continue
        properties = {key: row.get(key) for key in property_keys if key in row}
        features.append({"type": "Feature", "geometry": geometry, "properties": properties})
    return {"type": "FeatureCollection", "features": features}
