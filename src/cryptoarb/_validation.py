"""Input-coercion and validation guardrails.

These helpers canonicalize loosely-typed inputs to concrete pandas objects and
enforce the shape/dtype/alignment preconditions that the compute kernels assume.
Every public compute function is expected to funnel its inputs through these
helpers so that the rest of the library can rely on clean, aligned, finite data.

Importing this module has no side effects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from cryptoarb._exceptions import InsufficientDataError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

# quantcore-candidate: mirrors risk-metrics:src/riskmetrics/_validation.py
# quantcore-candidate: mirrors factorlab:src/factorlab/_validation.py


def ensure_series(
    data: object,
    *,
    name: str = "series",
    allow_nan: bool = False,
) -> pd.Series:
    """Coerce ``data`` to a 1-D :class:`pandas.Series` and validate it.

    Parameters
    ----------
    data:
        A ``pd.Series``, a 1-D ``np.ndarray``, or any sequence coercible to a
        1-D Series.
    name:
        Human-readable label used in error messages.
    allow_nan:
        If ``False`` (default), the presence of any NaN raises
        :class:`ValidationError`.

    Returns
    -------
    pandas.Series
        A float64 Series (a copy; the caller's input is never mutated).

    Raises
    ------
    ValidationError
        If ``data`` is not 1-dimensional, is empty, or contains NaN when
        ``allow_nan`` is ``False``.
    """
    if isinstance(data, pd.Series):
        series = data.copy()
    elif isinstance(data, np.ndarray):
        if data.ndim != 1:
            raise ValidationError(f"{name} must be 1-dimensional, got ndim={data.ndim}.")
        series = pd.Series(data)
    else:
        series = pd.Series(data)

    if series.ndim != 1:
        raise ValidationError(f"{name} must be 1-dimensional.")
    if series.empty:
        raise ValidationError(f"{name} must be non-empty.")

    series = series.astype("float64")
    if not allow_nan and bool(series.isna().any()):
        raise ValidationError(f"{name} contains NaN values.")
    return series


def ensure_dataframe(
    data: object,
    *,
    name: str = "dataframe",
    allow_nan: bool = False,
    columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Coerce ``data`` to a 2-D :class:`pandas.DataFrame` and validate it.

    Parameters
    ----------
    data:
        A ``pd.DataFrame``, a 2-D ``np.ndarray``, or a mapping coercible to a
        DataFrame.
    name:
        Human-readable label used in error messages.
    allow_nan:
        If ``False`` (default), any NaN raises :class:`ValidationError`.
    columns:
        Optional column labels applied when ``data`` is an ndarray.

    Returns
    -------
    pandas.DataFrame
        A float64 DataFrame (a copy).

    Raises
    ------
    ValidationError
        If ``data`` is not 2-dimensional, has zero rows or columns, or contains
        NaN when ``allow_nan`` is ``False``.
    """
    if isinstance(data, pd.DataFrame):
        frame = data.copy()
    elif isinstance(data, np.ndarray):
        if data.ndim != 2:
            raise ValidationError(f"{name} must be 2-dimensional, got ndim={data.ndim}.")
        frame = pd.DataFrame(data, columns=list(columns) if columns is not None else None)
    else:
        # Curated pandas suppression: pandas-stubs has no overload for the broad
        # ``object`` boundary type we accept here; the runtime constructor copes.
        frame = pd.DataFrame(data)  # type: ignore[call-overload]

    if frame.ndim != 2:
        raise ValidationError(f"{name} must be 2-dimensional.")
    if frame.shape[0] == 0 or frame.shape[1] == 0:
        raise ValidationError(f"{name} must have at least one row and one column.")

    frame = frame.astype("float64")
    if not allow_nan and bool(frame.isna().to_numpy().any()):
        raise ValidationError(f"{name} contains NaN values.")
    return frame


def align_inner(left: pd.DataFrame, right: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Align two DataFrames on the intersection of their indexes (inner join).

    Both inputs are reindexed to the sorted intersection of their row indexes,
    preserving each frame's own columns. This is the no-lookahead-safe way to
    line up two panels that may have differing date coverage.

    Parameters
    ----------
    left, right:
        DataFrames to align row-wise.

    Returns
    -------
    tuple[pandas.DataFrame, pandas.DataFrame]
        The two frames reindexed to their common, sorted index.

    Raises
    ------
    ValidationError
        If the index intersection is empty.
    """
    common = left.index.intersection(right.index)
    if len(common) == 0:
        raise ValidationError("align_inner: the two inputs share no common index labels.")
    common = common.sort_values()
    return left.reindex(common), right.reindex(common)


def validate_min_obs(data: pd.DataFrame, min_obs: int, *, name: str = "data") -> None:
    """Assert that ``data`` has at least ``min_obs`` rows.

    Used to guard covariance estimation: a sample covariance over ``N`` assets
    needs strictly more than ``N`` observations to be full-rank, so callers pass
    ``min_obs = n_assets + 1``.

    Parameters
    ----------
    data:
        The (already coerced) observation panel.
    min_obs:
        The minimum acceptable number of rows.
    name:
        Human-readable label used in error messages.

    Raises
    ------
    InsufficientDataError
        If ``data`` has fewer than ``min_obs`` rows.
    """
    n_obs = int(data.shape[0])
    if n_obs < min_obs:
        raise InsufficientDataError(
            f"{name} has {n_obs} observation(s) but at least {min_obs} are required."
        )
