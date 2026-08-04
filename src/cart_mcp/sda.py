"""Client for the USDA NRCS Soil Data Access (SDA) tabular web service.

Public federal service - no authentication. Returns the LAST result set of the
submitted query as XML (<NewDataSet>/<Table> rows), which for the CART pipeline
is the final #LandunitRatingsCART2 select.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

SDA_ENDPOINT = os.environ.get(
    "SDA_ENDPOINT", "https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest"
)
SDA_TIMEOUT = float(os.environ.get("SDA_TIMEOUT", "180"))

_NS = "{http://www.opengis.net/ogc}"


class SDAError(RuntimeError):
    pass


@dataclass
class SDAResult:
    columns: list[str]
    rows: list[dict[str, object]]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def submit(query: str, *, endpoint: str = SDA_ENDPOINT, timeout: float = SDA_TIMEOUT) -> SDAResult:
    """POST a SQL query to SDA and return the parsed last result set."""
    try:
        response = httpx.post(
            endpoint,
            params={"format": "xml"},
            data={"query": query},
            headers={"Accept": "application/xml"},
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise SDAError(f"SDA request failed ({response.status_code}): {_service_exception_message(response.text)}")
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SDAError(f"SDA request failed: {exc}") from exc

    return _parse_xml(response.text)


def _parse_xml(text: str) -> SDAResult:
    if "ServiceExceptionReport" in text:
        raise SDAError(_service_exception_message(text))
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SDAError(f"unparseable SDA response: {exc}") from exc

    columns: list[str] = []
    rows: list[dict[str, object]] = []
    for element in root:
        if element.tag.endswith("Table"):
            row = {}
            for child in element:
                column = child.tag.rsplit("}", 1)[-1]
                if column not in columns:
                    columns.append(column)
                value = child.text.strip() if child.text else None
                row[column] = _coerce(value)
            rows.append(row)
    return SDAResult(columns=columns, rows=rows)


def _coerce(value: str | None):
    if value is None or value == "":
        return None
    if value in ("True", "False"):
        return value == "True"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _service_exception_message(text: str) -> str:
    try:
        root = ET.fromstring(text)
        node = root.find(f"{_NS}ServiceException")
        if node is not None and node.text:
            return node.text.strip()
    except ET.ParseError:
        pass
    return text[:300]


def parse_ratings(result: SDAResult) -> list[dict]:
    """Normalize pipeline output rows into {landunit, rating_name, rating_value, rating_class}.

    The survey-area publication date from the final select (`MD.soils_metadata`)
    is carried through so each rating reports how fresh the underlying SSURGO data is.
    """
    ratings = []
    for row in result.rows:
        ratings.append(
            {
                "landunit": str(row.get("landunit") or "").strip(),
                "rating_name": str(row.get("rating_name") or "").strip(),
                "rating_value": row.get("rating_value"),
                "rating_class": str(row.get("rating_class") or "").strip(),
                "soils_metadata": row.get("soils_metadata"),
            }
        )
    return ratings
