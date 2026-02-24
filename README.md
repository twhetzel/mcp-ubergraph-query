# mcp-ubergraph-query

An [MCP](https://modelcontextprotocol.io) server for querying the
[Ubergraph](https://github.com/INCATools/ubergraph) biomedical ontology SPARQL endpoint.

Ubergraph is a merged knowledge graph of OBO ontologies including MONDO, UBERON, HP, CHEBI,
GO, CL, and more. This server exposes four tools that let AI assistants query it naturally.

## Tools

| Tool | Description |
|---|---|
| `query_ubergraph` | Execute custom SPARQL SELECT queries |
| `get_term_info` | Get label, definition, synonyms, and types for an ontology term |
| `search_terms` | Search terms by label or synonym across ontologies |
| `get_hierarchy` | Traverse parents, children, ancestors, or descendants |

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

### Install

```bash
git clone https://github.com/your-org/mcp-ubergraph-query
cd mcp-ubergraph-query
uv sync --all-extras
```

### Run the server

```bash
uv run mcp-ubergraph-query
```

Or directly:

```bash
uv run python -m ubergraph_query.server
```

### Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ubergraph": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/mcp-ubergraph-query",
        "run",
        "mcp-ubergraph-query"
      ]
    }
  }
}
```

## Configuration

Copy `.env.example` to `.env` and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `UBERGRAPH_ENDPOINT` | `https://ubergraph.apps.renci.org/sparql` | SPARQL endpoint URL |
| `QUERY_TIMEOUT_DEFAULT` | `30` | Default query timeout (seconds) |
| `QUERY_LIMIT_MAX` | `1000` | Maximum allowed LIMIT value |
| `ENABLE_QUERY_CACHE` | `true` | Enable in-memory LRU result cache |
| `CACHE_TTL_SECONDS` | `3600` | Cache entry lifetime |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Tool Reference

### `query_ubergraph`

Execute a custom SPARQL SELECT query against Ubergraph.

**Input:**
```json
{
  "query": "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5",
  "timeout": 30,
  "limit": 100,
  "format": "json"
}
```

**Output:**
```json
{
  "results": [{"s": "...", "p": "...", "o": "..."}],
  "query_time_ms": 234,
  "result_count": 5,
  "query_hash": "abc123def456"
}
```

Safety features: LIMIT is automatically injected if absent; write operations
(INSERT, DELETE, DROP, etc.) are rejected; timeout is capped at 60 s.

---

### `get_term_info`

Get comprehensive metadata for an ontology term by CURIE.

**Input:**
```json
{
  "curie": "MONDO:0005015",
  "include_hierarchy": false
}
```

**Output:**
```json
{
  "curie": "MONDO:0005015",
  "iri": "http://purl.obolibrary.org/obo/MONDO_0005015",
  "label": "diabetes mellitus",
  "definition": "A metabolic disorder characterized by...",
  "synonyms": ["DM", "diabetes"],
  "types": ["owl:Class"],
  "in_ontology": "mondo"
}
```

With `include_hierarchy: true`, `parents` and `children` arrays are added.

---

### `search_terms`

Search ontology terms by label or synonym.

**Input:**
```json
{
  "text": "diabetes",
  "ontologies": ["MONDO", "HP"],
  "limit": 10,
  "exact_match": false
}
```

**Output:**
```json
{
  "matches": [
    {
      "curie": "MONDO:0005015",
      "label": "diabetes mellitus",
      "match_type": "partial",
      "ontology": "mondo",
      "score": 0.6
    }
  ],
  "search_text": "diabetes",
  "total_matches": 1
}
```

---

### `get_hierarchy`

Traverse hierarchical relationships for a term.

**Input:**
```json
{
  "curie": "MONDO:0005015",
  "relation": "parents",
  "depth": 1
}
```

`relation` values: `parents`, `children`, `ancestors`, `descendants`

**Output:**
```json
{
  "curie": "MONDO:0005015",
  "relation": "parents",
  "depth": 1,
  "terms": [
    {"curie": "MONDO:0005066", "label": "metabolic disease", "distance": 1}
  ]
}
```

## Example SPARQL Queries

### Get term label and definition

```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX obo:  <http://purl.obolibrary.org/obo/>
SELECT ?label ?definition WHERE {
  obo:MONDO_0005015 rdfs:label ?label .
  OPTIONAL { obo:MONDO_0005015 obo:IAO_0000115 ?definition }
}
```

### Search by label substring

```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?term ?label WHERE {
  ?term rdfs:label ?label .
  FILTER(CONTAINS(LCASE(?label), "diabetes"))
  FILTER(STRSTARTS(STR(?term), "http://purl.obolibrary.org/obo/MONDO_"))
}
LIMIT 10
```

### Get immediate parents

```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX obo:  <http://purl.obolibrary.org/obo/>
SELECT ?parent ?label WHERE {
  obo:MONDO_0005015 rdfs:subClassOf ?parent .
  FILTER(!isBlank(?parent))
  OPTIONAL { ?parent rdfs:label ?label }
}
```

### Get all ancestors (transitive)

```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX obo:  <http://purl.obolibrary.org/obo/>
SELECT ?ancestor ?label WHERE {
  obo:MONDO_0005015 rdfs:subClassOf+ ?ancestor .
  FILTER(!isBlank(?ancestor))
  OPTIONAL { ?ancestor rdfs:label ?label }
}
LIMIT 100
```

### Find phenotype terms for a disease (HP + MONDO cross-ontology)

```sparql
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX obo:     <http://purl.obolibrary.org/obo/>
PREFIX oboInOwl: <http://www.geneontology.org/formats/oboInOwl#>
SELECT ?phenotype ?label WHERE {
  ?association obo:RO_0002200 obo:MONDO_0005015 ;
               obo:RO_0002200 ?phenotype .
  FILTER(STRSTARTS(STR(?phenotype), "http://purl.obolibrary.org/obo/HP_"))
  OPTIONAL { ?phenotype rdfs:label ?label }
}
LIMIT 20
```

## Development

```bash
# Install with dev dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run example queries (requires network access to Ubergraph)
uv run python examples/example_usage.py

# Lint
uv run ruff check src/ tests/
```

## Project Structure

```
mcp-ubergraph-query/
├── src/
│   └── ubergraph_query/
│       ├── __init__.py        # Package metadata
│       ├── server.py          # MCP server + tool implementations
│       ├── sparql_client.py   # Async HTTP SPARQL execution with retries
│       ├── query_builder.py   # SPARQL query construction helpers
│       ├── cache.py           # Thread-safe LRU cache with TTL
│       ├── validators.py      # CURIE validation, query safety checks
│       └── config.py          # Environment-based configuration
├── tests/
│   └── test_queries.py        # Unit tests (no network required)
├── examples/
│   └── example_usage.py       # Live query examples
├── pyproject.toml
├── .env.example
└── README.md
```

## Safety

- **Read-only**: Write operations (INSERT, DELETE, DROP, etc.) are rejected
- **LIMIT enforcement**: Queries without LIMIT get one injected; over-limit values are capped
- **Timeout cap**: Hard maximum of 60 seconds per query
- **Retry with backoff**: Transient 5xx/network errors are retried up to 3 times
- **Query logging**: Every query is logged with a SHA-256 hash for provenance

## License

MIT
