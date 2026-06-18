"""Parity + property tests for the ``arb/`` group (cross + triangular).

Pins the three contracts the brief assigns to this group:

- the triangular no-arb identity holds to ``1e-12`` on the consistent
  (no-dislocation) synthetic triangular books;
- cross-exchange leg-labeling symmetry: at a shared mid the two role orderings
  have equal-magnitude gross, and under a real dislocation swapping the roles
  flips the sign of the spread (the labeling is meaningful, not cosmetic);
- on the dislocated cross-exchange books a *positive* gross spread genuinely
  appears, so the downstream honest-null collapse is proven on a real fixture
  rather than a degenerate one.

All inputs are deterministic; no network or live data is touched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cryptoarb.arb.cross import _cross_leg, best_cross_leg, cross_gross_bps
from cryptoarb.arb.feasibility import ArbKind, assemble_arb_result
from cryptoarb.arb.triangular import no_arb_residual, triangular_cycle
from cryptoarb.books.synthetic import consistent_triangular_books
from cryptoarb.costs.fees import FeeSchedule
from cryptoarb.costs.transfer import TransferSchedule

if TYPE_CHECKING:
    from cryptoarb.books.model import OrderBook

_NOTIONAL = 10_000.0


# --------------------------------------------------------------------------- #
# Triangular no-arb identity (parity, 1e-12 on consistent books)
# --------------------------------------------------------------------------- #
@pytest.mark.parity
def test_triangular_no_arb_identity_holds_on_consistent_books() -> None:
    """The mid-rate cycle product is ``1`` to ``1e-12`` with no dislocation."""
    books = consistent_triangular_books(dislocation_bps=0.0, seed=7)
    residual = no_arb_residual(books)
    assert abs(residual) <= 1e-12


@pytest.mark.parity
@pytest.mark.parametrize("dislocation_bps", [5.0, -5.0, 25.0])
def test_triangular_residual_tracks_injected_dislocation(dislocation_bps: float) -> None:
    """A known C/A dislocation appears in the residual with the right sign/size.

    The generator perturbs the closing leg's mid by ``dislocation_bps``, so the
    product moves to ``1 * (1 + dislocation_bps / 1e4)`` and the residual is
    ``dislocation_bps / 1e4`` to machine precision.
    """
    books = consistent_triangular_books(dislocation_bps=dislocation_bps, seed=1)
    residual = no_arb_residual(books)
    assert residual == pytest.approx(dislocation_bps / 1e4, abs=1e-12)


@pytest.mark.parity
def test_triangular_cycle_gross_is_negative_on_consistent_books() -> None:
    """Walking the consistent cycle yields a negative gross (every leg pays spread)."""
    books = consistent_triangular_books(dislocation_bps=0.0, seed=3)
    cycle = triangular_cycle(books, _NOTIONAL)
    # No free lunch: the executable cycle return is strictly below 1.0.
    assert cycle.rate_product < 1.0
    assert cycle.gross_bps < 0.0
    assert cycle.legs == ("A/B", "B/C", "C/A")
    assert cycle.fillable_notional > 0.0


@pytest.mark.parity
def test_no_arb_residual_rejects_wrong_leg_count(
    consistent_books: dict[str, OrderBook],
) -> None:
    """A non-three-leg mapping is a ``ValidationError`` (it is not a cycle)."""
    from cryptoarb._exceptions import ValidationError

    two_legs = dict(list(consistent_books.items())[:2])
    with pytest.raises(ValidationError):
        no_arb_residual(two_legs)


# --------------------------------------------------------------------------- #
# Cross-exchange leg-labeling symmetry (property)
# --------------------------------------------------------------------------- #
@pytest.mark.property
def test_cross_leg_labeling_symmetry_same_mid(
    consistent_books: dict[str, OrderBook],
) -> None:
    """At a SHARED mid, the two role orderings have EQUAL-MAGNITUDE gross.

    With both venues straddling the same true mid, you cross the spread in either
    direction, so both ``cross_gross_bps`` orderings are (equally) negative - the
    pair has no rich side. The labeling is symmetric: ``|forward| ~= |reverse|``
    to well under a basis point, and neither orientation manufactures a gross
    edge out of the honest null.
    """
    binance = consistent_books["binance"]
    kraken = consistent_books["kraken"]
    forward = cross_gross_bps(binance, kraken, _NOTIONAL)
    reverse = cross_gross_bps(kraken, binance, _NOTIONAL)
    assert forward < 0.0
    assert reverse < 0.0
    assert abs(forward) == pytest.approx(abs(reverse), abs=0.05)


@pytest.mark.property
def test_cross_leg_labeling_flips_sign_under_dislocation(
    dislocated_books: dict[str, OrderBook],
) -> None:
    """Swapping buy/sell roles flips the SIGN of a dislocated gross spread.

    With kraken skewed rich, buying binance / selling kraken is the profitable
    orientation (positive gross); reversing the roles is the loss side (negative
    gross). The exact magnitudes are not negatives of each other (the spread and
    dislocation interact), but the sign must flip - the labeling is meaningful.
    """
    binance = dislocated_books["binance"]
    kraken = dislocated_books["kraken"]
    forward = cross_gross_bps(binance, kraken, _NOTIONAL)
    reverse = cross_gross_bps(kraken, binance, _NOTIONAL)
    assert forward > 0.0
    assert reverse < 0.0


@pytest.mark.property
def test_best_cross_leg_picks_the_positive_direction(
    dislocated_books: dict[str, OrderBook],
) -> None:
    """The best leg is the buy-cheap/sell-rich orientation with positive gross."""
    leg = best_cross_leg(dislocated_books, _NOTIONAL)
    assert leg.gross_bps > 0.0
    assert leg.buy_venue != leg.sell_venue
    # The reverse of the chosen pair must be no better (it is the loss side).
    reverse = cross_gross_bps(
        dislocated_books[leg.sell_venue],
        dislocated_books[leg.buy_venue],
        _NOTIONAL,
    )
    assert reverse <= leg.gross_bps


@pytest.mark.property
def test_cross_leg_consistent_helper_matches_public_api(
    consistent_books: dict[str, OrderBook],
) -> None:
    """``cross_gross_bps`` equals the gross on the ``_cross_leg`` it delegates to."""
    binance = consistent_books["binance"]
    kraken = consistent_books["kraken"]
    leg = _cross_leg(binance, kraken, _NOTIONAL)
    assert cross_gross_bps(binance, kraken, _NOTIONAL) == pytest.approx(leg.gross_bps, abs=1e-12)
    assert leg.buy_venue == "binance"
    assert leg.sell_venue == "kraken"


# --------------------------------------------------------------------------- #
# Dislocated fixture is REAL: a positive gross genuinely appears (regression)
# --------------------------------------------------------------------------- #
@pytest.mark.regression
def test_dislocated_books_show_positive_gross(
    dislocated_books: dict[str, OrderBook],
) -> None:
    """The dislocated fixture exposes a real, exploitable-looking gross spread.

    Without this guarantee the downstream "net collapses to <= 0" headline would
    be vacuously true on a fixture that never had a gross edge to erase.
    """
    leg = best_cross_leg(dislocated_books, _NOTIONAL)
    # ~8 bps dislocation, minus two half-spreads of depth, still clears a couple bps.
    assert leg.gross_bps > 1.0
    assert leg.fillable_notional > 0.0


@pytest.mark.regression
def test_consistent_books_show_non_positive_gross(
    consistent_books: dict[str, OrderBook],
) -> None:
    """The honest-null fixture has NO surviving cross-exchange gross edge.

    All venues straddle the same true mid, so the richest buy-cheap/sell-rich
    orientation is at best break-even (and generally negative) before any costs.
    """
    leg = best_cross_leg(consistent_books, _NOTIONAL)
    assert leg.gross_bps <= 0.0


# --------------------------------------------------------------------------- #
# Feasibility assembly: net <= gross, honest-null floor on consistent books
# --------------------------------------------------------------------------- #
def _fee(venue: str) -> FeeSchedule:
    return FeeSchedule(venue=venue, maker=0.0010, taker=0.0010)


def _transfer() -> TransferSchedule:
    return TransferSchedule(
        asset="BTC",
        withdrawal_flat=0.0002,
        network_minutes=30.0,
        latency_bps_per_min=0.1,
    )


@pytest.mark.regression
def test_assemble_arb_result_net_le_gross_and_honest_null(
    dislocated_books: dict[str, OrderBook],
) -> None:
    """The assembled result collapses a positive gross to a non-feasible net.

    On the dislocated fixture a real ~bps gross exists, but round-trip taker fees
    (20 bps) plus transfer cost dwarf it, so ``net_bps`` lands <= 0 and the
    structural ``feasible`` floor is ``False``.
    """
    leg = best_cross_leg(dislocated_books, _NOTIONAL)
    result = assemble_arb_result(
        kind=ArbKind.CROSS_EXCHANGE,
        symbol="BTC/USDT",
        legs=(f"buy@{leg.buy_venue}", f"sell@{leg.sell_venue}"),
        notional_usd=_NOTIONAL,
        gross_bps=leg.gross_bps,
        executable_bps=leg.gross_bps,
        fillable_notional=leg.fillable_notional,
        buy_fee=_fee(leg.buy_venue),
        sell_fee=_fee(leg.sell_venue),
        transfer=_transfer(),
        asset_price_usd=50_000.0,
    )
    assert result.net_bps <= result.gross_bps
    assert result.net_bps <= 0.0
    assert result.feasible is False
    assert result.dominant_cost_leg in {"taker_fees", "transfer"}
    # Round-trips through a plain dict for the API boundary.
    payload = result.to_dict()
    assert payload["kind"] == "cross_exchange"
    assert payload["feasible"] is False


@pytest.mark.regression
def test_assemble_arb_result_triangular_no_transfer() -> None:
    """A single-venue triangular cycle assembles with ``transfer=None``."""
    books = consistent_triangular_books(dislocation_bps=0.0, seed=5)
    cycle = triangular_cycle(books, _NOTIONAL)
    result = assemble_arb_result(
        kind=ArbKind.TRIANGULAR,
        symbol="A/B*B/C*C/A",
        legs=cycle.legs,
        notional_usd=_NOTIONAL,
        gross_bps=cycle.gross_bps,
        executable_bps=cycle.gross_bps,
        fillable_notional=cycle.fillable_notional,
        buy_fee=_fee(cycle.venue),
        sell_fee=_fee(cycle.venue),
        transfer=None,
        asset_price_usd=50_000.0,
    )
    assert result.kind is ArbKind.TRIANGULAR
    assert result.net_bps <= result.gross_bps
    assert result.dominant_cost_leg == "taker_fees"
    assert result.feasible is False


# --------------------------------------------------------------------------- #
# Input-validation branches + serialization (unit-level guards)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
@pytest.mark.parametrize("bad_q", [0.0, -1.0])
def test_cross_rejects_non_positive_notional(
    consistent_books: dict[str, OrderBook], bad_q: float
) -> None:
    """Both cross entry points reject a non-positive target notional."""
    from cryptoarb._exceptions import ValidationError

    binance = consistent_books["binance"]
    kraken = consistent_books["kraken"]
    with pytest.raises(ValidationError):
        best_cross_leg(consistent_books, bad_q)
    with pytest.raises(ValidationError):
        cross_gross_bps(binance, kraken, bad_q)


@pytest.mark.unit
def test_best_cross_leg_requires_two_venues(
    consistent_books: dict[str, OrderBook],
) -> None:
    """A single-venue mapping cannot form a cross-exchange pair."""
    from cryptoarb._exceptions import ValidationError

    one = dict(list(consistent_books.items())[:1])
    with pytest.raises(ValidationError):
        best_cross_leg(one, _NOTIONAL)


@pytest.mark.unit
@pytest.mark.parametrize("bad_q", [0.0, -100.0])
def test_triangular_cycle_rejects_non_positive_notional(bad_q: float) -> None:
    """``triangular_cycle`` rejects a non-positive target notional."""
    from cryptoarb._exceptions import ValidationError

    books = consistent_triangular_books(seed=2)
    with pytest.raises(ValidationError):
        triangular_cycle(books, bad_q)


@pytest.mark.unit
def test_triangular_cycle_rejects_wrong_leg_count(
    consistent_books: dict[str, OrderBook],
) -> None:
    """A non-three-leg mapping is not a closeable cycle."""
    from cryptoarb._exceptions import ValidationError

    two_legs = dict(list(consistent_books.items())[:2])
    with pytest.raises(ValidationError):
        triangular_cycle(two_legs, _NOTIONAL)


@pytest.mark.unit
def test_cross_leg_to_dict_is_json_plain(
    consistent_books: dict[str, OrderBook],
) -> None:
    """``CrossLeg.to_dict`` yields only plain, JSON-serializable scalars."""
    import json

    leg = best_cross_leg(consistent_books, _NOTIONAL)
    payload = leg.to_dict()
    assert set(payload) == {
        "buy_venue",
        "sell_venue",
        "buy_vwap",
        "sell_vwap",
        "fillable_notional",
        "gross_bps",
    }
    # Survives a JSON round-trip unchanged (API-boundary safety).
    assert json.loads(json.dumps(payload)) == payload


@pytest.mark.unit
def test_triangular_cycle_to_dict_is_json_plain() -> None:
    """``TriangularCycle.to_dict`` yields only plain, JSON-serializable scalars."""
    import json

    books = consistent_triangular_books(seed=4)
    cycle = triangular_cycle(books, _NOTIONAL)
    payload = cycle.to_dict()
    assert payload["legs"] == ["A/B", "B/C", "C/A"]
    assert json.loads(json.dumps(payload)) == payload


@pytest.mark.unit
def test_assemble_arb_result_propagates_validation_error() -> None:
    """A non-positive notional/price surfaces as a ``ValidationError`` from the waterfall."""
    from cryptoarb._exceptions import ValidationError

    with pytest.raises(ValidationError):
        assemble_arb_result(
            kind=ArbKind.CROSS_EXCHANGE,
            symbol="BTC/USDT",
            legs=("buy@a", "sell@b"),
            notional_usd=-1.0,
            gross_bps=5.0,
            executable_bps=4.0,
            fillable_notional=100.0,
            buy_fee=_fee("a"),
            sell_fee=_fee("b"),
            transfer=None,
            asset_price_usd=50_000.0,
        )
