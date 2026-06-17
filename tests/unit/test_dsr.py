"""Unit tests for the reused DSR/PSR module.

``evaluation/dsr.py`` is concrete, implemented code (the Bailey-Lopez de Prado
Deflated/Probabilistic Sharpe ratios) reused from the HRP infra. These tests
exercise its validation guards and the tail branches of the inverse-normal
approximation so the honest-statistics layer carries real coverage.
"""

from __future__ import annotations

import pytest

from cryptoarb._exceptions import ValidationError
from cryptoarb.evaluation.dsr import (
    _norm_ppf,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)


@pytest.mark.unit
def test_psr_in_unit_interval() -> None:
    """The PSR is a probability in [0, 1]."""
    psr = probabilistic_sharpe_ratio(0.2, n_obs=120, skew=-0.3, kurtosis=4.0)
    assert 0.0 <= psr <= 1.0


@pytest.mark.unit
def test_psr_rejects_tiny_sample() -> None:
    """The PSR needs at least two observations."""
    with pytest.raises(ValidationError, match="n_obs >= 2"):
        probabilistic_sharpe_ratio(0.1, n_obs=1)


@pytest.mark.unit
def test_psr_rejects_nonpositive_variance_term() -> None:
    """A skew/kurtosis combination that drives the bracket non-positive is rejected."""
    with pytest.raises(ValidationError, match="non-positive variance"):
        probabilistic_sharpe_ratio(5.0, n_obs=50, skew=10.0, kurtosis=3.0)


@pytest.mark.unit
def test_dsr_single_trial_reduces_to_psr_vs_zero() -> None:
    """With one trial the DSR collapses to the plain PSR against zero."""
    dsr = deflated_sharpe_ratio(0.2, n_obs=200, n_trials=1, variance_of_trial_sharpes=0.3)
    psr = probabilistic_sharpe_ratio(0.2, n_obs=200, benchmark_sharpe=0.0)
    assert dsr == pytest.approx(psr, abs=1e-12)


@pytest.mark.unit
def test_dsr_validation_guards() -> None:
    """The DSR rejects too-few obs, sub-one trials, and negative trial variance."""
    with pytest.raises(ValidationError, match="n_obs >= 2"):
        deflated_sharpe_ratio(0.1, n_obs=1, n_trials=4, variance_of_trial_sharpes=0.1)
    with pytest.raises(ValidationError, match="n_trials >= 1"):
        deflated_sharpe_ratio(0.1, n_obs=50, n_trials=0, variance_of_trial_sharpes=0.1)
    with pytest.raises(ValidationError, match="variance_of_trial_sharpes >= 0"):
        deflated_sharpe_ratio(0.1, n_obs=50, n_trials=4, variance_of_trial_sharpes=-0.1)


@pytest.mark.unit
def test_norm_ppf_tails_and_domain() -> None:
    """The inverse-normal approximation covers both tails and rejects [0,1] bounds."""
    assert _norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)
    assert _norm_ppf(0.001) < -2.5  # lower tail branch
    assert _norm_ppf(0.999) > 2.5  # upper tail branch
    with pytest.raises(ValidationError, match=r"p in \(0, 1\)"):
        _norm_ppf(0.0)
