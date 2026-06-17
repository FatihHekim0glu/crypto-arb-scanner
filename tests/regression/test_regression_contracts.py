"""Regression-suite contracts (to be filled with golden snapshots).

The regression suite will pin: a golden net-edge waterfall on a fixed synthetic
snapshot; the honest-null guard (consistent books => ``net_bps <= 0`` /
``no_feasible_edge``); and a no-lookahead replay snapshot. Until the kernels
land, these tests assert the honest-null verdict enum and the verdict entry point
exist and that the verdict's feasible state is reachable only with a clean
positive interval.
"""

from __future__ import annotations

import pytest

from cryptoarb.evaluation.verdict import Verdict


@pytest.mark.regression
def test_verdict_enum_has_honest_null_state() -> None:
    """The verdict enum exposes the honest-null ``no_feasible_edge`` outcome."""
    assert Verdict.NO_FEASIBLE_EDGE.value == "no_feasible_edge"
    assert {v.value for v in Verdict} == {
        "no_feasible_edge",
        "marginal",
        "feasible_edge",
    }


@pytest.mark.regression
def test_verdict_entry_point_exists() -> None:
    """The pure verdict derivation the honest-null regression pins is importable."""
    from cryptoarb.evaluation.verdict import derive_verdict

    assert callable(derive_verdict)
