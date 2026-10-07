"""Linguagem neutra: nenhuma afirmação causal na interface ou nos relatórios (SPEC §7.3)."""

import re
from pathlib import Path

from backend.app.services import report_service
from backend.app.statistics import binomial

ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN = [
    r"a\s+inten[çc][ãa]o\s+funcionou",
    r"a\s+consci[êe]ncia\s+alterou",
    r"a\s+ora[çc][ãa]o\s+causou",
    r"\bcomprova",
    r"\bprova\s+que\b",
    r"\bprovou\b",
    r"efeito\s+confirmado",
]


def _texts():
    files = list((ROOT / "frontend").rglob("*.*"))
    files += [ROOT / "backend/app/services/report_service.py", ROOT / "backend/app/statistics/binomial.py"]
    for f in files:
        if f.suffix in {".html", ".js", ".css", ".py"}:
            yield f, f.read_text(encoding="utf-8")


def test_no_causal_claims_in_ui_or_reports():
    for path, text in _texts():
        for pattern in FORBIDDEN:
            assert not re.search(pattern, text, re.IGNORECASE), f"{path.name}: {pattern}"


def test_result_statements_are_the_closed_list():
    assert binomial.STATEMENT_NOT_SIGNIFICANT == "Não foi detectado desvio estatisticamente significativo."
    assert binomial.STATEMENT_SIGNIFICANT == "Foi detectado um desvio estatisticamente significativo."
    assert "não é a probabilidade de a hipótese ser verdadeira" in binomial.P_VALUE_EXPLANATION


def test_report_footer():
    assert report_service.FOOTER == (
        "Este relatório descreve os dados observados. Ele não estabelece uma explicação "
        "causal para qualquer desvio observado."
    )
