"""SPARQL HTTP client with retry logic, logging, and result normalization."""

import hashlib
import json
import logging
import time
from typing import Any

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from . import config
from .query_builder import HEALTH_CHECK_QUERY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry predicate — retry on transient HTTP/network errors only
# ---------------------------------------------------------------------------

_RETRYABLE = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, _RETRYABLE):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


# ---------------------------------------------------------------------------
# Low-level executor
# ---------------------------------------------------------------------------

class SPARQLError(RuntimeError):
    """Raised when a SPARQL query fails after all retries."""


class SPARQLClient:
    """Async SPARQL client backed by httpx."""

    def __init__(self, endpoint: str | None = None, timeout: int | None = None) -> None:
        self.endpoint = endpoint or config.UBERGRAPH_ENDPOINT
        self._default_timeout = timeout or config.QUERY_TIMEOUT_DEFAULT

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        query: str,
        timeout: int | None = None,
        format: str = "json",
    ) -> dict[str, Any]:
        """Execute a SPARQL SELECT query and return parsed JSON results.

        Args:
            query:   SPARQL query string (already validated/sanitized).
            timeout: Per-request timeout in seconds.
            format:  One of "json", "xml", "turtle".

        Returns:
            dict with keys: results, query_time_ms, result_count, query_hash
        """
        effective_timeout = min(
            timeout or self._default_timeout, config.QUERY_TIMEOUT_MAX
        )
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:12]

        accept_map = {
            "json": "application/sparql-results+json",
            "xml": "application/sparql-results+xml",
            "turtle": "text/turtle",
        }
        accept = accept_map.get(format, "application/sparql-results+json")

        logger.info(
            "Executing SPARQL query hash=%s timeout=%ds endpoint=%s",
            query_hash,
            effective_timeout,
            self.endpoint,
        )
        logger.debug("Query:\n%s", query)

        t0 = time.monotonic()
        raw = await self._fetch_with_retry(query, accept, effective_timeout)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        parsed = self._parse_response(raw, format, query_hash)
        parsed["query_time_ms"] = elapsed_ms
        parsed["query_hash"] = query_hash
        return parsed

    # ------------------------------------------------------------------
    # Retry wrapper
    # ------------------------------------------------------------------

    async def _fetch_with_retry(
        self, query: str, accept: str, timeout_s: int
    ) -> str:
        @retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(config.HTTP_MAX_RETRIES),
            wait=wait_exponential(
                min=config.HTTP_RETRY_WAIT_MIN, max=config.HTTP_RETRY_WAIT_MAX
            ),
            reraise=True,
        )
        async def _inner() -> str:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.get(
                    self.endpoint,
                    params={"query": query},
                    headers={
                        "Accept": accept,
                        "User-Agent": "mcp-ubergraph-query/0.1.0",
                    },
                )
                response.raise_for_status()
                return response.text

        try:
            return await _inner()
        except RetryError as exc:
            last_err = exc.last_attempt.exception()
            raise SPARQLError(
                f"SPARQL query failed after {config.HTTP_MAX_RETRIES} retries: {last_err}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise SPARQLError(
                f"HTTP {exc.response.status_code} from endpoint: {exc.response.text[:200]}"
            ) from exc
        except _RETRYABLE as exc:
            raise SPARQLError(f"Network error querying endpoint: {exc}") from exc

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(raw: str, format: str, query_hash: str) -> dict[str, Any]:
        if format != "json":
            # Return raw text for non-JSON formats
            return {
                "results": raw,
                "result_count": None,
                "format": format,
            }

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SPARQLError(f"Invalid JSON from endpoint: {exc}") from exc

        bindings: list[dict] = data.get("results", {}).get("bindings", [])
        # Simplify the binding structure: {var: {type, value}} -> {var: value}
        simplified = [
            {k: v.get("value") for k, v in row.items()} for row in bindings
        ]
        return {
            "results": simplified,
            "result_count": len(simplified),
        }

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Ping the endpoint and return status info."""
        t0 = time.monotonic()
        try:
            result = await self.execute(HEALTH_CHECK_QUERY, timeout=10)
            return {
                "status": "ok",
                "endpoint": self.endpoint,
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "sample_result_count": result["result_count"],
            }
        except SPARQLError as exc:
            return {
                "status": "error",
                "endpoint": self.endpoint,
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "error": str(exc),
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client: SPARQLClient | None = None


def get_client() -> SPARQLClient:
    global _client
    if _client is None:
        _client = SPARQLClient()
    return _client
