"""Unit tests for query building, validation, caching, and SPARQL client parsing."""

import json
import time

import pytest

from ubergraph_query.cache import LRUCache
from ubergraph_query.query_builder import (
    build_ancestors_query,
    build_children_query,
    build_descendants_query,
    build_parents_query,
    build_search_query,
    build_term_info_query,
)
from ubergraph_query.sparql_client import SPARQLClient, SPARQLError
from ubergraph_query.validators import (
    ValidationError,
    curie_to_iri,
    validate_curie,
    validate_depth,
    validate_limit,
    validate_ontology_prefixes,
    validate_sparql_query,
    validate_timeout,
)


class TestValidateCurie:
    def test_valid_mondo(self):
        prefix, local = validate_curie("MONDO:0005015")
        assert prefix == "MONDO"
        assert local == "0005015"

    def test_valid_hp(self):
        prefix, local = validate_curie("HP:0001945")
        assert prefix == "HP"
        assert local == "0001945"

    def test_lowercase_normalised(self):
        prefix, _ = validate_curie("mondo:0005015")
        assert prefix == "MONDO"

    def test_invalid_no_colon(self):
        with pytest.raises(ValidationError):
            validate_curie("MONDO0005015")

    def test_invalid_empty(self):
        with pytest.raises(ValidationError):
            validate_curie("")

    def test_invalid_spaces(self):
        with pytest.raises(ValidationError):
            validate_curie("MONDO :0005015")


class TestCurieToIri:
    def test_mondo(self):
        iri = curie_to_iri("MONDO:0005015")
        assert iri == "http://purl.obolibrary.org/obo/MONDO_0005015"

    def test_hp(self):
        iri = curie_to_iri("HP:0001945")
        assert iri == "http://purl.obolibrary.org/obo/HP_0001945"


class TestValidateSparqlQuery:
    def test_injects_limit_when_absent(self):
        q = "SELECT ?s WHERE { ?s ?p ?o }"
        result = validate_sparql_query(q)
        assert "LIMIT" in result.upper()

    def test_preserves_existing_limit(self):
        q = "SELECT ?s WHERE { ?s ?p ?o } LIMIT 50"
        result = validate_sparql_query(q)
        assert "LIMIT 50" in result

    def test_caps_limit_over_max(self, monkeypatch):
        import ubergraph_query.config as cfg
        monkeypatch.setattr(cfg, "QUERY_LIMIT_MAX", 100)
        q = "SELECT ?s WHERE { ?s ?p ?o } LIMIT 9999"
        result = validate_sparql_query(q)
        assert "LIMIT 100" in result
        assert "9999" not in result

    def test_blocks_insert(self):
        with pytest.raises(ValidationError, match="forbidden"):
            validate_sparql_query("INSERT DATA { <x:a> <x:b> <x:c> }")

    def test_blocks_delete(self):
        with pytest.raises(ValidationError):
            validate_sparql_query("DELETE WHERE { ?s ?p ?o }")

    def test_blocks_drop(self):
        with pytest.raises(ValidationError):
            validate_sparql_query("DROP GRAPH <http://example.org/>")

    def test_empty_query_rejected(self):
        with pytest.raises(ValidationError):
            validate_sparql_query("   ")


class TestValidateHelpers:
    def test_depth_clamped_low(self):
        assert validate_depth(0) == 1

    def test_depth_clamped_high(self):
        assert validate_depth(10) == 5

    def test_limit_clamped(self):
        assert validate_limit(9999, cap=1000) == 1000

    def test_timeout_clamped(self, monkeypatch):
        import ubergraph_query.config as cfg
        monkeypatch.setattr(cfg, "QUERY_TIMEOUT_MAX", 60)
        assert validate_timeout(120) == 60

    def test_ontology_prefix_normalised(self):
        result = validate_ontology_prefixes(["mondo", " HP ", "GO"])
        assert result == ["MONDO", "HP", "GO"]


# ---------------------------------------------------------------------------
# query_builder
# ---------------------------------------------------------------------------


class TestQueryBuilder:
    def test_term_info_contains_iri(self):
        q = build_term_info_query("MONDO:0005015")
        assert "MONDO_0005015" in q
        assert "rdfs:label" in q

    def test_search_exact_match(self):
        q = build_search_query("diabetes", exact_match=True)
        # exact match uses = not CONTAINS
        assert "LCASE(?label) = LCASE" in q

    def test_search_substring(self):
        q = build_search_query("diabetes", exact_match=False)
        assert "CONTAINS(LCASE(?label)" in q

    def test_search_ontology_filter(self):
        q = build_search_query("diabetes", ontologies=["MONDO", "HP"])
        assert "MONDO_" in q
        assert "HP_" in q

    def test_search_has_limit(self):
        q = build_search_query("diabetes", limit=5)
        assert "LIMIT 5" in q

    def test_parents_query_contains_subClassOf(self):
        q = build_parents_query("MONDO:0005015", depth=1)
        assert "rdfs:subClassOf" in q
        assert "MONDO_0005015" in q

    def test_parents_query_returns_distance(self):
        q1 = build_parents_query("MONDO:0005015", depth=1)
        assert "?distance" in q1
        assert "1 AS ?distance" in q1
        q2 = build_parents_query("MONDO:0005015", depth=2)
        assert "MIN(?d) AS ?distance" in q2
        assert "GROUP BY ?parent" in q2

    def test_children_query(self):
        q = build_children_query("MONDO:0005015", depth=1)
        assert "rdfs:subClassOf" in q

    def test_ancestors_depth_path(self):
        q = build_ancestors_query("MONDO:0005015", depth=3)
        # Should have a property path
        assert "rdfs:subClassOf" in q

    def test_ancestors_returns_actual_distance(self):
        q = build_ancestors_query("MONDO:0005015", depth=3)
        assert "?distance" in q
        assert "MIN(?d) AS ?distance" in q
        assert "GROUP BY ?ancestor" in q

    def test_descendants_query(self):
        q = build_descendants_query("HP:0001945", depth=2)
        assert "HP_0001945" in q

    def test_descendants_returns_actual_distance(self):
        q = build_descendants_query("HP:0001945", depth=2)
        assert "MIN(?d) AS ?distance" in q
        assert "GROUP BY ?descendant" in q


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------


class TestLRUCache:
    def test_basic_get_set(self):
        cache = LRUCache(max_size=10, ttl=60)
        cache.set("k1", {"data": 42})
        found, val = cache.get("k1")
        assert found
        assert val == {"data": 42}

    def test_miss(self):
        cache = LRUCache(max_size=10, ttl=60)
        found, val = cache.get("nonexistent")
        assert not found
        assert val is None

    def test_ttl_expiry(self):
        cache = LRUCache(max_size=10, ttl=0.05)  # 50ms TTL
        cache.set("k", "value")
        time.sleep(0.1)
        found, _ = cache.get("k")
        assert not found

    def test_eviction_lru(self):
        cache = LRUCache(max_size=3, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # Access 'a' to make it recently used
        cache.get("a")
        # Insert 'd' — should evict 'b' (LRU)
        cache.set("d", 4)
        found_b, _ = cache.get("b")
        found_a, _ = cache.get("a")
        assert not found_b
        assert found_a

    def test_invalidate(self):
        cache = LRUCache(max_size=10, ttl=60)
        cache.set("k", "v")
        assert cache.invalidate("k")
        found, _ = cache.get("k")
        assert not found

    def test_stats(self):
        cache = LRUCache(max_size=10, ttl=60)
        cache.set("k", "v")
        cache.get("k")   # hit
        cache.get("nope")  # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1


# ---------------------------------------------------------------------------
# sparql_client — response parsing (no network)
# ---------------------------------------------------------------------------


class TestSPARQLClientParsing:
    def test_parse_json_response(self):
        raw = json.dumps({
            "results": {
                "bindings": [
                    {"label": {"type": "literal", "value": "diabetes mellitus"}},
                    {"label": {"type": "literal", "value": "DM"}},
                ]
            }
        })
        result = SPARQLClient._parse_response(raw, "json", "abc")
        assert result["result_count"] == 2
        assert result["results"][0] == {"label": "diabetes mellitus"}

    def test_parse_empty_json(self):
        raw = json.dumps({"results": {"bindings": []}})
        result = SPARQLClient._parse_response(raw, "json", "abc")
        assert result["result_count"] == 0
        assert result["results"] == []

    def test_parse_invalid_json(self):
        with pytest.raises(SPARQLError, match="Invalid JSON"):
            SPARQLClient._parse_response("not-json", "json", "abc")

    def test_parse_non_json_format(self):
        raw = "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> ."
        result = SPARQLClient._parse_response(raw, "turtle", "abc")
        assert result["results"] == raw
        assert result["result_count"] is None
