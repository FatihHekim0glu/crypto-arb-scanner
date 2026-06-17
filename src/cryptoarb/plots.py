"""Plotly figure builders for the gross -> net story.

Every builder imports ``plotly`` LAZILY inside the function and returns a
``plotly.graph_objects.Figure`` whose ``{data, layout}`` JSON crosses the API
boundary unchanged. Importing this module has no side effects and does not
require plotly to be installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from plotly.graph_objects import Figure

    from cryptoarb.costs.waterfall import Waterfall
    from cryptoarb.evaluation.netedge import CostSensitivityPoint


def waterfall_figure(waterfall: Waterfall, *, title: str | None = None) -> Figure:
    """Build the gross -> net waterfall bar chart.

    Renders the ordered cost stages as a Plotly ``waterfall`` trace: the
    ``gross`` anchor, each negative cost step, and the ``net`` anchor, so the
    collapse of the edge is visually obvious.

    Parameters
    ----------
    waterfall:
        The decomposition to plot (from :func:`cryptoarb.costs.waterfall.build_waterfall`).
    title:
        Optional figure title; a sensible default is used when omitted.

    Returns
    -------
    plotly.graph_objects.Figure
        The waterfall figure.
    """
    raise NotImplementedError


def spread_distribution_figure(
    spreads_bps: Sequence[float],
    *,
    net_bps: float | None = None,
    title: str | None = None,
) -> Figure:
    """Build a histogram of scanned gross spreads with an optional net-edge marker.

    The distribution shows where the raw spreads sit (often 5-40 bps) while a
    vertical marker at ``net_bps`` shows how far the *executable* edge has
    collapsed once costs are removed.

    Parameters
    ----------
    spreads_bps:
        The scanned gross spreads, in basis points.
    net_bps:
        Optional net edge to mark with a vertical line.
    title:
        Optional figure title.

    Returns
    -------
    plotly.graph_objects.Figure
        The spread-distribution figure.
    """
    raise NotImplementedError


def cost_sensitivity_figure(
    points: Sequence[CostSensitivityPoint], *, title: str | None = None
) -> Figure:
    """Build a line chart of net edge versus added cost (bps).

    Shows the net edge crossing zero as extra cost rises — the quantitative
    backbone of the "not executable via REST" caption.

    Parameters
    ----------
    points:
        The cost-sensitivity sweep (from
        :func:`cryptoarb.evaluation.netedge.cost_sensitivity_grid`).
    title:
        Optional figure title.

    Returns
    -------
    plotly.graph_objects.Figure
        The cost-sensitivity figure.
    """
    raise NotImplementedError


def figure_to_dict(figure: Figure) -> dict[str, Any]:
    """Return a figure as a ``{data, layout}`` dict for the API boundary.

    Serializes via ``plotly.io.to_json(fig, validate=False)`` and parses the
    result, matching the backend router's figure-encoding convention.

    Parameters
    ----------
    figure:
        The Plotly figure to serialize.

    Returns
    -------
    dict[str, Any]
        The JSON-safe ``{data, layout}`` mapping.
    """
    raise NotImplementedError
