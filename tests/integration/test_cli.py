"""Tests for the Typer CLI (``cryptoarb.cli``).

The two commands are plain functions over the pure library, so the synthetic
scan/replay smoke runs need neither ``typer`` nor the network. The ``--help`` /
Typer-wiring tests are skipped gracefully when the optional ``typer`` dependency
is not installed, so the suite stays offline-deterministic and green either way.

Pins:

- a tiny synthetic ``scan`` runs end-to-end and prints the honest-null verdict;
- ``replay`` enforces the no-lookahead guard (quotes stamped after the decision
  are invisible) and never claims a feasible edge on the consistent fixture;
- importing the module pulls in neither ``typer`` nor ``ccxt``;
- when ``typer`` is present, ``build_app`` wires both commands and ``--help`` works.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from cryptoarb.books.synthetic import SyntheticConfig, VenueSpec, synthetic_books
from cryptoarb.cli import build_app, replay, scan

_HAS_TYPER = importlib.util.find_spec("typer") is not None
_requires_typer = pytest.mark.skipif(not _HAS_TYPER, reason="optional 'typer' not installed")


@pytest.mark.unit
def test_cli_import_is_side_effect_free() -> None:
    """Importing ``cryptoarb.cli`` must not import typer or ccxt."""
    assert "cryptoarb.cli" in sys.modules
    assert "typer" not in sys.modules
    assert "ccxt" not in sys.modules


@pytest.mark.unit
def test_honest_verdict_truth_table() -> None:
    """The verdict rule cannot claim a feasible edge at or below the noise band.

    ``net <= noise`` -> ``no_feasible_edge``; above the feasibility threshold ->
    ``feasible_edge``; in between -> ``marginal``. This pins the honest-null
    discipline directly on the CLI's verdict helper.
    """
    from cryptoarb.cli import _honest_verdict

    assert _honest_verdict(-50.0) == "no_feasible_edge"
    assert _honest_verdict(0.0) == "no_feasible_edge"
    assert _honest_verdict(1.0) == "no_feasible_edge"  # == noise band -> not feasible
    assert _honest_verdict(3.0) == "marginal"  # above noise, below feasible
    assert _honest_verdict(5.0) == "feasible_edge"  # == feasible threshold
    assert _honest_verdict(42.0) == "feasible_edge"


@pytest.mark.integration
def test_scan_synthetic_smoke_prints_honest_null(capsys: pytest.CaptureFixture[str]) -> None:
    """A tiny synthetic scan runs end-to-end and reports the honest-null verdict.

    The consistent synthetic fixture has no exploitable cross-venue gap, so after
    fees + depth + transfer the net edge collapses and the verdict must be
    ``no_feasible_edge`` — the CLI can never print a profit claim here.
    """
    scan(
        symbol="BTC/USDT",
        venues="binance,coinbase,kraken",
        notional_usd=10_000.0,
        data_source_pref="synthetic",
        seed=0,
    )
    out = capsys.readouterr().out
    assert "data_source : synthetic" in out
    assert "verdict     : no_feasible_edge" in out
    assert "net_bps" in out
    assert "not executable via REST" in out


@pytest.mark.integration
@pytest.mark.parametrize("profile", ["default", "low", "high"])
def test_scan_synthetic_collapses_under_every_profile(
    profile: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Under every cost profile the consistent fixture yields no feasible edge."""
    scan(
        symbol="BTC/USDT",
        venues="binance,coinbase,kraken",
        notional_usd=25_000.0,
        fee_profile=profile,
        data_source_pref="synthetic",
        seed=3,
    )
    out = capsys.readouterr().out
    assert "verdict     : no_feasible_edge" in out


@pytest.mark.integration
def test_scan_without_transfer_still_collapses(capsys: pytest.CaptureFixture[str]) -> None:
    """Dropping transfer cost still leaves fees + depth, so the edge collapses."""
    scan(
        symbol="BTC/USDT",
        venues="binance,kraken",
        notional_usd=10_000.0,
        include_transfer=False,
        data_source_pref="synthetic",
        seed=0,
    )
    out = capsys.readouterr().out
    assert "verdict     : no_feasible_edge" in out
    # No transfer stage when transfer cost is excluded.
    assert "transfer" not in out.split("waterfall")[1].split("gross_bps")[0]


def _write_snapshot(tmp_path: Path, *, dislocation_bps: float, kraken_ts: int) -> Path:
    """Write a synthetic multi-venue snapshot with a per-venue timestamp twist."""
    config = SyntheticConfig(
        symbol="BTC/USDT",
        true_mid=50_000.0,
        venues=(VenueSpec("binance"), VenueSpec("coinbase"), VenueSpec("kraken")),
        dislocation_bps=dislocation_bps,
        ts_ms=1_000,
    )
    books = synthetic_books(config, seed=0)
    payload = {venue: book.to_dict() for venue, book in books.items()}
    # Kraken (the dislocated venue) is stamped fresh so the no-lookahead guard
    # can hide it at an earlier decision time.
    payload["kraken"]["ts_ms"] = kraken_ts
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.integration
def test_replay_no_lookahead_hides_future_quote(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A quote stamped after the decision time is invisible to the decision."""
    snapshot = _write_snapshot(tmp_path, dislocation_bps=30.0, kraken_ts=2_000)
    replay(str(snapshot), decision_ms=1_500, embargo_ms=0)
    out = capsys.readouterr().out
    # kraken (ts=2000 > 1500) must NOT appear among visible venues.
    assert "'binance', 'coinbase'" in out
    assert "kraken" not in out.split("visible venues")[1].splitlines()[0]
    assert "verdict     : no_feasible_edge" in out


@pytest.mark.integration
def test_replay_consistent_books_never_feasible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Even with every venue visible, the dislocated gap collapses after costs."""
    snapshot = _write_snapshot(tmp_path, dislocation_bps=30.0, kraken_ts=1_000)
    replay(str(snapshot), decision_ms=5_000, embargo_ms=0)
    out = capsys.readouterr().out
    assert "kraken" in out.split("visible venues")[1].splitlines()[0]
    # A +30 bps raw dislocation still nets negative after taker fees + transfer.
    assert "verdict     : no_feasible_edge" in out


@pytest.mark.integration
def test_replay_embargo_drops_all_but_one_venue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A large embargo can leave fewer than two venues -> no feasible edge."""
    snapshot = _write_snapshot(tmp_path, dislocation_bps=0.0, kraken_ts=1_000)
    # cutoff = decision_ms - embargo_ms = 900 < every venue ts (1000): all hidden.
    replay(str(snapshot), decision_ms=1_000, embargo_ms=100)
    out = capsys.readouterr().out
    assert "insufficient non-stale venues" in out


@_requires_typer
@pytest.mark.integration
def test_build_app_wires_both_commands() -> None:
    """``build_app`` returns a Typer app registering ``scan`` and ``replay``."""
    cli = build_app()
    names = {command.name or command.callback.__name__ for command in cli.registered_commands}
    assert {"scan", "replay"} <= names


@_requires_typer
@pytest.mark.integration
def test_cli_help_runs() -> None:
    """The top-level ``--help`` exits cleanly and lists both commands."""
    from typer.testing import CliRunner

    result = CliRunner().invoke(build_app(), ["--help"])
    assert result.exit_code == 0
    assert "scan" in result.stdout
    assert "replay" in result.stdout


@_requires_typer
@pytest.mark.integration
def test_cli_scan_via_runner_smoke() -> None:
    """The ``scan`` subcommand runs through Typer on the synthetic path."""
    from typer.testing import CliRunner

    result = CliRunner().invoke(
        build_app(),
        ["scan", "--data-source-pref", "synthetic", "--seed", "0"],
    )
    assert result.exit_code == 0
    assert "no_feasible_edge" in result.stdout
