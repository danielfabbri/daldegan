"""Testes estatísticos com datasets conhecidos (SPEC §15.3)."""

import math

import pytest

from backend.app.models.enums import Alternative
from backend.app.statistics.binomial import (
    STATEMENT_NOT_SIGNIFICANT,
    STATEMENT_SIGNIFICANT,
    binomial_analysis,
    minimum_detectable_deviation_pp,
)


def test_balanced_10000_bits():
    r = binomial_analysis(10_000, 5_000, Alternative.TWO_SIDED)
    assert r["observed_proportion"] == pytest.approx(0.5)
    assert r["p_value"] == pytest.approx(1.0)
    assert r["z_score"] == 0
    assert r["significant"] is False
    assert r["result_statement"] == STATEMENT_NOT_SIGNIFICANT
    assert r["ci_95"][0] < 0.5 < r["ci_95"][1]


@pytest.mark.parametrize("hits", [4_500, 5_500])  # 5.500 zeros / 4.500 uns, com alvo 1 ou 0
def test_5500_vs_4500_is_detected(hits):
    r = binomial_analysis(10_000, hits, Alternative.TWO_SIDED)
    assert r["significant"] is True
    assert r["p_value"] < 1e-20
    assert abs(r["z_score"]) == pytest.approx(10.0)
    assert r["result_statement"] == STATEMENT_SIGNIFICANT


def test_directional_test_in_opposite_direction_is_not_significant():
    r = binomial_analysis(10_000, 4_500, Alternative.GREATER)
    assert r["significant"] is False
    assert r["p_value"] > 0.99


def test_directional_test_in_predicted_direction():
    two = binomial_analysis(10_000, 5_100, Alternative.TWO_SIDED)
    one = binomial_analysis(10_000, 5_100, Alternative.GREATER)
    assert one["p_value"] == pytest.approx(two["p_value"] / 2, rel=1e-6)


@pytest.mark.parametrize(
    "n,hits",
    [(10, 0), (10, 10), (10, 5), (1, 1), (1_000_000, 500_000), (1_000_000, 0)],
)
def test_extreme_cases_are_well_defined(n, hits):
    r = binomial_analysis(n, hits, Alternative.TWO_SIDED)
    assert 0.0 <= r["p_value"] <= 1.0
    assert 0.0 <= r["ci_95"][0] <= r["observed_proportion"] <= r["ci_95"][1] <= 1.0
    assert not math.isnan(r["z_score"])


def test_all_zeros_small_sample():
    r = binomial_analysis(10, 0, Alternative.TWO_SIDED)
    assert r["p_value"] == pytest.approx(2 * 0.5**10)
    assert r["significant"] is True
    assert r["ci_95"][0] == 0.0


def test_clopper_pearson_reference_values():
    # Referência: IC exato 95% para 5/10 = [0.187086, 0.812914]
    r = binomial_analysis(10, 5, Alternative.TWO_SIDED)
    assert r["ci_95"][0] == pytest.approx(0.187086, abs=1e-6)
    assert r["ci_95"][1] == pytest.approx(0.812914, abs=1e-6)


def test_z_score_matches_manual_formula():
    r = binomial_analysis(10_000, 5_028, Alternative.TWO_SIDED)
    assert r["z_score"] == pytest.approx((5_028 - 5_000) / 50)
    assert r["deviation_pp"] == pytest.approx(0.28)
    assert r["significant"] is False


def test_invalid_inputs():
    with pytest.raises(ValueError):
        binomial_analysis(0, 0, Alternative.TWO_SIDED)
    with pytest.raises(ValueError):
        binomial_analysis(10, 11, Alternative.TWO_SIDED)


def test_minimum_detectable_deviation_does_not_need_data():
    assert minimum_detectable_deviation_pp(10_000) == pytest.approx(0.98, abs=0.01)
    assert minimum_detectable_deviation_pp(100) > minimum_detectable_deviation_pp(100_000)
