# cart-mcp user guide

How to use the **cart-mcp** MCP server: frame an area of interest, rate it for
soil resource concerns, read the results, and integrate it into an AI-assisted
conservation-planning workflow.

This guide is about *using* the server. For the CART methodology itself
(what CART is, the ranking components, the domain tables), see the public CART
reference repository: https://github.com/jneme910/CART.

## 1. Overview & scope

cart-mcp computes **soil-condition ratings** for an area of interest (AOI) using
the same SQL pipeline CART uses, against the public USDA **Soil Data Access**
(SDA) web service, and exposes the results as MCP tools, resources, and prompts.

> **What this is not:** an official NRCS/CART ranking engine. CART's full ranking
> score combines five components (Vulnerability, Planned Practice Effects,
> Resource Priorities, Program Priorities, Cost Efficiency). This server computes
> only the **soil-condition ratings** (the vulnerability input) from published
> SSURGO soil data. Official program determinations come from your NRCS field
> office. Every rating carries the advisory `cart://disclaimer`.

## 2. Key terms

| Term | Meaning |
|---|---|
| **AOI** | The area being assessed (a field, tract, or polygon). Supplied as WKT. |
| **Map Unit** | A distinct soil polygon on the soil survey map (identified by `mukey`). |
| **Component** | A soil series within a map unit (identified by `cokey`). |
| **Major Component** | A component covering ≥15% of a map unit; used in rating. Minor components are excluded. |
| **Rating Class** | The categorical output for a concern (e.g. 'Severe subsidence', 'High', 'Not rated'). |
| **Rating Value** | The numeric rating. Ascending value = **worse** rating. |
| **Not Rated** | Default when a map unit is Order 5 (lowest survey quality) or has no interpretation data. |
| **soils_metadata** | Survey-area publication dates returned with each rating, so you know how fresh the data is. |
| **SSURGO / SDA** | USDA NRCS digital soil database / the public web-service API used to query it. |
| **WKT / EPSG:4326** | Well-Known Text geometry format / the WGS84 lat-long coordinate system the server requires. |

## 3. Inputs: framing an AOI

Ratings need an AOI as **WKT in EPSG:4326**, and must be a Polygon or MultiPolygon:

```
MULTIPOLYGON (((-78.15 41.65, ...)))
```

Getting the WKT:

- **From a GIS** — draw the parcel and export the geometry as WKT (reproject to EPSG:4326 if needed).
- **From QGIS** — the harness pattern below converts the canvas/layer to EPSG:4326 WKT in one call.
- **A sample** — `examples/t89_fld1.wkt` is a valid, ready-to-use AOI.

Practical guardrails enforced by the server (fail fast with a `ValueError` before
any request):

| Limit | Value |
|---|---|
| AOI bounding-box area | ≤ 25 deg² |
| Landunits per call | ≤ 50 |
| Landunit name length | ≤ 20 characters |
| Geometry type | Polygon / MultiPolygon only |
| Coordinate reference | EPSG:4326 (WGS84) |
| Client timeout | 180 s per request |

## 4. Happy path (token-efficient)

The recommended, low-token workflow:

1. **`list_concerns`** — see which concerns are computable.
2. **`rate_aoi`** (or `rate_aois` for several parcels) — compute the ratings.
3. **`get_concern_details(summary=True)`** — compact overview (rating classes,
   top-3 practices) for every concern. Use the **full** mode (`summary=False`)
   only for the top 2–3 concerns you need to explain in depth.
4. **`list_practices_for_concern`** — NRCS practices that typically address a concern.

Prefer `summary=True` for most concerns: the summary mode is ~80 tokens vs ~280
for the full profile, which matters in long agent sessions. This is the pattern
the `rate-land-for-conservation` prompt follows.

For multiple fields, `rate_aois` rates several landunits in one run. Invalid
WKTs do not sink the batch — they are reported per-landunit in `errors`:

```json
{"landunits": ["F1", "F2"], "ratings": [...], "errors": [{"landunit": "BAD", "error": "invalid WKT: ..."}]}
```

## 5. Reading the output

Each rating carries:

- **`rating_name`** — the resource concern.
- **`rating_value`** — numeric severity. **Ascending = worse** (1 is the worst class for most concerns).
- **`rating_class`** — the human-readable class (e.g. 'Severe subsidence', 'High', 'Not rated').
- **`soils_metadata`** — survey-area publication dates; ratings are only as fresh as the last publication.

**`Not rated`** means the map unit is Order 5 (lowest survey quality) or has no
interpretation data — not "no concern". Treat it as "data insufficient to rate".

On the map tools, `truncated` and `dropped_features` report when the GeoJSON was
capped to bound the payload (see below).

## 6. Maps (soil map / risk map)

- **`get_aoi_soil_map`** — soil polygons clipped to the AOI as GeoJSON, with map-unit properties (`mukey`, `musym`, `muname`, `invesintens`, `farmlndcl`, `poly_acres`). No ratings.
- **`get_aoi_risk_map`** — the same polygons carrying the dominant component's rating (`rating_value`, `rating_class`) for one cointerp-backed concern.

Both return valid GeoJSON you can render directly in Leaflet/ArcGIS. Large AOIs
are bounded by feature-count and byte caps; when features are dropped, the
response sets `truncated: true` and `dropped_features: N` so clients know the
payload was reduced.

## 7. Integration patterns

### Transports

cart-mcp runs over stdio (default, for MCP clients) or HTTP:

```bash
uv run cart-mcp                                 # stdio
uv run cart-mcp --transport streamable-http --port 8000   # Streamable HTTP (recommended for remote clients)
uv run cart-mcp --transport sse --port 8000     # legacy HTTP+SSE
```

Register it in any MCP client config:

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

### QGIS orchestration

Drive QGIS Desktop and cart-mcp from one agent (e.g. opencode): extract an AOI
from the QGIS canvas, rate it with cart-mcp, and map the result back into QGIS.
Tools appear prefixed `cart_*` (rating) and `qgis_*` (QGIS).

1. **AOI** — canvas extent or layer features → EPSG:4326 WKT in one call: qgis
   `evaluate_expression` with `geom_to_wkt(transform($geometry, 'EPSG:4326'))`.
2. **Rate** — `cart_rate_aoi` / `cart_rate_aois` (optional `concerns` subset);
   maps via `cart_get_aoi_soil_map` / `cart_get_aoi_risk_map`.
3. **Map** — save GeoJSON to a temp file → qgis `add_vector_layer` →
   `set_layer_style` → `zoom_to_layer` → `render_map`.

A fully worked run (T89 Fld1, step-by-step prompts, expected outputs,
troubleshooting) is in `examples/qgis_cart_example.md`.

### Guided workflow

The **`rate-land-for-conservation`** prompt steers an agent through the whole
flow: get/ask for the AOI, run `rate_aoi`, summarize each concern in plain
language (summary mode), flag `Not rated` results, and never present the ratings
as official — pointing to `cart://disclaimer`.

### Resources

| URI | Description |
|---|---|
| `cart://disclaimer` | Advisory disclaimer for ratings |
| `cart://concerns` | Index of all concerns |
| `cart://concerns/{key}` | One concern's full profile |
| `cart://domains/{concern}` | Rating domain for a concern |
| `cart://interpretations` | Soil interpretation name mappings |

## 8. Benchmarking

cart-mcp can be benchmarked driven by local LLMs on a remote OpenAI-compatible
endpoint. See `scripts/bench_llm.py` + `scripts/bench_targets.json`.

```bash
uv run python scripts/bench_llm.py --target qwen3.6-27b-mtp --out out.json
uv run python scripts/bench_llm.py --out matrix.json        # all targets
```

## 9. Caveats & troubleshooting

- **Advisory only.** Ratings are educational estimates of current conditions, not
  official NRCS determinations. Carry `cart://disclaimer` and the returned
  `soils_metadata` (survey dates).
- **Live service.** Each rating hits the public SDA web service (~10 s per call);
  avoid `validate_pipeline` in interactive chat.
- **No credentials.** All data is public; the server sends no auth and talks only
  to the public SDA endpoint.

| Symptom | Likely cause / fix |
|---|---|
| `SDA returned no rows` | The AOI may not intersect any SSURGO map units. Retry with a larger or valid polygon. |
| `unknown concern: '...'` | Check the exact concern key via `list_concerns` (aliases are supported, but use the canonical key). |
| `invalid WKT` | Geometry must be a valid Polygon/MultiPolygon in EPSG:4326. |
| `rate_aois` partial `errors` | One or more landunits had invalid WKTs; the valid ones are still rated. |
| GeoJSON `truncated: true` | The AOI is large; some features were dropped to bound the payload. |
