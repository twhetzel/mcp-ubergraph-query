"""Configuration management via environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root if present
_root = Path(__file__).parent.parent.parent
load_dotenv(_root / ".env", override=False)


def _int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _bool(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    return default


# Endpoint
UBERGRAPH_ENDPOINT: str = os.environ.get(
    "UBERGRAPH_ENDPOINT", "https://ubergraph.apps.renci.org/sparql"
)

# Query safety limits
QUERY_TIMEOUT_DEFAULT: int = _int("QUERY_TIMEOUT_DEFAULT", 30)
QUERY_TIMEOUT_MAX: int = 60
QUERY_LIMIT_DEFAULT: int = 100
QUERY_LIMIT_MAX: int = _int("QUERY_LIMIT_MAX", 1000)

# Caching
ENABLE_QUERY_CACHE: bool = _bool("ENABLE_QUERY_CACHE", True)
CACHE_TTL_SECONDS: int = _int("CACHE_TTL_SECONDS", 3600)
CACHE_MAX_SIZE: int = _int("CACHE_MAX_SIZE", 512)

# HTTP retries
HTTP_MAX_RETRIES: int = 3
HTTP_RETRY_WAIT_MIN: float = 1.0
HTTP_RETRY_WAIT_MAX: float = 10.0

# Logging
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()
