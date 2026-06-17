# crypto-arb-scanner

Decompose cross-exchange and triangular crypto spreads into a fee-, depth-, and
transfer-cost-aware **gross → net waterfall**.

## Honest headline

Raw cross-exchange spreads on liquid pairs *look* profitable (5–40 bps), but
after **taker fees on both legs** + **order-book-depth slippage** for a realistic
notional + **withdrawal / network transfer cost**, the **net executable edge
collapses to ~0 or negative**. Residual positives are stale-quote / latency-arb
artifacts that a retail REST client cannot win — latency arbitrage is an HFT
co-location game, not a REST one.

This is a **diagnostic spread-decomposition tool, not a money printer.** The
verdict is a pure function of the net-edge inference and is structurally unable
to claim a feasible edge when the net bps are ≤ 0 (or within noise).

## Data reality

The library is built and tested **entirely on a deterministic synthetic
consistent-order-book generator** (`books.synthetic`). The live path
(`data.ccxt_source`) lazily imports async `ccxt`, fetches L2 books with short
timeouts and a token-bucket throttle, and on **any** failure (rate-limit,
geo-block, timeout, symbol mismatch) degrades to cache, then to synthetic. No
test requires live data.

## Quick start

```bash
uv venv
uv pip install -e '.[data,viz,dev]'
uv run cryptoarb --help
```

## Layout

```
src/cryptoarb/
  books/      model.py · vwap.py · synthetic.py
  arb/        cross.py · triangular.py · feasibility.py
  costs/      fees.py · transfer.py · waterfall.py
  evaluation/ dsr.py · netedge.py · verdict.py
  data/       ccxt_source.py · cache.py
  plots.py · cli.py
  profiles/   default.yaml · low.yaml · high.yaml
```

## Validation

| Check | Tolerance |
| --- | --- |
| VWAP / L2 aggregation vs hand-rolled reference | 1e-9 |
| Triangular no-arb identity on consistent books | 1e-12 |
| DSR / PSR vs reused `dsr.py` | 1e-10 |
| Net edge ≤ gross edge (monotone) | property test |
| Larger notional ⇒ worse (or equal) VWAP | property test |
| No-lookahead: post-`t` quotes cannot change a decision at `t` | property test |

## Limitations

- **Delisted-pair survivorship:** only currently-listed pairs are scanned; a
  backtest over surviving pairs overstates opportunity.
- **Latency-arb infeasibility:** any residual positive edge is a stale-quote
  artifact unreachable by a REST client.
- **REST staleness:** public REST books are snapshots, not a live feed; the
  replay path enforces a staleness/embargo guard.

## References

- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*.
- Standard cross-exchange and triangular no-arbitrage identities.

Licensed under the [MIT License](LICENSE).
