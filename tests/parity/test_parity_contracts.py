"""Parity-suite contracts (to be filled with oracle comparisons).

The parity suite will pin: VWAP/L2 aggregation vs a hand-rolled reference to
1e-9; the triangular no-arb identity to 1e-12 on consistent books; and DSR/PSR
vs the reused ``dsr.py`` to 1e-10. Until the kernels land, these tests assert the
parity *targets* exist and the reused DSR oracle is already callable.
"""

from __future__ import annotations

import pytest

from cryptoarb.evaluation.dsr import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)


@pytest.mark.parity
def test_reused_psr_oracle_is_callable() -> None:
    """The reused PSR returns a probability in [0, 1] for a known input."""
    psr = probabilistic_sharpe_ratio(0.1, n_obs=100)
    assert 0.0 <= psr <= 1.0


@pytest.mark.parity
def test_reused_dsr_is_monotone_in_trials() -> None:
    """The reused DSR is non-increasing in the multiplicity count ``n_trials``."""
    common = {
        "n_obs": 250,
        "variance_of_trial_sharpes": 0.25,
    }
    dsr_few = deflated_sharpe_ratio(0.2, n_trials=2, **common)
    dsr_many = deflated_sharpe_ratio(0.2, n_trials=200, **common)
    assert dsr_many <= dsr_few


@pytest.mark.parity
def test_vwap_parity_target_exists() -> None:
    """The VWAP kernel the parity oracle will pin against is importable."""
    from cryptoarb.books.vwap import vwap

    assert callable(vwap)
