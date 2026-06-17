# ADR-0001: Price spreads at VWAP depth, not top of book

- **Status:** Accepted
- **Date:** 2026-06-17
- **Deciders:** crypto-arb-scanner maintainers
- **Related:** [ADR-0002](0002-gross-to-net-waterfall.md) (the cost waterfall),
  [ADR-0004](0004-honest-null-no-feasible-edge.md) (the honest null)

## Context

A cross-exchange "spread" can be measured two ways:

1. **Top of book** — best ask on the cheap venue vs best bid on the rich venue.
2. **Executable VWAP** — the size-weighted average fill price obtained by *walking
   the book* to a real target notional `Q`, consuming asks (buy) or bids (sell)
   level by level until `Q` is filled.

Top-of-book is the number most naive scanners report, and it is the single
biggest source of fake arbitrage. The best bid/ask sit on *tiny* resting size;
the moment you try to fill a meaningful notional you walk down the ladder into
worse prices. A top-of-book spread is therefore a **hidden over-claim**: it prices
a trade you cannot actually do at size. The gap between the top-of-book spread and
the VWAP-executable spread *is* the depth-slippage cost, and ignoring it is how a
spread that nets negative gets reported as positive.

## Decision

The scanner prices every spread at **executable VWAP for a real target notional
`Q`**, never at top of book. `books/vwap.py` walks the relevant side of the book
(asks for a buy, bids for a sell) and returns the size-weighted average fill price,
the filled notional, and whether `Q` was fully fillable. The cross-exchange gross
spread is then `1e4 · (sell_VWAP − buy_VWAP) / buy_VWAP` for that `Q`, and the
fillable notional reported to the caller is the binding minimum of the two legs'
fills.

Because slippage is *already baked into* the VWAP-walked gross spread, it is **not**
a separate stage in the cost waterfall ([ADR-0002](0002-gross-to-net-waterfall.md))
— charging it again would double-count and understate the edge.

## Consequences

- **Positive.** The reported gross spread is one you could actually execute at the
  stated size. Two property tests pin this: *larger `Q` ⇒ worse (or equal) VWAP*
  (the ladder only gets worse as you consume it) and *net ≤ gross* (costs are
  non-negative). A `deep_vs_thin_book` fixture proves a thin book yields a
  materially worse VWAP and a partial fill past its depth.
- **Positive.** Depth realism is the first thing that kills fake edges: a
  +25 bps *top-of-book* gap on thin size routinely VWAPs to a far smaller — or
  negative — executable spread before a single fee is charged.
- **Cost.** The caller must supply a target notional `Q`; "the spread" is not a
  single number but a function of size. This is the honest framing, but it means
  every result is annotated with the `notional_usd` it was priced for.
- **Risk addressed.** "Top-of-book over-claim" — the most common way crypto-arb
  dashboards manufacture phantom profit — is structurally excluded.
</content>
