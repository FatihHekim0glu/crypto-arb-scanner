"""Public end-to-end scan entrypoint - the seam the backend router calls.

This module wires the six module groups into ONE coherent pipeline:

    books -> cross-exchange scan (depth-aware VWAP) -> cost waterfall ->
    net-edge series + verdict -> Plotly figures.

The single public entrypoint is :func:`run_scan`. It accepts either a ready
mapping of per-venue books OR a zero-argument ``books_loader`` (so the backend
can pass ``lambda: fetch_books(...).books`` and keep the lazy ``ccxt`` /
synthetic-fallback decision inside the data layer), runs the whole pipeline, and
returns a frozen :class:`ScanResult` whose :attr:`ScanResult.summary` carries the
exact headline contract the backend serializes:

    summary{ gross_bps, net_bps, fillable_notional, dominant_cost_leg,
             n_feasible, verdict, data_source }

The headline is the gross -> net COLLAPSE, never a profit claim: the verdict is a
PURE function of the net-edge inference (:func:`cryptoarb.evaluation.verdict.derive_verdict`)
and is structurally unable to claim a feasible edge when ``net_bps`` is at/below
the noise band or its lower confidence bound includes zero.

Importing this module has ZERO side effects: ``plotly`` is imported lazily inside
the figure helpers (via :mod:`cryptoarb.plots`) and ``ccxt`` is never touched
here at all - the data layer owns that decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import TYPE_CHECKING, Any

from cryptoarb._exceptions import ValidationError
from cryptoarb.arb.cross import best_cross_leg
from cryptoarb.arb.feasibility import ArbKind, ArbResult, assemble_arb_result
from cryptoarb.books.vwap import Side, vwap
from cryptoarb.costs.waterfall import CompositeCost
from cryptoarb.evaluation.netedge import cost_sensitivity_grid, effective_n_trials
from cryptoarb.evaluation.verdict import Verdict, derive_verdict

if TYPE_CHECKING:
    from collections.abc import Callable

    from cryptoarb.books.model import OrderBook
    from cryptoarb.costs.fees import FeeSchedule
    from cryptoarb.costs.transfer import TransferSchedule
    from cryptoarb.data.ccxt_source import DataSource

#: Minimum fraction of the requested notional that must be fillable across both
#: legs for a positive net edge to count as executable. Below this the requested
#: size overwhelms book depth and the verdict is forced to the honest null,
#: regardless of the thin-fill spread (see the depth gate in ``run_scan``).
_MIN_FILL_RATIO: float = 0.5

#: Default cost-sensitivity sweep (extra bps on top of the baseline waterfall).
#: This is the data behind the "net edge collapses after fees + depth + transfer"
#: caption and the cost-sensitivity figure.
_DEFAULT_EXTRA_COST_GRID: tuple[float, ...] = (0.0, 2.0, 5.0, 10.0, 20.0)


@dataclass(frozen=True, slots=True)
class ScanSummary:
    """The headline contract the backend serializes into ``summary``.

    Attributes
    ----------
    gross_bps:
        The best executable (depth-aware) cross-exchange gross spread, in bps.
    net_bps:
        The net edge after the full cost waterfall - the honest headline number.
    fillable_notional:
        The notional fully fillable across both legs of the best pair, in USD.
    dominant_cost_leg:
        The single largest cost contributor (``"taker_fees"`` or ``"transfer"``).
    n_feasible:
        Count of scanned venue-pair legs whose net edge is structurally feasible
        (``net_bps > 0``). The honest null drives this to ``0`` on consistent
        books.
    verdict:
        The derived headline verdict (PURE function of the net-edge inference).
    data_source:
        Where the books came from (``"live"``/``"cache"``/``"synthetic"``).
    """

    gross_bps: float
    net_bps: float
    fillable_notional: float
    dominant_cost_leg: str
    n_feasible: int
    verdict: Verdict
    data_source: DataSource

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this summary."""
        return {
            "gross_bps": float(self.gross_bps),
            "net_bps": float(self.net_bps),
            "fillable_notional": float(self.fillable_notional),
            "dominant_cost_leg": self.dominant_cost_leg,
            "n_feasible": int(self.n_feasible),
            "verdict": self.verdict.value,
            "data_source": self.data_source,
        }


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The full end-to-end scan result the backend renders.

    Attributes
    ----------
    summary:
        The headline :class:`ScanSummary`.
    best:
        The fully decomposed :class:`~cryptoarb.arb.feasibility.ArbResult` for the
        single best venue pair (carries the gross/executable/net bps + legs).
    waterfall:
        The gross -> net :class:`~cryptoarb.costs.waterfall.Waterfall` for the
        best pair (renders as the headline bar chart).
    pair_net_bps:
        The per-venue-pair net-edge series, in bps and venue-pair order. This is
        the input the DSR/PSR machinery would deflate; it also feeds the spread
        distribution figure.
    pair_gross_bps:
        The per-venue-pair executable gross-spread series, in bps and matching
        order (the raw spreads that look profitable before costs).
    cost_sensitivity:
        The extra-cost sweep showing how fast the best pair's net edge collapses.
    n_trials:
        The HONEST effective-trials count ``pair_legs * fee_grid_points`` used for
        any downstream DSR deflation (NEVER ``1``).
    symbol:
        The scanned ``BASE/QUOTE`` symbol.
    notional_usd:
        The target notional the scan was priced for, in USD.
    """

    summary: ScanSummary
    best: ArbResult
    waterfall: Any  # Waterfall - Any keeps this module free of an import cycle.
    pair_net_bps: tuple[float, ...]
    pair_gross_bps: tuple[float, ...]
    cost_sensitivity: tuple[Any, ...]  # tuple[CostSensitivityPoint, ...]
    n_trials: int
    symbol: str
    notional_usd: float

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of the whole result."""
        return {
            "summary": self.summary.to_dict(),
            "best": self.best.to_dict(),
            "waterfall": self.waterfall.to_dict(),
            "pair_net_bps": [float(value) for value in self.pair_net_bps],
            "pair_gross_bps": [float(value) for value in self.pair_gross_bps],
            "cost_sensitivity": [point.to_dict() for point in self.cost_sensitivity],
            "n_trials": int(self.n_trials),
            "symbol": self.symbol,
            "notional_usd": float(self.notional_usd),
        }


def _pair_executable_bps(
    buy_book: OrderBook, sell_book: OrderBook, target_notional: float
) -> tuple[float, float]:
    """Return ``(gross_bps, fillable_notional)`` for one ordered (buy, sell) pair.

    Walks the buyer's asks and the seller's bids to ``target_notional`` with the
    depth-aware VWAP kernel; the gross spread is therefore EXECUTABLE (never
    top-of-book), and the fillable notional is the binding minimum of the two
    legs' fills.
    """
    buy = vwap(buy_book, Side.BUY, target_notional)
    sell = vwap(sell_book, Side.SELL, target_notional)
    gross_bps = 1e4 * (sell.avg_price - buy.avg_price) / buy.avg_price
    fillable = min(buy.filled_notional, sell.filled_notional)
    return gross_bps, fillable


def _net_bps_for_pair(
    *,
    gross_bps: float,
    buy_fee: FeeSchedule,
    sell_fee: FeeSchedule,
    transfer: TransferSchedule | None,
    notional_usd: float,
    asset_price_usd: float,
) -> float:
    """Run one pair's executable gross spread through the cost waterfall to net bps."""
    from cryptoarb.costs.waterfall import build_waterfall

    waterfall = build_waterfall(
        gross_bps=gross_bps,
        buy_fee=buy_fee,
        sell_fee=sell_fee,
        transfer=transfer,
        notional_usd=notional_usd,
        asset_price_usd=asset_price_usd,
    )
    return waterfall.net_bps


def run_scan(
    symbol: str,
    venues: list[str],
    notional_usd: float = 10_000.0,
    *,
    fee_profile: str = "default",
    include_transfer_cost: bool = True,
    books: dict[str, OrderBook] | None = None,
    books_loader: Callable[[], tuple[dict[str, OrderBook], DataSource]] | None = None,
    noise_bps: float = 1.0,
    feasible_bps: float = 5.0,
    extra_cost_grid: tuple[float, ...] = _DEFAULT_EXTRA_COST_GRID,
) -> ScanResult:
    """Run the full cross-exchange scan and return a frozen :class:`ScanResult`.

    This is THE public entrypoint the backend router calls. It does not touch the
    network: the caller supplies books either directly (``books``) or via a
    zero-argument ``books_loader`` that returns ``(books, data_source)`` - the
    backend wires that to ``fetch_books`` so the lazy-``ccxt`` / synthetic-fallback
    decision stays in the data layer and NEVER becomes a hard dependency of this
    pure pipeline.

    Pipeline:

    1. For EVERY ordered venue pair, price the depth-aware executable gross spread
       to ``notional_usd`` (walk-the-book VWAP, never top-of-book) and run it
       through the cost waterfall to a net edge. The per-pair net/gross series are
       retained for the spread figure and any DSR deflation.
    2. Select the single best (richest gross) pair, assemble its
       :class:`~cryptoarb.arb.feasibility.ArbResult` and gross -> net
       :class:`~cryptoarb.costs.waterfall.Waterfall`.
    3. Derive the headline verdict as a PURE function of the best pair's net edge.
       The honest-null floor (net <= noise OR CI straddles zero) makes a feasible
       claim structurally impossible on consistent books.
    4. Sweep an extra-cost grid to show how fast the net edge collapses.

    Parameters
    ----------
    symbol:
        Unified ``BASE/QUOTE`` symbol (e.g. ``"BTC/USDT"``).
    venues:
        Venue identifiers to scan (at least two).
    notional_usd:
        Target notional in USD; ``> 0``.
    fee_profile:
        Cost profile name (``"default"``, ``"low"``, ``"high"``).
    include_transfer_cost:
        Whether to charge the cross-venue transfer cost in the waterfall.
    books:
        A ready ``{venue: OrderBook}`` mapping; ``data_source`` defaults to
        ``"synthetic"`` for the offline path.
    books_loader:
        A zero-argument callable returning ``(books, data_source)``; mutually
        exclusive with ``books``. Exactly one of the two MUST be supplied.
    noise_bps, feasible_bps:
        The verdict's "within noise" half-band and feasibility threshold (bps).
    extra_cost_grid:
        The extra-cost sweep (bps) for the cost-sensitivity figure.

    Returns
    -------
    ScanResult
        The full decomposition, headline summary, and figure inputs.

    Raises
    ------
    ValidationError
        If neither/both of ``books``/``books_loader`` are supplied, fewer than two
        venues are present, ``notional_usd`` is not positive, or an input is out
        of domain (propagated from the kernels).
    """
    if not (notional_usd > 0.0):
        raise ValidationError(
            f"run_scan: notional_usd must be strictly positive, got {notional_usd}."
        )
    if (books is None) == (books_loader is None):
        raise ValidationError("run_scan: supply exactly one of 'books' or 'books_loader'.")

    data_source: DataSource
    if books_loader is not None:
        resolved_books, data_source = books_loader()
    else:
        assert books is not None  # narrowed by the XOR guard above
        resolved_books, data_source = books, "synthetic"

    # Restrict to the requested venues (preserving the caller's intent) and demand
    # at least two - a cross-exchange scan is undefined on a single venue.
    selected = {venue: resolved_books[venue] for venue in venues if venue in resolved_books}
    if len(selected) < 2:
        raise ValidationError(
            f"run_scan: need at least two of the requested venues present, "
            f"got {sorted(selected)} from requested {sorted(venues)}."
        )

    cost = CompositeCost.from_profile(fee_profile)
    base_asset = symbol.split("/")[0].strip().upper()
    transfer = cost.transfers.get(base_asset) if include_transfer_cost else None

    # --- 1) Price EVERY ordered venue pair into a (gross, net, fillable) row. ---
    # Iterating sorted venue names keeps the scan deterministic when two pairs tie.
    pair_venues = sorted(selected)
    pair_gross: list[float] = []
    pair_net: list[float] = []
    n_feasible = 0
    for buy_venue, sell_venue in permutations(pair_venues, 2):
        gross_bps, _ = _pair_executable_bps(selected[buy_venue], selected[sell_venue], notional_usd)
        asset_price = selected[buy_venue].mid
        net_bps = _net_bps_for_pair(
            gross_bps=gross_bps,
            buy_fee=cost.fees[buy_venue],
            sell_fee=cost.fees[sell_venue],
            transfer=transfer,
            notional_usd=notional_usd,
            asset_price_usd=asset_price,
        )
        pair_gross.append(gross_bps)
        pair_net.append(net_bps)
        if net_bps > 0.0:
            n_feasible += 1

    # --- 2) Best pair: richest executable gross spread, fully decomposed. ---
    best_leg = best_cross_leg(selected, notional_usd)
    best_asset_price = selected[best_leg.buy_venue].mid
    best = assemble_arb_result(
        kind=ArbKind.CROSS_EXCHANGE,
        symbol=symbol,
        legs=(f"buy@{best_leg.buy_venue}", f"sell@{best_leg.sell_venue}"),
        notional_usd=notional_usd,
        gross_bps=best_leg.gross_bps,
        executable_bps=best_leg.gross_bps,
        fillable_notional=best_leg.fillable_notional,
        buy_fee=cost.fees[best_leg.buy_venue],
        sell_fee=cost.fees[best_leg.sell_venue],
        transfer=transfer,
        asset_price_usd=best_asset_price,
    )

    from cryptoarb.costs.waterfall import build_waterfall

    waterfall = build_waterfall(
        gross_bps=best_leg.gross_bps,
        buy_fee=cost.fees[best_leg.buy_venue],
        sell_fee=cost.fees[best_leg.sell_venue],
        transfer=transfer,
        notional_usd=notional_usd,
        asset_price_usd=best_asset_price,
    )

    # --- 3) Honest verdict: PURE function of the best pair's net edge. ---
    # The CI band here is a conservative +/- noise envelope around the point net
    # edge; it keeps the verdict from ever over-claiming on the honest null (a
    # net edge at/below noise can never read as a feasible edge). A richer
    # bootstrap CI can be threaded in by the backend without changing this seam.
    ci_low = waterfall.net_bps - noise_bps
    ci_high = waterfall.net_bps + noise_bps
    verdict = derive_verdict(
        waterfall.net_bps,
        ci_low_bps=ci_low,
        ci_high_bps=ci_high,
        noise_bps=noise_bps,
        feasible_bps=feasible_bps,
    )

    # Depth gate (anti-overstatement): a spread you can fill only a sliver of is
    # not an executable edge at the requested size. When VWAP saturates because
    # the requested notional exceeds book depth, ``fillable_notional`` is far
    # below ``notional_usd`` while ``net_bps`` keeps reporting the thin-fill
    # spread. Force the honest null in that case so the headline never implies an
    # executable edge for a size the book cannot support.
    fill_ratio = best_leg.fillable_notional / notional_usd if notional_usd > 0.0 else 0.0
    if fill_ratio < _MIN_FILL_RATIO:
        verdict = Verdict.NO_FEASIBLE_EDGE

    # --- 4) Cost-sensitivity sweep off the best pair's baseline cost. ---
    baseline_cost_bps = best_leg.gross_bps - waterfall.net_bps
    cost_points = cost_sensitivity_grid(
        gross_bps=best_leg.gross_bps,
        baseline_cost_bps=baseline_cost_bps,
        extra_cost_grid=extra_cost_grid,
    )

    # HONEST multiplicity: every venue-pair leg times each cost-grid point.
    n_trials = effective_n_trials(len(pair_net), len(extra_cost_grid))

    summary = ScanSummary(
        gross_bps=best_leg.gross_bps,
        net_bps=waterfall.net_bps,
        fillable_notional=best_leg.fillable_notional,
        dominant_cost_leg=waterfall.dominant_cost_leg,
        n_feasible=n_feasible,
        verdict=verdict,
        data_source=data_source,
    )

    return ScanResult(
        summary=summary,
        best=best,
        waterfall=waterfall,
        pair_net_bps=tuple(pair_net),
        pair_gross_bps=tuple(pair_gross),
        cost_sensitivity=tuple(cost_points),
        n_trials=n_trials,
        symbol=symbol,
        notional_usd=float(notional_usd),
    )


def scan_figures(result: ScanResult) -> dict[str, dict[str, Any]]:
    """Assemble the headline Plotly figures for a :class:`ScanResult`.

    Returns the gross -> net WATERFALL and the spread-distribution figures (plus
    the cost-sensitivity figure) already serialized to the ``{data, layout}``
    JSON the backend forwards unchanged. ``plotly`` is imported LAZILY inside the
    figure builders, so calling this requires the optional ``[viz]`` extra but
    importing this module does not.

    Parameters
    ----------
    result:
        The scan result to render.

    Returns
    -------
    dict[str, dict[str, Any]]
        ``{"waterfall_figure": ..., "spread_figure": ..., "cost_sensitivity_figure": ...}``,
        each a JSON-safe ``{data, layout}`` mapping.
    """
    from cryptoarb.plots import (
        cost_sensitivity_figure,
        figure_to_dict,
        spread_distribution_figure,
        waterfall_figure,
    )

    waterfall_fig = waterfall_figure(result.waterfall)
    spread_fig = spread_distribution_figure(result.pair_gross_bps, net_bps=result.summary.net_bps)
    sensitivity_fig = cost_sensitivity_figure(result.cost_sensitivity)
    return {
        "waterfall_figure": figure_to_dict(waterfall_fig),
        "spread_figure": figure_to_dict(spread_fig),
        "cost_sensitivity_figure": figure_to_dict(sensitivity_fig),
    }
