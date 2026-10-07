"""Teste binomial exato e métricas descritivas (SPEC §7).

A medida primária é HITS: número de eventos com bit == alvo.
H0: P(hit) = 0,5. A direção do teste e o α vêm do pré-registro.
"""

import math

from scipy.stats import binomtest

from ..models.enums import Alternative

EXPECTED_PROPORTION = 0.5
CONFIDENCE_LEVEL = 0.95
DEFAULT_ALPHA = 0.05

STATEMENT_NOT_SIGNIFICANT = "Não foi detectado desvio estatisticamente significativo."
STATEMENT_SIGNIFICANT = "Foi detectado um desvio estatisticamente significativo."

P_VALUE_EXPLANATION = (
    "O p-value indica quão incomum seria um resultado pelo menos tão extremo quanto este "
    "se apenas o acaso estivesse atuando (H0 verdadeira). Ele não é a probabilidade de a "
    "hipótese ser verdadeira, e um resultado isolado não estabelece causa."
)

_SCIPY_ALTERNATIVE = {Alternative.TWO_SIDED: "two-sided", Alternative.GREATER: "greater"}


def binomial_analysis(n: int, hits: int, alternative: Alternative, alpha: float = DEFAULT_ALPHA) -> dict:
    if n < 1:
        raise ValueError("n deve ser >= 1")
    if not 0 <= hits <= n:
        raise ValueError("hits fora do intervalo [0, n]")
    alternative = Alternative(alternative)

    result = binomtest(hits, n, p=EXPECTED_PROPORTION, alternative=_SCIPY_ALTERNATIVE[alternative])
    # IC sempre bilateral (Clopper-Pearson exato), independentemente da direção do teste.
    ci = binomtest(hits, n, p=EXPECTED_PROPORTION).proportion_ci(CONFIDENCE_LEVEL, method="exact")

    observed = hits / n
    deviation = observed - EXPECTED_PROPORTION
    p_value = float(min(1.0, result.pvalue))
    significant = p_value < alpha
    return {
        "n": n,
        "hits": hits,
        "observed_proportion": observed,
        "expected_proportion": EXPECTED_PROPORTION,
        "absolute_deviation": deviation,
        "deviation_pp": 100 * deviation,
        "z_score": (hits - n / 2) / math.sqrt(n / 4),
        "statistical_test": "BINOMIAL_EXACT",
        "alternative_hypothesis": str(alternative),
        "alpha": alpha,
        "p_value": p_value,
        "ci_method": "CLOPPER_PEARSON",
        "confidence_level": CONFIDENCE_LEVEL,
        "ci_95": [float(ci.low), float(ci.high)],
        "significant": significant,
        "result_statement": STATEMENT_SIGNIFICANT if significant else STATEMENT_NOT_SIGNIFICANT,
    }


def minimum_detectable_deviation_pp(n: int) -> float:
    """Desvio aproximado (p.p.) detectável com teste bilateral a 5% — não usa dados."""
    return 100 * 1.959963984540054 * 0.5 / math.sqrt(n)
