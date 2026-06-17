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


@pytest.mark.regression
def test_depth_gate_forces_honest_null_when_size_exceeds_depth(
    dislocated_books: dict,
) -> None:
    """A notional far larger than book depth is never reported as executable.

    ``dislocated_books`` carries a genuine positive gross spread, so at a small
    size it can read as marginal/feasible. But when the requested notional dwarfs
    the available depth, only a sliver is fillable and the headline net edge is
    not achievable at size — the depth gate must force ``no_feasible_edge``.
    """
    from cryptoarb import run_scan

    venues = list(dislocated_books.keys())
    huge_notional = 1_000_000_000.0
    result = run_scan("BTC/USDT", venues, huge_notional, books=dislocated_books)

    assert result.summary.fillable_notional < huge_notional
    assert result.summary.verdict == Verdict.NO_FEASIBLE_EDGE
