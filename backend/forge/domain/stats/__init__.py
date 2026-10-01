"""Statistics used by benchmarks, experiments and calibration (pure, seeded, vectorised).

See each module for the statistical assumptions: :mod:`.bootstrap` (percentile bootstrap, paired),
:mod:`.significance` (Wilcoxon signed-rank), :mod:`.agreement` (correlations, weighted kappa),
:mod:`.descriptive` (means, medians, dispersion, pooled noise).
"""

from forge.domain.stats.agreement import (
    DEFAULT_AGREEMENT_TOLERANCE,
    agreement_rate,
    mean_absolute_error,
    pearson,
    quadratic_weighted_kappa,
    spearman,
    to_ordinal,
)
from forge.domain.stats.bootstrap import (
    DEFAULT_CONFIDENCE,
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    BootstrapResult,
    bootstrap_mean,
    paired_bootstrap,
)
from forge.domain.stats.descriptive import (
    as_array,
    mean,
    median,
    p95,
    percentile,
    pooled_std,
    rate,
    std,
    total,
)
from forge.domain.stats.significance import wilcoxon_signed_rank

__all__ = [
    "DEFAULT_AGREEMENT_TOLERANCE",
    "DEFAULT_CONFIDENCE",
    "DEFAULT_RESAMPLES",
    "DEFAULT_SEED",
    "BootstrapResult",
    "agreement_rate",
    "as_array",
    "bootstrap_mean",
    "mean",
    "mean_absolute_error",
    "median",
    "p95",
    "paired_bootstrap",
    "pearson",
    "percentile",
    "pooled_std",
    "quadratic_weighted_kappa",
    "rate",
    "spearman",
    "std",
    "to_ordinal",
    "total",
    "wilcoxon_signed_rank",
]
