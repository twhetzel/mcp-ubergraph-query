"""
Example usage of mcp-ubergraph-query tools via direct async calls.

Run with:
    uv run python examples/example_usage.py
"""

import asyncio
import json

from ubergraph_query.sparql_client import get_client
from ubergraph_query.query_builder import (
    build_term_info_query,
    build_search_query,
    build_parents_query,
    HEALTH_CHECK_QUERY,
)
from ubergraph_query.validators import validate_sparql_query


def pretty(data: dict) -> str:
    return json.dumps(data, indent=2)


async def example_health_check():
    print("=" * 60)
    print("Health Check")
    print("=" * 60)
    client = get_client()
    result = await client.health_check()
    print(pretty(result))


async def example_term_info():
    print("\n" + "=" * 60)
    print("Term Info: MONDO:0005015 (diabetes mellitus)")
    print("=" * 60)
    client = get_client()
    query = build_term_info_query("MONDO:0005015")
    result = await client.execute(query)
    print(f"Query time: {result['query_time_ms']}ms")
    print(f"Result count: {result['result_count']}")
    print("Sample rows:")
    for row in result["results"][:3]:
        print(" ", row)


async def example_search():
    print("\n" + "=" * 60)
    print("Search: 'diabetes' in MONDO")
    print("=" * 60)
    client = get_client()
    query = build_search_query("diabetes", ontologies=["MONDO"], limit=5)
    result = await client.execute(query)
    print(f"Query time: {result['query_time_ms']}ms")
    for row in result["results"]:
        print(f"  {row}")


async def example_hierarchy():
    print("\n" + "=" * 60)
    print("Parents of MONDO:0005015")
    print("=" * 60)
    client = get_client()
    query = build_parents_query("MONDO:0005015", depth=1)
    result = await client.execute(query)
    print(f"Query time: {result['query_time_ms']}ms")
    for row in result["results"]:
        print(f"  {row}")


async def example_custom_query():
    print("\n" + "=" * 60)
    print("Custom SPARQL: Classes in UBERON")
    print("=" * 60)
    raw_query = """\
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?term ?label WHERE {
  ?term rdfs:label ?label .
  FILTER(STRSTARTS(STR(?term), "http://purl.obolibrary.org/obo/UBERON_"))
  FILTER(CONTAINS(LCASE(?label), "kidney"))
}
LIMIT 5
"""
    query = validate_sparql_query(raw_query)
    client = get_client()
    result = await client.execute(query)
    print(f"Query time: {result['query_time_ms']}ms")
    for row in result["results"]:
        print(f"  {row}")


async def main():
    await example_health_check()
    await example_term_info()
    await example_search()
    await example_hierarchy()
    await example_custom_query()


if __name__ == "__main__":
    asyncio.run(main())
