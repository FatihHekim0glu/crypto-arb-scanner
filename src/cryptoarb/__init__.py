"""crypto-arb-scanner — a pure, typed crypto-arbitrage decomposition library.

Decompose cross-exchange and triangular crypto spreads into a fee-, depth-, and
transfer-cost-aware gross -> net waterfall. The honest headline is the COLLAPSE
of the executable edge after taker fees + order-book-depth slippage + transfer
cost — a diagnostic spread-decomposition tool, never a profit claim.

The package has ZERO import-time side effects and ZERO UI coupling: ``ccxt`` and
``plotly`` are imported lazily inside the functions that need them, so the same
pure functions back a local CLI demo and a hosted FastAPI tool unchanged.

Public API is curated below; see :data:`__all__`.
"""

from __future__ import annotations

from cryptoarb._constants import EPS, PERIODS_PER_YEAR, TRADING_DAYS
from cryptoarb._exceptions import (
    BookError,
    CryptoArbError,
    InsufficientDataError,
    LiquidityError,
    ValidationError,
)
from cryptoarb._manifest import RunManifest, config_hash
from cryptoarb._rng import make_rng, spawn_substreams
from cryptoarb._validation import (
    align_inner,
    ensure_dataframe,
    ensure_series,
    validate_min_obs,
)
from cryptoarb.arb.cross import CrossLeg, best_cross_leg, cross_gross_bps
from cryptoarb.arb.feasibility import ArbKind, ArbResult
from cryptoarb.arb.triangular import (
    TriangularCycle,
    no_arb_residual,
    triangular_cycle,
)
from cryptoarb.books.model import OrderBook, make_book
from cryptoarb.books.synthetic import (
    SyntheticConfig,
    VenueSpec,
    consistent_triangular_books,
    synthetic_book,
    synthetic_books,
)
from cryptoarb.books.vwap import Side, VWAPResult, vwap
from cryptoarb.costs.fees import (
    FeeSchedule,
    load_fee_schedules,
    round_trip_taker_bps,
)
from cryptoarb.costs.transfer import (
    TransferSchedule,
    load_transfer_schedules,
    transfer_cost_bps,
)
from cryptoarb.costs.waterfall import (
    CompositeCost,
    Waterfall,
    WaterfallStage,
    build_waterfall,
)
from cryptoarb.data.cache import BookCache
from cryptoarb.data.ccxt_source import (
    DataSource,
    DataSourcePref,
    FetchConfig,
    FetchResult,
    fetch_books,
)
from cryptoarb.evaluation.dsr import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)
from cryptoarb.evaluation.netedge import (
    CostSensitivityPoint,
    NetEdgeStats,
    cost_sensitivity_grid,
    effective_n_trials,
    net_edge_stats,
)
from cryptoarb.evaluation.verdict import Verdict, derive_verdict, is_within_noise
from cryptoarb.plots import (
    cost_sensitivity_figure,
    figure_to_dict,
    spread_distribution_figure,
    waterfall_figure,
)

__version__ = "0.1.0"

__all__ = [
    "EPS",
    "PERIODS_PER_YEAR",
    "TRADING_DAYS",
    "ArbKind",
    "ArbResult",
    "BookCache",
    "BookError",
    "CompositeCost",
    "CostSensitivityPoint",
    "CrossLeg",
    "CryptoArbError",
    "DataSource",
    "DataSourcePref",
    "FeeSchedule",
    "FetchConfig",
    "FetchResult",
    "InsufficientDataError",
    "LiquidityError",
    "NetEdgeStats",
    "OrderBook",
    "RunManifest",
    "Side",
    "SyntheticConfig",
    "TransferSchedule",
    "TriangularCycle",
    "VWAPResult",
    "ValidationError",
    "VenueSpec",
    "Verdict",
    "Waterfall",
    "WaterfallStage",
    "__version__",
    "align_inner",
    "best_cross_leg",
    "build_waterfall",
    "config_hash",
    "consistent_triangular_books",
    "cost_sensitivity_figure",
    "cost_sensitivity_grid",
    "cross_gross_bps",
    "deflated_sharpe_ratio",
    "derive_verdict",
    "effective_n_trials",
    "ensure_dataframe",
    "ensure_series",
    "fetch_books",
    "figure_to_dict",
    "is_within_noise",
    "load_fee_schedules",
    "load_transfer_schedules",
    "make_book",
    "make_rng",
    "net_edge_stats",
    "no_arb_residual",
    "probabilistic_sharpe_ratio",
    "round_trip_taker_bps",
    "spawn_substreams",
    "spread_distribution_figure",
    "synthetic_book",
    "synthetic_books",
    "transfer_cost_bps",
    "triangular_cycle",
    "validate_min_obs",
    "vwap",
    "waterfall_figure",
]
