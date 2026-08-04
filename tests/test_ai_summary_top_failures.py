"""Tests for src.web.app._generate_ai_summary's top_failures computation.

Regression coverage for a bug where passing rows leaked into the "top
misses" list. screener.py writes failed_criteria as '' (empty string,
not NaN) for rows that passed every criterion, so pulling failed_criteria
from the full results dataframe (rather than just the FAIL rows) let a
blank '' entry compete with real failure reasons in value_counts() --
and win, whenever passes outnumbered fails, since .dropna() never drops
an empty string.
"""

from src.web.app import _generate_ai_summary


def _env():
    return {"thesis": ""}


def test_top_failures_excludes_passing_rows_even_when_they_outnumber_fails():
    results = [
        {"ticker": "AAPL", "status": "PASS", "failed_criteria": ""},
        {"ticker": "MSFT", "status": "PASS", "failed_criteria": ""},
        {"ticker": "GOOG", "status": "PASS", "failed_criteria": ""},
        {"ticker": "TSLA", "status": "FAIL", "failed_criteria": "pe_max: too high"},
        {"ticker": "META", "status": "FAIL", "failed_criteria": "roe_min: too low"},
    ]

    result = _generate_ai_summary(_env(), results)

    # Previously "Top misses: ; pe_max: too high; roe_min: too low." --
    # the blank entry from the three PASS rows sorted first since 3 > 1.
    assert "Top misses:" in result["summary"]
    top_misses_line = result["summary"].split("Top misses: ", 1)[1]
    assert not top_misses_line.startswith(";")
    assert "pe_max: too high" in top_misses_line
    assert "roe_min: too low" in top_misses_line


def test_top_failures_omitted_when_all_pass():
    results = [
        {"ticker": "AAPL", "status": "PASS", "failed_criteria": ""},
        {"ticker": "MSFT", "status": "PASS", "failed_criteria": ""},
    ]

    result = _generate_ai_summary(_env(), results)

    assert "Top misses" not in result["summary"]
    assert result["decision"] == "PROCEED"
