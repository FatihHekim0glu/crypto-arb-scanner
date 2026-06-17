"""Seeded random-number generation with reproducible substreams.

All stochastic code (block bootstrap, synthetic data generators) must draw from
a generator produced here, never from the global ``numpy.random`` state, so that
a single master seed reproduces an entire run. We use the PCG64 bit generator
(numpy's default, statistically robust) and derive independent substreams via
:meth:`numpy.random.SeedSequence.spawn`.

Importing this module has no side effects.
"""

from __future__ import annotations

import numpy as np

# quantcore-candidate: mirrors pairs-trading:src/pairs/_rng.py


def make_rng(seed: int) -> np.random.Generator:
    """Return a fresh PCG64-backed :class:`numpy.random.Generator`.

    Parameters
    ----------
    seed:
        A non-negative integer master seed.

    Returns
    -------
    numpy.random.Generator
        A generator seeded deterministically from ``seed``.

    Raises
    ------
    ValueError
        If ``seed`` is negative.
    """
    if seed < 0:
        raise ValueError(f"seed must be non-negative, got {seed}.")
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed)))


def spawn_substreams(seed: int, n: int) -> list[np.random.Generator]:
    """Spawn ``n`` independent, reproducible child generators from ``seed``.

    Each child is statistically independent of the others (via
    ``SeedSequence.spawn``), so parallel or repeated draws are reproducible and
    non-overlapping. Spawning is itself deterministic: the same ``(seed, n)``
    always yields the same children.

    Parameters
    ----------
    seed:
        The master seed.
    n:
        The number of independent substreams to create.

    Returns
    -------
    list[numpy.random.Generator]
        ``n`` independent PCG64-backed generators.

    Raises
    ------
    ValueError
        If ``seed`` is negative or ``n`` is negative.
    """
    if seed < 0:
        raise ValueError(f"seed must be non-negative, got {seed}.")
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}.")
    children = np.random.SeedSequence(seed).spawn(n)
    return [np.random.Generator(np.random.PCG64(child)) for child in children]
