"""Property-suite contracts (to be filled with Hypothesis invariants).

The property suite will enforce: net edge <= gross edge (monotone); larger
notional Q => worse-or-equal VWAP; no-lookahead future-perturbation invariance
on replay; cross-exchange leg-labeling symmetry; and spread scale-invariance in
the quote currency. Until the kernels land, these tests assert the invariant
*targets* exist and the already-pure DSR monotonicity holds under Hypothesis.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cryptoarb.evaluation.dsr import deflated_sharpe_ratio


@pytest.mark.property
@given(
    n_trials_a=st.integers(min_value=1, max_value=50),
    n_trials_b=st.integers(min_value=1, max_value=50),
)
def test_dsr_monotone_non_increasing_in_trials(n_trials_a: int, n_trials_b: int) -> None:
    """More trials never increases the deflated Sharpe (selection-bias guard)."""
    lo, hi = sorted((n_trials_a, n_trials_b))
    dsr_lo = deflated_sharpe_ratio(
        0.15, n_obs=250, n_trials=lo, variance_of_trial_sharpes=0.2
    )
    dsr_hi = deflated_sharpe_ratio(
        0.15, n_obs=250, n_trials=hi, variance_of_trial_sharpes=0.2
    )
    assert dsr_hi <= dsr_lo + 1e-12


@pytest.mark.property
def test_monotonicity_targets_exist() -> None:
    """The kernels the net<=gross and Q-monotonicity properties pin are importable."""
    from cryptoarb.books.vwap import vwap
    from cryptoarb.costs.waterfall import build_waterfall

    assert callable(vwap)
    assert callable(build_waterfall)
