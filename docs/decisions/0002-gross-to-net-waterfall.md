# ADR-0002: A single gross → net cost waterfall with no double-counting

- **Status:** Accepted
- **Date:** 2026-06-17
- **Deciders:** crypto-arb-scanner maintainers
- **Related:** [ADR-0001](0001-vwap-depth-not-top-of-book.md) (slippage lives in
  the gross spread), [ADR-0004](0004-honest-null-no-feasible-edge.md) (the verdict
  reads the net edge)

## Context

The whole point of the tool is the **gross → net collapse**: an executable spread
that looks profitable becomes ~0 or negative after costs. For that story to be
honest *and* legible, the cost decomposition has to satisfy two competing
constraints:

1. **No cost is missing.** Round-trip taker fees on *both* legs and the
   withdrawal/network transfer cost must always be charged, never zeroed, never
   assumed away with a generous fee tier.
2. **No cost is double-counted.** Depth slippage is *already inside* the
   VWAP-walked gross spread ([ADR-0001](0001-vwap-depth-not-top-of-book.md)). If we
   also subtracted a separate "slippage" stage we would charge it twice and
   understate the net edge, which would *exaggerate* the collapse and make the
   tool dishonest in the pessimistic direction.

## Decision

A single ordered waterfall in `costs/waterfall.py`:

```
gross   (anchor: executable VWAP spread, slippage already inside)
  − round_trip_taker_fees   (both legs, from a published schedule)
  − transfer                (withdrawal flat fee in bps + latency-decay penalty)
= net   (anchor: the honest headline number)
```

- **Slippage is not a stage.** It is represented by the difference between the
  hypothetical top-of-book spread and the VWAP-walked `gross`. The waterfall starts
  *from* `gross`, so slippage is counted exactly once.
- **Fees are real and never zeroed.** `round_trip_taker_bps` sums both legs' taker
  rates from `profiles/*.yaml`. The default profile uses realistic retail
  (non-VIP) numbers; `low` and `high` bracket best/worst case.
- **Transfer is real.** `transfer_cost_bps` converts the flat withdrawal fee to
  bps against the moved notional (so larger notionals dilute it) and adds a
  notional-invariant `network_minutes × latency_bps_per_min` settlement-risk
  penalty: while the asset is in transit the quoted edge can evaporate.
- **`dominant_cost_leg`** is reported as the single largest cost by magnitude, so
  the frontend can name *which* leg killed the edge (on liquid pairs it is almost
  always `taker_fees`).

A property test guarantees `net_bps ≤ gross_bps` (costs are non-negative).

## Consequences

- **Positive.** The waterfall renders directly as the headline bar chart, and the
  net number is defensible stage by stage. On a +25 bps manufactured gap the
  default-profile waterfall reads `+21.5 → −36.0 (fees) → −11.5 (transfer) =
  −26.0 bps`; fees alone exceed the spread.
- **Positive.** Excluding a separate slippage stage keeps the tool from cheating
  *in its own favor's opposite direction*; the collapse is exactly as deep as the
  arithmetic says, no deeper.
- **Cost.** Anyone reading the waterfall must understand that slippage lives in the
  `gross` anchor, not in a labeled bar. This ADR and the `build_waterfall`
  docstring state it explicitly.
- **Risk addressed.** Both "a cost was quietly dropped to make an edge appear" and
  "a cost was double-charged to manufacture a collapse" are excluded.
</content>
