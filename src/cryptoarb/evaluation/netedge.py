"""Per-pair net-edge series, effective-trials accounting, and cost sensitivity.

This module turns a sequence of scanned opportunities into a net-edge series and
applies the Deflated/Probabilistic Sharpe machinery (reused from
:mod:`cryptoarb.evaluation.dsr`) with an HONEST effective-trials count:
``n_trials = pair_legs * fee_grid_points``, NEVER ``1``. A guard asserts this so
nobody can quietly under-count the multiplicity and inflate the DSR. It also
sweeps a cost-sensitivity bps grid so the frontend can show how fast the net
edge collapses as costs rise.

Importing this module has no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cryptoarb._exceptions import InsufficientDataError, ValidationError
from cryptoarb._validation import ensure_series
from cryptoarb.evaluation.dsr import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np

    from cryptoarb._typing import NetEdgeLike


@dataclass(frozen=True, slots=True)
class NetEdgeStats:
    """DSR/PSR summary of a net-edge series under honest multiplicity.

    Attributes
    ----------
    mean_bps:
        Mean net edge across the series, in basis points.
    sharpe:
        Per-observation (non-annualized) Sharpe of the net-edge series.
    psr:
        Probabilistic Sharpe ratio against a zero benchmark.
    dsr:
        Deflated Sharpe ratio against the multiplicity-inflated benchmark, using
        ``n_trials = pair_legs * fee_grid_points``.
    n_obs:
        Number of net-edge observations.
    n_trials:
        The FULL effective-trials count (``pair_legs * fee_grid_points``).
    """

    mean_bps: float
    sharpe: float
    psr: float
    dsr: float
    n_obs: int
    n_trials: int

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of these stats."""
        return {
            "mean_bps": self.mean_bps,
            "sharpe": self.sharpe,
            "psr": self.psr,
            "dsr": self.dsr,
            "n_obs": self.n_obs,
            "n_trials": self.n_trials,
        }


@dataclass(frozen=True, slots=True)
class CostSensitivityPoint:
    """One point on the cost-sensitivity sweep.

    Attributes
    ----------
    extra_cost_bps:
        The additional cost (bps) added on top of the baseline waterfall.
    net_bps:
        The resulting mean net edge after the extra cost, in basis points.
    """

    extra_cost_bps: float
    net_bps: float

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this point."""
        return {
            "extra_cost_bps": self.extra_cost_bps,
            "net_bps": self.net_bps,
        }


def effective_n_trials(pair_legs: int, fee_grid_points: int) -> int:
    """Return the honest effective-trials count ``pair_legs * fee_grid_points``.

    The DSR multiplicity count must reflect EVERY configuration scanned: each
    venue-pair leg times each fee/cost-sensitivity grid point. A degenerate
    count of ``1`` would defeat the deflation entirely, so both factors must be
    ``>= 1``.

    Parameters
    ----------
    pair_legs:
        The number of venue-pair legs scanned; ``>= 1``.
    fee_grid_points:
        The number of fee/cost-sensitivity grid points; ``>= 1``.

    Returns
    -------
    int
        The product ``pair_legs * fee_grid_points``.

    Raises
    ------
    ValidationError
        If either factor is less than ``1``.
    """
    legs = int(pair_legs)
    grid = int(fee_grid_points)
    if legs < 1:
        raise ValidationError(f"effective_n_trials requires pair_legs >= 1, got {legs}.")
    if grid < 1:
        raise ValidationError(f"effective_n_trials requires fee_grid_points >= 1, got {grid}.")
    return legs * grid


def net_edge_stats(
    net_edge_bps: NetEdgeLike,
    *,
    pair_legs: int,
    fee_grid_points: int,
    variance_of_trial_sharpes: float,
) -> NetEdgeStats:
    """Compute DSR/PSR for a net-edge series under honest multiplicity.

    Coerces ``net_edge_bps`` to a 1-D float series, computes its per-observation
    Sharpe, and feeds the reused PSR/DSR functions with
    ``n_trials = effective_n_trials(pair_legs, fee_grid_points)``. A guard
    asserts ``n_trials > 1`` whenever more than one configuration was scanned.

    Parameters
    ----------
    net_edge_bps:
        The per-decision net edge series, in basis points.
    pair_legs:
        The number of venue-pair legs scanned (multiplicity factor).
    fee_grid_points:
        The number of fee/cost grid points scanned (multiplicity factor).
    variance_of_trial_sharpes:
        Cross-trial variance of per-observation Sharpe ratios, for the DSR
        benchmark; non-negative.

    Returns
    -------
    NetEdgeStats
        The net-edge summary including PSR and DSR.

    Raises
    ------
    ValidationError
        If the series is empty, the multiplicity factors are out of domain, or
        ``variance_of_trial_sharpes`` is negative.
    InsufficientDataError
        If fewer than two net-edge observations are supplied.
    """
    if variance_of_trial_sharpes < 0.0:
        raise ValidationError(
            "net_edge_stats requires variance_of_trial_sharpes >= 0, "
            f"got {variance_of_trial_sharpes}."
        )

    # Coerce to a clean, finite 1-D float series (raises ValidationError on
    # empty / NaN). Multiplicity accounting is validated up front.
    series = ensure_series(net_edge_bps, name="net_edge_bps")
    n_trials = effective_n_trials(pair_legs, fee_grid_points)

    n_obs = int(series.shape[0])
    if n_obs < 2:
        raise InsufficientDataError(
            f"net_edge_stats requires at least two net-edge observations, got {n_obs}."
        )

    # HONEST-MULTIPLICITY GUARD: whenever more than one configuration was
    # scanned the effective-trials count MUST exceed one, so the DSR deflation
    # cannot be silently defeated by an under-count of 1. This is a defensive
    # belt-and-suspenders check: ``effective_n_trials`` already forbids any
    # factor < 1, so a multiplicity > 1 implies ``n_trials >= 2`` and this raise
    # is unreachable in normal operation.
    if (pair_legs > 1 or fee_grid_points > 1) and n_trials <= 1:  # pragma: no cover
        raise ValidationError(
            "net_edge_stats: effective n_trials must exceed 1 when more than one "
            f"configuration is scanned (pair_legs={pair_legs}, "
            f"fee_grid_points={fee_grid_points}, n_trials={n_trials})."
        )

    mean_bps = float(series.mean())
    # Per-observation (non-annualized) Sharpe = mean / sample-std (ddof=1). A
    # zero-dispersion series carries no statistical edge signal, so its Sharpe is
    # defined as 0 (the PSR/DSR then evaluate against the zero/benchmark cleanly).
    std = float(series.std(ddof=1))
    sharpe = 0.0 if std == 0.0 else mean_bps / std

    # Curated pandas suppression: pandas-stubs types Series.skew/kurt with a broad
    # scalar union; the float64 Series we coerced always returns a real scalar.
    skew = float(series.skew()) if n_obs >= 3 else 0.0  # type: ignore[arg-type]
    # pandas ``kurt`` returns EXCESS kurtosis; the PSR/DSR want FULL kurtosis.
    excess_kurt = float(series.kurt()) if n_obs >= 4 else 0.0  # type: ignore[arg-type]
    kurtosis = excess_kurt + 3.0

    psr = probabilistic_sharpe_ratio(
        sharpe, n_obs=n_obs, skew=skew, kurtosis=kurtosis, benchmark_sharpe=0.0
    )
    dsr = deflated_sharpe_ratio(
        sharpe,
        n_obs=n_obs,
        n_trials=n_trials,
        variance_of_trial_sharpes=variance_of_trial_sharpes,
        skew=skew,
        kurtosis=kurtosis,
    )

    return NetEdgeStats(
        mean_bps=mean_bps,
        sharpe=sharpe,
        psr=psr,
        dsr=dsr,
        n_obs=n_obs,
        n_trials=n_trials,
    )


def cost_sensitivity_grid(
    gross_bps: float,
    baseline_cost_bps: float,
    extra_cost_grid: Sequence[float] | np.ndarray,
) -> tuple[CostSensitivityPoint, ...]:
    """Sweep extra cost (bps) and report how fast the net edge collapses.

    For each ``extra`` in ``extra_cost_grid`` the net edge is
    ``gross_bps - baseline_cost_bps - extra``. The sweep is the data behind the
    "net edge collapses after fees + depth + transfer" caption.

    Parameters
    ----------
    gross_bps:
        The executable gross spread in basis points.
    baseline_cost_bps:
        The baseline waterfall cost (fees + transfer) in basis points.
    extra_cost_grid:
        The grid of additional costs to apply, in basis points (non-negative).

    Returns
    -------
    tuple[CostSensitivityPoint, ...]
        One point per grid value, in input order.

    Raises
    ------
    ValidationError
        If the grid contains a negative value.
    """
    gross = float(gross_bps)
    baseline = float(baseline_cost_bps)
    points: list[CostSensitivityPoint] = []
    for raw_extra in extra_cost_grid:
        extra = float(raw_extra)
        if extra < 0.0:
            raise ValidationError(
                f"cost_sensitivity_grid: extra cost must be non-negative, got {extra}."
            )
        net = gross - baseline - extra
        points.append(CostSensitivityPoint(extra_cost_bps=extra, net_bps=net))
    return tuple(points)
