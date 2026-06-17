"""Shared type aliases for the cryptoarb library.

These aliases document *intent* at function boundaries (a net-edge series vs. a
wide spread panel vs. a price level) without committing to a single concrete
container. Functions coerce inputs to the canonical pandas/numpy type via
:mod:`cryptoarb._validation` at the boundary, so the aliases are deliberately
broad. Importing this module has no side effects.
"""

from __future__ import annotations

from typing import TypeAlias

import numpy as np
import pandas as pd
from numpy.typing import NDArray

# quantcore-candidate: mirrors factorlab:src/factorlab/_typing.py

#: A single order-book level: ``(price, size)`` in quote and base units.
PriceSize: TypeAlias = "tuple[float, float]"

#: A time-indexed series of per-decision net edge (in basis points), used by the
#: DSR/PSR effective-trials machinery. Accepted at the boundary as a Series, a
#: 1-D ndarray, or any sequence coercible to a 1-D Series.
NetEdgeLike: TypeAlias = "pd.Series | NDArray[np.float64]"

#: A wide panel of per-venue spreads or net edges: rows indexed by time, columns
#: by venue (or venue-pair). Canonicalized to ``pd.DataFrame`` internally.
SpreadPanelLike: TypeAlias = "pd.DataFrame | NDArray[np.float64]"

#: A float64 numpy array of unspecified shape (compute-kernel intermediate).
FloatArray: TypeAlias = NDArray[np.float64]
