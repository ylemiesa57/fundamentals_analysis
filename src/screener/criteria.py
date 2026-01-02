"""
Screening criteria definitions and validation.

This module provides functions to evaluate stocks against financial criteria
and load criteria from configuration files.
"""

import yaml
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


def min_market_cap(value: float) -> Callable:
    """
    Create a criterion function for minimum market capitalization.
    
    Args:
        value: Minimum market cap in dollars
        
    Returns:
        Function that evaluates if market cap meets minimum
    """
    def evaluate(data: Dict[str, Any]) -> Tuple[bool, str]:
        market_cap = data.get('market_cap')
        if market_cap is None:
            return False, "market_cap_missing"
        if market_cap >= value:
            return True, ""
        return False, f"market_cap_below_min ({market_cap:,.0f} < {value:,.0f})"
    
    return evaluate


def max_pe_ratio(value: float) -> Callable:
    """
    Create a criterion function for maximum P/E ratio.
    
    P/E ratio measures price relative to earnings. Lower is generally better
    for value investors, but growth stocks may have higher P/E ratios.
    Typical "reasonable" P/E is 15-25, but varies by industry.
    
    Args:
        value: Maximum acceptable P/E ratio
        
    Returns:
        Function that evaluates if P/E ratio is below maximum
    """
    def evaluate(data: Dict[str, Any]) -> Tuple[bool, str]:
        pe_ratio = data.get('pe_ratio')
        if pe_ratio is None:
            return False, "pe_ratio_missing"
        if pe_ratio <= value:
            return True, ""
        return False, f"pe_ratio_above_max ({pe_ratio:.2f} > {value:.2f})"
    
    return evaluate


def min_current_ratio(value: float) -> Callable:
    """
    Create a criterion function for minimum current ratio.
    
    Current ratio measures liquidity. Values above 1.0 indicate company
    can cover current liabilities. Values between 1.5-3.0 are healthy.
    
    Args:
        value: Minimum acceptable current ratio
        
    Returns:
        Function that evaluates if current ratio meets minimum
    """
    def evaluate(data: Dict[str, Any]) -> Tuple[bool, str]:
        current_ratio = data.get('current_ratio')
        if current_ratio is None:
            return False, "current_ratio_missing"
        if current_ratio >= value:
            return True, ""
        return False, f"current_ratio_below_min ({current_ratio:.2f} < {value:.2f})"
    
    return evaluate


def max_debt_to_equity(value: float) -> Callable:
    """
    Create a criterion function for maximum debt-to-equity ratio.
    
    Debt-to-equity measures financial leverage. Lower is generally better
    (less risky). Values below 1.0 are conservative, above 2.0 indicates high leverage.
    
    Args:
        value: Maximum acceptable debt-to-equity ratio
        
    Returns:
        Function that evaluates if debt-to-equity is below maximum
    """
    def evaluate(data: Dict[str, Any]) -> Tuple[bool, str]:
        debt_to_equity = data.get('debt_to_equity')
        if debt_to_equity is None:
            return False, "debt_to_equity_missing"
        if debt_to_equity <= value:
            return True, ""
        return False, f"debt_to_equity_above_max ({debt_to_equity:.2f} > {value:.2f})"
    
    return evaluate


def min_revenue_growth(value: float) -> Callable:
    """
    Create a criterion function for minimum revenue growth.
    
    Revenue growth measures year-over-year expansion. Positive growth indicates
    business expansion. Negative growth may signal declining business.
    
    Args:
        value: Minimum revenue growth rate (as decimal, e.g., 0.05 for 5%)
        
    Returns:
        Function that evaluates if revenue growth meets minimum
    """
    def evaluate(data: Dict[str, Any]) -> Tuple[bool, str]:
        revenue_growth = data.get('revenue_growth')
        if revenue_growth is None:
            return False, "revenue_growth_missing"
        if revenue_growth >= value:
            return True, ""
        return False, f"revenue_growth_below_min ({revenue_growth:.2%} < {value:.2%})"
    
    return evaluate


def positive_earnings() -> Callable:
    """
    Create a criterion function requiring positive net income.
    
    Positive earnings indicate profitability. Companies with consistent
    positive earnings are generally more stable investments.
    
    Returns:
        Function that evaluates if net income is positive
    """
    def evaluate(data: Dict[str, Any]) -> Tuple[bool, str]:
        net_income = data.get('net_income')
        if net_income is None:
            return False, "net_income_missing"
        if net_income > 0:
            return True, ""
        return False, f"negative_earnings ({net_income:,.0f})"
    
    return evaluate


def min_roe(value: float) -> Callable:
    """
    Create a criterion function for minimum Return on Equity (ROE).
    
    ROE measures how efficiently company uses equity to generate profit.
    Above 15% is generally strong, below 10% may indicate issues.
    
    Args:
        value: Minimum ROE (as decimal, e.g., 0.15 for 15%)
        
    Returns:
        Function that evaluates if ROE meets minimum
    """
    def evaluate(data: Dict[str, Any]) -> Tuple[bool, str]:
        roe = data.get('roe')
        if roe is None:
            return False, "roe_missing"
        if roe >= value:
            return True, ""
        return False, f"roe_below_min ({roe:.2%} < {value:.2%})"
    
    return evaluate


def load_criteria_from_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load screening criteria from YAML configuration file.
    
    Args:
        config_path: Path to config file. If None, uses default config/config.yaml
        
    Returns:
        Dictionary of criteria configuration
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / 'config' / 'config.yaml'
    else:
        config_path = Path(config_path)
    
    if not config_path.exists():
        logger.warning(f"Config file not found at {config_path}, using defaults")
        return {}
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        screener_config = config.get('screener', {})
        return screener_config.get('criteria', {})
    
    except Exception as e:
        logger.error(f"Error loading config from {config_path}: {str(e)}")
        return {}


def parse_inline_criteria(criteria_string: str) -> Dict[str, Any]:
    """
    Parse inline criteria string into dictionary.
    
    Format: "pe_max=25,market_cap_min=1000000000,roe_min=0.15"
    
    Args:
        criteria_string: Comma-separated key=value pairs
        
    Returns:
        Dictionary of criteria
    """
    criteria = {}
    if not criteria_string:
        return criteria
    
    for pair in criteria_string.split(','):
        pair = pair.strip()
        if '=' not in pair:
            continue
        
        key, value = pair.split('=', 1)
        key = key.strip()
        value = value.strip()
        
        # Try to convert to appropriate type
        if value.lower() == 'true':
            criteria[key] = True
        elif value.lower() == 'false':
            criteria[key] = False
        else:
            try:
                # Try float first (handles decimals)
                criteria[key] = float(value)
            except ValueError:
                # Fall back to string
                criteria[key] = value
    
    return criteria


def build_criteria_functions(criteria_config: Dict[str, Any]) -> List[tuple[str, Callable]]:
    """
    Build list of criterion evaluation functions from configuration.
    
    Args:
        criteria_config: Dictionary of criteria values
        
    Returns:
        List of tuples (criterion_name, evaluation_function)
    """
    functions = []
    
    # Map config keys to criterion builders
    criterion_map = {
        'market_cap_min': min_market_cap,
        'pe_max': max_pe_ratio,
        'current_ratio_min': min_current_ratio,
        'debt_to_equity_max': max_debt_to_equity,
        'revenue_growth_min': min_revenue_growth,
        'positive_earnings': positive_earnings,
        'roe_min': min_roe,
    }
    
    for key, value in criteria_config.items():
        if key in criterion_map:
            if key == 'positive_earnings':
                # Special case: boolean flag
                if value:
                    functions.append((key, criterion_map[key]()))
            else:
                # Regular numeric criteria
                try:
                    functions.append((key, criterion_map[key](value)))
                except Exception as e:
                    logger.warning(f"Error building criterion {key}: {str(e)}")
        else:
            logger.warning(f"Unknown criterion: {key}")
    
    return functions


def validate_criteria(criteria_config: Dict[str, Any]) -> bool:
    """
    Validate that criteria configuration is properly formatted.
    
    Args:
        criteria_config: Dictionary of criteria values
        
    Returns:
        True if valid, False otherwise
    """
    valid_keys = {
        'market_cap_min', 'pe_max', 'current_ratio_min', 'debt_to_equity_max',
        'revenue_growth_min', 'positive_earnings', 'roe_min'
    }
    
    for key in criteria_config.keys():
        if key not in valid_keys:
            logger.warning(f"Unknown criterion key: {key}")
            return False
    
    return True

