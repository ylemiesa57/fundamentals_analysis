"""
Unit tests for the DataFetcher module.

Covers the pure-logic pieces of DataFetcher that don't require network
access: ratio calculation, key lookup on pandas Series, and the on-disk
cache read/write path. Before this file, src/data/fetcher.py had no direct
test coverage at all (only exercised indirectly via mocks in
tests/test_screener.py), so bugs in ratio math or cache expiry could slip
through silently.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from src.data.fetcher import DataFetcher


class TestGetValue(unittest.TestCase):
    """Test DataFetcher._get_value key lookup on a pandas Series."""

    def setUp(self):
        self.fetcher = DataFetcher(use_cache=False)

    def test_returns_first_matching_key(self):
        series = pd.Series({'Total Current Assets': 500.0, 'Other': 1.0})
        value = self.fetcher._get_value(series, ['Total Current Assets', 'Current Assets'])
        self.assertEqual(value, 500.0)

    def test_falls_back_to_second_key(self):
        series = pd.Series({'Current Assets': 250.0})
        value = self.fetcher._get_value(series, ['Total Current Assets', 'Current Assets'])
        self.assertEqual(value, 250.0)

    def test_missing_key_returns_none(self):
        series = pd.Series({'Unrelated Field': 1.0})
        value = self.fetcher._get_value(series, ['Total Current Assets', 'Current Assets'])
        self.assertIsNone(value)

    def test_empty_series_returns_none(self):
        value = self.fetcher._get_value(pd.Series(dtype=object), ['Total Current Assets'])
        self.assertIsNone(value)

    def test_nan_value_returns_none(self):
        series = pd.Series({'Total Current Assets': float('nan')})
        value = self.fetcher._get_value(series, ['Total Current Assets'])
        self.assertIsNone(value)

    def test_non_numeric_value_returns_none(self):
        series = pd.Series({'Total Current Assets': 'not a number'})
        value = self.fetcher._get_value(series, ['Total Current Assets'])
        self.assertIsNone(value)

    def test_value_is_cast_to_float(self):
        series = pd.Series({'Total Current Assets': 100})
        value = self.fetcher._get_value(series, ['Total Current Assets'])
        self.assertIsInstance(value, float)
        self.assertEqual(value, 100.0)


class TestCalculateRatios(unittest.TestCase):
    """Test DataFetcher.calculate_ratios given fabricated financial data."""

    def setUp(self):
        self.fetcher = DataFetcher(use_cache=False)

    def _make_financial_data(self, **overrides):
        data = {
            'income_statement': pd.Series({
                'Total Revenue': 1000.0,
                'Net Income': 100.0,
            }),
            'balance_sheet': pd.Series({
                'Total Current Assets': 300.0,
                'Total Current Liabilities': 150.0,
                'Total Debt': 200.0,
                'Total Stockholders Equity': 500.0,
            }),
            'prev_income_statement': pd.Series({
                'Total Revenue': 800.0,
            }),
        }
        data.update(overrides)
        return data

    def test_none_financial_data_returns_empty_dict(self):
        self.assertEqual(self.fetcher.calculate_ratios(None), {})

    def test_all_ratios_calculated_correctly(self):
        ratios = self.fetcher.calculate_ratios(self._make_financial_data())
        self.assertAlmostEqual(ratios['current_ratio'], 300.0 / 150.0)
        self.assertAlmostEqual(ratios['debt_to_equity'], 200.0 / 500.0)
        self.assertAlmostEqual(ratios['roe'], 100.0 / 500.0)
        self.assertAlmostEqual(ratios['revenue_growth'], (1000.0 - 800.0) / 800.0)
        self.assertEqual(ratios['net_income'], 100.0)

    def test_zero_current_liabilities_avoids_division_by_zero(self):
        data = self._make_financial_data(balance_sheet=pd.Series({
            'Total Current Assets': 300.0,
            'Total Current Liabilities': 0.0,
            'Total Debt': 200.0,
            'Total Stockholders Equity': 500.0,
        }))
        ratios = self.fetcher.calculate_ratios(data)
        self.assertIsNone(ratios['current_ratio'])

    def test_zero_shareholders_equity_avoids_division_by_zero(self):
        data = self._make_financial_data(balance_sheet=pd.Series({
            'Total Current Assets': 300.0,
            'Total Current Liabilities': 150.0,
            'Total Debt': 200.0,
            'Total Stockholders Equity': 0.0,
        }))
        ratios = self.fetcher.calculate_ratios(data)
        self.assertIsNone(ratios['debt_to_equity'])
        self.assertIsNone(ratios['roe'])

    def test_zero_prev_revenue_avoids_division_by_zero(self):
        data = self._make_financial_data(prev_income_statement=pd.Series({'Total Revenue': 0.0}))
        ratios = self.fetcher.calculate_ratios(data)
        self.assertIsNone(ratios['revenue_growth'])

    def test_missing_balance_sheet_fields_yield_none_ratios(self):
        data = self._make_financial_data(balance_sheet=pd.Series(dtype=object))
        ratios = self.fetcher.calculate_ratios(data)
        self.assertIsNone(ratios['current_ratio'])
        self.assertIsNone(ratios['debt_to_equity'])
        self.assertIsNone(ratios['roe'])

    def test_alternate_key_names_are_used_as_fallback(self):
        data = self._make_financial_data(
            balance_sheet=pd.Series({
                'Current Assets': 300.0,
                'Current Liabilities': 150.0,
                'Total Liabilities Net Minority Interest': 200.0,
                'Stockholders Equity': 500.0,
            }),
            income_statement=pd.Series({
                'Total Revenue': 1000.0,
                'Net Income Common Stockholders': 100.0,
            }),
        )
        ratios = self.fetcher.calculate_ratios(data)
        self.assertAlmostEqual(ratios['current_ratio'], 2.0)
        self.assertAlmostEqual(ratios['debt_to_equity'], 0.4)
        self.assertAlmostEqual(ratios['roe'], 0.2)


class TestCacheReadWrite(unittest.TestCase):
    """Test DataFetcher's on-disk cache: path derivation, freshness, and I/O."""

    def test_cache_path_sanitizes_ticker(self):
        with TemporaryDirectory() as tmp:
            fetcher = DataFetcher(cache_dir=Path(tmp), use_cache=True)
            path = fetcher._cache_path('brk/b')
            self.assertEqual(path.name, 'BRK_B.pkl')

    def test_write_then_load_round_trips(self):
        with TemporaryDirectory() as tmp:
            fetcher = DataFetcher(cache_dir=Path(tmp), use_cache=True, cache_ttl_hours=24.0)
            payload = {'ticker': 'AAPL', 'market_cap': 123.0}
            fetcher._write_cache('AAPL', payload)
            loaded = fetcher._load_cache('AAPL')
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded['ticker'], 'AAPL')
            self.assertTrue(loaded['_cache_hit'])

    def test_missing_cache_file_returns_none(self):
        with TemporaryDirectory() as tmp:
            fetcher = DataFetcher(cache_dir=Path(tmp), use_cache=True)
            self.assertIsNone(fetcher._load_cache('NOPE'))

    def test_expired_cache_is_not_returned(self):
        with TemporaryDirectory() as tmp:
            # Use a negative TTL so any freshly written entry is already "stale".
            fetcher = DataFetcher(cache_dir=Path(tmp), use_cache=True, cache_ttl_hours=-1.0)
            fetcher._write_cache('AAPL', {'ticker': 'AAPL'})
            self.assertIsNone(fetcher._load_cache('AAPL'))

    def test_corrupted_cache_file_returns_none(self):
        with TemporaryDirectory() as tmp:
            fetcher = DataFetcher(cache_dir=Path(tmp), use_cache=True)
            cache_path = fetcher._cache_path('AAPL')
            cache_path.write_bytes(b'not a valid pickle')
            self.assertIsNone(fetcher._load_cache('AAPL'))


if __name__ == '__main__':
    unittest.main()
