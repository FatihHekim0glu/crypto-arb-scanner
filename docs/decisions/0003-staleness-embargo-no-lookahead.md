# ADR-0003: Staleness embargo and no-lookahead on the replay path

- **Status:** Accepted
- **Date:** 2026-06-17
- **Deciders:** crypto-arb-scanner maintainers
- **Related:** [ADR-0005](0005-synthetic-fallback-data-source.md) (the data
  layer), [ADR-0004](0004-honest-null-no-feasible-edge.md) (the verdict)

## Context

Public REST order books are **snapshots, not a live streaming feed**. When you
poll Coinbase and Kraken for the same symbol you get two independently-timestamped
pictures of the market taken a few hundred milliseconds apart. A raw cross-venue
spread computed from a mismatched pair is then partly (sometimes entirely) a
**timing artifact**: the "rich" venue's quote may simply be staler than the
"cheap" venue's, and the gap closes the instant both refresh.

This is the same leakage failure as look-ahead in a backtest. If a decision at
time `t` is allowed to consume a quote stamped *after* `t`, or to pair a fresh
quote on venue A with a stale one on venue B, the measured edge is contaminated by
information (or staleness) the strategy could not actually have acted on.

## Decision

Two guards, both enforced on the timestamp (`ts_ms`) carried by every `OrderBook`:

1. **No-lookahead.** A decision at time `t` may use only quotes with `ts ≤ t`.
   Perturbing any post-`t` quote must not change a decision made at `t`. This is
   pinned by a property test: future-perturbing the books after `t` leaves the
   decision invariant.
2. **Staleness embargo across venues.** A cross-venue scan is never run on a
   half-stale book set. In the data layer, a partial snapshot (some venues
   missing or older than the embargo window) is treated as a **full miss**, so the
   whole set degrades together rather than pairing a fresh quote on one venue with
   a stale one on another. We never mix live and stale/synthetic books across
   venues within a single scan.

The `ts_ms` field exists solely to drive these guards; it is **never** used in any
price/cost computation.

## Consequences

- **Positive.** Edges that are pure cross-venue timing artifacts are excluded by
  construction, not "filtered out" after the fact. The replay path produces the
  same decisions whether or not the future is known.
- **Positive.** Treating a partial snapshot as a full miss is the conservative
  choice: it costs a scan (fall back to synthetic) but never reports a spread that
  is really two quotes taken seconds apart.
- **Cost.** Under flaky live connectivity, the embargo will degrade more scans to
  synthetic than a lenient "use whatever arrived" policy would. That is the
  intended trade: a correct null beats a contaminated positive.
- **Risk addressed.** "REST staleness", the README limitation, and the broader
  look-ahead leakage class are both closed on the replay path.
</content>
