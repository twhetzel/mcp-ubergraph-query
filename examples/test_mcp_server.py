"""
Test the MCP server locally by spawning it over stdio and calling tools.

Run from project root with:
    uv run python examples/test_mcp_server.py

Requires network access to the Ubergraph SPARQL endpoint.
"""

import asyncio
import json
import sys
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


# Project root (directory containing pyproject.toml)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def run_test():
    # Spawn the MCP server as a subprocess; it communicates over stdin/stdout
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ubergraph_query.server"],
        cwd=PROJECT_ROOT,
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            print("Initializing MCP session...")
            await session.initialize()
            print("Initialized.\n")

            # 1. List tools
            print("=" * 60)
            print("Tools")
            print("=" * 60)
            result = await session.list_tools()
            for tool in result.tools:
                print(f"  - {tool.name}: {tool.description[:60]}...")
            print()

            # 2. get_term_info
            print("=" * 60)
            print("get_term_info(MONDO:0005015)")
            print("=" * 60)
            result = await session.call_tool("get_term_info", {"curie": "MONDO:0005015"})
            for content in result.content:
                if hasattr(content, "text"):
                    data = json.loads(content.text)
                    print(json.dumps(data, indent=2, default=str))
            print()

            # 3. search_terms
            print("=" * 60)
            print("search_terms('diabetes', ontologies=['MONDO'], limit=3)")
            print("=" * 60)
            result = await session.call_tool(
                "search_terms",
                {"text": "diabetes", "ontologies": ["MONDO"], "limit": 3},
            )
            for content in result.content:
                if hasattr(content, "text"):
                    data = json.loads(content.text)
                    print(json.dumps(data, indent=2, default=str))
            print()

            # 4. get_hierarchy (parents)
            print("=" * 60)
            print("get_hierarchy(MONDO:0005015, relation='parents', depth=1)")
            print("=" * 60)
            result = await session.call_tool(
                "get_hierarchy",
                {"curie": "MONDO:0005015", "relation": "parents", "depth": 1},
            )
            for content in result.content:
                if hasattr(content, "text"):
                    data = json.loads(content.text)
                    print(json.dumps(data, indent=2, default=str))

    print("\nDone. Server process exited.")


def main():
    anyio.run(run_test)


if __name__ == "__main__":
    main()
