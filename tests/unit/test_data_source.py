"""Offline tests for the ``data/`` group: ccxt source + cache + fallback chain.

Every test here is OFFLINE and deterministic. The live ccxt path is NEVER
exercised against the network: where a "live" result is needed it is injected by
monkeypatching the single network seam (:func:`cryptoarb.data.ccxt_source._ccxt_fetch_order_book`).
The synthetic tail is likewise injected via the module-level
:func:`cryptoarb.data.ccxt_source._synthetic_fallback` seam so these tests do not
depend on the (separately built) synthetic generator.

Covered contracts:

- **Import purity:** importing the data modules pulls in no ``ccxt`` and touches
  no network.
- ``pref='synthetic'`` returns synthetic books and NEVER imports/calls ccxt.
- With the live fetch failing, ``fetch_books`` falls back to synthetic and tags
  ``data_source='synthetic'``; with a fresh cache present it falls back to cache.
- A successful (injected) live fetch tags ``data_source='live'`` and warms cache.
- Input validation raises ``ValidationError`` for caller errors only.
- ``BookCache`` round-trips a book and honors its TTL staleness guard.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Any

import pytest

from cryptoarb._exceptions import ValidationError
from cryptoarb.books.model import OrderBook
from cryptoarb.data import (
    BookCache,
    FetchConfig,
    FetchResult,
    UpstreamError,
    fetch_books,
)
from cryptoarb.data import ccxt_source as src

# --------------------------------------------------------------------------- #
# Helpers / fakes (book group is built separately; we avoid its stubs).        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _FakeBook:
    """Minimal book-like object exposing the surface the data layer touches."""

    venue: str
    symbol: str
    ts_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"venue": self.venue, "symbol": self.symbol, "ts_ms": self.ts_ms}


def _fake_synthetic(venues: list[str], symbol: str = "BTC/USDT") -> dict[str, Any]:
    return {v: _FakeBook(v, symbol) for v in venues}


def _raw_book(*, ts: int = 1_700_000_000_000) -> dict[str, Any]:
    """A well-formed raw ccxt order-book dict (best-first, with a trailing field)."""
    return {
        "bids": [[100.0, 2.0, "ignored"], [99.5, 3.0]],
        "asks": [[100.5, 2.0], [101.0, 4.0]],
        "timestamp": ts,
    }


# --------------------------------------------------------------------------- #
# Import purity                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_importing_data_modules_loads_no_ccxt_and_no_network() -> None:
    """Importing the data subpackage must not import ccxt or touch the network."""
    code = (
        "import sys\n"
        "import cryptoarb.data\n"
        "import cryptoarb.data.ccxt_source\n"
        "import cryptoarb.data.cache\n"
        "assert 'ccxt' not in sys.modules, 'ccxt imported at import time'\n"
        "assert 'ccxt.async_support' not in sys.modules\n"
        "assert 'aiohttp' not in sys.modules\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


# --------------------------------------------------------------------------- #
# Synthetic preference: never touches ccxt                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_pref_synthetic_returns_synthetic_and_never_calls_ccxt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``pref='synthetic'`` must skip the network entirely and tag synthetic."""

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("ccxt must NOT be touched under pref='synthetic'")

    monkeypatch.setattr(src, "_ccxt_fetch_order_book", _boom)
    monkeypatch.setattr(src, "_fetch_all_live", _boom)
    monkeypatch.setattr(
        src,
        "_synthetic_fallback",
        lambda symbol, venues, **_k: _fake_synthetic(venues, symbol),
    )

    result = fetch_books("BTC/USDT", ["binance", "kraken"], pref="synthetic")

    assert isinstance(result, FetchResult)
    assert result.data_source == "synthetic"
    assert set(result.books) == {"binance", "kraken"}


@pytest.mark.unit
def test_pref_synthetic_passes_seed_and_config_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The synthetic seed and explicit config flow through unchanged."""
    captured: dict[str, Any] = {}

    def _record(symbol: str, venues: list[str], **kwargs: Any) -> dict[str, Any]:
        captured.update(symbol=symbol, venues=venues, **kwargs)
        return _fake_synthetic(venues, symbol)

    monkeypatch.setattr(src, "_synthetic_fallback", _record)
    sentinel = object()
    fetch_books(
        "ETH/USDT",
        ["coinbase"],
        pref="synthetic",
        seed=7,
        synthetic_config=sentinel,  # type: ignore[arg-type]
    )

    assert captured["seed"] == 7
    assert captured["synthetic_config"] is sentinel
    assert captured["symbol"] == "ETH/USDT"


# --------------------------------------------------------------------------- #
# Live failure -> synthetic / cache fallback                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_live_failure_falls_back_to_synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the live network seam raises, fetch_books degrades to synthetic."""

    def _fail(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("simulated geo-block / timeout")

    monkeypatch.setattr(src, "_ccxt_fetch_order_book", _fail)
    monkeypatch.setattr(
        src,
        "_synthetic_fallback",
        lambda symbol, venues, **_k: _fake_synthetic(venues, symbol),
    )

    result = fetch_books("BTC/USDT", ["kraken"], pref="live")

    assert result.data_source == "synthetic"
    assert set(result.books) == {"kraken"}


@pytest.mark.unit
def test_missing_ccxt_is_a_fallback_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ImportError from the lazy ccxt import degrades, never propagates."""

    def _no_ccxt(*_a: Any, **_k: Any) -> Any:
        raise ImportError("No module named 'ccxt'")

    monkeypatch.setattr(src, "_ccxt_fetch_order_book", _no_ccxt)
    monkeypatch.setattr(
        src,
        "_synthetic_fallback",
        lambda symbol, venues, **_k: _fake_synthetic(venues, symbol),
    )

    result = fetch_books("BTC/USDT", ["coinbase"], pref="auto")
    assert result.data_source == "synthetic"


@pytest.mark.unit
def test_live_failure_prefers_fresh_cache_over_synthetic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """On live failure a complete fresh cache snapshot wins over synthetic."""
    monkeypatch.setattr(
        src, "_ccxt_fetch_order_book", lambda *a, **k: (_ for _ in ()).throw(RuntimeError())
    )

    cache = BookCache(cache_dir=str(tmp_path / "c"), ttl_seconds=60.0)
    cache.put(OrderBook("binance", "BTC/USDT", ((100.0, 1.0),), ((101.0, 1.0),), ts_ms=1))
    cache.put(OrderBook("kraken", "BTC/USDT", ((100.0, 1.0),), ((101.0, 1.0),), ts_ms=1))

    # Synthetic must NOT be consulted when cache satisfies the whole venue set.
    monkeypatch.setattr(
        src,
        "_synthetic_fallback",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("synthetic should not run")),
    )

    result = fetch_books("BTC/USDT", ["binance", "kraken"], pref="auto", cache=cache)
    assert result.data_source == "cache"
    assert set(result.books) == {"binance", "kraken"}


@pytest.mark.unit
def test_partial_cache_is_a_miss_and_falls_through_to_synthetic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A cache snapshot missing a venue is treated as a full miss (all-or-nothing)."""
    monkeypatch.setattr(
        src, "_ccxt_fetch_order_book", lambda *a, **k: (_ for _ in ()).throw(RuntimeError())
    )
    cache = BookCache(cache_dir=str(tmp_path / "c"), ttl_seconds=60.0)
    cache.put(OrderBook("binance", "BTC/USDT", ((100.0, 1.0),), ((101.0, 1.0),), ts_ms=1))
    # kraken intentionally absent.
    monkeypatch.setattr(
        src,
        "_synthetic_fallback",
        lambda symbol, venues, **_k: _fake_synthetic(venues, symbol),
    )

    result = fetch_books("BTC/USDT", ["binance", "kraken"], pref="auto", cache=cache)
    assert result.data_source == "synthetic"


# --------------------------------------------------------------------------- #
# Live success path (injected)                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_live_success_tags_live_and_warms_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """An injected successful live fetch tags 'live' and writes through to cache."""
    monkeypatch.setattr(src, "_ccxt_fetch_order_book", lambda *a, **k: _raw_book())

    cache = BookCache(cache_dir=str(tmp_path / "c"), ttl_seconds=60.0)
    result = fetch_books("BTC/USDT", ["kraken"], pref="live", cache=cache)

    assert result.data_source == "live"
    book = result.books["kraken"]
    assert book.venue == "kraken"
    assert book.symbol == "BTC/USDT"
    assert book.bids[0] == (100.0, 2.0)  # best bid first
    assert book.asks[0] == (100.5, 2.0)  # best ask first
    assert book.ts_ms == 1_700_000_000_000
    # Cache was warmed by the live success.
    assert cache.get("kraken", "BTC/USDT") is not None


@pytest.mark.unit
def test_empty_book_side_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """A raw book with an empty side is an upstream failure -> synthetic."""
    monkeypatch.setattr(
        src, "_ccxt_fetch_order_book", lambda *a, **k: {"bids": [], "asks": [[1.0, 1.0]]}
    )
    monkeypatch.setattr(
        src,
        "_synthetic_fallback",
        lambda symbol, venues, **_k: _fake_synthetic(venues, symbol),
    )
    result = fetch_books("BTC/USDT", ["kraken"], pref="live")
    assert result.data_source == "synthetic"


@pytest.mark.unit
def test_unknown_venue_in_live_raises_upstream_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported live venue raises UpstreamError internally and falls back."""
    # The unknown venue trips inside _fetch_one_live before any ccxt import.
    with pytest.raises(UpstreamError):
        src._fetch_one_live("nasdaq", "BTC/USDT", FetchConfig())

    monkeypatch.setattr(
        src,
        "_synthetic_fallback",
        lambda symbol, venues, **_k: _fake_synthetic(venues, symbol),
    )
    result = fetch_books("BTC/USDT", ["nasdaq"], pref="auto")
    assert result.data_source == "synthetic"


# --------------------------------------------------------------------------- #
# Input validation (caller errors only)                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    ("symbol", "venues", "pref"),
    [
        ("BTC/USDT", [], "auto"),
        ("BTCUSDT", ["kraken"], "auto"),
        ("", ["kraken"], "auto"),
        ("BTC/USDT", ["kraken"], "bogus"),
        ("BTC/USDT", ["  "], "auto"),
    ],
)
def test_invalid_inputs_raise_validation_error(symbol: str, venues: list[str], pref: str) -> None:
    """Caller-side errors raise ValidationError (NEVER an upstream fallback)."""
    with pytest.raises(ValidationError):
        fetch_books(symbol, venues, pref=pref)  # type: ignore[arg-type]


@pytest.mark.unit
def test_venues_are_deduped_and_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Duplicate / mixed-case venues collapse to a normalized, ordered set."""
    captured: dict[str, Any] = {}

    def _record(symbol: str, venues: list[str], **_k: Any) -> dict[str, Any]:
        captured["venues"] = venues
        return _fake_synthetic(venues, symbol)

    monkeypatch.setattr(src, "_synthetic_fallback", _record)
    fetch_books("BTC/USDT", ["Kraken", "kraken", "BINANCE"], pref="synthetic")
    assert captured["venues"] == ["kraken", "binance"]


# --------------------------------------------------------------------------- #
# BookCache                                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_cache_round_trip(tmp_path: Any) -> None:
    """A put book is retrievable by (venue, symbol) within its TTL."""
    cache = BookCache(cache_dir=str(tmp_path / "c"), ttl_seconds=60.0)
    book = OrderBook("kraken", "BTC/USDT", ((100.0, 1.0),), ((101.0, 1.0),), ts_ms=5)
    assert cache.get("kraken", "BTC/USDT") is None  # cold miss
    cache.put(book)
    fetched = cache.get("kraken", "BTC/USDT")
    assert fetched is not None
    assert fetched.venue == "kraken"
    assert fetched.bids == ((100.0, 1.0),)


@pytest.mark.unit
def test_cache_ttl_expiry_is_a_miss(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A book older than ttl_seconds reads as a miss (staleness guard)."""
    clock = {"now": 1_000.0}

    import cryptoarb.data.cache as cache_mod

    monkeypatch.setattr(cache_mod.time, "time", lambda: clock["now"])

    cache = BookCache(cache_dir=str(tmp_path / "c"), ttl_seconds=5.0)
    book = OrderBook("kraken", "BTC/USDT", ((100.0, 1.0),), ((101.0, 1.0),))
    cache.put(book)
    assert cache.get("kraken", "BTC/USDT") is not None  # fresh

    clock["now"] += 10.0  # advance past TTL
    assert cache.get("kraken", "BTC/USDT") is None  # stale -> miss


@pytest.mark.unit
def test_cache_key_is_normalized() -> None:
    """Cache keys normalize whitespace/case so equivalent ids collapse."""
    cache = BookCache(cache_dir="x")
    assert cache.key(" Kraken ", " btc/usdt ") == cache.key("kraken", "BTC/USDT")


@pytest.mark.unit
def test_cache_to_dict_is_jsonable() -> None:
    """BookCache.to_dict returns a plain, JSON-serializable mapping."""
    import json

    cache = BookCache(cache_dir="/tmp/x", ttl_seconds=3.5)
    d = cache.to_dict()
    assert json.loads(json.dumps(d)) == {"cache_dir": "/tmp/x", "ttl_seconds": 3.5}


# --------------------------------------------------------------------------- #
# Dataclass to_dict surfaces                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_fetch_config_to_dict_is_jsonable() -> None:
    """FetchConfig.to_dict round-trips through json."""
    import json

    cfg = FetchConfig(timeout_ms=1500, rate_limit_per_sec=2.0, depth_limit=10)
    assert json.loads(json.dumps(cfg.to_dict())) == {
        "timeout_ms": 1500,
        "rate_limit_per_sec": 2.0,
        "depth_limit": 10,
    }


@pytest.mark.unit
def test_fetch_result_to_dict_delegates_to_books() -> None:
    """FetchResult.to_dict delegates per-book and carries the data_source tag."""
    result = FetchResult(
        books={"kraken": _FakeBook("kraken", "BTC/USDT", 9)},  # type: ignore[dict-item]
        data_source="synthetic",
    )
    d = result.to_dict()
    assert d["data_source"] == "synthetic"
    assert d["books"]["kraken"] == {"venue": "kraken", "symbol": "BTC/USDT", "ts_ms": 9}


@pytest.mark.unit
def test_upstream_error_is_library_error_not_validation() -> None:
    """UpstreamError is a CryptoArbError but NOT a ValidationError (always falls back)."""
    from cryptoarb._exceptions import CryptoArbError

    assert issubclass(UpstreamError, CryptoArbError)
    assert not issubclass(UpstreamError, ValidationError)


# --------------------------------------------------------------------------- #
# Defensive branches: malformed raw books and resilient cache I/O              #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_book_from_raw_malformed_levels_raise_upstream() -> None:
    """Non-numeric price/size in a raw book is normalized to UpstreamError."""
    raw = {"bids": [["oops", 1.0]], "asks": [[1.0, 1.0]], "timestamp": 1}
    with pytest.raises(UpstreamError):
        src._book_from_raw("kraken", "BTC/USDT", raw)


@pytest.mark.unit
def test_book_from_raw_empty_side_raises_upstream() -> None:
    """An empty bid/ask side raises UpstreamError before touching make_book."""
    with pytest.raises(UpstreamError):
        src._book_from_raw("kraken", "BTC/USDT", {"bids": [], "asks": [[1.0, 1.0]]})


@pytest.mark.unit
def test_cache_corrupt_entry_reads_as_miss(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stored entry with a non-numeric timestamp reads as a miss, not a crash."""
    cache = BookCache(cache_dir=str(tmp_path / "c"), ttl_seconds=60.0)

    class _FakeStore:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...
        def __enter__(self) -> _FakeStore:
            return self

        def __exit__(self, *_a: Any) -> None: ...
        def get(self, _key: str) -> Any:
            return ("book", "not-a-number")  # corrupt stored_at

    fake_diskcache = type("M", (), {"Cache": _FakeStore})
    monkeypatch.setitem(sys.modules, "diskcache", fake_diskcache)
    assert cache.get("kraken", "BTC/USDT") is None


@pytest.mark.unit
def test_cache_get_swallows_backend_errors(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A backend that raises on open is a silent miss (best-effort cache)."""

    class _Boom:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            raise OSError("disk gone")

    fake_diskcache = type("M", (), {"Cache": _Boom})
    monkeypatch.setitem(sys.modules, "diskcache", fake_diskcache)
    cache = BookCache(cache_dir=str(tmp_path / "c"))
    assert cache.get("kraken", "BTC/USDT") is None


@pytest.mark.unit
def test_cache_put_swallows_backend_errors(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A backend that raises on write must not break the caller (put is best-effort)."""

    class _Boom:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            raise OSError("disk gone")

    fake_diskcache = type("M", (), {"Cache": _Boom})
    monkeypatch.setitem(sys.modules, "diskcache", fake_diskcache)
    cache = BookCache(cache_dir=str(tmp_path / "c"))
    book = OrderBook("kraken", "BTC/USDT", ((100.0, 1.0),), ((101.0, 1.0),))
    cache.put(book)  # must not raise
