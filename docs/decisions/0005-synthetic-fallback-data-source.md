# ADR-0005: Synthetic generator as the source of truth; live ccxt is best-effort

- **Status:** Accepted
- **Date:** 2026-06-17
- **Deciders:** crypto-arb-scanner maintainers
- **Related:** [ADR-0003](0003-staleness-embargo-no-lookahead.md) (the staleness
  embargo on live data), [ADR-0001](0001-vwap-depth-not-top-of-book.md) (what the
  generator must reproduce)

## Context

Live exchange APIs are an unreliable foundation for a *test suite*. They are
non-deterministic, rate-limited, sometimes geo-blocked (Binance blocks several
regions), and may be entirely unreachable from a CI runner or a constrained deploy
environment. A library whose correctness depended on a live fetch would have a
flaky, environment-coupled test suite and an import that could hang on a network
call. Yet the tool must still be *able* to look at real books when deployed, and
must never crash a request because an upstream venue was down.

## Decision

The **synthetic consistent-order-book generator is the source of truth** for
building and testing; the live `ccxt` path is best-effort and always degrades.

1. **Build and test entirely on synthetic.** `books/synthetic.py` emits
   deterministic per-venue L2 books around a shared true mid (consistent / no-arb
   when `dislocation_bps == 0`), plus a triangular cycle whose three mids multiply
   to exactly `1`. Same seed + config ⇒ byte-identical books. **No test requires
   live data**; the whole suite is offline and deterministic.
2. **Live path degrades, never hard-fails.** `data/ccxt_source.py` lazily imports
   *async* `ccxt`, fetches L2 books with short timeouts behind a token-bucket
   throttle, and on **any** failure (rate-limit, geo-block, timeout, symbol
   mismatch) falls back: first to a fresh disk cache, then to the synthetic
   generator. The reported `data_source` literal is one of `live | cache |
   synthetic`, so a caller always knows the provenance.
3. **Import purity.** `ccxt` is never imported at module load, only lazily inside
   the data-layer functions that need it. The `src/cryptoarb` tree has zero
   import-time side effects (no network, no RNG draw), enforced by a subprocess
   import-purity test.

The deployed backend *may* attempt live (Coinbase/Kraken public endpoints need no
credentials) but is contractually forbidden from hard-failing on an upstream miss:
it returns a synthetic-backed result with `data_source: "synthetic"` rather than a
5xx.

## Consequences

- **Positive.** CI is fast, deterministic, and offline. The honest-null and
  golden-waterfall regressions reproduce byte-for-byte from a seed.
- **Positive.** The same code is safe to deploy: a geo-block or rate-limit
  produces a labeled synthetic fallback, not an error or a hang.
- **Positive.** Because the generator reproduces depth-aware L2 ladders, the VWAP
  and no-arb machinery is exercised on realistic book *shapes* without a network.
- **Cost.** The synthetic books are a model, not the market: they validate the
  *machinery and the cost arithmetic*, and the README is explicit that the
  negative headline is demonstrated on synthetic-realistic books (and argued to
  hold on real liquid pairs), not measured live in the test suite.
- **Risk addressed.** "Flaky, network-coupled tests" and "a request that 5xxs
  because an exchange was unreachable" are both excluded.
</content>
