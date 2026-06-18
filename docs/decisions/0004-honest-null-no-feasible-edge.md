# ADR-0004: An honest null, the verdict cannot claim a feasible edge

- **Status:** Accepted
- **Date:** 2026-06-17
- **Deciders:** crypto-arb-scanner maintainers
- **Related:** [ADR-0002](0002-gross-to-net-waterfall.md) (the net edge it reads),
  [ADR-0001](0001-vwap-depth-not-top-of-book.md) (executable pricing)

## Context

The headline of this tool is a **negative result**: on liquid pairs the net
executable cross-exchange edge collapses to ~0 or negative after costs. The
failure mode for any such tool is *narrating* a positive conclusion the numbers do
not support: eyeballing a residual `+3 bps`, calling it "a small but real edge,"
and quietly omitting that it is inside the noise or that its confidence interval
straddles zero. A negative headline is only credible if the verdict is **derived,
not narrated**, and is *structurally incapable* of over-claiming.

## Decision

The verdict is a **pure function** of the net-edge inference
(`evaluation/verdict.py::derive_verdict`), with the honest null evaluated *first*:

```
if net_bps ≤ noise_bps  OR  ci_low_bps ≤ 0:   →  NO_FEASIBLE_EDGE
elif net_bps ≥ feasible_bps  AND  ci_low_bps > 0:   →  FEASIBLE_EDGE
else:   →  MARGINAL
```

- **The null branch is checked first and dominates.** Whenever the net edge is at
  or below the noise band, *or* its lower confidence bound includes zero, the
  function returns `NO_FEASIBLE_EDGE`, regardless of any point estimate. It is
  *structurally impossible* for the function to return `FEASIBLE_EDGE` when
  `net_bps ≤ 0` or the CI straddles zero. This is stated as a HONESTY REQUIREMENT
  in the docstring and pinned by a truth-table unit test.
- **The verdict is the only headline.** `scan.py` builds a conservative `±noise`
  envelope around the point net edge and feeds it to `derive_verdict`; the
  backend serializes whatever the pure function returns. No code path narrates a
  verdict around the function.
- **Honest multiplicity feeds the inference.** The DSR that any richer CI would
  rest on uses `n_trials = pair_legs × fee_grid_points` (never `1`), so scanning
  many venue-pair/fee configurations cannot inflate significance by under-counting
  trials.

## Consequences

- **Positive.** On the consistent (no-dislocation) synthetic fixture, `net_bps` is
  negative and the verdict is `no_feasible_edge`; the honest null is locked by a
  regression test. A feasible verdict is reachable *only* with a large, durable
  gross dislocation under best-case (`low`) costs, exactly the artifact the README
  labels as latency-arb.
- **Positive.** Reviewers can audit the headline by reading one pure function and
  its truth table, not by trusting prose.
- **Cost.** The verdict is intentionally conservative: a genuinely tradeable edge
  near the threshold reads as `marginal`/`no_feasible_edge`. For a diagnostic that
  must not over-claim, false-negative-leaning is the correct bias.
- **Risk addressed.** "Narrated optimism", concluding a positive edge the
  statistics do not support, is made structurally impossible.
</content>
