"""Tests for src.web.app._generate_analysis.

Regression coverage for a bug where averages computed over all-missing
columns (pandas .mean() on an empty/all-NaN Series returns nan, not None)
were rendered into the report text as literal "nan" because the code
checked `avg is not None` instead of testing for NaN.
"""

import pandas as pd

from src.web.app import _generate_analysis


def _results_df(rows):
    return pd.DataFrame(rows)


def test_generate_analysis_reports_averages_when_data_present():
    df = _results_df(
        [
            {"status": "PASS", "pe_ratio": 10.0, "roe": 0.2, "revenue_growth": 0.1, "failed_criteria": None},
            {"status": "FAIL", "pe_ratio": 20.0, "roe": 0.1, "revenue_growth": 0.05, "failed_criteria": "pe_ratio"},
        ]
    )

    text = _generate_analysis(df, criteria_count=2)

    assert "Average P/E: 15.00." in text
    assert "Average ROE: 15.00%." in text
    assert "Average revenue growth: 7.50%." in text


def test_generate_analysis_omits_averages_when_column_is_all_missing():
    df = _results_df(
        [
            {"status": "FAIL", "pe_ratio": None, "roe": None, "revenue_growth": None, "failed_criteria": "pe_ratio"},
            {"status": "FAIL", "pe_ratio": None, "roe": None, "revenue_growth": None, "failed_criteria": "roe"},
        ]
    )

    text = _generate_analysis(df, criteria_count=2)

    # Previously this rendered "Average P/E: nan." etc. because
    # `avg_pe is not None` is True even when avg_pe is float('nan').
    assert "nan" not in text.lower()
    assert "Average P/E" not in text
    assert "Average ROE" not in text
    assert "Average revenue growth" not in text


def test_generate_analysis_handles_empty_results():
    df = _results_df([])
    text = _generate_analysis(df, criteria_count=3)
    assert text == "No results were returned. Check tickers and data availability."
