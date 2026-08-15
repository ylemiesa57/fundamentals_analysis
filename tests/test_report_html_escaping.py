"""
Regression tests for HTML-escaping in generated thesis reports.

_build_report_sections()/_write_report() used to interpolate several
free-text fields directly into raw HTML: the environment's "name" and
"thesis" (both typed by the user into the web UI with no character
restrictions), "criteria" values, and every results-table cell -- which
includes ticker company names sourced from yfinance (e.g. "AT&T Inc.",
"Johnson & Johnson"). An unescaped "<" or "&" in any of these corrupted
the generated report's HTML structure, and an unescaped "<" could inject
markup into a report someone else later opens in a browser.
"""

import pandas as pd

from src.web.app import _build_report_sections, _write_report


def _results_df():
    return pd.DataFrame(
        [
            {
                "ticker": "T",
                "company_name": "AT&T Inc.",
                "status": "PASS",
                "failed_criteria": "",
                "error": None,
            },
            {
                "ticker": "XYZ",
                "company_name": "<script>alert(1)</script>",
                "status": "FAIL",
                "failed_criteria": "pe_max: too high",
                "error": None,
            },
        ]
    )


def test_thesis_and_name_are_escaped_in_report_sections():
    env = {
        "thesis": "P/E < 20 & margin > 10%",
        "tickers": ["<b>AAPL</b>"],
        "criteria": {"pe_max": "20 & rising"},
        "use_default_criteria": True,
    }
    sections = _build_report_sections(env, _results_df(), "analysis text")

    for section_html in sections.values():
        assert "<b>AAPL</b>" not in section_html
        assert "P/E < 20 & margin > 10%" not in section_html

    assert "P/E &lt; 20 &amp; margin &gt; 10%" in sections["overview"]
    assert "&lt;b&gt;AAPL&lt;/b&gt;" in sections["overview"]


def test_company_name_and_env_name_are_escaped_in_written_html(tmp_path, monkeypatch):
    import src.web.app as app_module

    monkeypatch.setattr(app_module, "REPORTS_DIR", tmp_path)

    env = {
        "id": "env-1",
        "name": "<script>alert('x')</script>",
        "thesis": "",
        "tickers": ["T", "XYZ"],
        "criteria": {},
        "use_default_criteria": True,
    }
    paths = _write_report(env, _results_df(), "analysis text")
    html_text = open(paths["html"]).read()

    # The raw script tag must never appear unescaped in the output.
    assert "<script>alert('x')</script>" not in html_text
    assert "<script>alert(1)</script>" not in html_text

    # Escaped forms should be present instead.
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html_text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_text
    # A plain ampersand in a company name should also be escaped.
    assert "AT&amp;T Inc." in html_text


def test_analysis_text_is_escaped_in_written_html(tmp_path, monkeypatch):
    import src.web.app as app_module

    monkeypatch.setattr(app_module, "REPORTS_DIR", tmp_path)

    env = {
        "id": "env-1",
        "name": "Test Env",
        "thesis": "",
        "tickers": ["TEST"],
        "criteria": {},
        "use_default_criteria": True,
    }
    
    # Create a DataFrame that will generate analysis text with special characters
    results_df = pd.DataFrame([{
        "ticker": "TEST",
        "company_name": "Test Corp",
        "status": "FAIL",
        "failed_criteria": "<b>bad_ratio</b>",  # This also tests failed_criteria escaping in table
        "error": None,
        "pe_ratio": None,
        "roe": None,
        "revenue_growth": None,
    }])
    
    # Pass analysis text that contains HTML-like content
    analysis_text = "Pass rate: 0/1. Most misses: <script>alert(1)</script>."
    paths = _write_report(env, results_df, analysis_text)
    html_text = open(paths["html"]).read()
    
    # The unescaped script tag must never appear in the analysis div
    assert "<script>alert(1)</script>" not in html_text
    
    # The escaped form should be present in the analysis div
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_text
    
    # Also verify the failed_criteria in the table is escaped
    assert "&lt;b&gt;bad_ratio&lt;/b&gt;" in html_text
