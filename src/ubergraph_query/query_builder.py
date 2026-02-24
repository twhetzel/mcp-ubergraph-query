"""SPARQL query construction for each tool's use-case."""

from .validators import curie_to_iri, validate_depth

# ---------------------------------------------------------------------------
# Shared PREFIX block
# ---------------------------------------------------------------------------

PREFIXES = """\
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>
PREFIX obo:   <http://purl.obolibrary.org/obo/>
PREFIX oboInOwl: <http://www.geneontology.org/formats/oboInOwl#>
PREFIX skos:  <http://www.w3.org/2004/02/skos/core#>
"""

# IAO:0000115 = "definition"
_IAO_DEF = "obo:IAO_0000115"


# ---------------------------------------------------------------------------
# get_term_info
# ---------------------------------------------------------------------------

def build_term_info_query(curie: str) -> str:
    """Return SPARQL query for core term metadata (label, definition, synonyms, types)."""
    iri = curie_to_iri(curie)
    obo_iri = f"<{iri}>"
    return f"""\
{PREFIXES}
SELECT DISTINCT ?label ?definition ?synonym ?type WHERE {{
  BIND({obo_iri} AS ?term)
  OPTIONAL {{ ?term rdfs:label ?label }}
  OPTIONAL {{ ?term {_IAO_DEF} ?definition }}
  OPTIONAL {{
    ?term oboInOwl:hasExactSynonym ?synonym
  }}
  OPTIONAL {{ ?term rdf:type ?type }}
}}
"""


def build_term_parents_query(curie: str) -> str:
    """Return SPARQL query for immediate rdfs:subClassOf parents."""
    iri = curie_to_iri(curie)
    obo_iri = f"<{iri}>"
    return f"""\
{PREFIXES}
SELECT DISTINCT ?parent ?label WHERE {{
  {obo_iri} rdfs:subClassOf ?parent .
  FILTER(!isBlank(?parent))
  OPTIONAL {{ ?parent rdfs:label ?label }}
}}
LIMIT 100
"""


def build_term_children_query(curie: str) -> str:
    """Return SPARQL query for immediate rdfs:subClassOf children."""
    iri = curie_to_iri(curie)
    obo_iri = f"<{iri}>"
    return f"""\
{PREFIXES}
SELECT DISTINCT ?child ?label WHERE {{
  ?child rdfs:subClassOf {obo_iri} .
  FILTER(!isBlank(?child))
  OPTIONAL {{ ?child rdfs:label ?label }}
}}
LIMIT 100
"""


# ---------------------------------------------------------------------------
# search_terms
# ---------------------------------------------------------------------------

def build_search_query(
    text: str,
    ontologies: list[str] | None = None,
    limit: int = 10,
    exact_match: bool = False,
) -> str:
    """Return SPARQL query for label/synonym search.

    Searches rdfs:label and oboInOwl:hasExactSynonym.
    If `ontologies` is given, results are filtered to those prefixes via IRI FILTER.
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')

    if exact_match:
        label_filter = f'LCASE(?label) = LCASE("{escaped}")'
        syn_filter = f'LCASE(?synonym) = LCASE("{escaped}")'
    else:
        label_filter = f'CONTAINS(LCASE(?label), LCASE("{escaped}"))'
        syn_filter = f'CONTAINS(LCASE(?synonym), LCASE("{escaped}"))'

    # Build IRI prefix filter for requested ontologies
    onto_filter = ""
    if ontologies:
        conditions = " || ".join(
            f'STRSTARTS(STR(?term), "http://purl.obolibrary.org/obo/{p}_")'
            for p in ontologies
        )
        onto_filter = f"  FILTER({conditions})\n"

    return f"""\
{PREFIXES}
SELECT DISTINCT ?term ?label ?synonym WHERE {{
  {{
    ?term rdfs:label ?label .
    FILTER({label_filter})
  }}
  UNION
  {{
    ?term oboInOwl:hasExactSynonym ?synonym .
    FILTER({syn_filter})
    OPTIONAL {{ ?term rdfs:label ?label }}
  }}
  FILTER(!isBlank(?term))
{onto_filter}}}
LIMIT {limit}
"""


# ---------------------------------------------------------------------------
# get_hierarchy — path patterns that compute actual distance per term
# ---------------------------------------------------------------------------


def _path_patterns_forward(obo_iri: str, target_var: str, depth: int) -> str:
    """UNION of path patterns: start -[subClassOf]-> ... -> target, with BIND(1..depth AS ?d)."""
    parts = []
    for d in range(1, depth + 1):
        if d == 1:
            triples = f"{obo_iri} rdfs:subClassOf ?{target_var} ."
        elif d == 2:
            triples = f"{obo_iri} rdfs:subClassOf ?a1 . ?a1 rdfs:subClassOf ?{target_var} ."
        else:
            mid = " . ".join(
                f"?a{i} rdfs:subClassOf ?a{i - 1}" for i in range(d - 1, 1, -1)
            )
            triples = f"{obo_iri} rdfs:subClassOf ?a{d - 1} . {mid} . ?a1 rdfs:subClassOf ?{target_var} ."
        parts.append(f"  {{ {triples} BIND({d} AS ?d) }}")
    return "\n  UNION\n".join(parts)


def _path_patterns_backward(obo_iri: str, target_var: str, depth: int) -> str:
    """UNION of path patterns: target -[subClassOf]-> ... -> start, with BIND(1..depth AS ?d)."""
    parts = []
    for d in range(1, depth + 1):
        if d == 1:
            triples = f"?{target_var} rdfs:subClassOf {obo_iri} ."
        elif d == 2:
            triples = f"?{target_var} rdfs:subClassOf ?a1 . ?a1 rdfs:subClassOf {obo_iri} ."
        else:
            mid = " . ".join(
                f"?a{i} rdfs:subClassOf ?a{i + 1}" for i in range(1, d - 1)
            )
            triples = f"?{target_var} rdfs:subClassOf ?a1 . {mid} . ?a{d - 1} rdfs:subClassOf {obo_iri} ."
        parts.append(f"  {{ {triples} BIND({d} AS ?d) }}")
    return "\n  UNION\n".join(parts)


def build_parents_query(curie: str, depth: int = 1) -> str:
    depth = validate_depth(depth)
    iri = curie_to_iri(curie)
    obo_iri = f"<{iri}>"

    if depth == 1:
        return f"""\
{PREFIXES}
SELECT DISTINCT ?parent ?label (1 AS ?distance) WHERE {{
  {obo_iri} rdfs:subClassOf ?parent .
  FILTER(!isBlank(?parent))
  OPTIONAL {{ ?parent rdfs:label ?label }}
}}
LIMIT 200
"""
    patterns = _path_patterns_forward(obo_iri, "parent", depth)
    return f"""\
{PREFIXES}
SELECT ?parent (SAMPLE(?label) AS ?label) (MIN(?d) AS ?distance) WHERE {{
  {{
{patterns}
  }}
  FILTER(!isBlank(?parent))
  OPTIONAL {{ ?parent rdfs:label ?label }}
}} GROUP BY ?parent
LIMIT 200
"""


def build_children_query(curie: str, depth: int = 1) -> str:
    depth = validate_depth(depth)
    iri = curie_to_iri(curie)
    obo_iri = f"<{iri}>"

    if depth == 1:
        return f"""\
{PREFIXES}
SELECT DISTINCT ?child ?label (1 AS ?distance) WHERE {{
  ?child rdfs:subClassOf {obo_iri} .
  FILTER(!isBlank(?child))
  OPTIONAL {{ ?child rdfs:label ?label }}
}}
LIMIT 200
"""
    patterns = _path_patterns_backward(obo_iri, "child", depth)
    return f"""\
{PREFIXES}
SELECT ?child (SAMPLE(?label) AS ?label) (MIN(?d) AS ?distance) WHERE {{
  {{
{patterns}
  }}
  FILTER(!isBlank(?child))
  OPTIONAL {{ ?child rdfs:label ?label }}
}} GROUP BY ?child
LIMIT 200
"""


def build_ancestors_query(curie: str, depth: int = 5) -> str:
    """Transitive ancestors using rdfs:subClassOf (up to depth). Returns actual distance per term."""
    depth = validate_depth(depth)
    iri = curie_to_iri(curie)
    obo_iri = f"<{iri}>"

    if depth == 1:
        return f"""\
{PREFIXES}
SELECT DISTINCT ?ancestor ?label (1 AS ?distance) WHERE {{
  {obo_iri} rdfs:subClassOf ?ancestor .
  FILTER(!isBlank(?ancestor))
  OPTIONAL {{ ?ancestor rdfs:label ?label }}
}}
LIMIT 500
"""
    patterns = _path_patterns_forward(obo_iri, "ancestor", depth)
    return f"""\
{PREFIXES}
SELECT ?ancestor (SAMPLE(?label) AS ?label) (MIN(?d) AS ?distance) WHERE {{
  {{
{patterns}
  }}
  FILTER(!isBlank(?ancestor))
  OPTIONAL {{ ?ancestor rdfs:label ?label }}
}} GROUP BY ?ancestor
LIMIT 500
"""


def build_descendants_query(curie: str, depth: int = 5) -> str:
    """Transitive descendants using rdfs:subClassOf (up to depth). Returns actual distance per term."""
    depth = validate_depth(depth)
    iri = curie_to_iri(curie)
    obo_iri = f"<{iri}>"

    if depth == 1:
        return f"""\
{PREFIXES}
SELECT DISTINCT ?descendant ?label (1 AS ?distance) WHERE {{
  ?descendant rdfs:subClassOf {obo_iri} .
  FILTER(!isBlank(?descendant))
  OPTIONAL {{ ?descendant rdfs:label ?label }}
}}
LIMIT 500
"""
    patterns = _path_patterns_backward(obo_iri, "descendant", depth)
    return f"""\
{PREFIXES}
SELECT ?descendant (SAMPLE(?label) AS ?label) (MIN(?d) AS ?distance) WHERE {{
  {{
{patterns}
  }}
  FILTER(!isBlank(?descendant))
  OPTIONAL {{ ?descendant rdfs:label ?label }}
}} GROUP BY ?descendant
LIMIT 500
"""


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

HEALTH_CHECK_QUERY = f"""\
{PREFIXES}
SELECT ?s WHERE {{
  ?s rdf:type owl:Ontology .
}}
LIMIT 1
"""
