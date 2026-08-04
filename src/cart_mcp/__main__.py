"""Entry point: `python -m cart_mcp`."""
from __future__ import annotations

import argparse


def main() -> None:
    from .server import serve

    parser = argparse.ArgumentParser(prog="cart-mcp", description="CART MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument("--port", type=int, default=8000, help="port for SSE transport")
    args = parser.parse_args()
    serve(args.transport, args.port)


if __name__ == "__main__":
    main()
