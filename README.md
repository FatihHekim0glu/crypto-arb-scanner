# crypto-arb-scanner

Decompose cross-exchange and triangular crypto spreads into a fee-, depth-, and
transfer-cost-aware **gross → net waterfall**. This is a diagnostic
spread-decomposition tool, **not** a money printer.

## Honest headline: the gross to net collapse

Raw cross-exchange spreads on liquid pairs *look* profitable (a fabricated
+25 bps gap is easy to find in snapshot data), but once you charge **round-trip
taker fees on both legs**, **order-book-depth slippage** for a realistic
notional, and the **withdrawal / network-settlement transfer cost** of actually
moving the asset between venues, the **net executable edge collapses to ~0 or
negative**.

On the deterministic synthetic books shipped with the tests, scanning
`BTC/USDT` for a `$10,000` notional under the **default** retail cost profile:

| Scenario (synthetic) | Gross bps | → fees | → transfer | **Net bps** | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| Consistent (no dislocation) | −3.50 | −36.00 | −11.50 | **−51.00** | `no_feasible_edge` |
| +25 bps manufactured gap | +21.49 | −36.00 | −11.50 | **−26.01** | `no_feasible_edge` |
| +40 bps manufactured gap | +36.49 | −36.00 | −11.50 | **−11.01** | `no_feasible_edge` |

A standing **+25 bps** cross-exchange gap, the kind a naive top-of-book scanner
reports as "free money", nets **−26 bps** after costs. You would need a *durable*
~+48 bps gap just to break even at default retail fees, and liquid-pair gaps that
large do not sit still long enough for a REST round-trip to capture them.

The same `+40 bps` gap only reads as a feasible edge under the **`low`**
(best-case VIP / high-volume) cost profile (+19.4 bps net). That is precisely the
point of the headline: any residual positive edge is a **stale-quote /
latency-arbitrage artifact** that a retail REST client cannot win. Latency
arbitrage is an HFT co-location game played in microseconds, not something a
public REST snapshot loop can execute.

> **The dominant cost leg is the fee leg, not the spread.** Round-trip taker fees
> alone (36 bps at default) exceed almost every executable gross spread on a
> liquid pair. Transfer cost then finishes the job.

The verdict is a **pure function** of the net-edge inference
([`evaluation/verdict.py`](src/cryptoarb/evaluation/verdict.py)) and is
*structurally unable* to claim a feasible edge when the net bps are ≤ 0 or within
statistical noise of zero. See
[ADR-0004](docs/decisions/0004-honest-null-no-feasible-edge.md).

## Data reality

The library is built and tested **entirely on a deterministic synthetic
consistent-order-book generator** (`books.synthetic`). Live exchange APIs may be
unreachable or geo-blocked from a given build/deploy environment, so:

- The **live path** (`data.ccxt_source`) lazily imports async `ccxt`, fetches L2
  books with short timeouts behind a token-bucket throttle, and on **any** failure
  (rate-limit, geo-block, timeout, symbol mismatch) degrades to a fresh cache,
  then to synthetic. It **never** hard-fails. The reported `data_source` is one of
  `live | cache | synthetic`.
- **No test requires live data.** The whole suite is offline and deterministic.

`src/cryptoarb/` has **zero import-time side effects**: `ccxt` is imported lazily
inside functions, `plotly` lazily inside the figure builders, and there is no
network or RNG draw at import (subprocess-guarded). See
[ADR-0005](docs/decisions/0005-synthetic-fallback-data-source.md).

## Quick start

```bash
uv venv
uv pip install -e '.[data,viz,dev]'
```

The library is the primary surface (`from cryptoarb.scan import run_scan`); the
optional Typer CLI (`cryptoarb scan` / `cryptoarb replay`) additionally requires
`typer` and degrades to a skip in the test suite when it is absent.

```python
from cryptoarb.books.synthetic import SyntheticConfig, VenueSpec, synthetic_books
from cryptoarb.scan import run_scan

cfg = SyntheticConfig(
    symbol="BTC/USDT",
    true_mid=50_000.0,
    venues=(
        VenueSpec("binance", half_spread_bps=1.5, depth_base=8.0),
        VenueSpec("coinbase", half_spread_bps=2.5, depth_base=4.0),
        VenueSpec("kraken", half_spread_bps=2.0, depth_base=5.0),
    ),
    dislocation_bps=25.0,  # a generous, manufactured +25 bps gap
)
books = synthetic_books(cfg, seed=0)
result = run_scan("BTC/USDT", list(books), 10_000.0, fee_profile="default", books=books)
print(result.summary.to_dict())
# {'gross_bps': 21.49..., 'net_bps': -26.0..., 'dominant_cost_leg': 'taker_fees',
#  'n_feasible': 0, 'verdict': 'no_feasible_edge', 'data_source': 'synthetic'}
```

## Layout

```
src/cryptoarb/
  books/      model.py · vwap.py · synthetic.py
  arb/        cross.py · triangular.py · feasibility.py
  costs/      fees.py · transfer.py · waterfall.py
  evaluation/ dsr.py · netedge.py · verdict.py
  data/       ccxt_source.py · cache.py
  scan.py · plots.py · cli.py
  profiles/   default.yaml · low.yaml · high.yaml
```

Architecture and data flow: [`docs/DESIGN.md`](docs/DESIGN.md). Contested design
choices: the numbered ADRs in [`docs/decisions/`](docs/decisions/).

## Validation

Every claim above is pinned by a test. Each row maps an **oracle** to its
**tolerance** to the **test** that enforces it.

| Check | Oracle | Tolerance | Test |
| --- | --- | --- | --- |
| VWAP / L2 aggregation | hand-rolled walk-the-book reference | `1e-9` | `tests/parity/test_arb_parity.py` |
| Triangular no-arb identity | analytic `∏ rate = 1` on consistent books | `1e-12` | `tests/parity/test_arb_parity.py` |
| DSR / PSR | reused `evaluation/dsr.py` (Bailey and LdP) | `1e-10` | `tests/unit/test_dsr.py` |
| Net edge ≤ gross edge | monotonicity (costs ≥ 0) | property (Hypothesis) | `tests/property/test_books_group.py` |
| Larger notional ⇒ worse (or equal) VWAP | depth-realism monotonicity | property | `tests/property/test_books_group.py` |
| No-lookahead replay | post-`t` quotes cannot change a decision at `t` | property | `tests/property/test_property_contracts.py` |
| Spread scale-invariance | rescale quote currency | property | `tests/property/test_property_contracts.py` |
| Honest null | consistent books ⇒ `net_bps ≤ 0` / `no_feasible_edge` | regression (golden) | `tests/regression/test_regression_contracts.py` |
| DSR multiplicity | `n_trials = pair_legs × fee_grid_points` (never 1) | guard | `tests/unit/test_evaluation_group.py` |

## Limitations

- **Delisted-pair survivorship.** Only currently-listed pairs are scannable. Any
  backtest restricted to *surviving* pairs over-counts opportunity, because the
  pairs that produced the largest historical dislocations are disproportionately
  the ones that later delisted, failed, or had their venues collapse. This tool
  does not correct for that bias and does not claim to.
- **Latency-arbitrage infeasibility.** Any residual positive net edge is a
  stale-quote artifact. Capturing it requires winning a microsecond race against
  co-located HFT, infeasible for a retail REST client. The tool reports such
  cases as `marginal`/`feasible_edge` only under unrealistic best-case (`low`)
  costs, and the README headline labels them honestly as artifacts.
- **REST staleness.** Public REST order books are *snapshots*, not a live
  streaming feed. Two venues' snapshots are never perfectly simultaneous, so a
  raw cross-venue spread can be a timing artifact. The data layer treats a
  partial/half-stale snapshot set as a full miss (degrades the whole set rather
  than pairing a fresh quote on A with a stale one on B), and the replay path
  enforces a staleness/embargo guard so a decision at `t` uses only quotes with
  `ts ≤ t`. See [ADR-0003](docs/decisions/0003-staleness-embargo-no-lookahead.md).

## Reproduce

```bash
# 1. Environment (Python >= 3.11)
uv venv && uv pip install -e '.[data,viz,dev]'

# 2. Full quality gate: exactly what CI runs
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src/cryptoarb
uv run pytest --cov=cryptoarb --cov-report=term-missing   # coverage gate: fail_under = 85

# 3. Regenerate the headline waterfall numbers in this README
uv run python - <<'PY'
from cryptoarb.books.synthetic import SyntheticConfig, VenueSpec, synthetic_books
from cryptoarb.scan import run_scan

venues = (
    VenueSpec("binance", half_spread_bps=1.5, depth_base=8.0),
    VenueSpec("coinbase", half_spread_bps=2.5, depth_base=4.0),
    VenueSpec("kraken", half_spread_bps=2.0, depth_base=5.0),
)
for label, disloc in [("consistent", 0.0), ("+25bps gap", 25.0), ("+40bps gap", 40.0)]:
    books = synthetic_books(
        SyntheticConfig("BTC/USDT", 50_000.0, venues, dislocation_bps=disloc), seed=0
    )
    r = run_scan("BTC/USDT", list(books), 10_000.0, fee_profile="default", books=books)
    s = r.summary
    print(f"{label:>12}: gross={s.gross_bps:+7.2f}  net={s.net_bps:+8.2f}  {s.verdict.value}")
PY
```

The synthetic path is fully deterministic: the same `seed` and config yield
byte-identical books, so the waterfall numbers above reproduce exactly. The same
`run_scan` entrypoint is what the backend router calls.

## References

- Bailey, D. H. & López de Prado, M. (2014). *The Deflated Sharpe Ratio:
  Correcting for Selection Bias, Backtest Overfitting, and Non-Normality.* The
  Journal of Portfolio Management. The multiplicity-corrected yardstick used by
  `evaluation/dsr.py`.
- The classical **cross-exchange** and **triangular** no-arbitrage identities:
  a cross-venue spread that survives both legs' fees and transfer cost, and a
  single-venue cycle product `A/B · B/C · C/A = 1`, are the structural anchors the
  scan measures *deviation from*.

Licensed under the [MIT License](LICENSE).
</content>
