"""
Main screener module for evaluating stocks against financial criteria.

This module provides the StockScreener class which orchestrates data fetching,
ratio calculation, and criteria evaluation.
"""

import logging
from typing import Dict, List, Optional, Any
import pandas as pd

from ..data.fetcher import DataFetcher
from .criteria import build_criteria_functions, load_criteria_from_config, parse_inline_criteria

logger = logging.getLogger(__name__)


class StockScreener:
    """
    Screens stocks against financial criteria.
    
    Evaluates stocks by fetching financial data, calculating ratios,
    and checking against configured criteria.
    """
    
    def __init__(
        self,
        criteria_config: Optional[Dict[str, Any]] = None,
        fetcher: Optional[DataFetcher] = None,
    ):
        """
        Initialize the screener with criteria configuration.
        
        Args:
            criteria_config: Dictionary of criteria values. If None, loads from default config.
        """
        self.fetcher = fetcher or DataFetcher()
        
        if criteria_config is None:
            criteria_config = load_criteria_from_config()
        
        self.criteria_config = criteria_config
        self.criteria_functions = build_criteria_functions(criteria_config)
        
        logger.info(f"Initialized screener with {len(self.criteria_functions)} criteria")
    
    def screen_ticker(self, ticker: str) -> Dict[str, Any]:
        """
        Evaluate a single ticker against all criteria.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            
        Returns:
            Dictionary with screening results including:
            - ticker: Stock symbol
            - company_name: Company name
            - market_cap: Market capitalization
            - pe_ratio: P/E ratio
            - current_ratio: Current ratio
            - debt_to_equity: Debt-to-equity ratio
            - revenue_growth: Revenue growth %
            - roe: Return on Equity %
            - passed_criteria: Number of criteria passed
            - failed_criteria: List of failed criteria names
            - status: 'PASS' or 'FAIL'
        """
        logger.info(f"Screening {ticker}")
        
        # Fetch financial data
        financial_data = self.fetcher.get_financial_data(ticker)
        
        if financial_data is None:
            logger.warning(f"Could not fetch data for {ticker}")
            return {
                'ticker': ticker,
                'company_name': ticker,
                'status': 'FAIL',
                'error': 'data_fetch_failed',
                'passed_criteria': 0,
                'failed_criteria': ['data_unavailable']
            }
        
        # Calculate ratios
        ratios = self.fetcher.calculate_ratios(financial_data)
        
        # Combine all data for evaluation
        evaluation_data = {
            'market_cap': financial_data.get('market_cap'),
            'pe_ratio': financial_data.get('pe_ratio'),
            'current_ratio': ratios.get('current_ratio'),
            'debt_to_equity': ratios.get('debt_to_equity'),
            'revenue_growth': ratios.get('revenue_growth'),
            'net_income': ratios.get('net_income'),
            'roe': ratios.get('roe'),
        }
        
        # Evaluate against each criterion
        passed_count = 0
        failed_criteria = []
        
        for criterion_name, criterion_func in self.criteria_functions:
            try:
                passed, failure_reason = criterion_func(evaluation_data)
                if passed:
                    passed_count += 1
                else:
                    failed_criteria.append(f"{criterion_name}: {failure_reason}")
            except Exception as e:
                logger.error(f"Error evaluating criterion {criterion_name} for {ticker}: {str(e)}")
                failed_criteria.append(f"{criterion_name}: evaluation_error")
        
        # Determine overall status (all criteria must pass)
        total_criteria = len(self.criteria_functions)
        status = 'PASS' if passed_count == total_criteria else 'FAIL'
        
        # Build result dictionary
        result = {
            'ticker': ticker,
            'company_name': financial_data.get('company_name', ticker),
            'market_cap': financial_data.get('market_cap'),
            'pe_ratio': financial_data.get('pe_ratio'),
            'current_ratio': ratios.get('current_ratio'),
            'debt_to_equity': ratios.get('debt_to_equity'),
            'revenue_growth': ratios.get('revenue_growth'),
            'roe': ratios.get('roe'),
            'net_income': ratios.get('net_income'),
            'passed_criteria': passed_count,
            'total_criteria': total_criteria,
            'failed_criteria': ', '.join(failed_criteria) if failed_criteria else '',
            'status': status
        }
        
        logger.info(f"{ticker}: {status} ({passed_count}/{total_criteria} criteria passed)")
        
        return result
    
    def screen_list(self, tickers: List[str]) -> pd.DataFrame:
        """
        Screen multiple tickers and return results as DataFrame.
        
        Args:
            tickers: List of ticker symbols to screen
            
        Returns:
            DataFrame with screening results for all tickers
        """
        logger.info(f"Screening {len(tickers)} tickers")
        
        results = []
        for ticker in tickers:
            try:
                result = self.screen_ticker(ticker)
                results.append(result)
            except Exception as e:
                logger.error(f"Error screening {ticker}: {str(e)}")
                results.append({
                    'ticker': ticker,
                    'company_name': ticker,
                    'status': 'FAIL',
                    'error': str(e),
                    'passed_criteria': 0,
                    'failed_criteria': 'screening_error'
                })
        
        # Convert to DataFrame
        df = pd.DataFrame(results)
        
        # Ensure consistent column order
        column_order = [
            'ticker', 'company_name', 'market_cap', 'pe_ratio',
            'current_ratio', 'debt_to_equity', 'revenue_growth', 'roe',
            'passed_criteria', 'total_criteria', 'failed_criteria', 'status'
        ]
        
        # Add any missing columns
        for col in column_order:
            if col not in df.columns:
                df[col] = None
        
        # Reorder columns
        existing_cols = [col for col in column_order if col in df.columns]
        other_cols = [col for col in df.columns if col not in column_order]
        df = df[existing_cols + other_cols]
        
        return df
    
    def filter_by_criteria(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter DataFrame to only include stocks that passed all criteria.
        
        Args:
            df: DataFrame with screening results
            
        Returns:
            Filtered DataFrame with only passing stocks
        """
        if 'status' not in df.columns:
            logger.warning("DataFrame does not have 'status' column, returning as-is")
            return df
        
        filtered = df[df['status'] == 'PASS'].copy()
        logger.info(f"Filtered to {len(filtered)} passing stocks out of {len(df)} total")
        
        return filtered
