"""Data sourcing: live ccxt with cache -> synthetic fallback.

``ccxt`` and ``diskcache`` are imported lazily inside functions; importing this
subpackage has no side effects.
"""

from __future__ import annotations

from cryptoarb.data.cache import BookCache
from cryptoarb.data.ccxt_source import (
    DataSource,
    DataSourcePref,
    FetchConfig,
    FetchResult,
    fetch_books,
)

__all__ = [
    "BookCache",
    "DataSource",
    "DataSourcePref",
    "FetchConfig",
    "FetchResult",
    "fetch_books",
]
