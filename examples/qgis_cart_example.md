# Example: rate T89 Fld1 with cart-mcp and map it in QGIS via qgis-mcp

End-to-end walkthrough of the harness integration: one agent (opencode) drives the
cart-mcp rating server and the QGIS MCP server, moves the AOI and results between
them, and produces a styled soil/risk map in QGIS. Verified live on 2026-08-02
(QGIS 3.34.4, qgis-mcp plugin 0.9.1, cart-mcp v0.1.0).

## 0. Prerequisites

- [uv](https://docs.astral.sh/uv/) on PATH; repo synced (`uv sync`).
- QGIS 3.28+ with the **QGIS MCP** plugin (Plugins > Manage and Install Plugins >
  search "QGIS MCP").
- `opencode.json` at the repo root (registers the `cart` and `qgis` servers) and
  opencode started in this repo.
- Network access to the public USDA Soil Data Access service (ratings are live).

## 1. Setup the MCP servers

### 1a. Install the QGIS MCP plugin

1. QGIS 3.28+ -> Plugins -> Manage and Install Plugins -> search **QGIS MCP** -> Install.
2. Restart QGIS, open the **QGIS MCP** dock (Plugins > QGIS MCP) and click
   **Start Server** (TCP localhost:9876).
3. Keep plugin and server in sync: after any update, ask the agent to call
   `qgis_diagnose`.

### 1b. Register the servers in opencode

`opencode.json` at the repo root registers both servers (already committed in
this repo):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "cart": {
      "type": "local",
      "command": ["uv", "run", "cart-mcp"],
      "cwd": ".",
      "enabled": true,
      "timeout": 30000
    },
    "qgis": {
      "type": "local",
      "command": ["uvx", "--from", "https://github.com/nkarasiak/qgis-mcp/archive/refs/heads/main.zip", "qgis-mcp-server"],
      "enabled": true,
      "timeout": 60000
    }
  }
}
```

`cwd: "."` pins the cart server to the workspace root; the timeouts cover the
first-run `uv sync` and the `uvx` archive download. The first `uvx` run downloads
the qgis-mcp archive (network required), then it is cached.

### 1c. Other MCP clients (Claude Desktop, Codex, ...)

Copy the `cart` and `qgis` entries from `examples/mcp_config.json` into the
client's config file (`claude_desktop_config.json`, `~/.codex/config.toml`,
`~/.gemini/settings.json`, ...).

### 1d. Verify the connection

1. Restart opencode so it loads the config; `/mcp` should list the `cart_*` and
   `qgis_*` tools.
2. Ask: `call qgis_ping` -> expect `{"pong": true}` (QGIS must be running with
   the plugin server started).

## 2. Run the example

The AOI is the notebook's T89 Fld1 field (Pennsylvania, PA105). The source
geometry is a single-line EPSG:4326 WKT (the only accepted CRS). Rather than a
local file, it lives in the CART SQL geometry catalog at
`https://raw.githubusercontent.com/jneme910/CART/master/SQL-Library/AOI_Geometry_Examples.txt` -
a SQL file with one `GEOMETRY::STGeomFromText('<WKT>', 4326)` line per AOI
followed by an `INSERT INTO #AoiTable ( ... ) VALUES ('T89 Fld1', ...)`. The
agent must fetch that URL, find the `'T89 Fld1'` insert, and extract the WKT
from its preceding `STGeomFromText` line (verified identical to the notebook
cell 11 inline geometry). Generated maps and renders land in `examples/output/`
(gitignored); the agent creates the directory if missing.

Set <qgis/accessible/directory/>, then paste this prompt in your chat (the agent fetches and reads the WKT itself):

```markdown
Using the cart and qgis tools, rate the AOI T89 Fld1 for
"Soil Susceptibility to Compaction":

0. Fetch https://raw.githubusercontent.com/jneme910/CART/master/SQL-Library/AOI_Geometry_Examples.txt,
   find the 'T89 Fld1' INSERT and take the WKT from its preceding STGeomFromText
   line (one line, EPSG:4326), and use it verbatim in every cart call.
1. cart_rate_aoi -> show rating_class, rating_value, soils_metadata, disclaimer.
2. cart_get_aoi_risk_map for the same concern.
3. Save FeatureCollections to <qgis/accessible/directory/>.
4. qgis: create a memory MultiPolygon layer "T89 Fld1 AOI" with the AOI feature;
   add GeoJSON file as a vector layer.
5. Style layer categorized on rating_class (RdYlGn).
6. Zoom to the AOI.
```

### 2b. Natural-language alternative

Naming each tool is not required: the agent reads every MCP tool's name and
description from the registered servers and picks the calls itself. Same end
state as 2a (same AOI, same output paths, same expected results in Section 3),
but the goal is stated in plain language:

```markdown
Here's a farm field in Pennsylvania I'd like to check. Fetch the AOI catalog
from https://raw.githubusercontent.com/jneme910/CART/master/SQL-Library/AOI_Geometry_Examples.txt,
grab the T89 Fld1 boundary (the WKT in its STGeomFromText line, one line,
EPSG:4326). Rate it for "Soil Susceptibility to Compaction", show me where the
high-risk areas are on a map in QGIS, then render
the result in this chat. 
```

The agent should infer `cart_rate_aoi`, `cart_get_aoi_risk_map`,
`cart_get_aoi_soil_map`, the QGIS layer creation/styling/ordering, and the
render. Use the WKT verbatim. The tradeoff: tool selection, styling details,
and intermediate file names are up to the agent, so the render may differ
slightly from the deterministic run even though the ratings and end state
match.

## 3. Expected results

- `cart_rate_aoi`: `rating_value 1`, `rating_class "High"`,
  `soils_metadata "PA105 2025-09-04 13:13:25"`. The field has a High/Medium
  spread; the landunit rating reflects the dominant component.
- Risk map: 15 features, classes {High, Medium}.
- Soil map: 15 features, 13 map-unit symbols (BuB, CeC, CeD, CmC, CmD, CoB,
  HaC, HaD, HcC, HcD, HcfC, LeC, LeD).
- Render: red = High, green = Medium from the risk layer, with the Spectral
  soil classes blended on top at 0.7 opacity.

## 4. Variations

- **Any other AOI**: have the agent emit EPSG:4326 WKT from a QGIS layer with
  qgis `evaluate_expression` and
  `geom_to_wkt(transform($geometry, 'EPSG:4326'))`, then rate it.
- **Multiple fields**: `cart_rate_aois` with `[{landunit, wkt}, ...]` in one call.
- **Other concerns**: drop the `concerns` filter to rate every ratable concern.

## 5. Troubleshooting

- `qgis_ping` false: QGIS not running, or Start Server not clicked in the
  QGIS MCP dock.
- `qgis_diagnose` reports a plugin/server version mismatch (e.g. plugin 0.9.1 vs
  server 0.9.3): harmless for these tools; update the plugin if you hit
  "unknown command" errors.
- cart rejects the AOI (`invalid WKT: ParseException`): the geometry must be
  one line, EPSG:4326, with no trailing text.
- Soil map invisible after adding: QGIS stacked it below the risk layer - fix
  with qgis `set_layer_order`.
- Each rating takes ~10 s (SDA round trip); avoid running `cart_validate_pipeline`
  from chat (multi-minute sweep).

## 6. Optional headless render check

If you cannot view the rendered PNG, verify it pixel-wise (needs the dev extra):

```bash
uv run python - <<'PYEOF'
from collections import Counter
from PIL import Image
img = Image.open("examples/output/cart_t89_render.png").convert("RGB")
px = list(img.get_flattened_data())
n = len(px)
c = Counter(p for p in px if p != (255, 255, 255))
print(f"non-white {100*sum(c.values())/n:.1f}%, distinct colors {len(c)}")
for color, cnt in c.most_common(5):
    print(f"{color}  {100*cnt/n:.2f}%")
PYEOF
```

Reference values from the verified run: before the soil layer is reordered on
top, the render shows the risk layer alone - red (215,25,28) ~17% and green
(26,150,65) ~17% (RdYlGn endpoints for High/Medium). After reordering, distinct
colors jump from ~1800 to ~4300 with Spectral teal/orange/yellow classes
visible - the soil map blended over the risk map.
