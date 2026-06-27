"""Probabilistic and Deflated Sharpe ratios (Bailey & Lopez de Prado, 2014).

These overfitting guards adjust a realized Sharpe ratio for sample length,
non-normality (skew and kurtosis), and - for the Deflated Sharpe - the number of
configurations tried (multiple-testing / selection bias). The Deflated Sharpe is
the honest yardstick that counts the FULL configuration grid as ``n_trials``.

The numeric kernel is delegated VERBATIM to :mod:`quantcore.dsr` (the shared,
byte-identical honest-statistics package): the inverse-normal approximation
(``_norm_ppf`` / ``_norm_cdf``), the PSR and the DSR are proven byte-identical to
this repo's former local copy on a random-input grid (exact ``==``). The thin
wrappers here keep the local public names, signatures, annotations, and the
local :class:`cryptoarb.ValidationError` contract: ``quantcore`` raises its OWN
``ValidationError`` (no shared ancestry with this repo's), so each delegated call
is wrapped to re-raise as :class:`cryptoarb.ValidationError` with the IDENTICAL
message string (the message strings are byte-identical across the two packages,
so every ``match=`` regex in the test suite still binds).

Importing this module has no side effects.
"""

from __future__ import annotations

from quantcore._exceptions import ValidationError as _QuantCoreValidationError
from quantcore.dsr import _norm_cdf as _qc_norm_cdf
from quantcore.dsr import _norm_ppf as _qc_norm_ppf
from quantcore.dsr import deflated_sharpe_ratio as _qc_deflated_sharpe_ratio
from quantcore.dsr import probabilistic_sharpe_ratio as _qc_probabilistic_sharpe_ratio

from cryptoarb._exceptions import ValidationError

# Re-exported byte-identical from quantcore (proven exact ``==`` on a random grid).
# Re-exported keeping the repo's former public name + signature.

# Euler-Mascheroni constant for the expected-maximum order statistic.
_EULER_MASCHERONI: float = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    """Standard-normal CDF via the error function (no SciPy import needed)."""
    # Delegated byte-identically to quantcore.dsr._norm_cdf.
    return _qc_norm_cdf(x)


def _norm_ppf(p: float) -> float:
    """Standard-normal inverse CDF (Acklam's rational approximation).

    Accurate to ~1.15e-9 absolute error across ``p in (0, 1)``, which is well
    within the DSR parity tolerance (1e-4 against the Bailey-LdP table).
    """
    # Delegated byte-identically to quantcore.dsr._norm_ppf; translate the
    # domain-guard exception to the repo's ValidationError (identical message).
    try:
        return _qc_norm_ppf(p)
    except _QuantCoreValidationError as exc:
        raise ValidationError(str(exc)) from exc


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
    # Delegated byte-identically to quantcore.dsr.probabilistic_sharpe_ratio;
    # translate quantcore's ValidationError to the repo's (identical message).
    try:
        return _qc_probabilistic_sharpe_ratio(
            observed_sharpe,
            n_obs=n_obs,
            skew=skew,
            kurtosis=kurtosis,
            benchmark_sharpe=benchmark_sharpe,
        )
    except _QuantCoreValidationError as exc:
        raise ValidationError(str(exc)) from exc


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
    # Delegated byte-identically to quantcore.dsr.deflated_sharpe_ratio;
    # translate quantcore's ValidationError to the repo's (identical message).
    try:
        return _qc_deflated_sharpe_ratio(
            observed_sharpe,
            n_obs=n_obs,
            n_trials=n_trials,
            variance_of_trial_sharpes=variance_of_trial_sharpes,
            skew=skew,
            kurtosis=kurtosis,
        )
    except _QuantCoreValidationError as exc:
        raise ValidationError(str(exc)) from exc
