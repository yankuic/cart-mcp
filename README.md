# cart-mcp

This MCP server computes soil resource concern ratings for an area of interest (AOI) using the same SQL pipeline CART ([Nemecek, J. & Peaslee, S., USDA NRCS](https://github.com/jneme910/CART)) uses against the public USDA **Soil Data Access** (SDA) web service, and exposes the results as MCP tools, resources, and prompts for AI-assisted conservation planning.

> **What this is not:** an official NRCS/CART ranking engine. CART's full ranking score
> combines five components (Vulnerability, Planned Practice Effects, Resource Priorities,
> Program Priorities, Cost Efficiency). This server computes only the **soil-condition
> ratings** (the vulnerability input) from published SSURGO soil data. Official program
> determinations come from your NRCS field office.

## Install

Requires Python >= 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Run

```bash
uv run cart-mcp                 # stdio transport (default, for MCP clients)
uv run cart-mcp --transport streamable-http --port 8000   # Streamable HTTP (recommended for remote/HTTP clients)
uv run cart-mcp --transport sse --port 8000               # legacy HTTP+SSE transport
```

Or during development:

```bash
uv run python -m cart_mcp
```

### Client configuration

Add to your MCP client config (opencode, Claude Desktop, etc.):

```json
{
  "mcpServers": {
    "cart": {
      "command": "uv",
      "args": ["--directory", "/path/to/cart-assistant", "run", "cart-mcp"]
    }
  }
}
```

opencode users can preconfigure both servers in a root `opencode.json`; all other clients
use `examples/mcp_config.json` as a template.

### QGIS integration (external agent harness)

Drive QGIS Desktop and cart-mcp from one agent (e.g. opencode): ask the agent to
extract an AOI from the QGIS canvas, rate it with cart-mcp, and map the result back
into QGIS. Tools appear prefixed: `cart_*` (rating tools) and `qgis_*` (QGIS tools).

Setup (QGIS MCP plugin install, server registration for opencode and other MCP
clients) and a fully worked run (T89 Fld1, step-by-step prompts, expected
outputs, troubleshooting) are in `examples/qgis_cart_harness_example.md`.

#### Orchestration pattern

1. **AOI**: ask for the canvas extent or a layer's features → EPSG:4326 WKT in one call:
   qgis `evaluate_expression` with
   `geom_to_wkt(transform($geometry, 'EPSG:4326'))` (cart-mcp requires EPSG:4326).
2. **Rate**: `cart_rate_aoi` (or `cart_rate_aois` for several landunits) with
   `concerns` as an optional subset; maps via `cart_get_aoi_soil_map` / `cart_get_aoi_risk_map`.
3. **Map**: save the returned GeoJSON to a temp file → qgis `add_vector_layer` →
   `set_layer_style` → `zoom_to_layer` → `render_map`.

#### Caveats

- Ratings are **advisory**; keep the returned `disclaimer` and `soils_metadata` (survey dates).
- Each rating hits the public SDA web service (~10 s); avoid `cart_validate_pipeline` in chat.
- The QGIS socket binds localhost with **no auth** and `qgis_execute_code` runs arbitrary
  PyQGIS: on shared machines set `QGIS_MCP_TOKEN` in both the QGIS environment and the
  server's `environment` block.
- 117 QGIS tools bloat model context; on token-strapped models set
  `QGIS_MCP_TOOL_MODE=compound` (27 grouped tools) via the server `environment`, or gate
  with `"tools": {"qgis_*": false}` + per-agent re-enable.

## Tools

| Tool | Description |
|---|---|
| `rate_aoi` | Rate an AOI (WKT, EPSG:4326) for resource concerns via the SDA web service. Accepts an optional `concerns` subset. Returns ratings with survey-data dates and advisory disclaimer. |
| `rate_aois` | Rate multiple landunits in one pipeline run (`aois` = [{landunit, wkt}]); ideal for comparing fields/parcels. |
| `get_aoi_soil_summary` | Map units, components, and acreage intersecting an AOI (lightweight, no rating computation). |
| `get_aoi_soil_map` | Soil map as GeoJSON: AOI-clipped soil polygons with map unit properties (musym, muname, acres). Render directly with Leaflet/ArcGIS. |
| `get_aoi_risk_map` | Risk map as GeoJSON for one cointerp-backed concern: soil polygons carrying the dominant component's rating class/value; Order 5 units rated 'Not rated'. |
| `list_concerns` | All CART resource concerns with pipeline type, data source, and whether rating is computable in this server. |
| `get_concern_details` | Domain detail for one concern: name, source, rating domain, not-rated phrase, practices, regulatory crosswalk. |
| `get_rating_domain` | Ordered rating classes (best→worst) for a concern. |
| `list_practices_for_concern` | NRCS conservation practices typically addressing a concern (advisory, from public NRCS practice-points materials). |
| `validate_pipeline` | Re-run the pipeline against the known T9981 Fld3/Fld4 test AOIs and diff against embedded golden values. Requires network. |

## Resources

| URI | Description |
|---|---|
| `cart://concerns` | Index of all concerns |
| `cart://concerns/{key}` | One concern's full profile |
| `cart://domains/{concern}` | Rating domain for a concern |
| `cart://interpretations` | Soil interpretation name mappings |

## Prompts

| Prompt | Description |
|---|---|
| `rate-land-for-conservation` | Guided AI workflow: describe AOI, pick concerns, run `rate_aoi`, summarize ratings for a landowner. |
| `validate-cart-pipeline` | Run `validate_pipeline` and interpret results against golden values. |

## Data sources and public accessibility

All data used at runtime is public — no API keys, no credentials, no internal endpoints.

| Input | Source | Access | Public-domain status |
|---|---|---|---|
| Soil ratings (`cointerp`), interpretation metadata (`sdvattribute`, `distinterpmd`), map units, components, horizons | USDA NRCS SSURGO published snapshots via the Soil Data Access web service (`https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest`) | Anonymous, no auth | Federal government work (17 U.S.C. § 105) |
| `data/concerns.json`, `rating_domains.json`, `interpretations.json`, `practice_links.json`, `concern_regulatory_map.json` | Derived from public NRCS CART documentation and chapters | Embedded in package | Derived from federal works |
| `data/test_aois.json`, `expected_outputs/*.csv` | Public CART documentation test fields (T9981 Fld3/Fld4) | Embedded in package | Derived from federal works |

Notes:

- The SDA web service is a free public federal service without an SLA; the server makes one
  submission per `rate_aoi` call. `Query.aspx` (SOAP) is the documented fallback if the
  `post.rest` endpoint ever changes.
- Ratings are only as fresh as each survey area's last publication (`saverest`); the server
  returns these dates with every rating.
- Embedded data derives only from USDA NRCS federal publications; no third-party documents
  (e.g., journal articles) are redistributed.
- SDA request constraints (100k row cap, timeout/memory failure modes) are enforced by the
  server's request caps (landunits, AOI area, timeout).
- CART SQL queries, rating methodology, and domain tables are documented in the public
  CART reference repository:
  https://github.com/jneme910/CART (Nemecek, J. and Peaslee, S., USDA NRCS).

## Development

```bash
uv run pytest                # offline tests (default)
uv run pytest -m network     # opt-in tests requiring live SDA access
```

## License

MIT for the server code; embedded data is derived from public-domain US federal government
works. See `LICENSE`.
