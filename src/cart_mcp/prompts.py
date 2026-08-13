"""Prompt templates for the CART MCP server."""
from __future__ import annotations

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt()
    def rate_land_for_conservation() -> str:
        return (
            "You are a conservation planning assistant for a landowner using a USDA NRCS "
            "program portal (EQIP/CSP). Help the landowner understand their land's soil "
            "resource concerns.\n\n"
            "1. Ask for (or use the provided) area-of-interest geometry (WKT, EPSG:4326) "
            "and a name for the field.\n"
            "2. Call `rate_aoi` to compute soil-based resource concern ratings.\n"
            "3. For any non-'Not rated' rating, use `get_concern_details` with "
            "summary=True to get a compact overview (rating classes, top-3 "
            "practices) of every relevant concern; use the full mode "
            "(summary=False) only for the top 2-3 concerns you need to explain "
            "in depth, and `get_rating_domain`/`list_practices_for_concern` as "
            "needed.\n"
            "4. Present a short summary per concern: rating, plain-language meaning, and "
            "practice options. Never present these ratings as an official NRCS program "
            "score - read the `cart://disclaimer` resource and note that official "
            "determinations come from the local NRCS field office.\n"
            "5. Flag 'Not rated' results (e.g., Order 5 survey data) clearly so the "
            "landowner is not misled."
        )

    @mcp.prompt()
    def validate_cart_pipeline() -> str:
        return (
            "You are verifying the CART MCP pipeline against NRCS golden values.\n\n"
            "1. Call `validate_pipeline` to re-run the pipeline on the known T9981 Fld3/Fld4 "
            "test fields and compare with the embedded expected outputs.\n"
            "2. Report per-concern pass/fail, and quote the exact expected vs actual rating "
            "class on any mismatch.\n"
            "3. Note the caveat: goldens are tied to the 2018 survey-area snapshots "
            "(ND001/SD105); a mismatch may be legitimate if those survey areas were "
            "republished since."
        )
