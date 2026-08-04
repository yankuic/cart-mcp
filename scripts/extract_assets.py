"""One-time/repeatable asset extraction from the public CART source repo (GitHub).

Fetches the source files from the upstream USDA NRCS CART reference repository
(https://github.com/jneme910/CART) and regenerates the self-contained MCP package
assets:
  - src/cart_mcp/sql/kitchen_template.sql   (parameterized pipeline query)
  - src/cart_mcp/data/test_aois.json        (known AOI geometries)
  - src/cart_mcp/data/practice_links.json   (concern -> NRCS practices)
  - src/cart_mcp/data/expected_outputs/     (golden validation CSVs)

Usage:
    uv run --with openpyxl python scripts/extract_assets.py [DEST_DIR]

Requires network access to raw.githubusercontent.com. The CART source is never a
runtime dependency; these assets are committed.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]

CART_RAW = "https://raw.githubusercontent.com/jneme910/CART/master"
SQL_URL = f"{CART_RAW}/SQL-Library/CART_SoilsQuery_kitchensink_20240925.sql"
XLSX_URL = f"{CART_RAW}/documents/CART%20Practice%20Points%20Spreadsheet-5.xlsx"
SQL_SOURCE = "https://github.com/jneme910/CART/blob/master/SQL-Library/CART_SoilsQuery_kitchensink_20240925.sql"

AOI_START = "SELECT @aoiGeom = GEOMETRY::STGeomFromText"
AOI_END = "VALUES ('T9981 Fld4', @aoiGeomFixed);"
AIR_QUALITY_START = "--Air Quality"
AIR_QUALITY_END = "FROM #LandunitRatingsAirQualityData"

# concern key -> resource concern component id in the CART Practice Points Spreadsheet
CONCERN_RCID = {
    "Agricultural Organic Soil Subsidence": 153,
    "Soil Susceptibility to Compaction": 149,
    "Organic Matter Depletion": 151,
    "Surface Salt Concentration": 150,
    "Suitability for Aerobic Soil Organisms": 152,
    "Aggregate Stability": 148,
    "Soil Organic Carbon Stock": 191,
    "Ponding or Flooding": 184,
    "Hydric Rating by Map Unit": 185,
    "Depth to Water Table": 185,
    "Available Water Storage": 183,
}


def fetch_text(url: str) -> str:
    """Download a UTF-8 text file from the public CART GitHub repository."""
    resp = httpx.get(url, timeout=120.0)
    resp.raise_for_status()
    return resp.text


def fetch_xlsx(url: str) -> Path:
    """Download the practice-points workbook to a temp file (openpyxl needs a path)."""
    resp = httpx.get(url, timeout=120.0)
    resp.raise_for_status()
    tmp = Path(tempfile.gettempdir()) / "CART Practice Points Spreadsheet-5.xlsx"
    tmp.write_bytes(resp.content)
    return tmp


def extract_template(src: str, dest: Path) -> None:
    text = src

    start = text.index(AOI_START)
    end = text.index(AOI_END) + len(AOI_END)
    aoi_section = text[start:end]

    marker = (
        "-- BEGIN AOI SECTION (generated)\n"
        "-- This line below is replaced at runtime with parameterized, validated\n"
        "-- EPSG:4326 geometries:\n"
        "{AOI_SECTION}\n"
        "-- END AOI SECTION (generated)\n"
    )
    text = text[:start] + marker + text[end:]

    aq_start = text.index(AIR_QUALITY_START)
    aq_end = text.index(AIR_QUALITY_END, aq_start) + len(AIR_QUALITY_END)
    text = text[:aq_start] + text[aq_end:]

    # Surface survey-area publication dates with every rating (MCP requirement).
    final_select = (
        "SELECT LRC.landunit, LRC.attributename AS rating_name, LRC.rating_value, "
        "LRC.rating_class, MD.soils_metadata\n"
        "FROM #LandunitRatingsCART2 LRC\n"
        "INNER JOIN #AoiAcres AS a ON a.landunit = LRC.landunit\n"
        "LEFT JOIN #LandunitMetadata MD ON LRC.landunit = MD.landunit\n"
        "ORDER BY LRC.landunit, LRC.attributename  \n;"
    )
    text = re.sub(
        r"SELECT LRC\.landunit, LRC\.attributename AS rating_name, LRC\.rating_value, "
        r"LRC\.rating_class\nFROM #LandunitRatingsCART2 LRC\n"
        r"INNER JOIN #AoiAcres AS a ON a\.landunit = LRC\.landunit\n"
        r"ORDER BY LRC\.landunit, LRC\.attributename  \n;",
        lambda _: final_select,
        text,
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")

    geo = []
    for m in re.finditer(r"STGeomFromText\('(MULTIPOLYGON[^']*)', 4326\)", aoi_section):
        geo.append(m.group(1))
    names = re.findall(r"VALUES \('([^']+)'", aoi_section)
    if len(geo) != len(names):
        raise SystemExit(f"AOI geometry/name mismatch: {len(geo)} vs {len(names)}")
    return [{"landunit": n, "wkt": g} for n, g in zip(names, geo)]


def extract_practices(xlsx: Path, max_per_concern: int = 12) -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb["Practice Points-All Land Uses"]

    rcid_names = {}
    practices: dict[int, list[tuple[str, str, float]]] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        ptype, pcode, pname, rcid, rname, assoc = row[0], row[1], row[2], row[3], row[4], row[5]
        if rcid is None:
            continue
        rcid = int(rcid)
        rcid_names.setdefault(rcid, str(rname).strip())
        if ptype is None or pcode is None or pname is None:
            continue
        try:
            pts = float(assoc) if assoc not in (None, "", " ") else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if pts > 0:
            practices.setdefault(rcid, []).append((str(pcode), str(pname).strip(), pts))

    out = {}
    for concern, rcid in CONCERN_RCID.items():
        entries = sorted(practices.get(rcid, []), key=lambda t: -t[2])[:max_per_concern]
        out[concern] = {
            "resource_concern_component": rcid_names.get(rcid, ""),
            "resource_concern_component_id": rcid,
            "practices": [
                {"code": c, "name": n, "points": p} for c, n, p in entries
            ],
        }
    return out


def copy_goldens(src_dir: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in src_dir.glob("*.csv"):
        shutil.copy2(f, dest_dir / f.name)


def main() -> None:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "src" / "cart_mcp"

    sql_text = fetch_text(SQL_URL)
    xlsx = fetch_xlsx(XLSX_URL)
    goldens = REPO / "docs" / "validation" / "expected_outputs"

    aois = extract_template(sql_text, dest / "sql" / "kitchen_template.sql")
    (dest / "data").mkdir(parents=True, exist_ok=True)
    (dest / "data" / "test_aois.json").write_text(
        json.dumps({"aois": aois, "source": SQL_SOURCE}, indent=2) + "\n"
    )
    print(f"wrote {dest / 'sql' / 'kitchen_template.sql'} ({len(aois)} AOIs)")

    links = extract_practices(xlsx)
    (dest / "data" / "practice_links.json").write_text(
        json.dumps(links, indent=2) + "\n"
    )
    print(f"wrote {dest / 'data' / 'practice_links.json'}")

    if goldens.exists():
        copy_goldens(goldens, dest / "data" / "expected_outputs")
        print(f"copied {len(list((dest / 'data' / 'expected_outputs').glob('*.csv')))} golden CSVs")


if __name__ == "__main__":
    main()
