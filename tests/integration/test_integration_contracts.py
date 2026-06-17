"""Integration-suite contracts (to be filled with end-to-end scans).

The integration suite will run the full offline pipeline: synthetic books ->
cross/triangular scan -> cost waterfall -> net-edge stats -> verdict, plus the
``fetch_books`` synthetic-fallback path (NEVER requiring live data). Until the
kernels land, these tests assert the end-to-end entry points exist and that the
data path's synthetic preference never touches the network at import.
"""

from __future__ import annotations

import pytest

from cryptoarb.data.ccxt_source import fetch_books


@pytest.mark.integration
def test_fetch_books_entry_point_exists() -> None:
    """The live+cache+synthetic data entry point is importable and callable."""
    assert callable(fetch_books)


@pytest.mark.integration
def test_pipeline_entry_points_exist() -> None:
    """Every stage the end-to-end scan chains together is importable."""
    from cryptoarb.arb.cross import best_cross_leg
    from cryptoarb.arb.triangular import triangular_cycle
    from cryptoarb.costs.waterfall import build_waterfall
    from cryptoarb.evaluation.netedge import net_edge_stats
    from cryptoarb.evaluation.verdict import derive_verdict

    for fn in (
        best_cross_leg,
        triangular_cycle,
        build_waterfall,
        net_edge_stats,
        derive_verdict,
    ):
        assert callable(fn)
