"""Unit tests for the reused, fully-implemented infrastructure.

The ``_rng``, ``_validation``, and ``_manifest`` helpers are concrete code copied
from the HRP infra (not stubs), so they are exercised here directly. These tests
pin their contracts in this package and carry real coverage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cryptoarb import _typing  # noqa: F401  (import-coverage of the alias module)
from cryptoarb._exceptions import (
    CryptoArbError,
    InsufficientDataError,
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


@pytest.mark.unit
def test_make_rng_is_deterministic() -> None:
    """The same seed yields identical draws; a different seed diverges."""
    a = make_rng(7).standard_normal(16)
    b = make_rng(7).standard_normal(16)
    c = make_rng(8).standard_normal(16)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


@pytest.mark.unit
def test_make_rng_rejects_negative_seed() -> None:
    """A negative seed is rejected."""
    with pytest.raises(ValueError, match="non-negative"):
        make_rng(-1)


@pytest.mark.unit
def test_spawn_substreams_independent_and_reproducible() -> None:
    """Spawned children are reproducible and mutually distinct."""
    first = [g.standard_normal(4) for g in spawn_substreams(3, 3)]
    second = [g.standard_normal(4) for g in spawn_substreams(3, 3)]
    for x, y in zip(first, second, strict=True):
        assert np.array_equal(x, y)
    assert not np.array_equal(first[0], first[1])


@pytest.mark.unit
def test_spawn_substreams_rejects_bad_args() -> None:
    """Negative seed or count is rejected."""
    with pytest.raises(ValueError, match="non-negative"):
        spawn_substreams(-1, 2)
    with pytest.raises(ValueError, match="must be non-negative"):
        spawn_substreams(1, -2)


@pytest.mark.unit
def test_ensure_series_coerces_and_validates() -> None:
    """A clean sequence coerces to float64; NaN is rejected by default."""
    s = ensure_series([1, 2, 3], name="x")
    assert s.dtype == np.float64
    assert list(s) == [1.0, 2.0, 3.0]
    with pytest.raises(ValidationError, match="NaN"):
        ensure_series([1.0, np.nan], name="x")
    with pytest.raises(ValidationError, match="non-empty"):
        ensure_series([], name="x")


@pytest.mark.unit
def test_ensure_series_rejects_2d_ndarray() -> None:
    """A 2-D ndarray is not a valid series."""
    with pytest.raises(ValidationError, match="1-dimensional"):
        ensure_series(np.zeros((2, 2)), name="x")


@pytest.mark.unit
def test_ensure_dataframe_coerces_and_validates() -> None:
    """A clean mapping coerces to a float64 frame; NaN/empty are rejected."""
    df = ensure_dataframe({"a": [1, 2], "b": [3, 4]}, name="m")
    assert df.shape == (2, 2)
    assert (df.dtypes == np.float64).all()
    with pytest.raises(ValidationError, match="NaN"):
        ensure_dataframe({"a": [1.0, np.nan]}, name="m")
    with pytest.raises(ValidationError, match="2-dimensional"):
        ensure_dataframe(np.zeros((2, 2, 2)), name="m")


@pytest.mark.unit
def test_ensure_dataframe_ndarray_with_columns() -> None:
    """An ndarray frame can take explicit column labels."""
    df = ensure_dataframe(np.arange(6.0).reshape(3, 2), columns=["x", "y"])
    assert list(df.columns) == ["x", "y"]


@pytest.mark.unit
def test_align_inner_intersects_indexes() -> None:
    """Two frames align on the sorted intersection of their indexes."""
    left = pd.DataFrame({"a": [1.0, 2.0, 3.0]}, index=[1, 2, 3])
    right = pd.DataFrame({"b": [9.0, 8.0]}, index=[2, 3])
    la, ra = align_inner(left, right)
    assert list(la.index) == [2, 3]
    assert list(ra.index) == [2, 3]
    with pytest.raises(ValidationError, match="no common index"):
        align_inner(left, pd.DataFrame({"b": [0.0]}, index=[99]))


@pytest.mark.unit
def test_validate_min_obs_guard() -> None:
    """Too few rows raises ``InsufficientDataError``."""
    df = pd.DataFrame({"a": [1.0, 2.0]})
    validate_min_obs(df, 2)  # exactly enough is fine
    with pytest.raises(InsufficientDataError, match="at least 5"):
        validate_min_obs(df, 5)


@pytest.mark.unit
def test_config_hash_is_order_independent() -> None:
    """Logically-equal configs hash identically regardless of key order."""
    h1 = config_hash({"a": 1, "b": 2})
    h2 = config_hash({"b": 2, "a": 1})
    assert h1 == h2
    assert h1 != config_hash({"a": 1, "b": 3})
    assert len(h1) == 32


@pytest.mark.unit
def test_run_manifest_capture_and_to_dict() -> None:
    """A manifest captures git state + config hash and round-trips to a dict."""
    manifest = RunManifest.capture({"symbol": "BTC/USDT"}, seed=42)
    d = manifest.to_dict()
    assert d["seed"] == 42
    assert d["config_hash"] == config_hash({"symbol": "BTC/USDT"})
    assert isinstance(d["git_sha"], str)
    assert isinstance(d["dirty"], bool)


@pytest.mark.unit
def test_exception_hierarchy() -> None:
    """``InsufficientDataError`` is a ``ValidationError`` is a ``CryptoArbError``."""
    assert issubclass(InsufficientDataError, ValidationError)
    assert issubclass(ValidationError, CryptoArbError)
