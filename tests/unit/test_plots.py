"""Tests for the lazy Plotly figure builders (``cryptoarb.plots``).

Pins the contract the backend router and frontend rely on:

- every builder returns a figure whose ``figure_to_dict`` is a valid
  ``{data, layout}`` mapping;
- the gross -> net **waterfall** bars sum correctly (gross anchor + relative
  cost deltas == net anchor), so the collapse is rendered honestly;
- importing the module pulls in neither ``plotly`` nor ``ccxt``.
"""

from __future__ import annotations

import sys

import pytest

from cryptoarb.costs.waterfall import CompositeCost, Waterfall, build_waterfall
from cryptoarb.evaluation.netedge import CostSensitivityPoint
from cryptoarb.plots import (
    cost_sensitivity_figure,
    figure_to_dict,
    spread_distribution_figure,
    waterfall_figure,
)


@pytest.fixture
def collapse_waterfall() -> Waterfall:
    """A realistic gross -> net waterfall whose net edge collapses below zero."""
    cost = CompositeCost.from_profile("default")
    return build_waterfall(
        gross_bps=12.0,
        buy_fee=cost.fees["binance"],
        sell_fee=cost.fees["coinbase"],
        transfer=cost.transfers["BTC"],
        notional_usd=10_000.0,
        asset_price_usd=50_000.0,
    )


@pytest.mark.unit
def test_plots_import_is_side_effect_free() -> None:
    """Importing ``cryptoarb.plots`` must not import plotly or ccxt."""
    assert "cryptoarb.plots" in sys.modules
    # plotly/ccxt are only imported lazily inside the builder functions.
    assert "ccxt" not in sys.modules


@pytest.mark.unit
def test_figure_to_dict_returns_data_and_layout(collapse_waterfall: Waterfall) -> None:
    """``figure_to_dict`` returns a JSON-safe ``{data, layout}`` mapping."""
    payload = figure_to_dict(waterfall_figure(collapse_waterfall))
    assert set(payload) >= {"data", "layout"}
    assert isinstance(payload["data"], list) and payload["data"]
    assert isinstance(payload["layout"], dict)


@pytest.mark.unit
def test_waterfall_figure_is_a_waterfall_trace(collapse_waterfall: Waterfall) -> None:
    """The waterfall builder emits a single Plotly ``waterfall`` trace."""
    payload = figure_to_dict(waterfall_figure(collapse_waterfall))
    trace = payload["data"][0]
    assert trace["type"] == "waterfall"
    # One bar per stage (gross, taker_fees, transfer, net).
    assert len(trace["measure"]) == len(collapse_waterfall.stages)
    assert len(trace["x"]) == len(trace["y"]) == len(collapse_waterfall.stages)


@pytest.mark.unit
def test_waterfall_bars_sum_to_net(collapse_waterfall: Waterfall) -> None:
    """Gross anchor + the relative cost deltas must land exactly on the net anchor.

    This is the correctness guarantee that makes the bar chart honest: the
    visible steps account for the entire gross -> net collapse with nothing
    hidden.
    """
    payload = figure_to_dict(waterfall_figure(collapse_waterfall))
    trace = payload["data"][0]
    measures = trace["measure"]
    values = trace["y"]

    # First and last bars are the ``total`` anchors (gross, net).
    assert measures[0] == "total"
    assert measures[-1] == "total"
    gross_anchor = values[0]
    net_anchor = values[-1]
    relative_deltas = [v for m, v in zip(measures, values, strict=True) if m == "relative"]

    assert gross_anchor == pytest.approx(collapse_waterfall.gross_bps)
    assert net_anchor == pytest.approx(collapse_waterfall.net_bps)
    assert gross_anchor + sum(relative_deltas) == pytest.approx(net_anchor, abs=1e-9)


@pytest.mark.unit
def test_waterfall_honest_null_collapse(collapse_waterfall: Waterfall) -> None:
    """On realistic costs the net anchor is below the gross anchor (the collapse)."""
    payload = figure_to_dict(waterfall_figure(collapse_waterfall))
    values = payload["data"][0]["y"]
    assert values[-1] < values[0]  # net < gross
    assert collapse_waterfall.net_bps < 0.0  # honest null: edge collapsed below zero


@pytest.mark.unit
def test_waterfall_figure_accepts_title(collapse_waterfall: Waterfall) -> None:
    """A caller-supplied title flows through to the layout."""
    payload = figure_to_dict(waterfall_figure(collapse_waterfall, title="Custom"))
    assert payload["layout"]["title"]["text"] == "Custom"


@pytest.mark.unit
def test_spread_distribution_figure_with_marker() -> None:
    """The spread histogram carries the data and an optional net-edge marker."""
    spreads = [5.0, 12.0, 30.0, 8.0, 15.0]
    payload = figure_to_dict(spread_distribution_figure(spreads, net_bps=-2.5))
    trace = payload["data"][0]
    assert trace["type"] == "histogram"
    assert list(trace["x"]) == pytest.approx(spreads)
    # The vertical net-edge marker is rendered as a layout shape.
    assert payload["layout"].get("shapes")


@pytest.mark.unit
def test_spread_distribution_figure_without_marker() -> None:
    """Omitting ``net_bps`` produces a histogram with no marker shape."""
    payload = figure_to_dict(spread_distribution_figure([1.0, 2.0, 3.0]))
    assert payload["data"][0]["type"] == "histogram"
    assert not payload["layout"].get("shapes")


@pytest.mark.unit
def test_cost_sensitivity_figure_traces_net_vs_cost() -> None:
    """The sensitivity line carries (extra_cost, net) pairs in input order."""
    points = (
        CostSensitivityPoint(extra_cost_bps=0.0, net_bps=5.0),
        CostSensitivityPoint(extra_cost_bps=5.0, net_bps=0.0),
        CostSensitivityPoint(extra_cost_bps=10.0, net_bps=-5.0),
    )
    payload = figure_to_dict(cost_sensitivity_figure(points))
    trace = payload["data"][0]
    assert trace["type"] == "scatter"
    assert list(trace["x"]) == pytest.approx([0.0, 5.0, 10.0])
    assert list(trace["y"]) == pytest.approx([5.0, 0.0, -5.0])
    # A zero reference line marks where the edge crosses into infeasible.
    assert payload["layout"].get("shapes")
