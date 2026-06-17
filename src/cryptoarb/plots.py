"""Plotly figure builders for the gross -> net story.

Every builder imports ``plotly`` LAZILY inside the function and returns a
``plotly.graph_objects.Figure`` whose ``{data, layout}`` JSON crosses the API
boundary unchanged. Importing this module has no side effects and does not
require plotly to be installed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from plotly.graph_objects import Figure

    from cryptoarb.costs.waterfall import Waterfall
    from cryptoarb.evaluation.netedge import CostSensitivityPoint

# Shared palette so every figure tells the same gross -> net story.
_GROSS_COLOR = "#2563eb"  # blue: the headline raw spread
_COST_COLOR = "#dc2626"  # red: every cost that eats the edge
_NET_COLOR = "#16a34a"  # green when net survives, red when it collapses
_NET_NEGATIVE_COLOR = "#dc2626"
_MARKER_COLOR = "#dc2626"

# Human-readable names for the canonical waterfall stage labels.
_STAGE_DISPLAY: dict[str, str] = {
    "gross": "Gross spread",
    "taker_fees": "Taker fees",
    "slippage": "Slippage",
    "transfer": "Transfer",
    "net": "Net edge",
}


def _display_label(label: str) -> str:
    """Return a human-friendly axis label for a waterfall stage label."""
    return _STAGE_DISPLAY.get(label, label.replace("_", " ").title())


def waterfall_figure(waterfall: Waterfall, *, title: str | None = None) -> Figure:
    """Build the gross -> net waterfall bar chart.

    Renders the ordered cost stages as a Plotly ``waterfall`` trace: the
    ``gross`` anchor, each negative cost step, and the ``net`` anchor, so the
    collapse of the edge is visually obvious.

    The trace's ``measure``/``y`` arrays are constructed so the bars sum
    correctly: ``gross`` and ``net`` are ``"total"`` anchors carrying their
    running level, while each cost stage is a ``"relative"`` step carrying its
    signed delta. Walking the relative deltas from the gross anchor therefore
    lands exactly on the net anchor.

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
    import plotly.graph_objects as go

    labels: list[str] = []
    measures: list[str] = []
    values: list[float] = []
    text: list[str] = []
    for stage in waterfall.stages:
        labels.append(_display_label(stage.label))
        if stage.label in ("gross", "net"):
            # Anchor bars carry the absolute running level.
            measures.append("total")
            values.append(float(stage.running_bps))
            text.append(f"{stage.running_bps:+.2f} bps")
        else:
            # Cost bars carry the signed delta and accumulate relative to gross.
            measures.append("relative")
            values.append(float(stage.delta_bps))
            text.append(f"{stage.delta_bps:+.2f} bps")

    net_color = _NET_COLOR if waterfall.net_bps > 0.0 else _NET_NEGATIVE_COLOR
    trace = go.Waterfall(
        name="gross -> net",
        orientation="v",
        measure=measures,
        x=labels,
        y=values,
        text=text,
        textposition="outside",
        connector={"line": {"color": "#9ca3af", "width": 1}},
        increasing={"marker": {"color": _GROSS_COLOR}},
        decreasing={"marker": {"color": _COST_COLOR}},
        totals={"marker": {"color": net_color}},
    )

    resolved_title = (
        title
        if title is not None
        else f"Gross -> net edge collapse  (net {waterfall.net_bps:+.2f} bps)"
    )
    layout = go.Layout(
        title={"text": resolved_title},
        yaxis={"title": {"text": "Edge (bps)"}, "zeroline": True, "zerolinecolor": "#9ca3af"},
        xaxis={"title": {"text": "Cost stage"}},
        showlegend=False,
        template="plotly_white",
    )
    return go.Figure(data=[trace], layout=layout)


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
    import plotly.graph_objects as go

    spreads = [float(value) for value in spreads_bps]
    trace = go.Histogram(
        x=spreads,
        name="Gross spreads",
        marker={"color": _GROSS_COLOR},
        opacity=0.85,
    )

    layout = go.Layout(
        title={"text": title if title is not None else "Gross spread distribution (bps)"},
        xaxis={"title": {"text": "Gross spread (bps)"}},
        yaxis={"title": {"text": "Count"}},
        bargap=0.05,
        showlegend=False,
        template="plotly_white",
    )
    figure = go.Figure(data=[trace], layout=layout)

    if net_bps is not None:
        marker = float(net_bps)
        figure.add_vline(
            x=marker,
            line={"color": _MARKER_COLOR, "width": 2, "dash": "dash"},
            annotation={"text": f"net {marker:+.2f} bps"},
        )
    return figure


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
    import plotly.graph_objects as go

    xs = [float(point.extra_cost_bps) for point in points]
    ys = [float(point.net_bps) for point in points]
    trace = go.Scatter(
        x=xs,
        y=ys,
        mode="lines+markers",
        name="Net edge",
        line={"color": _GROSS_COLOR, "width": 2},
        marker={"color": _GROSS_COLOR},
    )

    layout = go.Layout(
        title={"text": title if title is not None else "Net edge vs. added cost (bps)"},
        xaxis={"title": {"text": "Extra cost (bps)"}},
        yaxis={"title": {"text": "Net edge (bps)"}, "zeroline": True, "zerolinecolor": "#9ca3af"},
        showlegend=False,
        template="plotly_white",
    )
    figure = go.Figure(data=[trace], layout=layout)
    # The zero line is where the edge collapses: mark it so the story is explicit.
    figure.add_hline(y=0.0, line={"color": _MARKER_COLOR, "width": 1, "dash": "dot"})
    return figure


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
    import plotly.io as pio

    payload: dict[str, Any] = json.loads(pio.to_json(figure, validate=False))
    return payload
