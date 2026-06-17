"""Typer command-line interface: ``scan`` and ``replay``.

The CLI is a thin shell over the pure compute library; ``typer`` is imported
LAZILY inside :func:`app` (and the package's optional ``[viz]``/``[data]`` extras
are only needed by the commands that use them), so importing this module has no
side effects. The interactive demo lives behind the ``__main__`` guard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typer import Typer


def build_app() -> Typer:
    """Construct and return the Typer application (lazy ``typer`` import).

    Wires up two commands:

    - ``scan``: scan one symbol across venues for a target notional, print the
      gross -> net waterfall and the verdict.
    - ``replay``: replay a saved snapshot under the no-lookahead guard and report
      whether the historical decision survives costs.

    Returns
    -------
    typer.Typer
        The configured CLI application.
    """
    raise NotImplementedError


def scan(
    symbol: str = "BTC/USDT",
    venues: str = "binance,coinbase,kraken",
    notional_usd: float = 10_000.0,
    fee_profile: str = "default",
    include_transfer: bool = True,
    data_source_pref: str = "auto",
    seed: int = 0,
) -> None:
    """Scan ``symbol`` across ``venues`` and print the gross -> net decomposition.

    Parameters
    ----------
    symbol:
        Unified ``BASE/QUOTE`` symbol.
    venues:
        Comma-separated venue identifiers.
    notional_usd:
        Target notional in USD.
    fee_profile:
        Cost profile name (``"default"``, ``"low"``, ``"high"``).
    include_transfer:
        Whether to include transfer cost in the waterfall.
    data_source_pref:
        Source preference (``"auto"``, ``"live"``, ``"synthetic"``).
    seed:
        Master seed for the synthetic fallback.
    """
    raise NotImplementedError


def replay(
    snapshot_path: str,
    decision_ms: int,
    embargo_ms: int = 0,
) -> None:
    """Replay a saved snapshot at ``decision_ms`` under the no-lookahead guard.

    Only quotes with ``ts_ms <= decision_ms - embargo_ms`` are visible to the
    decision; the command reports whether the historical opportunity survives
    costs and confirms that post-``t`` quotes cannot change the verdict.

    Parameters
    ----------
    snapshot_path:
        Path to a saved multi-venue snapshot.
    decision_ms:
        The decision timestamp in milliseconds since the epoch.
    embargo_ms:
        Extra staleness embargo subtracted from ``decision_ms``.
    """
    raise NotImplementedError


#: The Typer application object referenced by the ``cryptoarb`` console script.
#: Built lazily so that importing this module never imports ``typer``.
app = build_app


if __name__ == "__main__":  # pragma: no cover
    build_app()()
