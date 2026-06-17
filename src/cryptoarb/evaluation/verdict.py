"""Pure-function verdict derivation.

The headline verdict is a PURE FUNCTION of the net-edge inference. It is
structurally unable to claim a feasible edge when the net bps are ``<= 0`` or
within statistical noise of zero — this is what keeps the README honest. The
truth table is unit-tested; the verdict is derived, never narrated.

Importing this module has no side effects.
"""

from __future__ import annotations

from enum import StrEnum


class Verdict(StrEnum):
    """Possible headline verdicts for an arbitrage net-edge inference.

    The values are stable string identifiers safe to serialize across the API
    boundary and render in the frontend.
    """

    #: Net edge is at or below zero, OR positive but statistically
    #: indistinguishable from zero — the expected, honest outcome on liquid pairs.
    NO_FEASIBLE_EDGE = "no_feasible_edge"

    #: Net edge is positive and clears the noise band but not the (higher)
    #: feasibility threshold — a borderline, do-not-trade-on-it signal.
    MARGINAL = "marginal"

    #: Net edge is positive AND clears the feasibility threshold AND its lower
    #: confidence bound is strictly above zero — a (rare) feasible edge.
    FEASIBLE_EDGE = "feasible_edge"


def derive_verdict(
    net_bps: float,
    *,
    ci_low_bps: float,
    ci_high_bps: float,
    noise_bps: float = 1.0,
    feasible_bps: float = 5.0,
) -> Verdict:
    r"""Derive the headline verdict from the net-edge inference (pure function).

    Decision rule (truth-table unit-tested):

    1. If ``net_bps <= noise_bps`` OR the confidence interval straddles zero
       (``ci_low_bps <= 0``), return :attr:`Verdict.NO_FEASIBLE_EDGE`. A feasible
       claim is structurally impossible whenever the net edge is non-positive or
       its lower bound includes zero.
    2. Otherwise, if ``net_bps >= feasible_bps`` AND ``ci_low_bps > 0``, return
       :attr:`Verdict.FEASIBLE_EDGE`.
    3. Otherwise (positive, above noise, below the feasibility threshold), return
       :attr:`Verdict.MARGINAL`.

    HONESTY REQUIREMENT: this function MUST NOT return
    :attr:`Verdict.FEASIBLE_EDGE` whenever ``net_bps <= 0`` or the CI includes
    zero, regardless of any point estimate.

    Parameters
    ----------
    net_bps:
        The net edge after the full cost waterfall, in basis points.
    ci_low_bps, ci_high_bps:
        Confidence-interval bounds on the net edge, in basis points.
    noise_bps:
        Half-width of the "within noise" band around zero (default ``1.0`` bp).
    feasible_bps:
        Minimum net edge required to call an edge feasible (default ``5.0`` bps).

    Returns
    -------
    Verdict
        The derived headline verdict.

    Raises
    ------
    ValidationError
        If ``ci_low_bps > ci_high_bps``, or ``noise_bps``/``feasible_bps`` are
        negative, or any input is non-finite.
    """
    raise NotImplementedError


def is_within_noise(net_bps: float, noise_bps: float = 1.0) -> bool:
    """Return whether ``net_bps`` is within ``+/- noise_bps`` of zero.

    Parameters
    ----------
    net_bps:
        The net edge in basis points.
    noise_bps:
        Half-width of the noise band; non-negative.

    Returns
    -------
    bool
        ``True`` if ``abs(net_bps) <= noise_bps``.

    Raises
    ------
    ValidationError
        If ``noise_bps`` is negative or ``net_bps`` is non-finite.
    """
    raise NotImplementedError
