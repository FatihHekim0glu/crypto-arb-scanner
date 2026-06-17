"""Deterministic synthetic consistent-order-book generator.

This is the backbone of the offline test suite. Given a true mid, per-venue
spread/offset/depth parameters, and a seed, it emits internally consistent
per-venue L2 books. With **no cross-venue dislocation** every venue is centered
on the same true mid (up to its own half-spread), so the cross-exchange no-arb
condition holds and the net edge collapses — the honest-null fixture. A small
dislocation can be injected to produce an *apparently* exploitable gap that the
cost waterfall is expected to erase.

For triangular scans the generator builds three single-venue books
(``A/B``, ``B/C``, ``C/A``) whose mids multiply to ``1`` (the no-arb identity)
to within ``1e-12`` on the consistent fixture.

All randomness flows through :func:`cryptoarb._rng.make_rng`; the same arguments
always produce byte-identical books. Importing this module has no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryptoarb.books.model import OrderBook


@dataclass(frozen=True, slots=True)
class VenueSpec:
    """Per-venue order-book shape parameters.

    Attributes
    ----------
    venue:
        Venue identifier.
    half_spread_bps:
        Half the top-of-book spread, in basis points, applied symmetrically
        around the venue's mid.
    mid_offset_bps:
        Signed offset of this venue's mid from the global true mid, in basis
        points. Zero on every venue means no cross-venue dislocation.
    depth_base:
        Base-asset size available at the first level; deeper levels decay by
        ``depth_decay`` per level.
    n_levels:
        Number of price levels generated per side.
    depth_decay:
        Multiplicative size decay per level (``0 < depth_decay <= 1``).
    tick_bps:
        Price increment between consecutive levels, in basis points of the mid.
    """

    venue: str
    half_spread_bps: float = 2.0
    mid_offset_bps: float = 0.0
    depth_base: float = 5.0
    n_levels: int = 25
    depth_decay: float = 0.85
    tick_bps: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this spec."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SyntheticConfig:
    """Top-level configuration for a synthetic multi-venue snapshot.

    Attributes
    ----------
    symbol:
        Unified ``BASE/QUOTE`` symbol for the generated books.
    true_mid:
        The global "fair" mid price all venues are referenced to.
    venues:
        Per-venue shape specs.
    dislocation_bps:
        If non-zero, an extra signed mid offset (in bps) applied to the LAST
        venue in ``venues`` to manufacture an apparently exploitable gap. Zero
        produces the consistent (no-arb) fixture.
    size_noise:
        Relative multiplicative noise applied to level sizes (``0`` = none).
    ts_ms:
        Exchange timestamp stamped onto every generated book.
    """

    symbol: str = "BTC/USDT"
    true_mid: float = 50_000.0
    venues: tuple[VenueSpec, ...] = field(default_factory=tuple)
    dislocation_bps: float = 0.0
    size_noise: float = 0.0
    ts_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this config."""
        raise NotImplementedError


def synthetic_book(spec: VenueSpec, *, symbol: str, true_mid: float, seed: int) -> OrderBook:
    """Generate one venue's L2 book from a :class:`VenueSpec`.

    The venue mid is ``true_mid * (1 + mid_offset_bps / 1e4)``; the best bid/ask
    straddle it by ``half_spread_bps``; deeper levels step away by ``tick_bps``
    with sizes decaying by ``depth_decay``. Sizes are perturbed only if the
    caller's generator is seeded for noise.

    Parameters
    ----------
    spec:
        The venue shape parameters.
    symbol:
        Unified ``BASE/QUOTE`` symbol.
    true_mid:
        The global fair mid the venue is referenced to.
    seed:
        Master seed feeding :func:`cryptoarb._rng.make_rng`.

    Returns
    -------
    OrderBook
        A validated, frozen order book for the venue.

    Raises
    ------
    ValidationError
        If ``spec`` parameters are out of domain (non-positive depth, etc.).
    """
    raise NotImplementedError


def synthetic_books(config: SyntheticConfig, *, seed: int = 0) -> dict[str, OrderBook]:
    """Generate the full per-venue snapshot for a :class:`SyntheticConfig`.

    With ``config.dislocation_bps == 0`` the returned books share a common true
    mid (no cross-venue arb survives costs); a non-zero dislocation skews the
    last venue to manufacture an apparent gap.

    Parameters
    ----------
    config:
        The multi-venue snapshot configuration.
    seed:
        Master seed; each venue draws an independent substream.

    Returns
    -------
    dict[str, OrderBook]
        Mapping of venue identifier to its generated order book.

    Raises
    ------
    ValidationError
        If ``config`` has no venues or any spec is out of domain.
    """
    raise NotImplementedError


def consistent_triangular_books(
    *,
    venue: str = "binance",
    mid_ab: float = 50_000.0,
    mid_bc: float = 3_000.0,
    half_spread_bps: float = 2.0,
    seed: int = 0,
    dislocation_bps: float = 0.0,
) -> dict[str, OrderBook]:
    """Generate three single-venue books forming a triangular cycle ``A/B·B/C·C/A``.

    The third leg's mid is set to ``1 / (mid_ab * mid_bc)`` so the product of the
    three mids is exactly ``1`` — the no-arb identity that the parity suite
    checks to ``1e-12`` when ``dislocation_bps == 0``. A non-zero
    ``dislocation_bps`` perturbs the ``C/A`` mid to break the identity by a known
    amount.

    Parameters
    ----------
    venue:
        The single venue hosting all three legs.
    mid_ab, mid_bc:
        The mids of the ``A/B`` and ``B/C`` legs; the ``C/A`` mid is derived.
    half_spread_bps:
        Symmetric half-spread applied to each leg.
    seed:
        Master seed feeding the generator.
    dislocation_bps:
        Signed perturbation of the ``C/A`` mid, in bps (``0`` = consistent).

    Returns
    -------
    dict[str, OrderBook]
        Mapping of leg symbol (``"A/B"``, ``"B/C"``, ``"C/A"``) to its book.

    Raises
    ------
    ValidationError
        If any derived price is non-positive.
    """
    raise NotImplementedError
