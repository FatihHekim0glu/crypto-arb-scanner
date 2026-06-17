"""Reproducibility manifest.

A :class:`RunManifest` captures everything needed to reproduce a run byte-for-byte:
the git commit, whether the working tree was dirty, a deterministic BLAKE2b hash
of the run configuration, and the master RNG seed. It is a frozen, slotted
dataclass with a JSON-serializable :meth:`RunManifest.to_dict`, so it crosses the
API boundary cleanly.

Importing this module has no side effects (git is only shelled out to when the
classmethod is explicitly called).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

# quantcore-candidate: mirrors pairs-trading:src/pairs/_manifest.py


def config_hash(config: Mapping[str, Any]) -> str:
    """Return a deterministic BLAKE2b-16 hex digest of a config mapping.

    The mapping is serialized to canonical JSON (``sort_keys=True``, no
    whitespace ambiguity) before hashing so that logically-equal configs that
    differ only in key order produce the same digest. Values must be
    JSON-serializable.

    Parameters
    ----------
    config:
        The run configuration (any JSON-serializable mapping).

    Returns
    -------
    str
        A 32-character hex digest (16-byte BLAKE2b).
    """
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2b(canonical.encode("utf-8"), digest_size=16).hexdigest()


def _git_sha(short: bool = True) -> str:
    """Return the current git commit SHA, or ``"unknown"`` if unavailable."""
    args = ["git", "rev-parse", "--short", "HEAD"] if short else ["git", "rev-parse", "HEAD"]
    try:
        out = subprocess.run(args, capture_output=True, text=True, check=True, timeout=5)
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _git_dirty() -> bool:
    """Return ``True`` if the working tree has uncommitted changes."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return bool(out.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        return False


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Immutable record of the provenance of a single run.

    Attributes
    ----------
    git_sha:
        The git commit SHA the code was run from (``"unknown"`` outside a repo).
    dirty:
        Whether the working tree had uncommitted changes at capture time.
    config_hash:
        A deterministic BLAKE2b-16 hex digest of the run configuration.
    seed:
        The master RNG seed (feeds :func:`cryptoarb._rng.make_rng`).
    """

    git_sha: str
    dirty: bool
    config_hash: str
    seed: int
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def capture(cls, config: Mapping[str, Any], seed: int) -> RunManifest:
        """Build a manifest by introspecting git and hashing ``config``.

        Parameters
        ----------
        config:
            The JSON-serializable run configuration to hash.
        seed:
            The master RNG seed for the run.

        Returns
        -------
        RunManifest
            A frozen manifest with the current git state and a config hash.
        """
        return cls(
            git_sha=_git_sha(),
            dirty=_git_dirty(),
            config_hash=config_hash(config),
            seed=int(seed),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this manifest."""
        return asdict(self)
