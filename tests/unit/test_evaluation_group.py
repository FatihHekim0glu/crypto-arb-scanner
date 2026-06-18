"""Evaluation-group tests: net-edge stats, multiplicity guard, and the verdict.

This file owns the ``evaluation/netedge.py`` + ``evaluation/verdict.py`` kernels:

- the honest effective-trials count ``pair_legs * fee_grid_points`` and the guard
  that forbids an under-count of ``1`` when more than one configuration is scanned;
- the DSR/PSR parity (``net_edge_stats`` must reproduce a direct ``dsr.py`` call to
  1e-10);
- the verdict truth table, including the honest-null (a consistent / non-positive
  net edge can NEVER be called ``feasible_edge``).
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from cryptoarb._exceptions import InsufficientDataError, ValidationError
from cryptoarb.evaluation.dsr import deflated_sharpe_ratio, probabilistic_sharpe_ratio
from cryptoarb.evaluation.netedge import (
    CostSensitivityPoint,
    NetEdgeStats,
    cost_sensitivity_grid,
    effective_n_trials,
    net_edge_stats,
)
from cryptoarb.evaluation.verdict import Verdict, derive_verdict, is_within_noise

# --------------------------------------------------------------------------- #
# effective_n_trials  (multiplicity = pair-legs x fee-grid, NEVER 1)          #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_effective_n_trials_is_the_product() -> None:
    """The effective-trials count is exactly ``pair_legs * fee_grid_points``."""
    assert effective_n_trials(3, 7) == 21
    assert effective_n_trials(1, 1) == 1


@pytest.mark.unit
@pytest.mark.parametrize(("legs", "grid"), [(0, 5), (5, 0), (-1, 3), (3, -2)])
def test_effective_n_trials_rejects_sub_one_factors(legs: int, grid: int) -> None:
    """Each multiplicity factor must be ``>= 1``."""
    with pytest.raises(ValidationError):
        effective_n_trials(legs, grid)


# --------------------------------------------------------------------------- #
# net_edge_stats - DSR n_trials guard (>= pair-legs x fee-grid)               #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_net_edge_stats_uses_full_multiplicity_count() -> None:
    """``n_trials`` on the result equals the FULL ``pair_legs * fee_grid_points``."""
    series = np.array([2.0, -1.0, 0.5, -0.5, 1.5, -1.0], dtype=np.float64)
    stats = net_edge_stats(series, pair_legs=3, fee_grid_points=5, variance_of_trial_sharpes=0.2)
    assert isinstance(stats, NetEdgeStats)
    assert stats.n_trials == 15  # 3 x 5, never 1
    assert stats.n_obs == series.size


@pytest.mark.unit
def test_net_edge_stats_n_trials_at_least_pair_legs_times_grid() -> None:
    """The reported multiplicity never under-counts the scanned configuration grid."""
    series = np.array([1.0, -2.0, 0.5, 0.25], dtype=np.float64)
    pair_legs, fee_grid_points = 4, 9
    stats = net_edge_stats(
        series,
        pair_legs=pair_legs,
        fee_grid_points=fee_grid_points,
        variance_of_trial_sharpes=0.1,
    )
    assert stats.n_trials >= pair_legs * fee_grid_points
    assert stats.n_trials == pair_legs * fee_grid_points


@pytest.mark.unit
def test_net_edge_stats_rejects_tiny_series() -> None:
    """Fewer than two observations cannot support a Sharpe inference."""
    with pytest.raises(InsufficientDataError):
        net_edge_stats(
            np.array([1.0]), pair_legs=2, fee_grid_points=2, variance_of_trial_sharpes=0.1
        )


@pytest.mark.unit
def test_net_edge_stats_rejects_negative_trial_variance() -> None:
    """The DSR trial-variance must be non-negative."""
    with pytest.raises(ValidationError, match="variance_of_trial_sharpes"):
        net_edge_stats(
            np.array([1.0, 2.0, 3.0]),
            pair_legs=2,
            fee_grid_points=2,
            variance_of_trial_sharpes=-0.01,
        )


@pytest.mark.unit
def test_net_edge_stats_rejects_nan_series() -> None:
    """A NaN in the net-edge series is rejected at the boundary."""
    with pytest.raises(ValidationError):
        net_edge_stats(
            np.array([1.0, np.nan, 3.0]),
            pair_legs=2,
            fee_grid_points=2,
            variance_of_trial_sharpes=0.1,
        )


@pytest.mark.unit
def test_net_edge_stats_zero_dispersion_is_finite() -> None:
    """A constant series has zero Sharpe and well-defined PSR/DSR (no divide-by-zero)."""
    stats = net_edge_stats(
        np.full(8, -3.0), pair_legs=3, fee_grid_points=3, variance_of_trial_sharpes=0.2
    )
    assert stats.sharpe == 0.0
    assert stats.mean_bps == pytest.approx(-3.0)
    assert 0.0 <= stats.psr <= 1.0
    assert 0.0 <= stats.dsr <= 1.0


@pytest.mark.unit
def test_net_edge_stats_to_dict_is_serializable() -> None:
    """The stats ``to_dict`` is a plain JSON-friendly mapping."""
    stats = net_edge_stats(
        np.array([1.0, -1.0, 2.0, -2.0]),
        pair_legs=2,
        fee_grid_points=3,
        variance_of_trial_sharpes=0.15,
    )
    payload = stats.to_dict()
    assert set(payload) == {"mean_bps", "sharpe", "psr", "dsr", "n_obs", "n_trials"}
    assert payload["n_trials"] == 6


# --------------------------------------------------------------------------- #
# DSR / PSR parity to 1e-10 vs the reused dsr.py                              #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_net_edge_stats_dsr_parity_to_reused_oracle() -> None:
    """``net_edge_stats`` PSR/DSR reproduce a direct ``dsr.py`` call to 1e-10."""
    series = np.array([3.1, -2.4, 0.8, -1.9, 2.2, -0.7, 1.4, -3.0, 0.3, -1.1], dtype=np.float64)
    pair_legs, fee_grid_points, var = 3, 7, 0.27
    stats = net_edge_stats(
        series,
        pair_legs=pair_legs,
        fee_grid_points=fee_grid_points,
        variance_of_trial_sharpes=var,
    )

    # Reconstruct the inputs the kernel feeds the oracle.
    n_obs = series.size
    mean = float(series.mean())
    std = float(series.std(ddof=1))
    sharpe = 0.0 if std == 0.0 else mean / std
    import pandas as pd  # local: parity reference only

    ref = pd.Series(series)
    skew = float(ref.skew())
    kurt = float(ref.kurt()) + 3.0
    n_trials = pair_legs * fee_grid_points

    psr_ref = probabilistic_sharpe_ratio(
        sharpe, n_obs=n_obs, skew=skew, kurtosis=kurt, benchmark_sharpe=0.0
    )
    dsr_ref = deflated_sharpe_ratio(
        sharpe,
        n_obs=n_obs,
        n_trials=n_trials,
        variance_of_trial_sharpes=var,
        skew=skew,
        kurtosis=kurt,
    )

    assert stats.sharpe == pytest.approx(sharpe, abs=1e-10)
    assert stats.psr == pytest.approx(psr_ref, abs=1e-10)
    assert stats.dsr == pytest.approx(dsr_ref, abs=1e-10)


@pytest.mark.unit
def test_net_edge_stats_dsr_not_above_psr() -> None:
    """Deflating against multiplicity can only lower (or equal) the PSR."""
    series = np.array([2.0, -1.0, 1.5, -0.5, 2.5, -1.5, 0.5], dtype=np.float64)
    stats = net_edge_stats(series, pair_legs=5, fee_grid_points=5, variance_of_trial_sharpes=0.3)
    assert stats.dsr <= stats.psr + 1e-12


# --------------------------------------------------------------------------- #
# cost_sensitivity_grid                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_cost_sensitivity_grid_collapses_monotonically() -> None:
    """Net edge falls one-for-one with extra cost, in input order."""
    points = cost_sensitivity_grid(20.0, 12.0, [0.0, 2.0, 5.0, 10.0])
    assert all(isinstance(p, CostSensitivityPoint) for p in points)
    nets = [p.net_bps for p in points]
    # gross 20 - baseline 12 = 8, then minus each extra.
    assert nets == pytest.approx([8.0, 6.0, 3.0, -2.0])
    # Non-increasing as extra cost rises (adjacent pairs).
    assert all(b <= a for a, b in pairwise(nets))


@pytest.mark.unit
def test_cost_sensitivity_grid_accepts_numpy_grid() -> None:
    """A numpy grid is accepted and preserved in order."""
    points = cost_sensitivity_grid(10.0, 4.0, np.array([0.0, 3.0]))
    assert [p.extra_cost_bps for p in points] == [0.0, 3.0]
    assert points[0].to_dict() == {"extra_cost_bps": 0.0, "net_bps": 6.0}


@pytest.mark.unit
def test_cost_sensitivity_grid_rejects_negative_extra() -> None:
    """A negative extra-cost value is rejected."""
    with pytest.raises(ValidationError, match="non-negative"):
        cost_sensitivity_grid(10.0, 2.0, [1.0, -0.5])


# --------------------------------------------------------------------------- #
# verdict truth table  (incl. the honest-null)                                #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_verdict_honest_null_consistent_books() -> None:
    """A non-positive net edge is ALWAYS ``no_feasible_edge`` (the honest null)."""
    # Net at/below zero -> structurally cannot be feasible, regardless of CI.
    assert derive_verdict(0.0, ci_low_bps=-1.0, ci_high_bps=1.0) is Verdict.NO_FEASIBLE_EDGE
    assert derive_verdict(-4.0, ci_low_bps=-8.0, ci_high_bps=0.5) is Verdict.NO_FEASIBLE_EDGE
    # Big point estimate but CI straddles zero -> still no feasible edge.
    assert (
        derive_verdict(9.0, ci_low_bps=-2.0, ci_high_bps=20.0, feasible_bps=5.0)
        is Verdict.NO_FEASIBLE_EDGE
    )


@pytest.mark.unit
def test_verdict_within_noise_is_no_feasible_edge() -> None:
    """A small positive net edge inside the noise band is not feasible."""
    assert (
        derive_verdict(0.5, ci_low_bps=0.1, ci_high_bps=0.9, noise_bps=1.0)
        is Verdict.NO_FEASIBLE_EDGE
    )


@pytest.mark.unit
def test_verdict_marginal_band() -> None:
    """Positive, above noise, below the feasibility threshold, CI clear of zero."""
    assert (
        derive_verdict(3.0, ci_low_bps=0.5, ci_high_bps=6.0, noise_bps=1.0, feasible_bps=5.0)
        is Verdict.MARGINAL
    )


@pytest.mark.unit
def test_verdict_feasible_requires_clear_positive_interval() -> None:
    """Clears the feasibility threshold AND the lower CI bound is strictly above zero."""
    assert (
        derive_verdict(12.0, ci_low_bps=4.0, ci_high_bps=20.0, noise_bps=1.0, feasible_bps=5.0)
        is Verdict.FEASIBLE_EDGE
    )


@pytest.mark.unit
def test_verdict_cannot_be_feasible_with_zero_lower_bound() -> None:
    """At exactly ``ci_low_bps == 0`` the CI includes zero -> never feasible."""
    assert (
        derive_verdict(30.0, ci_low_bps=0.0, ci_high_bps=60.0, feasible_bps=5.0)
        is Verdict.NO_FEASIBLE_EDGE
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"net_bps": 1.0, "ci_low_bps": 2.0, "ci_high_bps": 1.0}, "ci_low_bps <= ci_high_bps"),
        ({"net_bps": 1.0, "ci_low_bps": 0.0, "ci_high_bps": 2.0, "noise_bps": -1.0}, "noise_bps"),
        (
            {"net_bps": 1.0, "ci_low_bps": 0.0, "ci_high_bps": 2.0, "feasible_bps": -1.0},
            "feasible_bps",
        ),
        ({"net_bps": float("nan"), "ci_low_bps": 0.0, "ci_high_bps": 2.0}, "finite"),
        ({"net_bps": 1.0, "ci_low_bps": float("inf"), "ci_high_bps": 2.0}, "finite"),
    ],
)
def test_verdict_validation_guards(kwargs: dict[str, float], match: str) -> None:
    """Out-of-domain / non-finite verdict inputs are rejected."""
    net = kwargs.pop("net_bps")
    with pytest.raises(ValidationError, match=match):
        derive_verdict(net, **kwargs)  # type: ignore[arg-type]


@pytest.mark.unit
def test_is_within_noise() -> None:
    """The noise-band helper is symmetric around zero."""
    assert is_within_noise(0.5, 1.0) is True
    assert is_within_noise(-1.0, 1.0) is True  # boundary inclusive
    assert is_within_noise(1.5, 1.0) is False


@pytest.mark.unit
def test_is_within_noise_rejects_bad_inputs() -> None:
    """A negative band or non-finite net edge is rejected."""
    with pytest.raises(ValidationError):
        is_within_noise(0.0, -1.0)
    with pytest.raises(ValidationError):
        is_within_noise(float("inf"), 1.0)
