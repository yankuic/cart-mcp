"""Opt-in benchmark tests driving cart-mcp through a local LLM on a remote
OpenAI-compatible endpoint (Unsloth Studio / llama.cpp backend).

Skipped unless a reachable endpoint is configured. Run with:
    uv run pytest -m bench
Requires the DYNAMIC_MODEL_API_KEY env var (or whatever bench_targets.json
api_key_env names) and a reachable model.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from cart_mcp import cache as cache_mod

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CONFIG = SCRIPTS / "bench_targets.json"

pytestmark = pytest.mark.bench


def _load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _endpoint_reachable(base_url: str, api_key: str) -> bool:
    try:
        resp = httpx.get(
            f"{base_url}/status",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _have_key(cfg: dict) -> bool:
    return bool(os.environ.get(cfg["api_key_env"], ""))


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_mod.clear_cache()
    yield
    cache_mod.clear_cache()


@pytest.fixture(scope="module")
def endpoint():
    cfg = _load_config()
    base_url = cfg["base_url"].rstrip("/")
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key or not _endpoint_reachable(base_url, api_key):
        pytest.skip("bench endpoint unreachable or no API key")
    return base_url, api_key, cfg


@pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_BENCH"),
    reason="set RUN_LIVE_BENCH=1 to execute the live local-LLM benchmark",
)
def test_bench_llm_end_to_end(endpoint):
    """Run the harness on the first configured target (live, slow, remote)."""
    _, _api_key, cfg = endpoint
    target = cfg["targets"][0]
    cmd = [
        sys.executable,
        str(SCRIPTS / "bench_llm.py"),
        "--config",
        str(CONFIG),
        "--target",
        target["label"],
        "--max-steps",
        "8",
        "--out",
        "/tmp/cart_bench_test.json",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
        env={**os.environ, cfg["api_key_env"]: _api_key},
    )
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(Path("/tmp/cart_bench_test.json").read_text(encoding="utf-8"))
    assert report["results"][0]["tool_calls"] >= 1
