"""Benchmark harness for cart-mcp driven by local LLMs on an OpenAI-compatible
endpoint (Unsloth Studio / llama.cpp backend).

Spawns the cart-mcp server over stdio, connects as a real MCP client, and drives
an agent loop against a remote chat-completions endpoint with tool calling. For
each target in the model matrix (scripts/bench_targets.json) it reports token
use, a tool-call trace, latency, and failure/retry counts.

Usage:
    uv run python scripts/bench_llm.py [--config scripts/bench_targets.json]
        [--target <label>] [--out out.json] [--task <prompt>] [--max-steps N]

Read-only w.r.t. the local repo; it talks to the remote endpoint (loads/unloads
models) and to the public Soil Data Access service via cart-mcp.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import timedelta
from pathlib import Path

import httpx
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).resolve().parent / "bench_targets.json"
DEFAULT_AOI = REPO_ROOT / "examples" / "t89_fld1.wkt"

DEFAULT_TASK = (
    "Using the CART tools, rate the T89 Fld1 AOI for soil compaction and give "
    "the landowner the rating and the top practice, using summary mode."
)


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_aoi(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def build_task(base: str, aoi_wkt: str) -> str:
    """Append the AOI WKT so the model can pass it to rate_aoi."""
    return f"{base}\n\nAOI WKT (EPSG:4326):\n{aoi_wkt}"


def count_tokens(text: str) -> int:
    """Best-effort token estimate (chars / 4). Server `usage` is authoritative;
    this is only a fallback when the endpoint omits it."""
    return max(1, len(text) // 4)


# -------------------------------------------------------------------- endpoint


class ChatEndpoint:
    """Thin OpenAI-compatible client for the remote inference backend."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.Client(timeout=httpx.Timeout(600.0, connect=20.0))

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def load_model(self, load_payload: dict) -> dict:
        return self._post("load", load_payload)

    def unload_model(self, model_path: str) -> dict:
        return self._post("unload", {"model_path": model_path})

    def status(self) -> dict:
        return self._get("status")

    def chat(self, payload: dict) -> dict:
        return self._post("chat/completions", payload)

    def _get(self, path: str) -> dict:
        resp = self._client.get(self._url(path), headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        resp = self._client.post(
            self._url(path), headers=self._headers, json=payload
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"endpoint {path} failed ({resp.status_code}): "
                f"{resp.text[:300]}"
            )
        return resp.json()

    def close(self) -> None:
        self._client.close()


# ------------------------------------------------------------------- MCP tools


def to_openai_tools(tool_list) -> list[dict]:
    """Convert MCP tool schemas to OpenAI function definitions."""
    tools = []
    for t in tool_list:
        params = getattr(t, "inputSchema", None) or {}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": params,
                },
            }
        )
    return tools


# ------------------------------------------------------------------ agent loop


async def run_tool_call(session: ClientSession, call: dict) -> dict:
    """Execute one tool call against the MCP session; returns {ok, output, error}."""
    name = call["function"]["name"]
    try:
        args = json.loads(call["function"]["arguments"] or "{}")
    except json.JSONDecodeError as exc:
        return {"ok": False, "output": "", "error": f"malformed args: {exc}"}

    result = await session.call_tool(
        name, args or None, read_timeout_seconds=timedelta(seconds=180)
    )
    if getattr(result, "isError", False):
        text = "".join(b.text for b in result.content if getattr(b, "text", None))
        return {"ok": False, "output": text, "error": text or "tool error"}
    text = "".join(b.text for b in result.content if getattr(b, "text", None))
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = text
    return {"ok": True, "output": parsed}


def called_names(messages: list[dict]) -> set[str]:
    """Set of tool names the model has invoked across the conversation."""
    names: set[str] = set()
    for m in messages:
        for c in m.get("tool_calls") or []:
            name = c.get("function", {}).get("name")
            if name:
                names.add(name)
    return names


async def run_target(
    endpoint: ChatEndpoint,
    session: ClientSession,
    target: dict,
    tools: list[dict],
    task: str,
    max_steps: int,
    max_tokens: int = 4096,
) -> dict:
    """Run the agent loop for one model; returns a full trace report."""
    label = target["label"]
    model = target["model"]
    report: dict = {
        "label": label,
        "model": model,
        "rounds": [],
        "total": {"prompt": 0, "completion": 0, "total": 0, "cached": 0},
        "tool_calls": 0,
        "tool_errors": 0,
        "retries": 0,
        "latency_ms": [],
        "schema_chars": len(json.dumps(tools)),
        "schema_tokens_est": count_tokens(json.dumps(tools)),
        "success": False,
        "load_ms": None,
        "unload_ms": None,
        "error": None,
    }

    # load
    load_payload = target.get("load", {"model_path": model})
    t0 = time.perf_counter()
    try:
        endpoint.load_model(load_payload)
    except Exception as exc:  # noqa: BLE001 - bench must not crash a run
        report["error"] = f"load failed: {exc}"
        report["load_ms"] = (time.perf_counter() - t0) * 1000
        return report
    report["load_ms"] = (time.perf_counter() - t0) * 1000

    messages: list[dict] = [{"role": "user", "content": task}]
    steps = 0
    chat_failures = 0
    try:
        while steps < max_steps:
            steps += 1
            payload = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "stream": False,
                "enable_thinking": False,
                "max_tokens": max_tokens,
            }
            t_start = time.perf_counter()
            try:
                resp = endpoint.chat(payload)
            except Exception as exc:  # noqa: BLE001 - bench must not crash a run
                report["retries"] += 1
                chat_failures += 1
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"The previous request failed on the server "
                            f"({exc}). Please retry, making sure any tool-call "
                            "arguments are valid, complete JSON."
                        ),
                    }
                )
                if chat_failures >= 3:
                    report["error"] = f"chat failed repeatedly: {exc}"
                    break
                continue
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            report["latency_ms"].append(elapsed_ms)

            usage = resp.get("usage") or {}
            report["total"]["prompt"] += usage.get("prompt_tokens", 0)
            report["total"]["completion"] += usage.get("completion_tokens", 0)
            report["total"]["total"] += usage.get("total_tokens", 0)
            report["total"]["cached"] += (usage.get("prompt_tokens_details") or {}).get(
                "cached_tokens", 0
            )

            choice = (resp.get("choices") or [{}])[0]
            msg = choice.get("message", {})

            round_rec: dict = {
                "step": steps,
                "elapsed_ms": round(elapsed_ms, 1),
                "usage": usage,
                "timings": resp.get("timings"),
                "content": (msg.get("content") or "")[:2000],
                "tool_calls": msg.get("tool_calls") or [],
            }
            report["rounds"].append(round_rec)

            tcalls = msg.get("tool_calls") or []
            if tcalls:
                for call in tcalls:
                    report["tool_calls"] += 1
                    out = await run_tool_call(session, call)
                    if not out["ok"]:
                        report["tool_errors"] += 1
                    messages.append({"role": "assistant", "tool_calls": tcalls})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", ""),
                            "content": json.dumps(out["output"], default=str)[:4000],
                        }
                    )
                continue

            # no more tool calls -> final answer
            report["success"] = "rate_aoi" in called_names(messages)
            break

        if steps >= max_steps:
            report["error"] = report.get("error") or f"max_steps ({max_steps}) reached"
    finally:
        try:
            t0 = time.perf_counter()
            endpoint.unload_model(load_payload.get("model_path", model))
            report["unload_ms"] = (time.perf_counter() - t0) * 1000
        except Exception as exc:  # noqa: BLE001 - bench must not crash a run
            report["unload_ms"] = None
            report["error"] = report.get("error") or f"unload failed: {exc}"

    return report


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--target", default=None, help="run a single target by label")
    ap.add_argument("--out", default=None, help="write JSON report to this path")
    ap.add_argument("--task", default=DEFAULT_TASK)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--aoi", default=str(DEFAULT_AOI))
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        raise SystemExit(f"{cfg['api_key_env']} env var not set")

    targets = cfg["targets"]
    if args.target:
        targets = [t for t in targets if t["label"] == args.target]
        if not targets:
            raise SystemExit(f"no target with label {args.target!r} in {args.config}")

    aoi_wkt = load_aoi(Path(args.aoi))
    task = build_task(args.task, aoi_wkt)

    params = StdioServerParameters(
        command="uv", args=["run", "cart-mcp"], cwd=str(REPO_ROOT)
    )

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tool_list = (await session.list_tools()).tools
        tools = to_openai_tools(tool_list)

        endpoint = ChatEndpoint(cfg["base_url"], api_key)
        try:
            results = []
            for target in targets:
                print(f"\n=== {target['label']} ({target['model']}) ===")
                report = await run_target(
                    endpoint, session, target, tools, task, args.max_steps, args.max_tokens
                )
                results.append(report)
                _print_report(report)

            summary = {"config": cfg, "task": task, "results": results}
            if args.out:
                Path(args.out).write_text(
                    json.dumps(summary, indent=2, default=str), encoding="utf-8"
                )
                print(f"\nwrote report -> {args.out}")
        finally:
            endpoint.close()


def _print_report(report: dict) -> None:
    tot = report["total"]
    print(
        f"  tokens: prompt={tot['prompt']} completion={tot['completion']} "
        f"total={tot['total']} (cached={tot['cached']})"
    )
    print(f"  tool_calls={report['tool_calls']} tool_errors={report['tool_errors']} "
          f"retries={report['retries']} success={report['success']}")
    print(f"  load={report.get('load_ms')}ms unload={report.get('unload_ms')}ms "
          f"schema={report['schema_chars']}ch / ~{report['schema_tokens_est']}tok")
    if report["rounds"]:
        avg = sum(r["elapsed_ms"] for r in report["rounds"]) / len(report["rounds"])
        print(f"  rounds={len(report['rounds'])} avg_latency={avg:.0f}ms")
        for r in report["rounds"]:
            calls = ", ".join(c["function"]["name"] for c in r.get("tool_calls", []))
            print(f"    step {r['step']}: {calls or '(answer)'} "
                  f"{r['elapsed_ms']:.0f}ms prompt={r['usage'].get('prompt_tokens')} "
                  f"comp={r['usage'].get('completion_tokens')}")
    if report.get("error"):
        print(f"  error: {report['error']}")


if __name__ == "__main__":
    asyncio.run(main())
