# Design

This document explains how `crypto-arb-scanner` is put together: the layering,
the data flow through one scan, the invariants the compute core guarantees, and
the testing strategy that keeps the honest negative headline honest. For *why*
individual contested choices were made, see the numbered ADRs in
[`docs/decisions/`](decisions/).

## Goals and non-goals

**Goals**

- A pure, typed (`mypy --strict`, `py.typed`), side-effect-free compute core that
  can be audited line by line and vendored into a backend without dragging UI or
  network dependencies along.
- An honest gross → net decomposition in which the **spread is priced at the depth
  a real notional would actually fill** (VWAP-walked L2, never top-of-book) and
  **every cost is real** (round-trip taker fees from published schedules, plus the
  withdrawal/settlement transfer cost).
- A verdict that is *mechanically* prevented from over-claiming: it cannot read
  "feasible edge" when the net edge is non-positive or within noise of zero.

**Non-goals**

- A trading system, signal, or alpha. The honest finding is that the net
  executable cross-exchange edge on liquid pairs collapses to ~0 or negative after
  costs.
- A latency-arbitrage engine. Capturing residual positive edges is a co-located
  HFT race; a REST client structurally cannot win it. The tool names such cases as
  artifacts rather than pretending to harvest them.
- A live market-data dependency. The library is built and tested entirely on a
  deterministic synthetic generator; the live `ccxt` path is best-effort and
  always degrades to synthetic.

## Layered architecture

The package is strictly layered; each layer imports only from the ones below it.
`src/cryptoarb/` has **zero import-time side effects**, guarded by a subprocess
import-purity test. `ccxt` is imported lazily inside data-layer functions, and
`plotly` lazily inside the figure builders.

```
                cli.py (Typer)            plots.py (Plotly, lazy)
                     |                          |
   ┌─────────────────┴──────────────────────────┘
   │                          scan.py
   │      run_scan  ──►  ScanResult{ summary, waterfall, series }
   │   (THE public entrypoint the backend router calls; pure pipeline)
   ├──────────────────────────────────────────────────────────────────
   │                       evaluation/
   │            dsr.py · netedge.py · verdict.py
   │   (Deflated/Probabilistic Sharpe · honest n_trials · pure verdict)
   ├──────────────────────────────────────────────────────────────────
   │            arb/                            costs/
   │   cross.py · triangular.py        fees.py · transfer.py · waterfall.py
   │   feasibility.py (ArbResult)      (CompositeCost from profiles/*.yaml)
   ├──────────────────────────────────────────────────────────────────
   │                        books/
   │        model.py · vwap.py · synthetic.py
   │   (frozen L2 OrderBook · walk-the-book VWAP · consistent generator)
   ├──────────────────────────────────────────────────────────────────
   │   data/ccxt_source.py · data/cache.py     foundation (no internal deps)
   │   (live ─► cache ─► synthetic fallback)   _validation · _constants · _typing
   │                                            _exceptions · _manifest · _rng
   └──────────────────────────────────────────────────────────────────
```

### Foundation (`_*.py`)

Copied verbatim from the HRP infra and renamed `hrp` → `cryptoarb`:

- `_constants.py`: shared scalar constants; one source of truth.
- `_validation.py`: input guards (shape, finiteness, sufficient observations).
- `_typing.py` / `_exceptions.py`: shared aliases and the exception taxonomy
  (base `CryptoArbError` with `BookError` / `LiquidityError` / `ValidationError`).
- `_manifest.py` / `_rng.py`: `RunManifest` (BLAKE2b config-hash) plus seeded
  PCG64 substreams. The manifest makes a run reproducible; the same seed yields
  byte-identical books.

### `books/`

`model.py` is a frozen `OrderBook` dataclass: canonically sorted `(price, size)`
bid/ask ladders with a `ts_ms` exchange timestamp carried for the replay
staleness guard (never used in compute). `vwap.py` walks the book (buy consumes
asks, sell consumes bids) to an **executable** average fill price for a target
notional `Q`, returning `(avg_price, filled_notional, fully_fillable)`. Pricing at
VWAP, not top of book, is [ADR-0001](decisions/0001-vwap-depth-not-top-of-book.md).
`synthetic.py` is the deterministic consistent-book generator: per-venue L2 books
around a shared true mid (consistent / no-arb when `dislocation_bps == 0`), plus a
triangular cycle whose three mids multiply to exactly `1`.

### `arb/`

`cross.py` prices a two-leg cross-exchange spread: sell-VWAP on the rich venue
minus buy-VWAP on the cheap venue for notional `Q`. `triangular.py` prices a
single-venue `A/B · B/C · C/A` cycle and exposes the no-arb residual
`∏ rate − 1`. `feasibility.py` assembles a frozen `ArbResult` carrying the
gross/executable/net bps and the legs.

### `costs/`

`fees.py` loads per-venue maker/taker schedules and computes the **round-trip
taker** cost (both legs always pay taker, never zeroed). `transfer.py` loads
per-asset withdrawal + network/settlement schedules and amortizes them to bps
(flat withdrawal fee diluted by notional, plus a notional-invariant
latency-decay penalty). `waterfall.py` assembles the headline: `gross →
−taker_fees → −transfer → net`, with slippage already baked into `gross` by the
VWAP walk (so it is *not* a separate stage; double-counting would understate the
edge). This is [ADR-0002](decisions/0002-gross-to-net-waterfall.md). A
`CompositeCost` bundles both schedules from one profile (`default` / `low` /
`high`) so callers configure costs once.

### `evaluation/`

`dsr.py` (reused) computes the Probabilistic and Deflated Sharpe ratios
(Bailey and LdP, 2014) with the full-grid `n_trials`. `netedge.py` builds the
per-pair net-edge series and enforces the honest multiplicity count
`n_trials = pair_legs × fee_grid_points` (never `1`), plus the cost-sensitivity
sweep. `verdict.py` is a **pure function** mapping the net-edge inference to a
fixed `Verdict` enum; it is structurally unable to emit `feasible_edge` when the
net edge is ≤ noise or its lower confidence bound includes zero
([ADR-0004](decisions/0004-honest-null-no-feasible-edge.md)).

### `data/`

`ccxt_source.py` is the live path: lazy async `ccxt`, short timeouts, a
token-bucket throttle, and graceful degradation `live → cache → synthetic` on any
failure. A partial snapshot (some venues stale/absent) is treated as a *full*
miss so a cross-venue scan never pairs a fresh quote with a stale one. `cache.py`
is the disk cache. This fallback chain is
[ADR-0005](decisions/0005-synthetic-fallback-data-source.md).

## Data flow through one scan

```
per-venue L2 books  (synthetic generator, or live ─► cache ─► synthetic)
        │
        ▼   for EVERY ordered (buy, sell) venue pair
   walk-the-book VWAP to notional Q   ──►  executable gross_bps  (never top-of-book)
        │
        ▼
   cost waterfall:  gross  −round_trip_taker  −transfer  =  net_bps
        │                        (real schedules from profiles/*.yaml)
        ▼
   per-pair net-edge series  ──►  n_feasible (count of net_bps > 0)
        │                        ──►  honest n_trials = pair_legs × fee_grid
        ▼   best (richest gross) pair, fully decomposed
   ArbResult + Waterfall  ──►  cost-sensitivity sweep
        │
        ▼   PURE function of the best pair's net edge (CI ± noise envelope)
   derive_verdict  ──►  no_feasible_edge | marginal | feasible_edge
        │
        ▼
   ScanSummary{ gross_bps, net_bps, fillable_notional, dominant_cost_leg,
                n_feasible, verdict, data_source }  +  Plotly figures
```

The headline number is `net_bps`, and on the consistent (no-dislocation) fixture
it is negative *before* the verdict is even consulted; the collapse is a property
of the cost arithmetic, not of the labeling.

## Key invariants

The compute core guarantees, and tests enforce:

1. **Depth realism.** Spreads are VWAP-walked from L2 for a real notional, never
   top-of-book. *Larger `Q` ⇒ worse (or equal) VWAP* (monotone). Property-tested.
2. **Net ≤ gross.** Costs are non-negative, so `net_bps ≤ gross_bps` always; the
   net edge can never exceed the gross edge. Property-tested.
3. **Triangular no-arb identity.** On the consistent synthetic books the cycle
   product is `1` to within `1e-12`. Parity-tested.
4. **No-lookahead (replay).** A decision at `t` uses only quotes with `ts ≤ t`;
   perturbing post-`t` quotes cannot change it. Property-tested.
5. **Honest multiplicity.** `n_trials = pair_legs × fee_grid_points`, never `1`;
   a guard rejects an under-count.
6. **Real fees.** Round-trip taker on both legs is always charged from a published
   schedule; fees are never zeroed.
7. **Verdict safety.** `derive_verdict` cannot emit `feasible_edge` while
   `net_bps ≤ noise` or the CI straddles zero (truth-table unit-tested).
8. **Scale & label invariance.** Rescaling the quote currency or relabeling the
   buy/sell legs does not change the measured spread. Property-tested.
9. **Determinism.** Same seed + config ⇒ byte-identical books and scan output.
10. **Import purity.** Importing any `src/cryptoarb` module triggers no I/O, no
    network, no `ccxt`/`plotly` import, no RNG draw (subprocess-tested).

## Testing strategy

Tests are partitioned by intent under `tests/`:

- **`unit/`**: isolated kernels: fee/transfer math, the DSR/PSR functions, the
  verdict truth table, the `effective_n_trials` guard.
- **`property/`** (Hypothesis): the invariants above: net ≤ gross monotonicity,
  larger-`Q`-worse-VWAP, no-lookahead future-perturbation invariance, spread
  scale-invariance, cross-exchange leg-labeling symmetry.
- **`parity/`**: golden checks against independent references: VWAP/L2
  aggregation vs a hand-rolled reference at `1e-9`, the triangular no-arb identity
  at `1e-12`, DSR/PSR vs the reused `dsr.py` at `1e-10`.
- **`regression/`**: the honest null, locked: consistent books ⇒ `net_bps ≤ 0` /
  `no_feasible_edge`; a golden net-edge waterfall on a fixed synthetic snapshot;
  the no-lookahead replay case; the import-purity subprocess test.
- **`integration/`**: end-to-end `run_scan` and CLI runs on synthetic data.

Seeded fixtures in `conftest.py` (`consistent_books`, `dislocated_books`,
`deep_vs_thin_book`) give every layer deterministic, adversarial inputs. Coverage
gate: `fail_under = 85`.

## Backend & frontend boundary

The compute core is decoupled from delivery. The backend vendors
`crypto-arb-scanner[data]` (not a heavy `[all]`) under
`api/lib/crypto_arb_scanner/` and exposes `POST /tools/crypto-arb-scanner/run`,
returning the `summary` scalars plus Plotly `{data, layout}` figures (the gross →
net waterfall and the spread distribution). `ccxt` is lazily imported inside the
handler with short timeouts; **any** upstream failure degrades to synthetic and
the handler never hard-fails (422 on validation, 502 only on a true *internal*
error, never on an upstream miss). The frontend renders the figures and surfaces
the pure-derived `verdict` and a `data_source` badge as the first things a visitor
reads, beside the honest caption "Net edge collapses after fees + depth +
transfer, not executable via REST."
</content>
