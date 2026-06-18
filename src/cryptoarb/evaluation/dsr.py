"""Probabilistic and Deflated Sharpe ratios (Bailey & Lopez de Prado, 2014).

These overfitting guards adjust a realized Sharpe ratio for sample length,
non-normality (skew and kurtosis), and - for the Deflated Sharpe - the number of
configurations tried (multiple-testing / selection bias). The Deflated Sharpe is
the honest yardstick that counts the FULL configuration grid as ``n_trials``.

Importing this module has no side effects.
"""

from __future__ import annotations

import math

from cryptoarb._exceptions import ValidationError

# quantcore-candidate: mirrors pairs-trading:evaluation/dsr.py (cross-checked to
# ma-crossover-backtest:data_snooping.py for the (k+2)/4 term).

# Euler-Mascheroni constant for the expected-maximum order statistic.
_EULER_MASCHERONI: float = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    """Standard-normal CDF via the error function (no SciPy import needed)."""
    # quantcore-candidate: Phi(x) = 0.5 * (1 + erf(x / sqrt(2))).
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Standard-normal inverse CDF (Acklam's rational approximation).

    Accurate to ~1.15e-9 absolute error across ``p in (0, 1)``, which is well
    within the DSR parity tolerance (1e-4 against the Bailey-LdP table).
    """
    # quantcore-candidate: Acklam's algorithm (mirrors pairs:evaluation/dsr.py).
    if not 0.0 < p < 1.0:
        raise ValidationError(f"_norm_ppf requires p in (0, 1), got {p}.")

    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )

    # One Halley refinement step for full double precision.
    e = _norm_cdf(x) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    x = x - u / (1.0 + x * u / 2.0)
    return x


def probabilistic_sharpe_ratio(
    observed_sharpe: float,
    *,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    benchmark_sharpe: float = 0.0,
) -> float:
    r"""Probabilistic Sharpe Ratio: P(true SR > benchmark) given the sample.

    Returns

    .. math::

        \text{PSR} = \Phi\!\left(
            \frac{(\widehat{SR} - SR^\*)\sqrt{n - 1}}
                 {\sqrt{1 - \gamma_3\,\widehat{SR} + \frac{\gamma_4 - 1}{4}\widehat{SR}^2}}
        \right),

    where :math:`\widehat{SR}` is the (non-annualized, per-observation) observed
    Sharpe, :math:`SR^\*` the benchmark Sharpe, :math:`\gamma_3` the skewness,
    :math:`\gamma_4` the kurtosis, and :math:`\Phi` the standard-normal CDF.

    HONESTY REQUIREMENT: ``kurtosis`` here is the **full** (non-excess) kurtosis,
    so a Gaussian has ``kurtosis=3`` and the bracket uses :math:`(\gamma_4 - 1)/4`.
    The excess-vs-full-kurtosis mix-up is a known PSR footgun and is rejected.

    Parameters
    ----------
    observed_sharpe:
        The observed per-observation (non-annualized) Sharpe ratio.
    n_obs:
        The number of return observations.
    skew:
        Sample skewness of the returns (``0`` for symmetric).
    kurtosis:
        Sample FULL kurtosis of the returns (``3`` for Gaussian).
    benchmark_sharpe:
        The per-observation benchmark Sharpe to test against (default ``0``).

    Returns
    -------
    float
        The probabilistic Sharpe ratio in ``[0, 1]``.

    Raises
    ------
    ValidationError
        If ``n_obs < 2``.
    """
    if n_obs < 2:
        raise ValidationError(f"probabilistic_sharpe_ratio requires n_obs >= 2, got {n_obs}.")

    sr = float(observed_sharpe)
    # FULL (non-excess) kurtosis term: (gamma_4 - 1) / 4. For a Gaussian this is
    # (3 - 1) / 4 = 0.5, the canonical Bailey-Lopez de Prado coefficient. This is
    # equivalent to the excess-kurtosis form (k + 2) / 4 with k = gamma_4 - 3.
    variance = 1.0 - skew * sr + 0.25 * (kurtosis - 1.0) * sr * sr
    # The bracket variance is a non-negativity-guaranteed quantity in theory; if
    # numerical inputs push it non-positive the statistic is undefined.
    if variance <= 0.0:
        raise ValidationError(
            "probabilistic_sharpe_ratio: non-positive variance term "
            f"(1 - skew*SR + (kurt-1)/4*SR^2 = {variance}); check skew/kurtosis."
        )

    z = (sr - benchmark_sharpe) * math.sqrt(n_obs - 1) / math.sqrt(variance)
    return _norm_cdf(z)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    *,
    n_obs: int,
    n_trials: int,
    variance_of_trial_sharpes: float,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    r"""Deflated Sharpe Ratio: PSR against a multiplicity-inflated benchmark.

    The DSR is the PSR evaluated against an *expected-maximum* benchmark Sharpe
    that grows with the number of independent trials :math:`N`:

    .. math::

        SR^\*_0 = \sqrt{V}\left[(1 - \gamma)\,\Phi^{-1}\!\left(1 - \tfrac{1}{N}\right)
                  + \gamma\,\Phi^{-1}\!\left(1 - \tfrac{1}{N}e^{-1}\right)\right],

    where :math:`V` is the variance of the trial Sharpe ratios, :math:`\gamma`
    the Euler-Mascheroni constant, and :math:`N` = ``n_trials``. The DSR is then
    ``probabilistic_sharpe_ratio(observed_sharpe, ..., benchmark_sharpe=SR*_0)``.

    HONESTY REQUIREMENT: ``n_trials`` must count the FULL explored configuration
    grid. For the arb scanner that is ``pair-legs x fee-grid-points`` (the number
    of venue-pair legs scanned times the number of fee/cost-sensitivity grid
    points), NEVER ``1`` - a guard in :mod:`cryptoarb.evaluation.netedge` asserts
    this. The PSR uses the FULL ``(\gamma_4)`` kurtosis term. The DSR is
    non-increasing in ``n_trials`` (monotonicity asserted in the property suite).

    Parameters
    ----------
    observed_sharpe:
        The observed per-observation (non-annualized) Sharpe ratio of the
        selected configuration.
    n_obs:
        The number of return observations.
    n_trials:
        The FULL number of configurations explored (the multiplicity count).
    variance_of_trial_sharpes:
        The cross-trial variance :math:`V` of the per-observation Sharpe ratios.
    skew:
        Sample skewness of the selected configuration's returns.
    kurtosis:
        Sample FULL kurtosis of the selected configuration's returns.

    Returns
    -------
    float
        The deflated Sharpe ratio in ``[0, 1]``.

    Raises
    ------
    ValidationError
        If ``n_obs < 2``, ``n_trials < 1``, or
        ``variance_of_trial_sharpes < 0``.
    """
    if n_obs < 2:
        raise ValidationError(f"deflated_sharpe_ratio requires n_obs >= 2, got {n_obs}.")
    if n_trials < 1:
        raise ValidationError(f"deflated_sharpe_ratio requires n_trials >= 1, got {n_trials}.")
    if variance_of_trial_sharpes < 0.0:
        raise ValidationError(
            "deflated_sharpe_ratio requires variance_of_trial_sharpes >= 0, "
            f"got {variance_of_trial_sharpes}."
        )

    # Expected maximum of n_trials i.i.d. trial Sharpes (Gumbel/extreme-value
    # approximation): SR*_0 = sqrt(V) * [ (1 - gamma) * z(1 - 1/N)
    #                                     + gamma * z(1 - 1/(N*e)) ].
    # With a single trial (N == 1) the expected-maximum benchmark collapses to
    # zero, so the DSR reduces to the plain PSR against zero.
    sqrt_v = math.sqrt(variance_of_trial_sharpes)
    n = float(n_trials)
    if n_trials == 1 or sqrt_v == 0.0:
        benchmark = 0.0
    else:
        gamma = _EULER_MASCHERONI
        z1 = _norm_ppf(1.0 - 1.0 / n)
        z2 = _norm_ppf(1.0 - 1.0 / (n * math.e))
        benchmark = sqrt_v * ((1.0 - gamma) * z1 + gamma * z2)

    return probabilistic_sharpe_ratio(
        observed_sharpe,
        n_obs=n_obs,
        skew=skew,
        kurtosis=kurtosis,
        benchmark_sharpe=benchmark,
    )
