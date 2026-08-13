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

See **[`docs/usage.md`](docs/usage.md)** for the user guide: framing an AOI, the
token-efficient rating workflow, reading output, soil/risk maps, QGIS
orchestration, benchmarking, and troubleshooting.

## Tools

| Tool | Description |
|---|---|
| `rate_aoi` | Rate an AOI (WKT, EPSG:4326) for resource concerns via the SDA web service. Accepts an optional `concerns` subset. Returns ratings with survey-data dates. |
| `rate_aois` | Rate multiple landunits in one pipeline run (`aois` = [{landunit, wkt}]); ideal for comparing fields/parcels. Invalid WKTs are reported per-landunit in `errors` without sinking the others. |
| `get_aoi_soil_summary` | Map units, components, and acreage intersecting an AOI (lightweight, no rating computation). |
| `get_aoi_soil_map` | Soil map as GeoJSON: AOI-clipped soil polygons with map unit properties (musym, muname, acres). Render directly with Leaflet/ArcGIS. Feature-count/byte caps bound the payload; `truncated`/`dropped_features` report omissions. |
| `get_aoi_risk_map` | Risk map as GeoJSON for one cointerp-backed concern: soil polygons carrying the dominant component's rating class/value; Order 5 units rated 'Not rated'. Feature-count/byte caps bound the payload; `truncated`/`dropped_features` report omissions. |
| `list_concerns` | All CART resource concerns with pipeline type, data source, and whether rating is computable in this server. |
| `get_concern_details` | Profile for one concern. `summary=True` returns a compact profile (rating classes, top-3 practices); `summary=False` returns the full profile (practices, regulatory crosswalk, interpretation). |
| `get_rating_domain` | Ordered rating classes (best→worst) for a concern. |
| `list_practices_for_concern` | NRCS conservation practices typically addressing a concern (advisory, from public NRCS practice-points materials). |
| `validate_pipeline` | Re-run the pipeline against the known T9981 Fld3/Fld4 test AOIs and diff against embedded golden values. Requires network. |

## Resources

| URI | Description |
|---|---|
| `cart://disclaimer` | Advisory disclaimer for ratings |
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
uv run pytest -m bench       # opt-in benchmark: cart-mcp driven by a local LLM
```

## License

MIT for the server code; embedded data is derived from public-domain US federal government
works. See `LICENSE`.
