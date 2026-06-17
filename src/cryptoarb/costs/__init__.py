"""Fee, transfer, and gross -> net waterfall cost modelling.

Importing this subpackage has no side effects.
"""

from __future__ import annotations

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

__all__ = [
    "CompositeCost",
    "FeeSchedule",
    "TransferSchedule",
    "Waterfall",
    "WaterfallStage",
    "build_waterfall",
    "load_fee_schedules",
    "load_transfer_schedules",
    "round_trip_taker_bps",
    "transfer_cost_bps",
]
