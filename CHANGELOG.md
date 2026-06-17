# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-17

### Added

- Initial release: a pure, typed (`mypy --strict`, `py.typed`), import-pure
  src-layout package (`cryptoarb`) that decomposes cross-exchange and triangular
  crypto spreads into a fee-, depth-, and transfer-cost-aware gross → net
  waterfall. The headline is the gross → net collapse, never a profit claim.
- Foundation helpers copied from the HRP infra and renamed: `_constants`,
  `_typing`, `_exceptions` (base `CryptoArbError` + `BookError`/`LiquidityError`),
  `_validation`, `_manifest` (`RunManifest` with BLAKE2b config-hash), and `_rng`
  (seeded PCG64 generator + substream spawning). `py.typed` marker.
- Order-book layer: frozen L2 `OrderBook` (`books.model`), walk-the-book
  executable VWAP (`books.vwap`), and the deterministic consistent-book generator
  (`books.synthetic`) including the triangular cycle whose mids multiply to `1`.
- Arbitrage layer: cross-exchange two-leg spread (`arb.cross`), single-venue
  triangular cycle with the no-arb residual (`arb.triangular`), and the frozen
  `ArbResult` (`arb.feasibility`).
- Cost layer: per-venue maker/taker fees (`costs.fees`), per-asset
  withdrawal + settlement-latency transfer cost (`costs.transfer`), and the
  gross → net `Waterfall` / `CompositeCost` (`costs.waterfall`).
- Evaluation layer: reused Probabilistic/Deflated Sharpe (`evaluation.dsr`),
  per-pair net-edge series with honest `n_trials = pair_legs × fee_grid_points`
  and the cost-sensitivity sweep (`evaluation.netedge`), and the **pure** verdict
  deriver (`evaluation.verdict`) that cannot claim a feasible edge on the null.
- Public end-to-end `run_scan` entrypoint (`scan`) wiring the pipeline into a
  frozen `ScanResult` with the backend `summary` contract; Plotly figure builders
  (`plots`, lazy); live + cache + synthetic data path (`data.ccxt_source`,
  `data.cache`); and the Typer CLI (`cli`).
- Fee/transfer reference profiles: `profiles/{default,low,high}.yaml`.
- Partitioned `tests/` (unit, parity, property, regression, integration) and
  seeded `conftest.py` fixtures (`consistent_books`, `dislocated_books`,
  `deep_vs_thin_book`); coverage gate `fail_under = 85`.
- Documentation: honest negative-headline `README` with the actual synthetic
  waterfall numbers, validation table, and limitations; `docs/DESIGN.md`; ADRs
  0001–0005; `CITATION.cff`; and the `no-ai-attribution` CI guard.

[Unreleased]: https://github.com/FatihHekim0glu/crypto-arb-scanner/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/FatihHekim0glu/crypto-arb-scanner/releases/tag/v0.1.0
