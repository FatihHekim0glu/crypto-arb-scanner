"""Live L2 order-book source with cache -> synthetic fallback.

The live path lazily imports **async ccxt**, fetches L2 books with SHORT
timeouts behind a token-bucket throttle, and on ANY failure (rate-limit,
geo-block, timeout, symbol mismatch) degrades gracefully: first to a fresh
cached snapshot, then to the deterministic synthetic generator. It must NEVER
hard-fail — the deployed backend may attempt live data but always falls back.
No test depends on live data; the whole module is exercised through the
synthetic fallback.

``ccxt`` is imported INSIDE the fetch functions only, so importing this module
has zero import-time side effects and never touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from cryptoarb.books.model import OrderBook
    from cryptoarb.books.synthetic import SyntheticConfig
    from cryptoarb.data.cache import BookCache

#: Where a returned book actually came from.
DataSource = Literal["live", "cache", "synthetic"]

#: Preference for which source to try first.
DataSourcePref = Literal["auto", "live", "synthetic"]


@dataclass(frozen=True, slots=True)
class FetchResult:
    """A multi-venue snapshot plus where it came from.

    Attributes
    ----------
    books:
        Mapping of venue identifier to its fetched (or generated) order book.
    data_source:
        Which source actually produced ``books`` (``live``/``cache``/``synthetic``).
    """

    books: dict[str, OrderBook]
    data_source: DataSource

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this result."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class FetchConfig:
    """Tunables for the live fetch + fallback chain.

    Attributes
    ----------
    timeout_ms:
        Per-request timeout in milliseconds (kept short so failures fall back
        fast).
    rate_limit_per_sec:
        Token-bucket refill rate (requests per second) for throttling ccxt.
    depth_limit:
        Number of L2 levels to request per side.
    """

    timeout_ms: int = 2_000
    rate_limit_per_sec: float = 4.0
    depth_limit: int = 50

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this config."""
        raise NotImplementedError


def fetch_books(
    symbol: str,
    venues: list[str],
    *,
    pref: DataSourcePref = "auto",
    cache: BookCache | None = None,
    synthetic_config: SyntheticConfig | None = None,
    fetch_config: FetchConfig | None = None,
    seed: int = 0,
) -> FetchResult:
    """Fetch L2 books for ``symbol`` across ``venues`` with graceful fallback.

    Resolution order depends on ``pref``:

    - ``"synthetic"``: skip the network entirely; return synthetic books.
    - ``"live"`` / ``"auto"``: attempt the live ccxt fetch; on ANY failure fall
      back to a fresh cache hit, then to synthetic. The function NEVER raises on
      an upstream failure — it always returns *some* books and an honest
      ``data_source`` tag.

    ``ccxt`` is imported lazily inside this function; absence of ``ccxt`` is
    itself a fallback trigger, not an import error.

    Parameters
    ----------
    symbol:
        Unified ``BASE/QUOTE`` symbol.
    venues:
        Venue identifiers to fetch (subset of supported public venues).
    pref:
        Which source to prefer (``"auto"``, ``"live"``, or ``"synthetic"``).
    cache:
        Optional disk cache consulted on live failure before synthetic.
    synthetic_config:
        Optional explicit synthetic config; a sensible default is derived from
        ``symbol`` when omitted.
    fetch_config:
        Optional live-fetch tunables (timeouts, throttle, depth).
    seed:
        Master seed for the synthetic fallback (keeps fallbacks deterministic).

    Returns
    -------
    FetchResult
        The books and the honest ``data_source`` they came from.

    Raises
    ------
    ValidationError
        Only for caller-side input errors (empty ``venues``, bad ``symbol``);
        NEVER for an upstream/live failure, which always falls back.
    """
    raise NotImplementedError


def _fetch_one_live(
    venue: str, symbol: str, fetch_config: FetchConfig
) -> OrderBook:
    """Fetch a single venue's L2 book via async ccxt (lazy import).

    This is the only function that touches ccxt/the network. It is wrapped by
    :func:`fetch_books`, which converts any failure here into a fallback.

    Parameters
    ----------
    venue:
        Venue identifier (must map to a public ccxt exchange).
    symbol:
        Unified ``BASE/QUOTE`` symbol.
    fetch_config:
        Timeout/throttle/depth tunables.

    Returns
    -------
    OrderBook
        The fetched, validated order book.

    Raises
    ------
    Exception
        Any ccxt/network error is allowed to propagate to the caller, which
        catches it and falls back.
    """
    raise NotImplementedError
