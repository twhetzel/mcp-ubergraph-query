"""MCP server exposing Ubergraph SPARQL tools."""

import logging
import re
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import config
from .cache import get_cache
from .query_builder import (
    build_ancestors_query,
    build_children_query,
    build_descendants_query,
    build_parents_query,
    build_search_query,
    build_term_children_query,
    build_term_info_query,
    build_term_parents_query,
)
from .sparql_client import SPARQLError, get_client
from .validators import (
    ValidationError,
    curie_to_iri,
    validate_curie,
    validate_depth,
    validate_limit,
    validate_ontology_prefixes,
    validate_sparql_query,
    validate_timeout,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IRI → CURIE helper
# ---------------------------------------------------------------------------

_OBO_IRI_RE = re.compile(r"http://purl\.obolibrary\.org/obo/([A-Za-z]+)_(\w+)")


def _iri_to_curie(iri: str) -> str | None:
    m = _OBO_IRI_RE.match(iri)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return None


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

app = Server("mcp-ubergraph-query")


# ------------------------------------------------------------------
# Tool definitions
# ------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="query_ubergraph",
            description=(
                "Execute a SPARQL query against the Ubergraph endpoint. "
                "Use for custom queries when other tools don't fit your needs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SPARQL query to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "default": 30,
                        "description": "Query timeout in seconds (max: 60)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 100,
                        "description": "Maximum results to return (max: 1000)",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["json", "turtle", "xml"],
                        "default": "json",
                        "description": "Result format",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_term_info",
            description=(
                "Get comprehensive information about a specific ontology term "
                "(labels, definitions, synonyms, types)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "curie": {
                        "type": "string",
                        "description": "Ontology term CURIE (e.g., 'MONDO:0005015', 'HP:0001945')",
                    },
                    "include_hierarchy": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include immediate parent and child terms",
                    },
                },
                "required": ["curie"],
            },
        ),
        Tool(
            name="search_terms",
            description=(
                "Search for ontology terms by label or synonym. "
                "Returns matching terms with their IDs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Search text (label or synonym)",
                    },
                    "ontologies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by ontology prefixes (e.g., ['MONDO', 'HP'])",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum results",
                    },
                    "exact_match": {
                        "type": "boolean",
                        "default": False,
                        "description": "Require exact match vs substring",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="get_hierarchy",
            description=(
                "Get hierarchical relationships for a term "
                "(parents, children, ancestors, descendants)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "curie": {
                        "type": "string",
                        "description": "Ontology term CURIE",
                    },
                    "relation": {
                        "type": "string",
                        "enum": ["parents", "children", "ancestors", "descendants"],
                        "default": "parents",
                        "description": "Type of relationship to retrieve",
                    },
                    "depth": {
                        "type": "integer",
                        "default": 1,
                        "description": "How many levels to traverse (1-5)",
                    },
                },
                "required": ["curie"],
            },
        ),
    ]


# ------------------------------------------------------------------
# Tool call dispatcher
# ------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "query_ubergraph":
            result = await _tool_query_ubergraph(arguments)
        elif name == "get_term_info":
            result = await _tool_get_term_info(arguments)
        elif name == "search_terms":
            result = await _tool_search_terms(arguments)
        elif name == "get_hierarchy":
            result = await _tool_get_hierarchy(arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}
    except ValidationError as exc:
        result = {"error": f"Validation error: {exc}"}
    except SPARQLError as exc:
        result = {"error": f"SPARQL error: {exc}"}
    except Exception as exc:
        logger.exception("Unexpected error in tool %s", name)
        result = {"error": f"Internal error: {exc}"}

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


# ------------------------------------------------------------------
# Tool implementations
# ------------------------------------------------------------------

async def _tool_query_ubergraph(args: dict[str, Any]) -> dict[str, Any]:
    raw_query: str = args.get("query", "")
    timeout = validate_timeout(int(args.get("timeout", config.QUERY_TIMEOUT_DEFAULT)))
    limit = validate_limit(int(args.get("limit", config.QUERY_LIMIT_DEFAULT)))
    fmt = args.get("format", "json")
    if fmt not in ("json", "turtle", "xml"):
        fmt = "json"

    # Validate & inject LIMIT
    query = validate_sparql_query(raw_query)

    # Override LIMIT with user's explicit value if smaller than injected
    # (validate_sparql_query already handles injection; we just ensure the
    # user's limit parameter caps it further if desired)
    import re as _re
    limit_re = _re.compile(r"\bLIMIT\s+\d+\b", _re.IGNORECASE)
    query = limit_re.sub(f"LIMIT {limit}", query)

    client = get_client()
    return await client.execute(query, timeout=timeout, format=fmt)


async def _tool_get_term_info(args: dict[str, Any]) -> dict[str, Any]:
    curie: str = args.get("curie", "").strip()
    include_hierarchy: bool = bool(args.get("include_hierarchy", False))

    validate_curie(curie)  # raises ValidationError if malformed
    iri = curie_to_iri(curie)

    # Check cache
    cache = get_cache()
    cache_key = f"term_info:{curie}:{include_hierarchy}"
    if cache:
        found, cached = cache.get(cache_key)
        if found:
            logger.debug("Cache hit for %s", cache_key)
            return cached

    client = get_client()

    # Core info query
    info_query = build_term_info_query(curie)
    info_result = await client.execute(info_query)

    rows = info_result.get("results", [])
    if not rows:
        return {"error": f"No information found for {curie}. Term may not exist in Ubergraph."}

    # Aggregate multi-valued fields
    labels: set[str] = set()
    definitions: set[str] = set()
    synonyms: set[str] = set()
    types: set[str] = set()

    for row in rows:
        if row.get("label"):
            labels.add(row["label"])
        if row.get("definition"):
            definitions.add(row["definition"])
        if row.get("synonym"):
            synonyms.add(row["synonym"])
        if row.get("type"):
            t = row["type"]
            # Shorten well-known type IRIs
            t = t.replace("http://www.w3.org/2002/07/owl#", "owl:")
            t = t.replace("http://www.w3.org/2000/01/rdf-schema#", "rdfs:")
            types.add(t)

    # Derive ontology from CURIE prefix
    prefix = curie.split(":")[0].lower()

    result: dict[str, Any] = {
        "curie": curie,
        "iri": iri,
        "label": next(iter(labels), None),
        "definition": next(iter(definitions), None),
        "synonyms": sorted(synonyms),
        "types": sorted(types),
        "in_ontology": prefix,
    }

    if include_hierarchy:
        parents_q = build_term_parents_query(curie)
        children_q = build_term_children_query(curie)
        parents_r, children_r = await _run_parallel(client, parents_q, children_q)
        result["parents"] = _format_term_list(parents_r.get("results", []), "parent")
        result["children"] = _format_term_list(children_r.get("results", []), "child")

    if cache:
        cache.set(cache_key, result)

    return result


async def _tool_search_terms(args: dict[str, Any]) -> dict[str, Any]:
    text: str = args.get("text", "").strip()
    if not text:
        raise ValidationError("Search text must not be empty.")

    ontologies_raw: list[str] = args.get("ontologies") or []
    ontologies = validate_ontology_prefixes(ontologies_raw) if ontologies_raw else []
    limit = validate_limit(int(args.get("limit", 10)), cap=200)
    exact_match: bool = bool(args.get("exact_match", False))

    # Cache key
    cache = get_cache()
    onto_key = ",".join(sorted(ontologies))
    cache_key = f"search:{text}:{onto_key}:{limit}:{exact_match}"
    if cache:
        found, cached = cache.get(cache_key)
        if found:
            return cached

    query = build_search_query(
        text=text, ontologies=ontologies or None, limit=limit, exact_match=exact_match
    )
    client = get_client()
    raw = await client.execute(query)

    matches = []
    seen: set[str] = set()
    for row in raw.get("results", []):
        term_iri = row.get("term", "")
        curie = _iri_to_curie(term_iri) or term_iri
        if curie in seen:
            continue
        seen.add(curie)

        label = row.get("label") or ""
        synonym = row.get("synonym")
        onto = curie.split(":")[0].lower() if ":" in curie else ""

        # Determine match type
        if synonym and not label:
            match_type = "synonym"
        elif label and text.lower() == label.lower():
            match_type = "exact_label"
        else:
            match_type = "partial"

        # Simple score: exact wins
        score = 1.0 if match_type == "exact_label" else (0.8 if match_type == "synonym" else 0.6)

        matches.append({
            "curie": curie,
            "label": label or synonym,
            "match_type": match_type,
            "ontology": onto,
            "score": score,
        })

    # Sort by score descending, then label alphabetically
    matches.sort(key=lambda x: (-x["score"], x["label"] or ""))

    result = {
        "matches": matches,
        "search_text": text,
        "total_matches": len(matches),
    }
    if cache:
        cache.set(cache_key, result)
    return result


async def _tool_get_hierarchy(args: dict[str, Any]) -> dict[str, Any]:
    curie: str = args.get("curie", "").strip()
    relation: str = args.get("relation", "parents")
    depth: int = validate_depth(int(args.get("depth", 1)))

    validate_curie(curie)

    if relation not in ("parents", "children", "ancestors", "descendants"):
        relation = "parents"

    cache = get_cache()
    cache_key = f"hierarchy:{curie}:{relation}:{depth}"
    if cache:
        found, cached = cache.get(cache_key)
        if found:
            return cached

    query_builders = {
        "parents": build_parents_query,
        "children": build_children_query,
        "ancestors": build_ancestors_query,
        "descendants": build_descendants_query,
    }
    query = query_builders[relation](curie, depth)

    client = get_client()
    raw = await client.execute(query)

    # The variable name differs by relation type
    var_map = {
        "parents": "parent",
        "children": "child",
        "ancestors": "ancestor",
        "descendants": "descendant",
    }
    term_var = var_map[relation]

    terms = []
    for row in raw.get("results", []):
        iri = row.get(term_var, "")
        child_curie = _iri_to_curie(iri) or iri
        label = row.get("label") or ""
        terms.append({"curie": child_curie, "label": label, "distance": depth})

    result: dict[str, Any] = {
        "curie": curie,
        "relation": relation,
        "depth": depth,
        "terms": terms,
    }
    if cache:
        cache.set(cache_key, result)
    return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

async def _run_parallel(client, query_a: str, query_b: str):
    """Run two SPARQL queries concurrently."""
    import anyio

    results = [None, None]

    async def run(idx: int, q: str) -> None:
        results[idx] = await client.execute(q)

    async with anyio.create_task_group() as tg:
        tg.start_soon(run, 0, query_a)
        tg.start_soon(run, 1, query_b)

    return results[0], results[1]


def _format_term_list(rows: list[dict], var_name: str) -> list[dict]:
    out = []
    seen: set[str] = set()
    for row in rows:
        iri = row.get(var_name, "")
        curie = _iri_to_curie(iri) or iri
        if curie in seen:
            continue
        seen.add(curie)
        out.append({"curie": curie, "label": row.get("label") or ""})
    return out


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

async def _run() -> None:
    logger.info(
        "Starting mcp-ubergraph-query server (endpoint=%s)", config.UBERGRAPH_ENDPOINT
    )
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def main() -> None:
    import anyio

    anyio.run(_run)


if __name__ == "__main__":
    main()
