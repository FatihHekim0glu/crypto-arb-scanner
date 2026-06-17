# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-17

### Added

- Initial package skeleton (src-layout, import name `cryptoarb`).
- Core helpers copied from the HRP infra and renamed: `_constants`, `_typing`,
  `_exceptions` (base `CryptoArbError` + `BookError`/`LiquidityError`),
  `_validation`, `_manifest` (`RunManifest` with BLAKE2b config-hash), and
  `_rng` (seeded PCG64 generator + substream spawning). `py.typed` marker.
- Stub signatures with full contracts for the order-book (`books.model`,
  `books.vwap`, `books.synthetic`), arbitrage (`arb.cross`, `arb.triangular`,
  `arb.feasibility`), cost (`costs.fees`, `costs.transfer`, `costs.waterfall`),
  and evaluation (`evaluation.dsr` reused, `evaluation.netedge`,
  `evaluation.verdict`) subpackages.
- Plotly figure builders (`plots`), live + cache + synthetic data path
  (`data.ccxt_source`, `data.cache`), and Typer CLI (`cli`) stubs.
- Fee/transfer reference profiles: `profiles/{default,low,high}.yaml`.
- Partitioned `tests/` (unit, parity, property, regression, integration) and
  seeded `conftest.py` fixtures (`consistent_books`, `dislocated_books`,
  `deep_vs_thin_book`).

[Unreleased]: https://github.com/FatihHekim0glu/crypto-arb-scanner/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/FatihHekim0glu/crypto-arb-scanner/releases/tag/v0.1.0
