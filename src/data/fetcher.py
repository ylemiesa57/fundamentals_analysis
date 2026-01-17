"""
Data fetcher module for retrieving financial data from yfinance.

This module handles fetching income statements, balance sheets, and key metrics,
as well as calculating financial ratios for analysis.
"""

import time
import logging
import pickle
from typing import Dict, Optional, Any
from pathlib import Path
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


class DataFetcher:
    """
    Fetches financial data from yfinance and calculates key financial ratios.
    
    Handles API rate limiting, error recovery, and data validation.
    """
    
    def __init__(
        self,
        delay_between_requests: float = 0.5,
        cache_dir: Optional[Path] = None,
        cache_ttl_hours: float = 24.0,
        use_cache: bool = True,
    ):
        """
        Initialize the DataFetcher.
        
        Args:
            delay_between_requests: Seconds to wait between API requests to avoid rate limiting
        """
        self.delay_between_requests = delay_between_requests
        self._last_request_time = 0
        self.cache_ttl_seconds = cache_ttl_hours * 3600
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir) if cache_dir else Path(__file__).parent.parent.parent / 'data' / 'cache'
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, ticker: str) -> Path:
        """Get cache file path for a ticker."""
        safe_ticker = ticker.upper().replace('/', '_')
        return self.cache_dir / f"{safe_ticker}.pkl"

    def _load_cache(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Load cached data if it exists and is fresh."""
        cache_path = self._cache_path(ticker)
        if not cache_path.exists():
            return None
        try:
            age_seconds = time.time() - cache_path.stat().st_mtime
            if age_seconds > self.cache_ttl_seconds:
                return None
            with open(cache_path, 'rb') as f:
                cached = pickle.load(f)
            if isinstance(cached, dict):
                cached['_cache_hit'] = True
                return cached
        except Exception as e:
            logger.warning(f"Failed to read cache for {ticker}: {str(e)}")
        return None

    def _write_cache(self, ticker: str, data: Dict[str, Any]) -> None:
        """Write fetched data to cache."""
        cache_path = self._cache_path(ticker)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.warning(f"Failed to write cache for {ticker}: {str(e)}")
    
    def _rate_limit(self):
        """Add delay between requests to avoid rate limiting."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self.delay_between_requests:
            time.sleep(self.delay_between_requests - time_since_last)
        self._last_request_time = time.time()
    
    def get_financial_data(self, ticker: str, retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        Fetch all financial data needed for screening.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            retries: Number of retry attempts on failure
            
        Returns:
            Dictionary containing financial data, or None if fetch fails
        """
        if self.use_cache:
            cached = self._load_cache(ticker)
            if cached is not None:
                return cached

        self._rate_limit()
        
        for attempt in range(retries):
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                
                # Get financial statements (annual)
                income_stmt = stock.financials
                balance_sheet = stock.balance_sheet
                
                # Extract key metrics from info
                market_cap = info.get('marketCap')
                pe_ratio = info.get('trailingPE')
                company_name = info.get('longName', ticker)
                
                # Get income statement data (most recent year)
                if income_stmt.empty:
                    logger.warning(f"No income statement data available for {ticker}")
                    return None
                
                # Get balance sheet data (most recent year)
                if balance_sheet.empty:
                    logger.warning(f"No balance sheet data available for {ticker}")
                    return None
                
                # Extract most recent year's data (first column)
                latest_income = income_stmt.iloc[:, 0] if len(income_stmt.columns) > 0 else pd.Series()
                latest_balance = balance_sheet.iloc[:, 0] if len(balance_sheet.columns) > 0 else pd.Series()
                
                # Get previous year for growth calculations
                prev_income = income_stmt.iloc[:, 1] if len(income_stmt.columns) > 1 else pd.Series()
                
                financial_data = {
                    'ticker': ticker,
                    'company_name': company_name,
                    'market_cap': market_cap,
                    'pe_ratio': pe_ratio,
                    'income_statement': latest_income,
                    'balance_sheet': latest_balance,
                    'prev_income_statement': prev_income,
                    'info': info
                }
                
                if self.use_cache:
                    self._write_cache(ticker, financial_data)
                return financial_data
                
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{retries} failed for {ticker}: {str(e)}")
                if attempt < retries - 1:
                    time.sleep(1 * (attempt + 1))  # Exponential backoff
                else:
                    logger.error(f"Failed to fetch data for {ticker} after {retries} attempts")
                    return None
        
        return None
    
    def calculate_ratios(self, financial_data: Dict[str, Any]) -> Dict[str, Optional[float]]:
        """
        Calculate financial ratios from fetched data.
        
        Args:
            financial_data: Dictionary returned by get_financial_data()
            
        Returns:
            Dictionary with calculated ratios
        """
        if financial_data is None:
            return {}
        
        ratios = {}
        income = financial_data.get('income_statement', pd.Series())
        balance = financial_data.get('balance_sheet', pd.Series())
        prev_income = financial_data.get('prev_income_statement', pd.Series())
        
        # Current Ratio = Current Assets / Current Liabilities
        # Measures short-term liquidity - ability to pay short-term obligations
        # Higher is better. Values above 1.0 indicate company can cover current liabilities
        # Values between 1.5-3.0 are generally considered healthy
        current_assets = self._get_value(balance, ['Total Current Assets', 'Current Assets'])
        current_liabilities = self._get_value(balance, ['Total Current Liabilities', 'Current Liabilities'])
        
        if current_assets is not None and current_liabilities is not None and current_liabilities != 0:
            ratios['current_ratio'] = current_assets / current_liabilities
        else:
            ratios['current_ratio'] = None
        
        # Debt-to-Equity = Total Debt / Total Stockholders Equity
        # Measures financial leverage - how much debt vs equity company uses
        # Lower is generally better (less risky). Values below 1.0 are conservative
        # Values above 2.0 indicate high leverage and higher risk
        total_debt = self._get_value(balance, ['Total Debt', 'Total Liabilities Net Minority Interest'])
        shareholders_equity = self._get_value(balance, ['Total Stockholders Equity', 'Stockholders Equity'])
        
        if total_debt is not None and shareholders_equity is not None and shareholders_equity != 0:
            ratios['debt_to_equity'] = total_debt / shareholders_equity
        else:
            ratios['debt_to_equity'] = None
        
        # ROE (Return on Equity) = Net Income / Shareholders Equity
        # Measures how efficiently company uses equity to generate profit
        # Higher is better. Above 15% is generally strong, below 10% may indicate issues
        # Shows management's ability to generate returns for shareholders
        net_income = self._get_value(income, ['Net Income', 'Net Income Common Stockholders'])
        if net_income is not None and shareholders_equity is not None and shareholders_equity != 0:
            ratios['roe'] = net_income / shareholders_equity
        else:
            ratios['roe'] = None
        
        # Revenue Growth = (Current Revenue - Previous Revenue) / Previous Revenue
        # Measures year-over-year revenue growth rate
        # Higher is better for growth companies. Positive growth indicates expansion
        # Negative growth may signal declining business
        current_revenue = self._get_value(income, ['Total Revenue', 'Revenue'])
        prev_revenue = self._get_value(prev_income, ['Total Revenue', 'Revenue'])
        
        if current_revenue is not None and prev_revenue is not None and prev_revenue != 0:
            ratios['revenue_growth'] = (current_revenue - prev_revenue) / prev_revenue
        else:
            ratios['revenue_growth'] = None
        
        # Store net income for positive earnings check
        ratios['net_income'] = net_income
        
        return ratios
    
    def _get_value(self, series: pd.Series, possible_keys: list) -> Optional[float]:
        """
        Extract value from pandas Series using multiple possible key names.
        
        Args:
            series: Pandas Series to search
            possible_keys: List of possible index names to try
            
        Returns:
            Value as float, or None if not found
        """
        if series.empty:
            return None
        
        for key in possible_keys: # maybe try to narrow down the possible keys to a smaller list of keys that are most likely to be the correct key
            if key in series.index:
                value = series[key]
                # Handle different data types
                if pd.isna(value):
                    return None
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
        
        return None
