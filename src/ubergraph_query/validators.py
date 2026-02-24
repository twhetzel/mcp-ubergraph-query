"""Input validation for CURIEs and SPARQL queries."""

import re

from . import config

# Known biomedical ontology prefixes supported by Ubergraph
KNOWN_PREFIXES = {
    "BFO", "CHEBI", "CL", "ECO", "ENVO", "GAZ", "GO", "HP",
    "IAO", "MA", "MONDO", "MP", "OBI", "OBO", "PATO", "PR",
    "RO", "SO", "UBERON", "UO", "XAO", "ZFA",
}

# CURIE pattern: PREFIX:LOCALID  (prefix is letters/digits, id is alphanumeric + _-)
_CURIE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):([\w\-\.]+)$")

# Forbidden SPARQL keywords that could trigger dangerous operations
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|DELETE|DROP|CREATE|CLEAR|LOAD|COPY|MOVE|ADD)\b",
    re.IGNORECASE,
)

# Simple LIMIT clause detector (captures the integer)
_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)


class ValidationError(ValueError):
    """Raised when a user-supplied value fails validation."""


def validate_curie(curie: str) -> tuple[str, str]:
    """Validate a CURIE string and return (prefix, local_id).

    Args:
        curie: e.g. "MONDO:0005015"

    Returns:
        Tuple of (prefix, local_id)

    Raises:
        ValidationError: if the CURIE is malformed
    """
    m = _CURIE_RE.match(curie.strip())
    if not m:
        raise ValidationError(
            f"Invalid CURIE format: {curie!r}. Expected PREFIX:LOCAL_ID "
            "(e.g. MONDO:0005015, HP:0001945)."
        )
    prefix, local_id = m.group(1).upper(), m.group(2)
    return prefix, local_id


def curie_to_iri(curie: str) -> str:
    """Convert a CURIE to its OBO IRI.

    e.g. "MONDO:0005015" -> "http://purl.obolibrary.org/obo/MONDO_0005015"
    """
    prefix, local_id = validate_curie(curie)
    return f"http://purl.obolibrary.org/obo/{prefix}_{local_id}"


def validate_sparql_query(query: str) -> str:
    """Validate and sanitize a user-supplied SPARQL SELECT query.

    Checks:
    - Must not be empty
    - Must not contain write/admin operations
    - Enforces LIMIT <= QUERY_LIMIT_MAX; injects LIMIT if absent

    Returns the (possibly modified) query string.
    Raises:
        ValidationError: on policy violation
    """
    query = query.strip()
    if not query:
        raise ValidationError("SPARQL query must not be empty.")

    if _FORBIDDEN_KEYWORDS.search(query):
        raise ValidationError(
            "Query contains forbidden write/admin operations "
            "(INSERT, DELETE, DROP, CREATE, etc.)."
        )

    # Check or inject LIMIT
    limit_match = _LIMIT_RE.search(query)
    if limit_match:
        found_limit = int(limit_match.group(1))
        if found_limit > config.QUERY_LIMIT_MAX:
            # Replace with max allowed
            query = _LIMIT_RE.sub(f"LIMIT {config.QUERY_LIMIT_MAX}", query)
    else:
        # No LIMIT present — append a safe default
        query = f"{query}\nLIMIT {config.QUERY_LIMIT_DEFAULT}"

    return query


def validate_depth(depth: int) -> int:
    """Clamp hierarchy depth to [1, 5]."""
    return max(1, min(5, depth))


def validate_limit(limit: int, cap: int | None = None) -> int:
    """Clamp a result limit to [1, cap or QUERY_LIMIT_MAX]."""
    cap = cap or config.QUERY_LIMIT_MAX
    return max(1, min(cap, limit))


def validate_timeout(timeout: int) -> int:
    """Clamp timeout to [1, QUERY_TIMEOUT_MAX]."""
    return max(1, min(config.QUERY_TIMEOUT_MAX, timeout))


def validate_ontology_prefixes(prefixes: list[str]) -> list[str]:
    """Normalize and return ontology prefix list (uppercased)."""
    return [p.strip().upper() for p in prefixes if p.strip()]
