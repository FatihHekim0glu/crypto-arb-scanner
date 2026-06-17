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

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from cryptoarb._exceptions import CryptoArbError, ValidationError

if TYPE_CHECKING:
    from cryptoarb.books.model import OrderBook
    from cryptoarb.books.synthetic import SyntheticConfig
    from cryptoarb.data.cache import BookCache

#: Where a returned book actually came from.
DataSource = Literal["live", "cache", "synthetic"]

#: Preference for which source to try first.
DataSourcePref = Literal["auto", "live", "synthetic"]

#: Public ccxt exchange id for each supported venue identifier. Coinbase/Kraken
#: are reachable without credentials; Binance geo-blocks some regions (which is
#: precisely why every live failure must degrade to synthetic).
_VENUE_TO_CCXT: dict[str, str] = {
    "binance": "binance",
    "coinbase": "coinbase",
    "kraken": "kraken",
}


class UpstreamError(CryptoArbError):
    """Raised when the live ccxt path fails for any reason.

    This is the single typed signal :func:`fetch_books` catches to trigger its
    cache -> synthetic fallback. It wraps the underlying cause (missing ``ccxt``,
    a rate-limit / geo-block / timeout, an unknown venue, or a malformed book)
    so the caller never has to enumerate ccxt's own exception zoo. It is a
    library error (subclass of :class:`~cryptoarb._exceptions.CryptoArbError`),
    NOT a :class:`~cryptoarb._exceptions.ValidationError`: an upstream failure is
    never a caller-input bug and must always fall back rather than surface.
    """


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
        return {
            "books": {venue: book.to_dict() for venue, book in self.books.items()},
            "data_source": self.data_source,
        }


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
        return {
            "timeout_ms": int(self.timeout_ms),
            "rate_limit_per_sec": float(self.rate_limit_per_sec),
            "depth_limit": int(self.depth_limit),
        }


class _TokenBucket:
    """Minimal monotonic-clock token bucket for throttling live requests.

    Capacity equals the per-second rate (burst of one second's worth); tokens
    refill continuously. :meth:`acquire` blocks just long enough to stay within
    ``rate_per_sec``. Pure-Python, no import-time work, deterministic given the
    clock — but in practice it only ever runs on the (untested) live path.
    """

    __slots__ = ("_capacity", "_last", "_rate", "_tokens")

    def __init__(self, rate_per_sec: float) -> None:
        rate = max(float(rate_per_sec), 1e-6)
        self._rate = rate
        self._capacity = rate
        self._tokens = rate
        self._last = time.monotonic()

    def acquire(self) -> None:  # pragma: no cover - only on the live network path
        now = time.monotonic()
        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens < 1.0:
            time.sleep((1.0 - self._tokens) / self._rate)
            self._tokens = 0.0
        else:
            self._tokens -= 1.0


def _default_synthetic_config(symbol: str, venues: list[str]) -> SyntheticConfig:
    """Build a sensible default :class:`SyntheticConfig` for the fallback path.

    Produces one consistent (no-dislocation) venue spec per requested venue so
    the synthetic fallback yields the honest-null book set unless the caller
    supplied an explicit config. Kept tiny and import-light; the heavy lifting
    lives in :mod:`cryptoarb.books.synthetic`.
    """
    from cryptoarb.books.synthetic import SyntheticConfig, VenueSpec

    specs = tuple(VenueSpec(venue=venue) for venue in venues)
    return SyntheticConfig(symbol=symbol, venues=specs)


def _synthetic_fallback(
    symbol: str,
    venues: list[str],
    *,
    synthetic_config: SyntheticConfig | None,
    seed: int,
) -> dict[str, OrderBook]:
    """Generate the deterministic synthetic book set for the fallback tail.

    Indirected through this module-level helper (rather than calling
    :func:`cryptoarb.books.synthetic.synthetic_books` inline) so the offline
    test suite can substitute a known book set without depending on the
    synthetic generator's internals.
    """
    from cryptoarb.books.synthetic import synthetic_books

    config = (
        synthetic_config
        if synthetic_config is not None
        else _default_synthetic_config(symbol, venues)
    )
    return synthetic_books(config, seed=seed)


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
    symbol = _validate_symbol(symbol)
    venues = _validate_venues(venues)
    if pref not in ("auto", "live", "synthetic"):
        raise ValidationError(f"pref must be 'auto', 'live', or 'synthetic', got {pref!r}.")

    # Synthetic preference must NEVER touch ccxt, the cache, or the network.
    if pref == "synthetic":
        books = _synthetic_fallback(symbol, venues, synthetic_config=synthetic_config, seed=seed)
        return FetchResult(books=books, data_source="synthetic")

    cfg = fetch_config if fetch_config is not None else FetchConfig()

    # 1) Live ccxt. Any upstream failure (caught as UpstreamError) falls through.
    try:
        live_books = _fetch_all_live(symbol, venues, cfg)
    except UpstreamError:
        live_books = None
    if live_books is not None:
        if cache is not None:
            for book in live_books.values():
                cache.put(book)
        return FetchResult(books=live_books, data_source="live")

    # 2) Cache: serve a complete, fresh snapshot if every venue is present.
    if cache is not None:
        cached = _read_cache(symbol, venues, cache)
        if cached is not None:
            return FetchResult(books=cached, data_source="cache")

    # 3) Synthetic: deterministic, always available, the honest-null tail.
    books = _synthetic_fallback(symbol, venues, synthetic_config=synthetic_config, seed=seed)
    return FetchResult(books=books, data_source="synthetic")


def _read_cache(symbol: str, venues: list[str], cache: BookCache) -> dict[str, OrderBook] | None:
    """Return a complete cached snapshot for every venue, or ``None`` on any miss.

    A partial snapshot (some venues stale/absent) is treated as a full miss so a
    cross-venue scan is never run on a half-stale book set — the staleness guard
    is all-or-nothing.
    """
    out: dict[str, OrderBook] = {}
    for venue in venues:
        book = cache.get(venue, symbol)
        if book is None:
            return None
        out[venue] = book
    return out


def _fetch_all_live(
    symbol: str, venues: list[str], fetch_config: FetchConfig
) -> dict[str, OrderBook]:
    """Fetch every venue's live book, throttled by a shared token bucket.

    Raises :class:`UpstreamError` if ANY venue fails, so the caller falls back as
    a whole rather than mixing live and stale/synthetic books across venues.
    """
    bucket = _TokenBucket(fetch_config.rate_limit_per_sec)
    out: dict[str, OrderBook] = {}
    for venue in venues:
        bucket.acquire()
        out[venue] = _fetch_one_live(venue, symbol, fetch_config)
    return out


def _fetch_one_live(venue: str, symbol: str, fetch_config: FetchConfig) -> OrderBook:
    """Fetch a single venue's L2 book via async ccxt (lazy import).

    This is the only function that touches ccxt/the network. It is wrapped by
    :func:`fetch_books`, which converts any failure here into a fallback. Every
    failure mode (missing ccxt, unknown venue, network/timeout, malformed book)
    is normalized to :class:`UpstreamError`.

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
    UpstreamError
        On any ccxt/network/validation failure; the caller catches it to fall
        back to cache then synthetic.
    """
    ccxt_id = _VENUE_TO_CCXT.get(venue.strip().lower())
    if ccxt_id is None:
        raise UpstreamError(f"unsupported live venue: {venue!r}")

    try:
        raw = _ccxt_fetch_order_book(ccxt_id, symbol, fetch_config)
    except UpstreamError:
        raise
    except Exception as exc:  # any ccxt/runtime error degrades to a fallback
        raise UpstreamError(f"live fetch failed for {venue}:{symbol}: {exc}") from exc

    return _book_from_raw(venue, symbol, raw)


def _ccxt_fetch_order_book(
    ccxt_id: str, symbol: str, fetch_config: FetchConfig
) -> dict[str, Any]:  # pragma: no cover - exercised only against the live network
    """Run one async ccxt ``fetch_order_book`` and return its raw dict.

    Lazily imports ``ccxt.async_support`` and drives the coroutine with a fresh
    event loop, always closing the exchange to release its aiohttp session.
    """
    import asyncio

    import ccxt.async_support as ccxt_async

    async def _run() -> dict[str, Any]:
        exchange = getattr(ccxt_async, ccxt_id)(
            {"enableRateLimit": True, "timeout": int(fetch_config.timeout_ms)}
        )
        try:
            book: dict[str, Any] = await exchange.fetch_order_book(
                symbol, limit=int(fetch_config.depth_limit)
            )
            return book
        finally:
            await exchange.close()

    return asyncio.run(_run())


def _book_from_raw(venue: str, symbol: str, raw: dict[str, Any]) -> OrderBook:
    """Convert a raw ccxt order-book dict into a validated :class:`OrderBook`.

    ccxt returns ``{"bids": [[price, size], ...], "asks": [...], "timestamp": ms}``
    with bids/asks pre-sorted (best first). Empty sides or malformed levels are
    normalized to :class:`UpstreamError` so they trigger a fallback.
    """
    from cryptoarb.books.model import make_book

    try:
        bids = [(float(p), float(s)) for p, s, *_ in raw.get("bids", [])]
        asks = [(float(p), float(s)) for p, s, *_ in raw.get("asks", [])]
        ts_raw = raw.get("timestamp")
        ts_ms = int(ts_raw) if ts_raw is not None else 0
    except (TypeError, ValueError) as exc:
        raise UpstreamError(f"malformed book for {venue}:{symbol}: {exc}") from exc

    if not bids or not asks:
        raise UpstreamError(f"empty book side for {venue}:{symbol}")

    try:
        return make_book(venue, symbol, bids, asks, ts_ms=ts_ms, sort=True)
    except CryptoArbError as exc:
        raise UpstreamError(f"invalid book for {venue}:{symbol}: {exc}") from exc


def _validate_symbol(symbol: str) -> str:
    """Validate and canonicalize a ``BASE/QUOTE`` symbol.

    Raises
    ------
    ValidationError
        If ``symbol`` is not a non-empty ``BASE/QUOTE`` string.
    """
    if not isinstance(symbol, str):
        raise ValidationError(f"symbol must be a string, got {type(symbol).__name__}.")
    cleaned = symbol.strip().upper()
    parts = cleaned.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValidationError(f"symbol must be a non-empty 'BASE/QUOTE' string, got {symbol!r}.")
    return cleaned


def _validate_venues(venues: list[str]) -> list[str]:
    """Validate a non-empty list of unique, non-blank venue identifiers.

    Returns the venues lower-cased and de-duplicated while preserving order.

    Raises
    ------
    ValidationError
        If ``venues`` is empty or contains a blank/non-string entry.
    """
    if not isinstance(venues, list) or not venues:
        raise ValidationError("venues must be a non-empty list of venue identifiers.")
    seen: set[str] = set()
    out: list[str] = []
    for venue in venues:
        if not isinstance(venue, str) or not venue.strip():
            raise ValidationError(f"each venue must be a non-empty string, got {venue!r}.")
        norm = venue.strip().lower()
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out
