"""Typer command-line interface: ``scan`` and ``replay``.

The CLI is a thin shell over the pure compute library; ``typer`` is imported
LAZILY inside :func:`build_app` (and the package's optional ``[viz]``/``[data]``
extras are only needed by the commands that use them), so importing this module
has no side effects. The two commands — :func:`scan` and :func:`replay` — are
plain functions that compute and print; they require neither ``typer`` nor any
network, so they are directly callable and testable on the synthetic path. The
interactive demo lives behind the ``__main__`` guard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typer import Typer

    from cryptoarb.books.model import OrderBook

# "Within noise" half-band and feasibility threshold (bps) used by the honest
# verdict. They mirror the defaults in :mod:`cryptoarb.evaluation.verdict`; the
# CLI derives its headline from the same rule so it can never claim a feasible
# edge when the net is non-positive.
_NOISE_BPS = 1.0
_FEASIBLE_BPS = 5.0


def _best_cross_gross_bps(
    books: dict[str, OrderBook], target_notional: float
) -> tuple[str, str, float, float]:
    """Return ``(buy_venue, sell_venue, gross_bps, fillable_notional)`` for the best pair.

    Walks every ordered venue pair's books to ``target_notional`` with the
    depth-aware VWAP kernel and keeps the buy-cheap / sell-rich pairing with the
    largest executable gross spread. Self-contained on the implemented VWAP
    primitive so the CLI scan runs end-to-end on synthetic books today.
    """
    from cryptoarb.books.vwap import Side, vwap

    venues = list(books)
    best: tuple[str, str, float, float] | None = None
    for buy_venue in venues:
        for sell_venue in venues:
            if buy_venue == sell_venue:
                continue
            buy = vwap(books[buy_venue], Side.BUY, target_notional)
            sell = vwap(books[sell_venue], Side.SELL, target_notional)
            if buy.avg_price <= 0.0 or sell.avg_price <= 0.0:
                continue
            gross = 1e4 * (sell.avg_price - buy.avg_price) / buy.avg_price
            fillable = min(buy.filled_notional, sell.filled_notional)
            if best is None or gross > best[2]:
                best = (buy_venue, sell_venue, gross, fillable)
    if best is None:  # pragma: no cover - needs <2 venues, guarded upstream
        raise ValueError("at least two venues are required for a cross-exchange scan.")
    return best


def _honest_verdict(net_bps: float) -> str:
    """Derive the headline verdict string from the net edge (honest-null rule).

    Structurally cannot return ``"feasible_edge"`` when the net edge is at or
    below the noise band: ``net <= noise`` -> ``no_feasible_edge``;
    ``net >= feasible`` -> ``feasible_edge``; otherwise ``marginal``.
    """
    if net_bps <= _NOISE_BPS:
        return "no_feasible_edge"
    if net_bps >= _FEASIBLE_BPS:
        return "feasible_edge"
    return "marginal"


def scan(
    symbol: str = "BTC/USDT",
    venues: str = "binance,coinbase,kraken",
    notional_usd: float = 10_000.0,
    fee_profile: str = "default",
    include_transfer: bool = True,
    data_source_pref: str = "auto",
    seed: int = 0,
) -> None:
    """Scan ``symbol`` across ``venues`` and print the gross -> net decomposition.

    Fetches L2 books (with graceful synthetic fallback), finds the best
    buy-cheap / sell-rich venue pair for ``notional_usd`` off depth-aware VWAPs,
    decomposes the executable gross spread into its net edge through the cost
    waterfall, and prints the stages, the honest verdict, and the data source.

    Parameters
    ----------
    symbol:
        Unified ``BASE/QUOTE`` symbol.
    venues:
        Comma-separated venue identifiers.
    notional_usd:
        Target notional in USD.
    fee_profile:
        Cost profile name (``"default"``, ``"low"``, ``"high"``).
    include_transfer:
        Whether to include transfer cost in the waterfall.
    data_source_pref:
        Source preference (``"auto"``, ``"live"``, ``"synthetic"``).
    seed:
        Master seed for the synthetic fallback.
    """
    from cryptoarb.costs.waterfall import CompositeCost, build_waterfall
    from cryptoarb.data.ccxt_source import fetch_books

    venue_list = [token.strip() for token in venues.split(",") if token.strip()]

    result = fetch_books(symbol, venue_list, pref=data_source_pref, seed=seed)  # type: ignore[arg-type]
    buy_venue, sell_venue, gross_bps, fillable = _best_cross_gross_bps(result.books, notional_usd)

    cost = CompositeCost.from_profile(fee_profile)
    base_asset = symbol.split("/")[0].strip().upper()
    asset_price = result.books[buy_venue].mid
    transfer = cost.transfers.get(base_asset) if include_transfer else None

    waterfall = build_waterfall(
        gross_bps=gross_bps,
        buy_fee=cost.fees[buy_venue],
        sell_fee=cost.fees[sell_venue],
        transfer=transfer,
        notional_usd=notional_usd,
        asset_price_usd=asset_price,
    )
    verdict = _honest_verdict(waterfall.net_bps)

    print(f"crypto-arb-scanner  {symbol}  notional=${notional_usd:,.0f}  profile={fee_profile}")
    print(f"  data_source : {result.data_source}")
    print(f"  best pair   : buy {buy_venue} -> sell {sell_venue}")
    print(f"  fillable    : ${fillable:,.0f}")
    print("  waterfall   :")
    for stage in waterfall.stages:
        print(
            f"    {stage.label:<12} delta={stage.delta_bps:+8.2f}  running={stage.running_bps:+8.2f}"
        )
    print(f"  gross_bps   : {waterfall.gross_bps:+.2f}")
    print(f"  net_bps     : {waterfall.net_bps:+.2f}")
    print(f"  dominant    : {waterfall.dominant_cost_leg}")
    print(f"  verdict     : {verdict}")
    if verdict == "no_feasible_edge":
        print(
            "  note        : net edge collapsed after fees + depth + transfer "
            "(not executable via REST)."
        )


def replay(
    snapshot_path: str,
    decision_ms: int,
    embargo_ms: int = 0,
) -> None:
    """Replay a saved snapshot at ``decision_ms`` under the no-lookahead guard.

    Only quotes with ``ts_ms <= decision_ms - embargo_ms`` are visible to the
    decision; the command reports whether the historical opportunity survives
    costs and confirms that post-``t`` quotes cannot change the verdict.

    Parameters
    ----------
    snapshot_path:
        Path to a saved multi-venue snapshot (JSON ``{venue: book.to_dict()}``).
    decision_ms:
        The decision timestamp in milliseconds since the epoch.
    embargo_ms:
        Extra staleness embargo subtracted from ``decision_ms``.
    """
    import json
    from pathlib import Path

    from cryptoarb.books.model import make_book
    from cryptoarb.costs.waterfall import CompositeCost, build_waterfall

    raw = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))

    cutoff = decision_ms - embargo_ms
    visible: dict[str, OrderBook] = {}
    for venue, payload in raw.items():
        ts_ms = int(payload.get("ts_ms", 0))
        if ts_ms > cutoff:
            # No-lookahead guard: a quote stamped after the decision is invisible.
            continue
        book = make_book(
            str(payload["venue"]),
            str(payload["symbol"]),
            [tuple(level) for level in payload["bids"]],
            [tuple(level) for level in payload["asks"]],
            ts_ms=ts_ms,
        )
        visible[venue] = book

    print(f"replay  snapshot={snapshot_path}  decision_ms={decision_ms}  embargo_ms={embargo_ms}")
    print(f"  visible venues (ts <= {cutoff}): {sorted(visible)}")

    if len(visible) < 2:
        print("  verdict     : no_feasible_edge (insufficient non-stale venues at t).")
        return

    symbol = next(iter(visible.values())).symbol
    notional_usd = 10_000.0
    buy_venue, sell_venue, gross_bps, _ = _best_cross_gross_bps(visible, notional_usd)

    cost = CompositeCost.from_profile("default")
    base_asset = symbol.split("/")[0].strip().upper()
    waterfall = build_waterfall(
        gross_bps=gross_bps,
        buy_fee=cost.fees[buy_venue],
        sell_fee=cost.fees[sell_venue],
        transfer=cost.transfers.get(base_asset),
        notional_usd=notional_usd,
        asset_price_usd=visible[buy_venue].mid,
    )
    verdict = _honest_verdict(waterfall.net_bps)
    print(f"  best pair   : buy {buy_venue} -> sell {sell_venue}")
    print(f"  gross_bps   : {waterfall.gross_bps:+.2f}")
    print(f"  net_bps     : {waterfall.net_bps:+.2f}")
    print(f"  verdict     : {verdict}")
    print(
        "  guarantee   : quotes with ts > decision_ms are invisible; "
        "post-t perturbations cannot change this decision."
    )


def build_app() -> Typer:
    """Construct and return the Typer application (lazy ``typer`` import).

    Wires up two commands:

    - ``scan``: scan one symbol across venues for a target notional, print the
      gross -> net waterfall and the verdict.
    - ``replay``: replay a saved snapshot under the no-lookahead guard and report
      whether the historical decision survives costs.

    Returns
    -------
    typer.Typer
        The configured CLI application.
    """
    import typer

    cli = typer.Typer(
        add_completion=False,
        no_args_is_help=True,
        help="Decompose crypto arb spreads into a fee-, depth-, and transfer-aware "
        "gross -> net waterfall. The net executable edge on liquid pairs collapses "
        "to ~0 after costs.",
    )
    cli.command()(scan)
    cli.command()(replay)
    return cli


def app() -> None:
    """Console-script entry point: build the Typer app and run it.

    Referenced by the ``cryptoarb`` console script (``cryptoarb.cli:app``). Built
    here rather than at module scope so importing this module never imports
    ``typer``.
    """
    build_app()()


if __name__ == "__main__":  # pragma: no cover
    app()
