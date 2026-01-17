"""
Unit tests for the screener module.

Tests screening functionality, criteria evaluation, and error handling.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import pandas as pd

from src.screener.screener import StockScreener
from src.utils.cli import _load_tickers_from_file
from src.screener.criteria import (
    min_market_cap, max_pe_ratio, min_current_ratio,
    max_debt_to_equity, min_revenue_growth, positive_earnings, min_roe,
    build_criteria_functions, parse_inline_criteria
)


class TestCriteriaFunctions(unittest.TestCase):
    """Test individual criterion evaluation functions."""
    
    def test_min_market_cap_pass(self):
        """Test market cap criterion when value meets minimum."""
        criterion = min_market_cap(1000000000)  # $1B minimum
        data = {'market_cap': 2000000000}
        passed, reason = criterion(data)
        self.assertTrue(passed)
        self.assertEqual(reason, "")
    
    def test_min_market_cap_fail(self):
        """Test market cap criterion when value below minimum."""
        criterion = min_market_cap(1000000000)
        data = {'market_cap': 500000000}
        passed, reason = criterion(data)
        self.assertFalse(passed)
        self.assertIn("market_cap_below_min", reason)
    
    def test_max_pe_ratio_pass(self):
        """Test P/E ratio criterion when value below maximum."""
        criterion = max_pe_ratio(25)
        data = {'pe_ratio': 20}
        passed, reason = criterion(data)
        self.assertTrue(passed)
    
    def test_max_pe_ratio_fail(self):
        """Test P/E ratio criterion when value above maximum."""
        criterion = max_pe_ratio(25)
        data = {'pe_ratio': 30}
        passed, reason = criterion(data)
        self.assertFalse(passed)
        self.assertIn("pe_ratio_above_max", reason)
    
    def test_min_current_ratio_pass(self):
        """Test current ratio criterion when value meets minimum."""
        criterion = min_current_ratio(1.5)
        data = {'current_ratio': 2.0}
        passed, reason = criterion(data)
        self.assertTrue(passed)
    
    def test_min_current_ratio_fail(self):
        """Test current ratio criterion when value below minimum."""
        criterion = min_current_ratio(1.5)
        data = {'current_ratio': 1.0}
        passed, reason = criterion(data)
        self.assertFalse(passed)
    
    def test_max_debt_to_equity_pass(self):
        """Test debt-to-equity criterion when value below maximum."""
        criterion = max_debt_to_equity(1.0)
        data = {'debt_to_equity': 0.5}
        passed, reason = criterion(data)
        self.assertTrue(passed)
    
    def test_max_debt_to_equity_fail(self):
        """Test debt-to-equity criterion when value above maximum."""
        criterion = max_debt_to_equity(1.0)
        data = {'debt_to_equity': 2.0}
        passed, reason = criterion(data)
        self.assertFalse(passed)
    
    def test_min_revenue_growth_pass(self):
        """Test revenue growth criterion when value meets minimum."""
        criterion = min_revenue_growth(0.05)  # 5% minimum
        data = {'revenue_growth': 0.10}  # 10% growth
        passed, reason = criterion(data)
        self.assertTrue(passed)
    
    def test_min_revenue_growth_fail(self):
        """Test revenue growth criterion when value below minimum."""
        criterion = min_revenue_growth(0.05)
        data = {'revenue_growth': 0.02}  # 2% growth
        passed, reason = criterion(data)
        self.assertFalse(passed)
    
    def test_positive_earnings_pass(self):
        """Test positive earnings criterion when earnings are positive."""
        criterion = positive_earnings()
        data = {'net_income': 1000000}
        passed, reason = criterion(data)
        self.assertTrue(passed)
    
    def test_positive_earnings_fail(self):
        """Test positive earnings criterion when earnings are negative."""
        criterion = positive_earnings()
        data = {'net_income': -1000000}
        passed, reason = criterion(data)
        self.assertFalse(passed)
        self.assertIn("negative_earnings", reason)
    
    def test_min_roe_pass(self):
        """Test ROE criterion when value meets minimum."""
        criterion = min_roe(0.15)  # 15% minimum
        data = {'roe': 0.20}  # 20% ROE
        passed, reason = criterion(data)
        self.assertTrue(passed)
    
    def test_min_roe_fail(self):
        """Test ROE criterion when value below minimum."""
        criterion = min_roe(0.15)
        data = {'roe': 0.10}  # 10% ROE
        passed, reason = criterion(data)
        self.assertFalse(passed)
    
    def test_missing_data(self):
        """Test criteria handle missing data gracefully."""
        criterion = min_market_cap(1000000000)
        data = {'market_cap': None}
        passed, reason = criterion(data)
        self.assertFalse(passed)
        self.assertIn("missing", reason.lower())


class TestCriteriaParsing(unittest.TestCase):
    """Test criteria parsing and building."""
    
    def test_parse_inline_criteria(self):
        """Test parsing inline criteria string."""
        criteria_str = "pe_max=25,market_cap_min=1000000000,roe_min=0.15"
        result = parse_inline_criteria(criteria_str)
        
        self.assertEqual(result['pe_max'], 25.0)
        self.assertEqual(result['market_cap_min'], 1000000000.0)
        self.assertEqual(result['roe_min'], 0.15)
    
    def test_parse_inline_criteria_boolean(self):
        """Test parsing boolean values in inline criteria."""
        criteria_str = "positive_earnings=true"
        result = parse_inline_criteria(criteria_str)
        
        self.assertTrue(result['positive_earnings'])
    
    def test_build_criteria_functions(self):
        """Test building criterion functions from config."""
        config = {
            'market_cap_min': 1000000000,
            'pe_max': 25,
            'positive_earnings': True
        }
        functions = build_criteria_functions(config)
        
        self.assertEqual(len(functions), 3)
        self.assertTrue(all(isinstance(f[1], type(lambda x: x)) or callable(f[1]) for f in functions))


class TestStockScreener(unittest.TestCase):
    """Test StockScreener class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.criteria_config = {
            'market_cap_min': 1000000000,
            'pe_max': 25,
            'current_ratio_min': 1.5
        }
    
    @patch('src.screener.screener.DataFetcher')
    def test_screen_ticker_success(self, mock_fetcher_class):
        """Test successful screening of a ticker."""
        # Mock the fetcher
        mock_fetcher = Mock()
        mock_fetcher.get_financial_data.return_value = {
            'ticker': 'AAPL',
            'company_name': 'Apple Inc.',
            'market_cap': 2000000000,
            'pe_ratio': 20,
            'income_statement': pd.Series({'Total Revenue': 100000000}),
            'balance_sheet': pd.Series({'Total Current Assets': 150000000, 'Total Current Liabilities': 100000000}),
            'prev_income_statement': pd.Series({'Total Revenue': 90000000}),
            'info': {}
        }
        mock_fetcher.calculate_ratios.return_value = {
            'current_ratio': 1.5,
            'debt_to_equity': 0.5,
            'revenue_growth': 0.11,
            'roe': 0.20,
            'net_income': 10000000
        }
        mock_fetcher_class.return_value = mock_fetcher
        
        screener = StockScreener(self.criteria_config)
        result = screener.screen_ticker('AAPL')
        
        self.assertEqual(result['ticker'], 'AAPL')
        self.assertEqual(result['company_name'], 'Apple Inc.')
        self.assertIn('status', result)
        self.assertIn('passed_criteria', result)
    
    @patch('src.screener.screener.DataFetcher')
    def test_screen_ticker_fetch_failure(self, mock_fetcher_class):
        """Test handling of data fetch failure."""
        mock_fetcher = Mock()
        mock_fetcher.get_financial_data.return_value = None
        mock_fetcher_class.return_value = mock_fetcher
        
        screener = StockScreener(self.criteria_config)
        result = screener.screen_ticker('INVALID')
        
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['passed_criteria'], 0)
        self.assertIn('error', result)
    
    @patch('src.screener.screener.DataFetcher')
    def test_screen_list(self, mock_fetcher_class):
        """Test screening multiple tickers."""
        mock_fetcher = Mock()
        mock_fetcher.get_financial_data.return_value = {
            'ticker': 'AAPL',
            'company_name': 'Apple Inc.',
            'market_cap': 2000000000,
            'pe_ratio': 20,
            'income_statement': pd.Series({'Total Revenue': 100000000}),
            'balance_sheet': pd.Series({'Total Current Assets': 150000000, 'Total Current Liabilities': 100000000}),
            'prev_income_statement': pd.Series({'Total Revenue': 90000000}),
            'info': {}
        }
        mock_fetcher.calculate_ratios.return_value = {
            'current_ratio': 1.5,
            'debt_to_equity': 0.5,
            'revenue_growth': 0.11,
            'roe': 0.20,
            'net_income': 10000000
        }
        mock_fetcher_class.return_value = mock_fetcher
        
        screener = StockScreener(self.criteria_config)
        results_df = screener.screen_list(['AAPL', 'MSFT'])
        
        self.assertIsInstance(results_df, pd.DataFrame)
        self.assertEqual(len(results_df), 2)
        self.assertIn('ticker', results_df.columns)
        self.assertIn('status', results_df.columns)
    
    def test_filter_by_criteria(self):
        """Test filtering DataFrame by criteria."""
        df = pd.DataFrame({
            'ticker': ['AAPL', 'MSFT', 'GOOGL'],
            'status': ['PASS', 'FAIL', 'PASS']
        })
        
        screener = StockScreener(self.criteria_config)
        filtered = screener.filter_by_criteria(df)
        
        self.assertEqual(len(filtered), 2)
        self.assertTrue(all(filtered['status'] == 'PASS'))


class TestTickerFileParsing(unittest.TestCase):
    """Test ticker file parsing utility."""

    def test_load_tickers_from_file(self):
        """Parse tickers from newline and comma separated input."""
        import tempfile
        content = "AAPL, msft\n# comment line\nGOOGL\nAMZN, META\n"
        with tempfile.NamedTemporaryFile(mode='w+', delete=True) as tmp:
            tmp.write(content)
            tmp.flush()
            tickers = _load_tickers_from_file(Path(tmp.name))
        self.assertEqual(tickers, ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META'])


if __name__ == '__main__':
    unittest.main()
