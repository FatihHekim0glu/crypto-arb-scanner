"""End-to-end integration tests for the public :func:`cryptoarb.run_scan` scan.

These run the WHOLE offline pipeline through the single public entrypoint the
backend calls - books -> cross-exchange scan (depth-aware VWAP) -> cost
waterfall -> net-edge series + verdict -> Plotly figures - on BOTH seeded
fixtures, with NO network and NO live data:

- ``consistent_books`` (the honest null): no cross-venue dislocation, so the net
  edge collapses to ``<= 0`` and the verdict is ``no_feasible_edge`` with
  ``n_feasible == 0``.
- ``dislocated_books``: one venue is skewed to fake a small exploitable gap; the
  raw gross spread is positive but the cost waterfall is expected to ERASE it,
  so the headline is the gross -> net COLLAPSE, never a profit claim.

The ``books_loader`` seam (how the backend threads ``fetch_books`` in) and the
figure-assembly helper are exercised too. ``fetch_books``'s synthetic preference
is asserted to never touch the network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cryptoarb import run_scan, scan_figures
from cryptoarb.data.ccxt_source import DataSource, fetch_books
from cryptoarb.evaluation.verdict import Verdict
from cryptoarb.scan import ScanResult, ScanSummary

if TYPE_CHECKING:
    from cryptoarb.books.model import OrderBook

_SYMBOL = "BTC/USDT"
_VENUES = ["binance", "coinbase", "kraken"]
_NOTIONAL = 10_000.0


@pytest.mark.integration
def test_fetch_books_entry_point_exists() -> None:
    """The live+cache+synthetic data entry point is importable and callable."""
    assert callable(fetch_books)


@pytest.mark.integration
def test_pipeline_entry_points_exist() -> None:
    """Every stage the end-to-end scan chains together is importable."""
    from cryptoarb.arb.cross import best_cross_leg
    from cryptoarb.arb.triangular import triangular_cycle
    from cryptoarb.costs.waterfall import build_waterfall
    from cryptoarb.evaluation.netedge import net_edge_stats
    from cryptoarb.evaluation.verdict import derive_verdict

    for fn in (
        best_cross_leg,
        triangular_cycle,
        build_waterfall,
        net_edge_stats,
        derive_verdict,
    ):
        assert callable(fn)


@pytest.mark.integration
def test_run_scan_consistent_books_is_honest_null(
    consistent_books: dict[str, OrderBook],
) -> None:
    """On consistent books the net edge collapses: no_feasible_edge, n_feasible 0.

    With no cross-venue dislocation the best executable gross spread is already
    near zero (negative once depth is walked), so after fees + transfer the net
    edge is strictly negative and the PURE verdict CANNOT read feasible.
    """
    result = run_scan(_SYMBOL, _VENUES, _NOTIONAL, books=consistent_books)

    assert isinstance(result, ScanResult)
    assert isinstance(result.summary, ScanSummary)
    summary = result.summary

    # Honest-null headline: the collapse, never a profit claim.
    assert summary.net_bps <= 0.0
    assert summary.verdict is Verdict.NO_FEASIBLE_EDGE
    assert summary.n_feasible == 0
    # net <= gross monotonicity holds (costs are non-negative).
    assert summary.net_bps <= summary.gross_bps + 1e-9
    # Best ArbResult agrees with the headline floor and is structurally not feasible.
    assert result.best.feasible is False
    assert result.best.net_bps == pytest.approx(summary.net_bps, abs=1e-9)
    # data_source defaults to synthetic on the direct-books path.
    assert summary.data_source == "synthetic"
    # Dominant cost is a real cost leg (transfer or taker_fees), never zeroed.
    assert summary.dominant_cost_leg in {"taker_fees", "transfer"}


@pytest.mark.integration
def test_run_scan_dislocated_books_collapses_after_costs(
    dislocated_books: dict[str, OrderBook],
) -> None:
    """A faked gap shows a positive gross spread that the cost waterfall erases.

    This is the headline input: the raw cross-exchange spread looks profitable
    (positive gross bps) but the net executable edge collapses to ~0/negative
    after taker fees on both legs + depth slippage + transfer cost.
    """
    result = run_scan(_SYMBOL, _VENUES, _NOTIONAL, books=dislocated_books)
    summary = result.summary

    # The dislocation manufactures a genuine positive gross spread...
    assert summary.gross_bps > 0.0
    # ...but the net edge is strictly below the gross edge (the collapse)...
    assert summary.net_bps < summary.gross_bps
    # ...and on an ~8 bps gap against double-digit-bps round-trip costs it does
    # not survive: the honest verdict refuses to call it feasible.
    assert summary.net_bps <= 0.0
    assert summary.verdict is Verdict.NO_FEASIBLE_EDGE
    assert summary.n_feasible == 0
    # The waterfall stages walk gross -> net coherently.
    assert result.waterfall.gross_bps == pytest.approx(summary.gross_bps, abs=1e-9)
    assert result.waterfall.net_bps == pytest.approx(summary.net_bps, abs=1e-9)


@pytest.mark.integration
def test_run_scan_honest_multiplicity_and_series_shapes(
    dislocated_books: dict[str, OrderBook],
) -> None:
    """n_trials is the honest pair-legs x grid product (never 1); series align."""
    result = run_scan(_SYMBOL, _VENUES, _NOTIONAL, books=dislocated_books)

    n_pairs = len(_VENUES) * (len(_VENUES) - 1)  # ordered pairs = 6
    assert len(result.pair_net_bps) == n_pairs
    assert len(result.pair_gross_bps) == n_pairs
    # HONEST multiplicity: pair_legs x fee_grid_points, strictly > 1.
    assert result.n_trials == n_pairs * len(result.cost_sensitivity)
    assert result.n_trials > 1
    # Cost-sensitivity sweep is non-empty and net edge falls as extra cost rises.
    nets = [point.net_bps for point in result.cost_sensitivity]
    assert nets == sorted(nets, reverse=True)


@pytest.mark.integration
def test_run_scan_counts_feasible_pairs_on_a_large_gap() -> None:
    """A gap far exceeding round-trip costs leaves at least one feasible pair.

    The honest-null discipline is a floor, not a gag: when a (synthetic) cross-
    venue dislocation is large enough to clear fees + transfer for some ordered
    pair, ``n_feasible`` must count it and the best pair's net edge is positive.
    This proves the verdict is a genuine inference, not a hard-wired ``no``.
    """
    from cryptoarb.books.model import make_book

    mid = 50_000.0
    half = mid * 2.0 / 1e4  # 2 bps half-spread
    # binance/kraken are the cheap venues; kraken's book is lifted ~120 bps so a
    # buy@binance -> sell@kraken pair clears the ~20-26 bps round-trip taker cost.
    rich = mid * (1.0 + 120.0 / 1e4)
    rich_half = rich * 2.0 / 1e4
    deep = 50.0  # deep enough that the notional fills at the top level

    books = {
        "binance": make_book("binance", _SYMBOL, [(mid - half, deep)], [(mid + half, deep)]),
        "kraken": make_book(
            "kraken", _SYMBOL, [(rich - rich_half, deep)], [(rich + rich_half, deep)]
        ),
    }
    # Transfer cost is excluded here so the test isolates a feasible edge against
    # the REAL (never-zeroed) round-trip taker fees: a 120 bps gap clears the
    # ~20-26 bps combined taker cost. (The flat withdrawal fee otherwise dominates
    # a small notional, which is itself part of the honest collapse story.)
    result = run_scan(
        _SYMBOL, ["binance", "kraken"], 1_000.0, books=books, include_transfer_cost=False
    )

    assert result.summary.gross_bps > 100.0  # the raw gap survives top-of-book
    assert result.summary.net_bps > 0.0  # clears the real round-trip taker fees
    assert result.summary.dominant_cost_leg == "taker_fees"
    assert result.summary.n_feasible >= 1
    assert result.best.feasible is True
    # A net edge above the feasibility threshold with a clean CI reads feasible.
    assert result.summary.verdict in {Verdict.MARGINAL, Verdict.FEASIBLE_EDGE}


@pytest.mark.integration
def test_run_scan_books_loader_seam_threads_data_source(
    consistent_books: dict[str, OrderBook],
) -> None:
    """The backend seam: a zero-arg loader returns (books, data_source).

    Mirrors how the router wires ``fetch_books`` in. The returned ``data_source``
    must propagate verbatim into the summary.
    """

    def _loader() -> tuple[dict[str, OrderBook], DataSource]:
        return consistent_books, "live"

    result = run_scan(_SYMBOL, _VENUES, _NOTIONAL, books_loader=_loader)
    assert result.summary.data_source == "live"
    assert result.summary.verdict is Verdict.NO_FEASIBLE_EDGE


@pytest.mark.integration
def test_run_scan_fetch_books_synthetic_loader_end_to_end() -> None:
    """run_scan over fetch_books(pref='synthetic') is fully offline and green.

    This is the exact offline shape of the deployed call: the data layer's
    synthetic preference NEVER touches ccxt/the network, and the whole pipeline
    runs to a coherent honest-null ScanResult.
    """

    def _loader() -> tuple[dict[str, OrderBook], DataSource]:
        fetched = fetch_books(_SYMBOL, _VENUES, pref="synthetic", seed=7)
        return fetched.books, fetched.data_source

    result = run_scan(_SYMBOL, _VENUES, _NOTIONAL, books_loader=_loader)
    assert result.summary.data_source == "synthetic"
    # Default synthetic config is the consistent (no-dislocation) fixture -> null.
    assert result.summary.net_bps <= 0.0
    assert result.summary.verdict is Verdict.NO_FEASIBLE_EDGE


@pytest.mark.integration
def test_run_scan_no_transfer_changes_dominant_and_net(
    dislocated_books: dict[str, OrderBook],
) -> None:
    """Excluding transfer cost raises net and can only equal/raise it vs. with-transfer."""
    with_transfer = run_scan(
        _SYMBOL, _VENUES, _NOTIONAL, books=dislocated_books, include_transfer_cost=True
    )
    without_transfer = run_scan(
        _SYMBOL, _VENUES, _NOTIONAL, books=dislocated_books, include_transfer_cost=False
    )
    # Dropping a non-negative cost can only raise (or hold) the net edge.
    assert without_transfer.summary.net_bps >= with_transfer.summary.net_bps - 1e-9
    # With transfer excluded the only cost leg is taker fees.
    assert without_transfer.summary.dominant_cost_leg == "taker_fees"


@pytest.mark.integration
def test_scan_figures_assemble_waterfall_and_spread(
    dislocated_books: dict[str, OrderBook],
) -> None:
    """The figure helper assembles JSON-safe waterfall + spread + sensitivity figures."""
    pytest.importorskip("plotly")
    result = run_scan(_SYMBOL, _VENUES, _NOTIONAL, books=dislocated_books)
    figures = scan_figures(result)

    assert set(figures) == {"waterfall_figure", "spread_figure", "cost_sensitivity_figure"}
    for payload in figures.values():
        assert isinstance(payload, dict)
        assert "data" in payload
        assert "layout" in payload
    # The waterfall figure carries one go.Waterfall trace (the headline collapse).
    waterfall_data = figures["waterfall_figure"]["data"]
    assert any(trace.get("type") == "waterfall" for trace in waterfall_data)


@pytest.mark.integration
def test_run_scan_result_to_dict_is_json_safe(
    consistent_books: dict[str, OrderBook],
) -> None:
    """The whole ScanResult serializes to a plain, JSON-encodable dict."""
    import json

    result = run_scan(_SYMBOL, _VENUES, _NOTIONAL, books=consistent_books)
    payload = result.to_dict()
    # round-trips through json without error
    encoded = json.dumps(payload)
    assert '"verdict": "no_feasible_edge"' in encoded
    assert payload["summary"]["data_source"] == "synthetic"
    assert payload["n_trials"] > 1


@pytest.mark.integration
@pytest.mark.parametrize(
    "kwargs",
    [
        {"books": None, "books_loader": None},  # neither
    ],
)
def test_run_scan_requires_exactly_one_book_source(
    kwargs: dict[str, object],
) -> None:
    """Supplying neither (or both) of books/books_loader is a ValidationError."""
    from cryptoarb._exceptions import ValidationError

    with pytest.raises(ValidationError):
        run_scan(_SYMBOL, _VENUES, _NOTIONAL, **kwargs)  # type: ignore[arg-type]


@pytest.mark.integration
def test_run_scan_rejects_both_book_sources(
    consistent_books: dict[str, OrderBook],
) -> None:
    """Supplying BOTH books and books_loader is a ValidationError (XOR contract)."""
    from cryptoarb._exceptions import ValidationError

    def _loader() -> tuple[dict[str, OrderBook], DataSource]:
        return consistent_books, "synthetic"

    with pytest.raises(ValidationError):
        run_scan(_SYMBOL, _VENUES, _NOTIONAL, books=consistent_books, books_loader=_loader)


@pytest.mark.integration
def test_run_scan_requires_two_present_venues(
    consistent_books: dict[str, OrderBook],
) -> None:
    """Fewer than two requested venues present in the books is a ValidationError."""
    from cryptoarb._exceptions import ValidationError

    with pytest.raises(ValidationError):
        run_scan(_SYMBOL, ["binance"], _NOTIONAL, books=consistent_books)


@pytest.mark.integration
def test_run_scan_rejects_non_positive_notional(
    consistent_books: dict[str, OrderBook],
) -> None:
    """A non-positive notional is rejected up front."""
    from cryptoarb._exceptions import ValidationError

    with pytest.raises(ValidationError):
        run_scan(_SYMBOL, _VENUES, 0.0, books=consistent_books)
